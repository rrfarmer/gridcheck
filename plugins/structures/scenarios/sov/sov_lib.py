# Sovereignty driver, loaded into the client agent's namespace after upwell/upwell_lib.py by the
# sov scenarios. Every player action goes through the client's own services: LaunchFromShip (the
# cargo menu's "Launch for Self", spacecomponents/client/components/deploy.py:55), the HUD module
# buttons (entosis), sovSvc / sovHubSvc / sovereigntyResourceSvc (what the sov windows read), the
# skyhook and mercenary den space components. GM slash commands are used only for setup (skills,
# ISK, items, moving the test ship between highsec and null) and to skip timers (owner ruling
# 2026-11-06: hybrid time control, as for the Keepstar siege on 2026-11-05).
import blue, uthread, evetypes

SOV_HUB = 32458
SOV_SKYHOOK = 81080
SOV_SILO = 81933
SOV_DEN = 85230
SOV_GANTRY = 3962
SOV_ENTOSIS_T1 = 34593
SOV_ENTOSIS_T2 = 34595
SOV_STRONTIUM = 16275
SOV_GAS = 81143
SOV_ICE = 81144
SOV_NODE = 34832
# Test systems (doc/SOV_CLIENT_CHECK_MANIFEST.md, phase 0): Deklein constellation 20000431.
SOV_MAIN = 30002939      # WUZ-WM: every planet type
SOV_SECOND = 30002945    # N2IS-B: 2.05 ly from WUZ-WM, for workforce transit
SOV_BRIDGE = 30002941    # 43B-O1: 0.57 ly from WUZ-WM, the Ansiblex pair
SOV_FAR = 30002947       # GY5-26: two jumps from WUZ-WM, for raid alerts
SOV_STAR = {30002939: 40186554, 30002945: 40187002, 30002947: 40187083}
SOV_HOME = 60003760      # Jita IV - Moon 4 - Caldari Navy Assembly Plant: ships are made here


def sov_log(*args):
    up_log('sov', *args)


def sov_bp_items(typeID):
    bp = up_bp()
    if not bp:
        return []
    return [k for k, v in bp.slimItems.items() if v.typeID == typeID]


def sov_alliance(name, short):
    # The Alliances window's Create Alliance form (all_ui_home.CreateAllianceForm) calls
    # corp.CreateAlliance. Safe to run again.
    if session.allianceid:
        return session.allianceid
    sm.GetService('corp').CreateAlliance(name, short, 'client check', '')
    up_wait(lambda: session.allianceid, 60000, 1000)
    return session.allianceid


def sov_setup(corpName, ticker, allianceName, allianceShort):
    up_pilot_setup(corpName, ticker, SOV_HOME)
    return (session.corpid, sov_alliance(allianceName, allianceShort))


def sov_go(destID, wait_ms=60000):
    # GM setup move: /tr me <system, celestial or station>.
    before = session.solarsystemid2
    up_slash('/tr me %d' % destID)
    up_wait(lambda: up_bp() and session.solarsystemid2 and session.shipid in up_bp().balls, wait_ms, 1000)
    up_sleep(8000)
    return (before, session.solarsystemid2)


def sov_home():
    if session.stationid == SOV_HOME:
        return session.stationid
    up_slash('/tr me %d' % SOV_HOME)
    up_wait(lambda: session.stationid == SOV_HOME, 60000, 1000)
    up_sleep(12000)
    return session.stationid


def sov_load(typeID, qty):
    # GM setup: items into the hangar, then dragged into the ship's cargo.
    up_hangar_give(typeID, qty)
    up_sleep(2000)
    item = up_wait(lambda: [i for i in up_hangar_items(typeID)], 10000)[0]
    sm.GetService('invCache').GetInventoryFromId(session.shipid).Add(item.itemID, item.locationID, qty=item.stacksize, flag=const.flagCargo)
    return up_wait(lambda: [i for i in up_cargo() if i.typeID == typeID], 10000)[0].itemID


def sov_launch(typeID, timeout_ms=30000):
    # The cargo menu's "Launch for Self" / "Launch for Corporation": for a type with a deploy
    # component both call LaunchFromShip([item], maxQty=1) with no owner (menusvc.py:344-354).
    from eve.client.script.util.eveMisc import LaunchFromShip
    item = [i for i in up_cargo() if i.typeID == typeID][0]
    before = set(sov_bp_items(typeID))
    LaunchFromShip([item], maxQty=1)
    new = up_wait(lambda: [k for k in sov_bp_items(typeID) if k not in before], timeout_ms)
    sov_log('launched', typeID, new)
    return new[0] if new else None


def sov_entosis_ship(hull='Vexor', hullTypeID=626, tier=SOV_ENTOSIS_T2):
    # GM setup at home: a cruiser with an Entosis Link and strontium.
    sov_home()
    up_board_ship(hull, hullTypeID)
    up_slash('/fit me %d' % tier)
    up_sleep(2000)
    sov_load(SOV_STRONTIUM, 100)  # a Vexor holds 480 m3
    return session.shipid


def sov_entosis(targetID, typeID=None):
    # Lock the target and press the Entosis Link's HUD button, as a pilot does.
    ts = sm.GetService('target')
    if targetID not in ts.GetTargets():
        uthread.new(ts.TryLockTarget, targetID)
        up_wait(lambda: targetID in ts.GetTargets(), 60000)
    buttons = up_hud_buttons([typeID] if typeID else [SOV_ENTOSIS_T1, SOV_ENTOSIS_T2])
    for b in buttons:
        if not b.def_effect.isActive:
            uthread.new(b.ActivateModule)
    up_sleep(3000)
    return [(b.moduleinfo.itemID, b.def_effect.isActive) for b in buttons]


def sov_entosis_stop():
    for b in up_hud_buttons([SOV_ENTOSIS_T1, SOV_ENTOSIS_T2]):
        if b.def_effect.isActive:
            uthread.new(b.DeactivateModule)
    up_sleep(2000)


def sov_score(itemID):
    s = up_slim(itemID)
    return s and getattr(s, 'entosis_score', None)


def sov_system_info(solarSystemID=None):
    # What the info panel and the Sovereignty tab read (sovSvc).
    sid = solarSystemID or session.solarsystemid2
    svc = sm.GetService('sov')
    out = {}
    try:
        info = svc.GetSystemSovereigntyInfo(sid)
        out['owner'] = info and (getattr(info, 'allianceID', None), getattr(info, 'corporationID', None))
    except Exception as e:
        out['ownerErr'] = repr(e)
    try:
        out['hub'] = svc.GetInfrastructureHubInfo(sid)
    except Exception as e:
        out['hubErr'] = repr(e)
    return out


def sov_notifications(typeIDs=None, groupIDs=range(1, 40)):
    # The notification window's lists: notificationSvc.GetFormattedNotifications(groupID), one
    # group at a time (sov notices are in group 6).
    svc = sm.GetService('notificationSvc')
    out = []
    for g in groupIDs:
        try:
            rows = svc.GetFormattedNotifications(g) or []
        except Exception:
            continue
        for n in rows:
            t = getattr(n, 'typeID', None)
            if typeIDs is None or t in typeIDs:
                out.append((getattr(n, 'notificationID', None), t, getattr(n, 'subject', None),
                            getattr(n, 'body', None)))
    return out


def sov_hub_window(hubID):
    # The Hub configuration window (openFunctions.py:181 OpenSovHubWnd) and its controller.
    from eve.client.script.ui.shared.sov.sovHub.sovHubWnd import OpenSovHubWnd
    OpenSovHubWnd(hubID, session.solarsystemid2)
    wnd = up_wait(lambda: [w for w in uicore.registry.GetWindows() if w.__class__.__name__ == 'SovHubWnd'], 20000)
    wnd = wnd[0]
    up_wait(lambda: getattr(wnd, 'hubController', None) and wnd.hubController.installedUpgradesSimulated is not None, 20000)
    return wnd.hubController


class _SovDragItem(object):
    # What a cargo item dragged into the window carries (listentry.InvItem: invtype and rec).
    __guid__ = 'listentry.InvItem'

    def __init__(self, rec):
        self.rec = rec
        self.invtype = rec.typeID


def sov_hub_drop(ctrl, typeIDs):
    # Drag each cargo item of these types into the window: the controller's own DoDropData,
    # which refuses with GetDropError's text (hubController.py:176) the way the player sees it.
    errors = {}
    for typeID in typeIDs:
        rec = [i for i in up_cargo() if i.typeID == typeID][0]
        data = _SovDragItem(rec)
        err = ctrl.GetDropError(data)
        if err:
            errors[typeID] = err
            continue
        ctrl.DoDropData(None, [data])
    return errors


def sov_hub_save(ctrl):
    # SaveChanges without its confirmation dialog: the same SaveUpgradeConfiguration call
    # (hubController.py:360-364), then the power states it compares.
    newUpgrades = ctrl._newUpgrades.keys()
    installed = [(u.typeID, u.isConfiguredOnline) for u in ctrl.installedUpgradesSimulated]
    before = [(u.typeID, u.powerState) for u in ctrl.installedUpgradesSimulated]
    res = sm.GetService('sovHubSvc').SaveUpgradeConfiguration(ctrl.itemID, newUpgrades, installed)
    ctrl._newUpgrades.clear()
    after = [(x.upgrade_type_id, x.power_state) for x in res]
    return (before == after, before, after)


def sov_hub_upgrades(hubID):
    return [(x.upgrade_type_id, x.power_state, getattr(x, 'is_power_offline', None))
            for x in sm.GetService('sovHubSvc').GetInstalledUpgradesForHub(hubID)]


def sov_orbital_state(itemID):
    s = up_slim(itemID)
    if s is None:
        return None
    return dict(orbitalState=getattr(s, 'orbitalState', None), orbitalTimestamp=getattr(s, 'orbitalTimestamp', None),
                skyhook_state=getattr(s, 'skyhook_state', None), skyhook_timer=getattr(s, 'skyhook_timer', None),
                skyhook_damage=getattr(s, 'skyhook_damage', None), damage=up_bp().GetDamageState(itemID))


def sov_shoot_orbital(itemID, shield, armor=1.0, hull=1.0, real_seconds=40):
    # The hybrid rule (owner, 2026-11-06): a logged GM /sov orbital damage leaves the orbital
    # just above the threshold, then real fire from the Revelation (up_dread) crosses it.
    up_slash('/sov orbital %d damage %s %s %s' % (itemID, shield, armor, hull))
    up_sleep(3000)
    before = sov_orbital_state(itemID)
    up_strontium(300)
    up_attack(itemID, 37298, 4292)
    up_sleep(real_seconds * 1000)
    return (before, sov_orbital_state(itemID))


def sov_answer_yes():
    # Answer the open yes/no MessageBox the way its Yes button does (client_click cannot press
    # MessageBox buttons).
    from carbonui import uiconst
    m = up_wait(lambda: uicore.registry.GetModalWindow(), 20000)
    m.SetModalResult(uiconst.ID_YES)
    return True


def sov_board_flex(structureID):
    # structureControl.BoardStructure (the space menu's Board Structure): asks BoardingFlexStructure
    # first when leaving a ship in space.
    uthread.new(sm.GetService('structureControl').BoardStructure, structureID)
    sov_answer_yes()
    return up_wait(lambda: session.shipid == structureID, 60000) and session.shipid


def sov_flex_modules(structureID):
    # What the fitting window reads: the client's own dogma location.
    dl = sm.GetService('clientDogmaIM').GetDogmaLocation()
    ship = dl.SafeGetDogmaItem(structureID)
    out = []
    for k, v in (ship.GetFittedItems().items() if ship else []):
        if v.flagID >= 164:
            out.append((k, v.typeID, v.flagID, dl.SafeGetDogmaItem(k).IsOnline()))
    return out


def sov_online_module(moduleID):
    # The fitting window's Put Online: clientDogmaLocation.OnlineModule. Answers the module's
    # online flag and any message the server sent back.
    dl = sm.GetService('clientDogmaIM').GetDogmaLocation()
    try:
        dl.OnlineModule(moduleID)
    except UserError as e:
        return (False, e.msg, e.dict)
    up_wait(lambda: dl.SafeGetDogmaItem(moduleID).IsOnline(), 20000)
    return (dl.SafeGetDogmaItem(moduleID).IsOnline(), None, None)


def sov_board_previous():
    sc = sm.GetService('structureControl')
    shipID = sc.GetOldShipInfo()[0]
    uthread.new(sc.BoardPreviousShip)
    return up_wait(lambda: session.shipid == shipID and not session.structureid, 60000) and session.shipid


def sov_corp_balance(accountKey=1000):
    return [d.balance for d in sm.RemoteSvc('account').GetWalletDivisionsInfo() if d.key == accountKey][0]


def sov_corp_deposit(amount, accountKey=1000):
    # The wallet's Give ISK to the own corporation (transferMoneyWnd.py:148).
    sm.RemoteSvc('account').GiveCash(session.corpid, float(amount), 'client check', toAccountKey=accountKey)
    return sov_corp_balance(accountKey)


def sov_cleanup_candidates():
    # What the system cleanup window lists (sovSvc.GetStructuresAvailableToCleanUp).
    return [(i.itemID, i.ownerID, i.allianceID) for i in sm.GetService('sov').GetStructuresAvailableToCleanUp()]


def sov_cleanup(acquireIDs, destroyIDs, accessListID=None):
    # cleanupWndController.ProcessSkyhooks: AcquireSkyhooks then DestroySkyhooks; each answers the
    # IDs it processed. Then what the ballpark shows for each and the corp wallet.
    sov = sm.GetService('sov')
    before = sov_corp_balance()
    try:
        acquired = sov.AcquireSkyhooks(list(acquireIDs), accessListID)
    except UserError as e:
        return dict(error=(e.msg, e.dict), balance=before)
    destroyed = sov.DestroySkyhooks(list(destroyIDs))
    up_sleep(3000)
    bp = up_bp()
    owners = dict((i, (bp.GetInvItem(i).ownerID, bp.GetInvItem(i).allianceID) if bp.GetInvItem(i) else None)
                  for i in list(acquireIDs) + list(destroyIDs))
    return dict(acquired=list(acquired), destroyed=list(destroyed), owners=owners,
                paid=before - sov_corp_balance(), left=[c[0] for c in sov_cleanup_candidates()])


def sov_check_cleanup(result, convertID, destroyID):
    # One converted to the caller for 200M, one gone from the ballpark, neither still listed.
    assert result.get('acquired') == [convertID], result
    assert result.get('destroyed') == [destroyID], result
    assert result.get('paid') == 200000000, result
    assert result['owners'][convertID] == (session.corpid, session.allianceid), result
    assert result['owners'][destroyID] is None, result
    assert not set([convertID, destroyID]) & set(result['left']), result
    return True


def sov_hub_uninstall(hubID, typeID):
    # The Hub window's remove button: hubController.DeleteUpgrade asks ConfirmDestroyUpgrade
    # ("...remove the Upgrade from the Sovereignty Hub and destroy it") and calls
    # sovHubSvc.UninstallUpgrade. Answers what the Hub then lists and the cargo.
    ctrl = sov_hub_window(hubID)
    up = [u for u in ctrl.installedUpgradesSimulated if u.typeID == typeID][0]
    uthread.new(ctrl.DeleteUpgrade, typeID, up.upgradeKey, None)
    sov_answer_yes()
    up_sleep(5000)
    return dict(upgrades=sov_hub_upgrades(hubID), cargo=[(i.typeID, i.stacksize) for i in up_cargo()])


def sov_menu_offers(itemID):
    from menucheckers.celestialCheckers import CelestialChecker
    from menucheckers.sessionChecker import SessionChecker
    cc = CelestialChecker(up_bp().slimItems[itemID], cfg, SessionChecker(session, sm))
    return dict(selfDestruct=cc.OfferSelfDestructShipOrPod(), abort=cc.OfferAbortSelfDestructStructure())


def sov_self_destruct(hubID, abort=False):
    # The space menu's Self-Destruct / Abort Self-Destruct (menuFunctions.SelfDestructStructure,
    # AbortSelfDestructStructure), each with its confirmation. Answers the slim deadline.
    from eve.client.script.ui.services.menuSvcExtras import menuFunctions
    fn = menuFunctions.AbortSelfDestructStructure if abort else menuFunctions.SelfDestructStructure
    uthread.new(fn, hubID)
    sov_answer_yes()
    up_sleep(4000)
    return getattr(up_bp().slimItems[hubID], 'selfDestructTime', None)


def sov_pi_colony(planetID, ccTypeID, padTypeID, level=3):
    # The planet view's build-and-submit: a command center from cargo, its upgrade, a launchpad
    # and a link (clientPlanet.CreatePin / UpgradeCommandCenter / CreateLink / SubmitChanges).
    planet = sm.GetService('planetSvc').GetPlanet(planetID)
    cc = planet.CreatePin(ccTypeID, 0.6, 0.6)
    planet.UpgradeCommandCenter(cc.id, level)
    pad = planet.CreatePin(padTypeID, 0.62, 0.61)
    planet.CreateLink(cc.id, pad.id, list(evetypes.GetTypeIDsByGroup(const.groupPlanetaryLinks))[0])
    planet.SubmitChanges()
    up_sleep(3000)
    planet = sm.GetService('planetSvc').GetPlanet(planetID)
    return [p.id for p in planet.GetColony(session.charid).colonyData.pins.values() if p.typeID == padTypeID][0]


def sov_pi_transfer(orbitalID, padID, importTypeID=None, importQty=0, exportTypeID=None, exportQty=0):
    # The import/export window's Transfer: cargo into the orbital's bay first (its drag-and-drop),
    # then ImportExportWithPlanet at the registry's current tax. Answers what the pilot paid and
    # what the owner's corporation gained (the caller should belong to it to read that).
    import eve.common.script.net.eveMoniker as eveMoniker
    inv = sm.GetService('invCache').GetInventoryFromId(orbitalID)
    imports = {}
    if importTypeID:
        src = [i for i in up_cargo() if i.typeID == importTypeID][0]
        inv.Add(src.itemID, session.shipid, qty=importQty)
        up_sleep(3000)
        imports = {[i for i in inv.List() if i.typeID == importTypeID][0].itemID: importQty}
    exports = {exportTypeID: exportQty} if exportTypeID else {}
    tax = eveMoniker.GetPlanetOrbitalRegistry(session.solarsystemid).GetTaxRate(orbitalID)
    pad = sm.GetService('planetSvc').GetPlanet(up_bp().slimItems[orbitalID].planetID).GetPin(padID)
    expected = pad.GetImportTax({importTypeID: importQty} if importTypeID else {}, tax) +         pad.GetExportTax(exports, tax)
    c0 = sov_corp_balance()
    w0 = sm.GetService('wallet').GetWealth()
    inv.ImportExportWithPlanet(padID, imports, exports, tax)
    up_sleep(4000)
    return dict(tax=tax, expected=expected, paid=w0 - sm.GetService('wallet').GetWealth(),
                ownerGain=sov_corp_balance() - c0)


def sov_hub_fuel(hubID, typeID, qty):
    # The Hub's reagent bay deposit (reagentBay/controllers.py DoDepositItems): sovHubSvc.AddFuel
    # per cargo stack.
    rec = [i for i in up_cargo() if i.typeID == typeID][0]
    sm.GetService('sovHubSvc').AddFuel(rec.itemID, qty, hubID)
    up_sleep(3000)
    return True


def sov_hub_set_online(hubID, typeID, online):
    # The Hub window's online toggle, then its save.
    for w in [w for w in uicore.registry.GetWindows() if w.__class__.__name__ == 'SovHubWnd']:
        w.Close()
    ctrl = sov_hub_window(hubID)
    ctrl.SetOnlineState(typeID, online)
    return sov_hub_save(ctrl)


def sov_ansiblex_jump(gateID):
    # The space menu's Jump (menusvc.ReallyJumpThroughStructureJumpBridge:
    # structureJumpBridgeMgr.CmdJumpThroughStructureStargate in a session change). GM /tr puts
    # the ship on the gate first, since the bridge refuses beyond its activation range. Answers
    # the systems before and after, or the refusal.
    from eve.client.script.ui.services.menusvc import MenuSvc
    up_slash('/tr me %d' % gateID)
    up_sleep(8000)
    before = session.solarsystemid2
    try:
        MenuSvc.ReallyJumpThroughStructureJumpBridge(gateID)
    except UserError as e:
        return dict(before=before, after=session.solarsystemid2, error=(e.msg, e.dict))
    up_wait(lambda: session.solarsystemid2 != before, 60000, 1000)
    up_sleep(5000)
    return dict(before=before, after=session.solarsystemid2, error=None)


def sov_raid_window(skyhookID):
    # What the skyhook window and the map read (sovereigntyResourceSvc).
    vd = sm.GetService('sovereigntyResourceSvc').GetTheftVulnerabilityForSkyhook(skyhookID)
    return dict(start=vd.start, end=vd.end, vulnerable=vd.vulnerable)


def sov_raid_stock(skyhookID):
    # (secured, unsecured): the raidable surplus is the unsecured part.
    return sm.GetService('sovereigntyResourceSvc').GetReagentsInSkyhookNow(skyhookID)


def sov_raid_set_stock(skyhookID, reagentTypeID, secured, unsecured):
    # GM setup: the client's own dev admin call (skyhook messenger admin_modify_reagents).
    return sm.GetService('sovereigntyResourceSvc').skyhookMessenger.admin_modify_reagents(
        skyhookID, reagentTypeID, secured, unsecured)


def sov_silo_for(skyhookID):
    bp = up_bp()
    for k, v in bp.slimItems.items():
        if v.typeID == SOV_SILO:
            comp = bp.componentRegistry.GetComponentForItem(k, 'skyhookReagentSilo')
            if comp is not None and getattr(comp, 'skyhookID', None) == skyhookID:
                return k
    return None


def sov_link_checks(siloID):
    # The link component's own checks (linkWithShip.CanCreateLink), as its tooltip shows them.
    from menucheckers.celestialCheckers import CelestialChecker
    from menucheckers.sessionChecker import SessionChecker
    bp = up_bp()
    comp = bp.componentRegistry.GetComponentForItem(siloID, 'linkWithShip')
    return comp.CanCreateLink(CelestialChecker(bp.slimItems[siloID], cfg, SessionChecker(session, sm)))[0]


def sov_link(siloID):
    # The space menu's Link (linkWithShip.InitiateLink). Answers the component's link tuple, or
    # the refusal text.
    from spacecomponents.client.components.linkWithShip import InitiateLink
    try:
        InitiateLink(sm.GetService('michelle'), siloID)
    except UserError as e:
        return ('refused', e.dict.get('notify') if isinstance(e.dict, dict) else e.msg)
    up_sleep(4000)
    return getattr(up_bp().slimItems[siloID], 'component_linkWithShip', None)


def sov_link_state(siloID):
    comp = up_bp().componentRegistry.GetComponentForItem(siloID, 'linkWithShip')
    return (comp.linkedShipID, comp.GetLinkState())
