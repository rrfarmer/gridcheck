# Upwell structure driver, loaded into the client agent's namespace by the structures scenarios.
# Everything a player does goes through the client's own services: structureDeployment (the
# deploy window's controller), movementFunctions (dock), invControllers (core room, fuel bay),
# structureControl (take control), invCache (fitting) and clientDogmaLocation (online). GM slash
# commands are used only for setup (skills, ISK, items, moving the test ship) and for timers, and
# the timer command is the one the client's own GM structure menu sends
# (eve/client/script/ui/structure/structuremenu.py:79).
import blue, uthread, evetypes
from eve.client.script.environment import invControllers as up_ic
from eve.client.script.ui.services.menuSvcExtras import movementFunctions as up_move

UP_FLAG_SERVICE = range(164, 172)
UP_FLAG_RIG = range(92, 95)
UP_FLAG_FUEL = 172
UP_FLAG_DEED = 180
UP_STATE_NAMES = {0: 'unknown', 1: 'unanchored', 2: 'anchoring', 101: 'fitting_invulnerable',
                  102: 'onlining_vulnerable', 110: 'shield_vulnerable', 111: 'armor_reinforce',
                  112: 'armor_vulnerable', 113: 'hull_reinforce', 114: 'hull_vulnerable',
                  115: 'anchor_vulnerable', 116: 'deploy_vulnerable'}
# Quantum core per structure type (structureRequiresDeedType, attribute 3101).
UP_CORE = {35832: 56201, 35835: 56202, 35825: 56203, 35833: 56204, 35836: 56205, 35826: 56206,
           35834: 56207, 35827: 56208, 40340: 56207, 47512: 56204, 47513: 56204, 47514: 56204,
           47515: 56204, 47516: 56204}
# Service modules to try, in fitting order; each structure takes the ones its canFitShipType
# attributes and service slots allow.
UP_SERVICES = [35892, 35894, 35899, 35878, 35891, 35886, 35881, 35877, 45009, 45537, 45538, 45539]
# Refineries carry the moon drill and reactors first.
UP_SERVICES_BY_TYPE = {35835: [45009, 35899, 45537], 35836: [45009, 35899, 45537, 45538, 45539]}
# Three rigs per size (rigSize 2 M, 3 L, 4 XL), each from its own group (one rig per group,
# CantFitTooManyByGroup): combat rigs for citadels, moon drilling and reprocessing rigs for the
# refineries.
UP_RIGS = {2: [37234, 37216, 37228], 3: [37260, 37248, 37254], 4: [37268, 37272, 37274]}
UP_RIGS_BY_TYPE = {35835: [46323, 46325, 37234], 35836: [46327, 46639, 37260]}
UP_ATTR = {'shield': 263, 'armor': 265, 'hull': 9, 'shieldCap': 2034, 'armorCap': 2035,
           'hullCap': 2036, 'serviceSlots': 2056, 'rigSlots': 1137, 'rigSize': 1547,
           'core': 3101, 'disallowInHighSec': 1970}
FUEL_HELIUM = 4247


def up_log(*args):
    if not hasattr(agent, 'up_log'):
        agent.up_log = []
    agent.up_log.append((blue.os.GetWallclockTime(),) + args)


def up_slash(cmd):
    reply = sm.GetService('slash').SlashCmd(cmd)
    up_log('slash', cmd, reply)
    return reply


def up_sleep(ms):
    blue.pyos.synchro.SleepWallclock(ms)


def up_wait(fn, timeout_ms=60000, every=500):
    t0 = blue.os.GetWallclockTime()
    while True:
        try:
            v = fn()
        except Exception:
            v = None
        if v:
            return v
        if (blue.os.GetWallclockTime() - t0) / 10000 > timeout_ms:
            return v
        up_sleep(every)


def up_static(typeID, attributeID, default=None):
    return sm.GetService('clientDogmaStaticSvc').GetTypeAttribute(typeID, attributeID, default)


def up_can_fit(moduleTypeID, structureTypeID):
    # canFitShipType1..11 (1302-1305, 1944, 2103, 2463, 2486-2488, 2758); none listed fits all.
    ids = [1302, 1303, 1304, 1305, 1944, 2103, 2463, 2486, 2487, 2488, 2758]
    allowed = [int(up_static(moduleTypeID, a, 0) or 0) for a in ids]
    allowed = [a for a in allowed if a]
    return (not allowed) or structureTypeID in allowed


def up_bp():
    return sm.GetService('michelle').GetBallpark()


def up_slim(structureID):
    bp = up_bp()
    return bp and bp.slimItems.get(structureID)


def up_state(structureID):
    s = up_slim(structureID)
    if s is None:
        info = sm.RemoteSvc('structureDirectory').GetStructureInfo(structureID)
        return (info.state, None, info.upkeepState, None)
    return (s.state, getattr(s, 'timer', None), getattr(s, 'upkeepState', None), getattr(s, 'deedState', None))


def up_info(structureID):
    return sm.RemoteSvc('structureDirectory').GetStructureInfo(structureID)


def up_hangar_give(typeID, qty):
    # GM setup: items into the hangar where the pilot is docked (station or structure).
    return up_slash('/giveitem %d %d' % (typeID, qty))


def up_hangar_items(typeID=None):
    # Docked in a structure the item hangar is the structure's own inventory at flag 4
    # (invControllers.StructureItemHangar); in a station it is containerHangar.
    if session.structureid:
        rows = up_ic.StructureItemHangar(session.structureid).GetItems()
    else:
        rows = sm.GetService('invCache').GetInventory(const.containerHangar).List()
    return [i for i in rows if i.flagID == const.flagHangar and i.ownerID == session.charid and (typeID is None or i.typeID == typeID)]


def up_ship_hangar(typeID=None):
    # Ships sit at flag 4 in both: the structure's ship hangar (invControllers.StructureShipHangar)
    # or the station hangar.
    if session.structureid:
        rows = up_ic.StructureShipHangar(session.structureid).GetItems()
    else:
        rows = [i for i in sm.GetService('invCache').GetInventory(const.containerHangar).List() if i.flagID == const.flagHangar]
    return [i for i in rows if i.categoryID == const.categoryShip and i.ownerID == session.charid and (typeID is None or i.typeID == typeID)]


def up_cargo():
    return sm.GetService('invCache').GetInventoryFromId(session.shipid).List(const.flagCargo)


def up_board(hull, tries=4):
    # The client refuses a session change within 10 s of the last one (SESSIONCHANGEDELAY), so a
    # board right after docking is retried.
    for k in range(tries):
        try:
            sm.GetService('station').TryActivateShip(hull)
        except Exception as e:
            up_log('board retry', hull.itemID, repr(e))
        if up_wait(lambda: session.shipid == hull.itemID, 6000):
            up_sleep(2000)
            return session.shipid
        up_sleep(4000)
    return session.shipid


def up_board_freighter():
    # GM setup: a Charon with three Expanded Cargohold II (1.2M m3) carries even a Keepstar.
    ship = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    if ship.typeID == 20185:
        return session.shipid
    have = up_ship_hangar(20185)
    if have:
        return up_board(have[0])
    up_slash('/ship Charon')
    up_sleep(3000)
    hull = up_wait(lambda: up_ship_hangar(20185), 15000)[0]
    up_board(hull)
    for k in range(3):
        up_slash('/fit me 1319')
    return session.shipid


def up_load_hull(typeID):
    # GM setup: the packaged structure, then moved into the freighter's hold the way a drag does.
    up_hangar_give(typeID, 1)
    up_sleep(2000)
    item = up_wait(lambda: [i for i in up_hangar_items(typeID)], 10000)[0]
    sm.GetService('invCache').GetInventoryFromId(session.shipid).Add(item.itemID, item.locationID, qty=1, flag=const.flagCargo)
    return up_wait(lambda: [i for i in up_cargo() if i.typeID == typeID], 10000)[0].itemID


def up_undock(tries=5):
    # The client drops an undock asked for within 10 s of the last session change
    # (SESSIONCHANGEDELAY), e.g. right after login or boarding, so it is asked again.
    for k in range(tries):
        if not (session.stationid or session.structureid):
            break
        uicore.cmd.CmdExitStation()
        up_wait(lambda: not session.stationid and not session.structureid and up_bp(), 20000)
    if session.stationid or session.structureid:
        raise RuntimeError('still docked after %d undock tries' % tries)
    up_sleep(12000)
    return session.solarsystemid


def up_move_away(km):
    # GM setup: moves the test ship to a fresh spot; structures need 1,000 km from each other
    # and from celestials (structures/deployment.py CATEGORY_DISTANCES).
    return up_slash('/tr me offset=%d,0,%d' % (km * 1000, km * 1000))


def up_deploy(typeID, name, weekday=4, hour=18):
    # The deploy window (structureDeployment.Deploy), its placement entity moved out along -x
    # until the client's own FindDeploymentConflict reports no conflict, then ConfirmDeployment,
    # which sends structureDeployment.Anchor(...).
    item = [i for i in up_cargo() if i.typeID == typeID][0]
    sd = sm.GetService('structureDeployment')
    if sd.IsDeploying():
        sd.CancelDeployment()
    # Deploy returns without opening its window while the ship is not yet in space after a
    # session change or a move (InShipInSpace, the inflight view); try again until it opens.
    for k in range(10):
        sd.Deploy(item)
        if up_wait(lambda: sd.entity is not None, 3000, 250):
            break
        up_sleep(3000)
    up_sleep(2000)
    e = sd.entity
    if e is None:
        raise RuntimeError('the deploy window did not open for %s' % typeID)
    e.movingOffset = (0, 0, 0)
    radius = evetypes.GetRadius(typeID)
    shipRadius = up_bp().GetBall(session.shipid).radius
    conflict = None
    for extra in (6000, 10000, 20000, 50000, 100000, 200000):
        e.UpdateModelPosition((-(radius + shipRadius + extra), 0.0, 0.0))
        e.UpdateModel()
        conflict = e.FindDeploymentConflict()
        if conflict is None:
            break
    if conflict is not None:
        sd.CancelDeployment()
        raise RuntimeError('no free spot to deploy %s: %r' % (typeID, conflict))
    before = set(k for k, v in up_bp().slimItems.items() if v.categoryID == const.categoryStructure)
    sd.ConfirmDeployment(weekday, hour, None, name, 'client check')
    new = up_wait(lambda: [k for k, v in up_bp().slimItems.items() if v.categoryID == const.categoryStructure and k not in before], 20000)
    structureID = new[0]
    up_log('deployed', typeID, structureID, up_state(structureID))
    return structureID


def up_timer(structureID, seconds=3):
    # The client's GM structure menu: sm.RemoteSvc('slash').SlashCmd('/structure timer %d %d').
    reply = sm.RemoteSvc('slash').SlashCmd('/structure timer %d %d' % (structureID, seconds))
    up_log('timer', structureID, reply)
    return reply


def up_walk(structureID, until=(110,), max_steps=6):
    # Runs the structure's timers down one at a time until its state is in `until`.
    path = [up_state(structureID)[0]]
    for k in range(max_steps):
        if path[-1] in until:
            break
        old = path[-1]
        up_timer(structureID, 3)
        up_wait(lambda: up_state(structureID)[0] != old, 20000)
        path.append(up_state(structureID)[0])
        if path[-1] == old:
            break
    return path


def up_dock(structureID, timeout_ms=280000):
    if session.structureid == structureID:
        return True
    uthread.new(up_move.DockOrJumpOrActivateGate, structureID)
    return bool(up_wait(lambda: session.structureid == structureID, timeout_ms, 1000))


def up_control(structureID):
    if session.shipid != structureID:
        # The cache only learns corp-owned fitting moves made while in control
        # (invCache._ProcessItemChange); start from a clean listing.
        sm.GetService('invCache').InvalidateLocationCache(structureID)
        sm.GetService('structureControl').TakeControl(structureID)
        up_wait(lambda: session.shipid == structureID, 20000)
        up_sleep(3000)
    return session.shipid == structureID


def up_release():
    if session.structureid and session.shipid == session.structureid:
        sm.GetService('structureControl').ReleaseControl()
        up_wait(lambda: session.shipid != session.structureid, 20000)
    return session.shipid


def up_insert_core(structureID):
    coreTypeID = UP_CORE[up_slim(structureID).typeID if up_slim(structureID) else up_info(structureID).typeID]
    have = [i for i in up_ic.StructureDeedBay(structureID).GetItems()]
    if have:
        return have[0].itemID
    up_hangar_give(coreTypeID, 1)
    core = up_wait(lambda: [i for i in up_hangar_items(coreTypeID)], 10000)[0]
    up_ic.StructureDeedBay(structureID).AddItems([core])
    return up_wait(lambda: [i.itemID for i in up_ic.StructureDeedBay(structureID).GetItems()], 10000)


def up_fuel_count(structureID):
    return sum(i.stacksize for i in up_ic.StructureFuelBay(structureID).GetItems())


def up_add_fuel(structureID, qty, typeID=FUEL_HELIUM):
    up_hangar_give(typeID, qty)
    stacks = up_wait(lambda: [i for i in up_hangar_items(typeID)], 10000)
    before = up_fuel_count(structureID)
    up_ic.StructureFuelBay(structureID).AddItems(stacks)
    up_wait(lambda: up_fuel_count(structureID) >= before + qty, 15000)
    return up_fuel_count(structureID)


def up_dogma():
    return sm.GetService('clientDogmaIM').GetDogmaLocation()


def up_fitted(structureID):
    try:
        items = up_dogma().GetDogmaItem(structureID).GetFittedItems()
    except KeyError:
        return {}
    return dict((k, (v.typeID, v.flagID)) for k, v in items.items() if v.flagID in UP_FLAG_SERVICE or v.flagID in UP_FLAG_RIG)


def up_fit(structureID, typeID, flagID):
    # The fitting window's drop: invCache structure inventory Add, while in control.
    up_hangar_give(typeID, 1)
    item = up_wait(lambda: [i for i in up_hangar_items(typeID)], 10000)[0]
    try:
        sm.GetService('invCache').GetInventoryFromId(structureID).Add(item.itemID, item.locationID, qty=1, flag=flagID)
    except Exception as e:
        up_log('fit refused', typeID, flagID, repr(e))
        return repr(e)
    ok = up_wait(lambda: item.itemID in up_fitted(structureID), 10000)
    return item.itemID if ok else 'not in fitting after Add'


def up_online(moduleID):
    # A service module that fits while the bay can pay onlines on its own; the button is then
    # already lit and a second online would only raise EffectAlreadyActive2.
    if up_dogma().GetDogmaItem(moduleID).IsOnline():
        return 'auto'
    try:
        up_dogma().OnlineModule(moduleID)
    except Exception as e:
        return repr(e)
    return bool(up_wait(lambda: up_dogma().GetDogmaItem(moduleID).IsOnline(), 10000))


def up_attrs(structureID):
    dl = up_dogma()
    out = {}
    for name, attributeID in UP_ATTR.items():
        try:
            out[name] = dl.GetAttributeValue(structureID, attributeID)
        except Exception as e:
            out[name] = repr(e)
    return out


def up_static_attrs(typeID):
    return dict((name, up_static(typeID, attributeID, None)) for name, attributeID in UP_ATTR.items())


def up_outfit(structureID, fuel_blocks=200000):
    # Fits every service this hull takes (one of each) and its three rigs, fuels the bay and
    # onlines the services. Returns what happened per module and the fuel each online took.
    typeID = up_slim(structureID).typeID if up_slim(structureID) else up_info(structureID).typeID
    report = {'services': [], 'rigs': [], 'refused': []}
    # Fuel goes in docked, before control: with the structure as the active ship the client's
    # godma has no capacity slot for the fuel bay (RuntimeError BadSlotForCapacity 172).
    up_release()
    up_add_fuel(structureID, fuel_blocks)
    up_control(structureID)
    slots = int(up_static(typeID, UP_ATTR['serviceSlots'], 0) or 0)
    used = [f for (t, f) in up_fitted(structureID).values()]
    flags = [f for f in UP_FLAG_SERVICE[:slots] if f not in used]
    for moduleTypeID in UP_SERVICES_BY_TYPE.get(typeID, UP_SERVICES):
        if not flags:
            break
        if moduleTypeID in [t for (t, f) in up_fitted(structureID).values()]:
            continue
        if not up_can_fit(moduleTypeID, typeID):
            continue
        flag = flags[0]
        before = up_fuel_count(structureID)
        res = up_fit(structureID, moduleTypeID, flag)
        if not isinstance(res, (int, long)):
            report['refused'].append((moduleTypeID, res))
            continue
        flags.pop(0)
        on = up_online(res)
        up_sleep(1500)
        # Fuel the server took to online it, against the client's own dogma value (2110).
        clientOnlineFuel = up_dogma().GetAttributeValue(res, 2110)
        report['services'].append((moduleTypeID, res, on, before - up_fuel_count(structureID), clientOnlineFuel))
    rigSize = int(up_static(typeID, UP_ATTR['rigSize'], 0) or 0)
    usedRigs = [f for (t, f) in up_fitted(structureID).values() if f in UP_FLAG_RIG]
    usedRigTypes = [t for (t, f) in up_fitted(structureID).values() if f in UP_FLAG_RIG]
    rigChoices = [r for r in UP_RIGS_BY_TYPE.get(typeID, UP_RIGS.get(rigSize, [])) if r not in usedRigTypes]
    for flag, rigTypeID in zip([f for f in UP_FLAG_RIG if f not in usedRigs], rigChoices):
        res = up_fit(structureID, rigTypeID, flag)
        report['rigs'].append((rigTypeID, flag, res))
    info = up_info(structureID)
    now = blue.os.GetWallclockTime()
    report['fuel'] = up_fuel_count(structureID)
    report['fuelDays'] = (info.fuelExpires - now) / (864000000000.0) if info.fuelExpires else None
    report['upkeep'] = info.upkeepState
    report['state'] = info.state
    report['services_online'] = sm.RemoteSvc('structureSettings').CharacterGetServices(structureID)
    return report


def up_check_stats(structureID):
    # Live dogma values against the type's static data (client's own clientDogmaStaticSvc).
    typeID = up_slim(structureID).typeID if up_slim(structureID) else up_info(structureID).typeID
    live = up_attrs(structureID)
    static = up_static_attrs(typeID)
    diffs = {}
    for k in ('shieldCap', 'armorCap', 'hullCap', 'serviceSlots', 'rigSlots', 'rigSize', 'core'):
        if static.get(k) is not None and live.get(k) != static.get(k):
            diffs[k] = (live.get(k), static.get(k))
    return {'typeID': typeID, 'live': live, 'static': static, 'diffs': diffs}


def up_build_a(typeID, name, move_km=3000, warp_to=None):
    # Part one of putting up a structure: hull into the freighter, undock, move to a clear spot
    # (or warp to warp_to, e.g. a moon mining beacon for a refinery), deploy, run the anchor
    # timers down to onlining, dock. Leaves agent.up_current set.
    up_board_freighter()
    up_load_hull(typeID)
    up_undock()
    if warp_to:
        up_warp_to(warp_to, 0)
        up_sleep(4000)
        structureID = up_deploy(typeID, name)
    else:
        # A hop can land within 1,000 km of a structure an earlier run left; hop on.
        for hop in range(4):
            up_move_away(move_km)
            up_sleep(4000)
            try:
                structureID = up_deploy(typeID, name)
                break
            except RuntimeError as e:
                if hop == 3 or 'no free spot' not in str(e):
                    raise
                up_log('hop again', typeID, str(e))
    path = up_walk(structureID, until=(102, 110))
    docked = up_dock(structureID)
    agent.up_current = {'typeID': typeID, 'structureID': structureID, 'name': name,
                        'deployPath': path, 'docked': docked}
    return agent.up_current


def up_build_b(fuel_blocks=200000):
    # Part two: core in, run the core's repair timer down to shield_vulnerable, fit every service
    # and three rigs, fuel, online, read stats, release control.
    cur = agent.up_current
    structureID = cur['structureID']
    cur['core'] = up_insert_core(structureID)
    cur['onlinePath'] = up_walk(structureID, until=(110,))
    cur['outfit'] = up_outfit(structureID, fuel_blocks)
    cur['stats'] = up_check_stats(structureID)
    up_release()
    return cur


# ---- Moon mining -------------------------------------------------------------------------

def up_board_ship(typeName, typeID):
    # GM setup: a hull spawned into the hangar where the pilot is docked, then boarded.
    up_slash('/ship %s' % typeName)
    hull = up_wait(lambda: up_ship_hangar(typeID), 15000)[-1]
    return up_board(hull)


def up_hud_module(typeID):
    out = []
    def walk(n):
        mi = getattr(n, 'moduleinfo', None)
        if mi is not None and hasattr(n, 'ActivateModule') and mi.typeID == typeID:
            out.append(n)
        for c in getattr(n, 'children', []) or []:
            walk(c)
    walk(uicore.layer.shipui)
    return out[0] if out else None


def up_surveyor():
    # GM setup: a Heron with a Survey Probe Launcher II and Gaze Survey Probes in the hold.
    up_board_ship('Heron', 605)
    up_slash('/fit me 33272')
    up_hangar_give(18637, 20)
    probes = up_wait(lambda: up_hangar_items(18637), 10000)[0]
    sm.GetService('invCache').GetInventoryFromId(session.shipid).Add(probes.itemID, probes.locationID, qty=probes.stacksize, flag=const.flagCargo)
    up_sleep(2000)
    return session.shipid


def up_warp_to(itemID, distance=0, timeout_ms=200000):
    up_move.WarpToItem(itemID, distance)
    up_wait(lambda: up_bp().GetBall(session.shipid).mode == 3, 20000)
    up_wait(lambda: up_bp().GetBall(session.shipid).mode != 3, timeout_ms, 1000)
    up_sleep(2000)
    return int(up_bp().DistanceBetween(session.shipid, itemID))


def up_survey(moonID, timeout_ms=280000):
    # Loads Gaze probes into the launcher and fires it at the moon the ship faces, as the HUD
    # button does; the server answers OnNewMoonProbe, then OnMoonScanComplete(moonID, results).
    svc = sm.GetService('moonScan')
    launcher = [m for m in up_dogma().GetDogmaItem(session.shipid).GetFittedItems().values() if m.typeID == 33272][0]
    up_dogma().LoadAmmoTypeToModule(launcher.itemID, 18637)
    up_sleep(4000)
    sm.GetService('menu').AlignTo(moonID)
    up_sleep(8000)
    btn = up_hud_module(33272)
    uthread.new(btn.ActivateModule)
    got = up_wait(lambda: svc.GetScans().get(moonID), timeout_ms, 2000)
    return dict(got) if got else {'scans': dict(svc.GetScans())}


def up_moon_beacon(moonID):
    from moonmining.miningBeacons import GetMiningBeaconPositionForMoon
    return GetMiningBeaconPositionForMoon(moonID)


def up_extraction(structureID):
    # The moon scheduling window's calls act on the structure the pilot controls.
    return sm.RemoteSvc('moonExtractions').GetExtractionAndEventIDFromStructureID()


def up_start_extraction(structureID, seconds):
    return sm.RemoteSvc('moonExtractions').StartNewExtraction(structureID, seconds, False)


def up_moon_resources():
    return sm.RemoteSvc('moonExtractions').GetMoonResourcesForStructure()


def up_miner():
    # GM setup: a Retriever with two Strip Miner I, boarded where the pilot is docked.
    up_board_ship('Retriever', 17478)
    up_slash('/fit me 17482')
    up_slash('/fit me 17482')
    up_sleep(2000)
    return session.shipid


def up_field_rocks(near_id):
    bp = up_bp()
    return sorted([(int(bp.DistanceBetween(near_id, k)), k, bp.slimItems[k].typeID) for k in bp.slimItems
                   if bp.slimItems[k].categoryID == const.categoryAsteroid])


def up_mine(rockID, seconds=200):
    # Approach the rock, lock it, start both strip miners on it from their HUD buttons, and let
    # them run; returns what the ore hold holds afterwards.
    up_move.Approach(rockID, 5000)
    up_wait(lambda: up_bp().DistanceBetween(session.shipid, rockID) < 14000, 240000, 1000)
    ts = sm.GetService('target')
    uthread.new(ts.TryLockTarget, rockID)
    up_wait(lambda: rockID in ts.GetTargets(), 30000)
    ts.SetActiveTarget(rockID) if hasattr(ts, 'SetActiveTarget') else None
    btns = []
    def walk(n):
        mi = getattr(n, 'moduleinfo', None)
        if mi is not None and hasattr(n, 'ActivateModule') and mi.typeID == 17482:
            btns.append(n)
        for c in getattr(n, 'children', []) or []:
            walk(c)
    walk(uicore.layer.shipui)
    for b in btns:
        uthread.new(b.ActivateModule)
        up_sleep(1000)
    up_sleep(seconds * 1000)
    return up_ore_hold()


def up_ore_hold():
    inv = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    return [(i.typeID, evetypes.GetName(i.typeID), i.stacksize) for i in inv.List() if i.flagID in (const.flagCargo, 134)]


def up_reprocess(typeIDs):
    # The reprocessing window's calls: GetQuotes(itemIDs, activeShipID) then
    # Reprocess(itemIDs, fromLocation, ownerID, outputLocationID, outputFlagID), for ore in the
    # hangar of the structure the pilot is docked in.
    svc = sm.GetService('reprocessing').GetReprocessingSvc()
    items = [i for i in up_hangar_items() if i.typeID in typeIDs]
    ids = [i.itemID for i in items]
    tax, efficiency, quotes = svc.GetQuotes(ids, session.shipid)
    before = dict((i.typeID, i.stacksize) for i in up_hangar_items())
    svc.Reprocess(ids, session.structureid, session.charid, session.structureid, const.flagHangar)
    up_sleep(4000)
    after = {}
    for i in up_hangar_items():
        after[i.typeID] = after.get(i.typeID, 0) + i.stacksize
    return {'tax': tax, 'efficiency': efficiency, 'quotes': quotes, 'in': [(i.typeID, i.stacksize) for i in items],
            'out': dict((evetypes.GetName(t), q) for t, q in after.items() if t not in before)}


# ---- Siege -------------------------------------------------------------------------------

def up_hud_buttons(typeIDs):
    out = []
    def walk(n):
        mi = getattr(n, 'moduleinfo', None)
        if mi is not None and hasattr(n, 'ActivateModule') and mi.typeID in typeIDs:
            out.append(n)
        for c in getattr(n, 'children', []) or []:
            walk(c)
    walk(uicore.layer.shipui)
    return out


def up_load_turrets(turretTypeID, chargeTypeID):
    dl = up_dogma()
    turrets = [m for m in dl.GetDogmaItem(session.shipid).GetFittedItems().values() if m.typeID == turretTypeID]
    for m in turrets:
        try:
            dl.LoadAmmoTypeToModule(m.itemID, chargeTypeID)
        except Exception as e:
            up_log('load', m.itemID, repr(e))
        up_sleep(1500)
    return [m.itemID for m in turrets]


def up_attack(targetID, turretTypeID, siegeTypeID=None):
    # Lock the target and start the guns from their HUD buttons (and the siege module), the way a
    # pilot clicks them; the guns then repeat on their own.
    ts = sm.GetService('target')
    if targetID not in ts.GetTargets():
        uthread.new(ts.TryLockTarget, targetID)
        up_wait(lambda: targetID in ts.GetTargets(), 60000)
    started = []
    if siegeTypeID:
        for b in up_hud_buttons([siegeTypeID]):
            if not b.def_effect.isActive:
                uthread.new(b.ActivateModule)
                started.append('siege')
        up_sleep(3000)
    for b in up_hud_buttons([turretTypeID]):
        if not b.def_effect.isActive:
            uthread.new(b.ActivateModule)
            started.append(b.moduleinfo.itemID)
            up_sleep(500)
    up_sleep(3000)
    # A "Proceed with this dangerous act?" style question blocks the guns; answer it.
    for w in uicore.registry.GetWindows():
        if getattr(w, 'name', '') in ('message', 'modal') or w.__class__.__name__ in ('MessageBox',):
            up_log('dialog', getattr(w, 'name', ''), getattr(w, 'caption', ''))
    return started


def up_layer_hp(structureID):
    # Shield, armor and hull hit points left, from the slim damage fractions and full-power HP.
    s = up_slim(structureID)
    dmg = getattr(s, 'damage', None)
    return dmg


def up_measure_dps(structureID, seconds=60):
    # Damage dealt over a window, from the server's structure HP readings in the client's ballpark
    # (michelle GetDamageState: fractions of shield, armor, hull).
    bp = up_bp()
    def hp():
        st = bp.GetDamageState(structureID)
        return st
    a = hp(); t0 = blue.os.GetWallclockTime()
    up_sleep(seconds * 1000)
    b = hp(); t1 = blue.os.GetWallclockTime()
    return {'before': a, 'after': b, 'seconds': (t1 - t0) / 1e7}


# ---- Scenario helpers ----------------------------------------------------------------------

def up_pilot_setup(corpName, ticker, stationID):
    # GM setup for a scenario pilot: every skill, ISK, docked at stationID, and a player corp of
    # its own made through the client's corp service (AddCorporation). Safe to run again.
    if not agent.__dict__.get('up_skills_done'):
        up_slash('/giveskill me all 5')
        agent.up_skills_done = True
    if sm.GetService('wallet').GetWealth() < 100000000000:
        up_slash('/addisk 500000000000')
    if session.stationid != stationID and session.structureid is None:
        up_slash('/tr me %d' % stationID)
        up_wait(lambda: session.stationid == stationID, 30000)
        up_sleep(12000)
    from inventorycommon.util import IsNPC
    if IsNPC(session.corpid):
        sm.GetService('corp').AddCorporation(corpName, ticker, 'client check')
        up_wait(lambda: not IsNPC(session.corpid), 20000)
    for w in [w for w in uicore.registry.GetWindows() if getattr(w, 'name', '') == 'TaskConversationWindow']:
        w.Close()
    return (session.corpid, session.stationid or session.structureid)


def up_built_ok():
    # Whether the last up_build_b left a structure online at full power, with every fitted
    # service online for exactly the fuel the client's own dogma says (attribute 2110), a fuel
    # expiry in the structure browser, and live stats equal to the type's static data.
    cur = agent.up_current
    o = cur.get('outfit') or {}
    services = o.get('services') or []
    fuel_ok = all(int(round(s[4])) == s[3] or (s[2] == 'auto' and s[3] >= int(s[4])) for s in services)
    ok = (cur.get('onlinePath', [None])[-1] == 110 and o.get('upkeep') == 1 and len(services) > 0 and
          fuel_ok and (o.get('fuelDays') or 0) > 1 and not (cur.get('stats') or {}).get('diffs'))
    up_log('built', cur.get('typeID'), cur.get('structureID'), ok, services, o.get('fuelDays'))
    return ok


def up_attacker_setup(corpName, ticker, warHQStation):
    return up_pilot_setup(corpName, ticker, warHQStation)


def up_declare_war(againstCorpID, warHQ, fund=2000000000.0):
    # The corp wallet UI's transfer to the master wallet, then the war window's declare.
    sm.RemoteSvc('account').GiveCash(session.corpid, fund, 'war chest', toAccountKey=1000)
    up_sleep(2000)
    war = sm.GetService('corp').DeclareWarAgainst(againstCorpID, warHQ)
    agent.up_war = war
    return war.warID


def up_dread():
    # GM setup: Revelation with three Dual Giga Pulse Laser II, Siege Module II, three Heat Sink
    # II, Multifrequency XL (T1 crystals do not burn out) and strontium for the siege.
    up_board_ship('Revelation', 19720)
    for t in (37298, 37298, 37298, 4292, 2364, 2364, 2364):
        up_slash('/fit me %d' % t)
    up_hangar_give(17686, 30)
    cr = up_wait(lambda: up_hangar_items(17686), 10000)[0]
    sm.GetService('invCache').GetInventoryFromId(session.shipid).Add(cr.itemID, cr.locationID, qty=cr.stacksize, flag=const.flagCargo)
    up_sleep(2000)
    up_load_turrets(37298, 17686)
    return session.shipid


def up_strontium(qty=500):
    return up_slash('/giveitem 16275 %d' % qty)


def up_shoot_layer(structureID, layer, leave_fraction=0.01, real_seconds=60):
    # The hybrid siege the owner chose: real fire for real_seconds, then a logged GM
    # /upwell damage leaving leave_fraction of the layer, then real fire until the state moves on.
    index = {'shield': 0, 'armor': 1, 'hull': 2}[layer]
    # The attacker's client has no dogma for the target, so the layer's size is the type's static
    # hit points, times 4 for shield and armor at full power (the service modules'
    # serviceModuleFullPowerStateHitpointMultiplier, as the owner's dogma showed on every hull).
    typeID = up_slim(structureID).typeID
    maxHP = up_static(typeID, UP_ATTR[layer], 0)
    if layer != 'hull' and up_state(structureID)[2] == 1:
        maxHP *= 4
    up_strontium(300)
    up_attack(structureID, 37298, 4292)
    before = up_bp().GetDamageState(structureID)[index]
    up_sleep(real_seconds * 1000)
    after = up_bp().GetDamageState(structureID)[index]
    state = up_state(structureID)[0]
    left = up_bp().GetDamageState(structureID)[index] * maxHP
    up_slash('/upwell damage %d %s %d' % (structureID, layer, max(0, int(left - leave_fraction * maxHP))))
    up_attack(structureID, 37298, 4292)
    moved = up_wait(lambda: structureID not in up_bp().slimItems or up_state(structureID)[0] != state, 200000, 2000)
    return {'realDamage': (before - after) * maxHP, 'seconds': real_seconds, 'moved': bool(moved),
            'state': None if structureID not in up_bp().slimItems else up_state(structureID)}


def up_find_structure(nameFragment):
    # A structure in the current system by name, from the ballpark (Upwell structures are seen
    # system-wide).
    bp = up_bp()
    hits = [k for k, v in bp.slimItems.items() if v.categoryID == const.categoryStructure and nameFragment in (getattr(v, 'name', '') or '')]
    return hits[0] if hits else None


def up_drain_fuel(structureID, keep):
    # Drags all but `keep` blocks out of the fuel bay into the hangar, while docked.
    up_release()
    inv = sm.GetService('invCache').GetInventoryFromId(structureID)
    left = up_fuel_count(structureID)
    for st in list(up_ic.StructureFuelBay(structureID).GetItems()):
        take = min(st.stacksize, left - keep)
        if take > 0:
            inv.Add(st.itemID, structureID, qty=take, flag=const.flagHangar)
            left -= take
    up_wait(lambda: up_fuel_count(structureID) <= keep, 15000)
    return up_fuel_count(structureID)


agent.up_ready = True
result = 'upwell driver loaded'
