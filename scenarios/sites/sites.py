# Site driver: universe sites in a real EVE client (EvEJS). Loaded into the client agent's
# namespace by the site scenarios. Player actions go through the client's own services:
# michelle's remote park (CmdWarpToStuff, as a scanned result's Warp To calls it), the target
# service, the HUD module buttons, the drone functions (EngageTarget, as the drone window's menu)
# and dungeonTracking (what the objective panel reads). GM slash commands only set the stage:
# skills, a ship, moving between systems.
import blue, uthread, evetypes

SITE_HOME = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
SITE_DRONE_PREFIX = 'Hobgoblin'


def site_sleep(ms):
    blue.pyos.synchro.SleepWallclock(ms)


def site_wait(fn, ms=60000, every=500):
    end = blue.os.GetWallclockTime() + ms * 10000
    while blue.os.GetWallclockTime() < end:
        try:
            value = fn()
        except Exception:
            value = None
        if value:
            return value
        site_sleep(every)
    raise AssertionError('timed out after %d ms' % ms)


def site_slash(text):
    return sm.GetService('slash').SlashCmd(text)


def site_bp():
    return sm.GetService('michelle').GetBallpark()


def site_in_space():
    bp = site_bp()
    return session.stationid is None and session.structureid is None and bp is not None and session.shipid in bp.balls


def site_dock_home():
    if session.stationid == SITE_HOME:
        return True
    site_slash('/tr me %d' % SITE_HOME)
    site_wait(lambda: session.stationid == SITE_HOME, 60000)
    site_sleep(12000)
    return True


def site_board(shipID):
    # The hangar's Make Active: station.TryActivateShip with the inventory row.
    site_dock_home()
    if session.shipid != shipID:
        inv = sm.GetService('invCache').GetInventory(const.containerHangar)
        row = [i for i in inv.List(const.flagHangar) if i.itemID == shipID][0]
        uthread.new(sm.GetService('station').TryActivateShip, row)
        site_wait(lambda: session.shipid == shipID, 30000)
        site_sleep(2000)
    return session.shipid


def site_undock():
    if site_in_space():
        return True
    uicore.cmd.CmdExitStation()
    site_wait(site_in_space, 60000, 1000)
    site_sleep(11000)
    return True


def site_goto_system(systemID):
    if session.solarsystemid2 == systemID and site_in_space():
        return True
    site_slash('/tr me %d' % systemID)
    site_wait(lambda: session.solarsystemid2 == systemID and site_in_space(), 60000, 1000)
    site_sleep(12000)
    return True


def site_warp_to(siteID, timeout_ms=180000):
    # A scanned signature's Warp To: the server materializes the site on this warp.
    sm.GetService('michelle').GetRemotePark().CmdWarpToStuff('item', siteID)
    site_sleep(4000)
    site_wait(lambda: site_bp().GetBall(session.shipid).mode != 3, timeout_ms, 2000)
    site_sleep(5000)
    return True


def site_entities(names=None):
    bp = site_bp()
    rows = []
    for itemID, slim in bp.slimItems.items():
        if itemID == session.shipid or itemID not in bp.balls:
            continue
        name = evetypes.GetName(slim.typeID)
        if names and name not in names:
            continue
        rows.append((bp.DistanceBetween(session.shipid, itemID), itemID, name, slim))
    return sorted(rows)


def site_npcs(exclude=()):
    return [row for row in site_entities() if row[3].categoryID == const.categoryEntity and row[2] not in exclude]


def site_dungeon():
    # What the objective panel reads (dungeonTracking.ActiveDungeon).
    current = sm.GetService('dungeonTracking').current_dungeon
    if not current:
        return None
    return {'dungeonID': current.dungeon_id, 'title': current.title, 'values': dict(current._context.values)}


def site_drones_out():
    bp = site_bp()
    return [i for i, s in bp.slimItems.items() if s.categoryID == const.categoryDrone and getattr(s, 'ownerID', 0) == session.charid]


def site_restock_drones(count=10):
    # The Rampant drones shoot drones too; refill the bay with the GM /create (into cargo) and
    # move them to the drone bay as the cargo window's drag does (setup help, not the check).
    inv = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    if inv.List(const.flagDroneBay):
        return False
    typeName = '%s II' % SITE_DRONE_PREFIX
    site_slash('/create %s %d' % (typeName, count))
    site_sleep(2000)
    for item in inv.List(const.flagCargo):
        if evetypes.GetName(item.typeID) == typeName:
            inv.Add(item.itemID, session.shipid, qty=item.stacksize, flag=const.flagDroneBay)
    site_sleep(2000)
    return True


def site_launch_drones():
    from eve.client.script.util import eveMisc
    if site_drones_out():
        return site_drones_out()
    site_restock_drones()
    bay = sm.GetService('invCache').GetInventoryFromId(session.shipid).List(const.flagDroneBay)
    # Light drones keep up with the fast Rampant frigates (Hammerheads did ~23 DPS on an
    # orbiting Corrupted Handler); launch the preferred kind when the bay has it.
    preferred = [i for i in bay if evetypes.GetName(i.typeID).startswith(SITE_DRONE_PREFIX)]
    eveMisc.LaunchFromShip(preferred or bay)
    return site_wait(lambda: site_drones_out(), 20000)


def site_hud_buttons():
    found = []

    def walk(node):
        if getattr(node, 'moduleinfo', None) is not None and hasattr(node, 'ActivateModule'):
            found.append(node)
        for child in getattr(node, 'children', []) or []:
            walk(child)
    walk(uicore.layer.shipui)
    return found


def site_answer_yes():
    for wnd in uicore.registry.GetWindows():
        if getattr(wnd, 'name', '') == 'modal':
            for node in wnd.Find('trinity.Tr2Sprite2dContainer') if hasattr(wnd, 'Find') else []:
                pass
    modal = uicore.registry.GetModalWindow()
    if modal and hasattr(modal, 'SetModalResult'):
        modal.SetModalResult(uiconst.ID_YES)
        return True
    return False


def site_kill(targetID, timeout_ms=90000, modules=('Stasis Webifier',)):
    # Lock, send the drones (the drone window's Engage Target), web it; wait for it to go.
    from eve.client.script.ui.services.menuSvcExtras import droneFunctions, movementFunctions
    ts = sm.GetService('target')
    if targetID not in site_bp().balls:
        return True
    movementFunctions.Orbit(targetID, 2500)
    if targetID not in ts.GetTargets():
        uthread.new(ts.TryLockTarget, targetID)
        site_wait(lambda: targetID in ts.GetTargets() or targetID not in site_bp().balls, 40000)
    if targetID not in site_bp().balls:
        return True
    drones = site_launch_drones()
    uthread.new(droneFunctions.EngageTarget, drones)
    for button in site_hud_buttons():
        name = evetypes.GetName(button.moduleinfo.typeID)
        if any(name.startswith(prefix) for prefix in modules) and not (button.def_effect and button.def_effect.isActive):
            uthread.new(button.ActivateModule)
    site_sleep(1500)
    site_answer_yes()
    end = blue.os.GetWallclockTime() + timeout_ms * 10000
    while blue.os.GetWallclockTime() < end and targetID in site_bp().balls:
        site_sleep(1000)
    return targetID not in site_bp().balls


TANK_PREFIXES = ('Medium Armor Repairer', 'Large Armor Repairer', 'Small Armor Repairer', 'Multispectrum',
                 'Damage Control', 'Shield Booster', 'Medium Shield Booster', 'Large Shield Booster')


def site_tank():
    # Start the ship's repairers and hardeners through their HUD buttons (they repeat).
    started = []
    for button in site_hud_buttons():
        name = evetypes.GetName(button.moduleinfo.typeID)
        if any(name.startswith(prefix) for prefix in TANK_PREFIXES) and not (button.def_effect and button.def_effect.isActive):
            uthread.new(button.ActivateModule)
            started.append(name)
    return started


def site_repair():
    # Keep the test ship alive between waves: the GM /heal (setup only, not the behaviour checked).
    return site_slash('/heal')


# ---------- Rampant Drone Fabricator (EvEJS PR 379) ----------

FAB_NAME = 'Rampant Fabricator'
FAB_PROBES = []


def fab_values():
    d = site_dungeon()
    return d and d['values']


def fab_id():
    rows = site_entities([FAB_NAME])
    return rows[0][1] if rows else None


def fab_health():
    fab = fab_id()
    return [round(x, 4) for x in site_bp().GetDamageState(fab)[:3]] if fab else None


def fab_clear_wave(timeout_ms=240000):
    # Kill every hostile on grid with real fire (the Fabricator counts its own kills, so a GM
    # clear does not advance it).
    end = blue.os.GetWallclockTime() + timeout_ms * 10000
    killed = 0
    while blue.os.GetWallclockTime() < end:
        npcs = site_npcs(exclude=(FAB_NAME,))
        if not npcs:
            return killed
        site_tank()
        if site_kill(npcs[0][1], 90000):
            killed += 1
        site_repair()
    raise AssertionError('wave not cleared in time: %r' % [row[2] for row in site_npcs(exclude=(FAB_NAME,))])


def fab_shoot_fabricator(seconds=20):
    # Lock the Fabricator and send the drones at it; answer how its health moved.
    from eve.client.script.ui.services.menuSvcExtras import droneFunctions
    fab = fab_id()
    ts = sm.GetService('target')
    before = fab_health()
    if fab not in ts.GetTargets():
        uthread.new(ts.TryLockTarget, fab)
        site_wait(lambda: fab in ts.GetTargets(), 40000)
    uthread.new(droneFunctions.EngageTarget, site_launch_drones())
    site_sleep(1500)
    site_answer_yes()
    site_sleep(seconds * 1000)
    return (before, fab_health())


def fab_run_to_wave(last_wave=5, timeout_ms=1500000, probe_waves=(), probe_seconds=14):
    # Fight waves until wave last_wave is cleared; answer each wave's record. After clearing a
    # wave in probe_waves (and wave last_wave), shoot the Fabricator in the 20 s break and
    # record its health before and after (FAB_PROBES).
    record = []
    end = blue.os.GetWallclockTime() + timeout_ms * 10000
    while blue.os.GetWallclockTime() < end:
        values = fab_values() or {}
        state, wave = values.get('dungeon_state'), values.get('wave_number', 0)
        if state not in ('Wave', 'Initialising', 'Cooldown', None) and not str(state).startswith('Wave'):
            raise AssertionError('site ended: %r at wave %r (%r)' % (state, wave, record))
        npcs = site_npcs(exclude=(FAB_NAME,))
        if npcs:
            killed = fab_clear_wave(1200000)
            record.append((wave, killed, fab_health()))
            if wave in probe_waves or wave >= last_wave:
                FAB_PROBES.append((wave, (fab_values() or {}).get('dungeon_state'), fab_shoot_fabricator(probe_seconds)))
            if wave >= last_wave:
                return record
        else:
            site_tank()
            site_sleep(2000)
    raise AssertionError('timed out: %r' % record)


SITE_GUARD = {'on': False, 'heals': 0}


def site_guard(on=True, armor_floor=0.5):
    # A background watch that keeps the test ship alive: the GM /heal (which also refills the
    # capacitor the repairers drain) whenever armor falls under the floor, then restarts the
    # tank. Only for checks about a site, never for checks about the ship's own tank.
    SITE_GUARD['on'] = on
    if not on or SITE_GUARD.get('running'):
        return SITE_GUARD

    def watch():
        SITE_GUARD['running'] = True
        try:
            while SITE_GUARD['on']:
                try:
                    if site_in_space():
                        state = site_bp().GetDamageState(session.shipid)
                        if state and (state[1] < armor_floor or state[2] < 1.0):
                            site_repair()
                            SITE_GUARD['heals'] += 1
                            site_sleep(1000)
                            site_tank()
                except Exception:
                    pass
                site_sleep(2000)
        finally:
            SITE_GUARD['running'] = False
    uthread.new(watch)
    return SITE_GUARD


# ---------- scenario steps (scenarios/fabricator-waves.json) ----------

def site_board_type(typeName):
    # Board the newest hull of this type in the home hangar (the scenario's loadout puts it there).
    site_dock_home()
    inv = sm.GetService('invCache').GetInventory(const.containerHangar)
    rows = [i for i in inv.List(const.flagHangar) if i.categoryID == const.categoryShip and evetypes.GetName(i.typeID) == typeName and i.singleton]
    if not rows:
        raise AssertionError('no assembled %s in the home hangar' % typeName)
    return site_board(max(rows, key=lambda i: i.itemID).itemID)


def fab_site_id(systemID):
    # EvEJS numbers the Fabricator anomaly of a system 664<system - 30000000><nnn>; the
    # sensor suite lists it as an unscanned signature (no dungeon name until scanned).
    prefix = '664%d' % (systemID - 30000000)
    sites = [s.siteID for s in sm.GetService('sensorSuite').siteController.GetVisibleSites() if str(s.siteID).startswith(prefix)]
    if not sites:
        raise AssertionError('no Fabricator site visible in %d' % systemID)
    return min(sites)


def fab_step_arrive(systemID, typeName='Ishtar'):
    site_board_type(typeName)
    site_undock()
    site_goto_system(systemID)
    site_warp_to(fab_site_id(systemID))
    site_guard(True)
    site_tank()
    values = site_wait(lambda: (fab_values() or {}).get('dungeon_state') == 'Wave' and fab_values(), 60000)
    return values['wave_number'] == 1 and values['dungeonID'] if 'dungeonID' in values else values['wave_number'] == 1


def fab_step_waves(last_wave=5, probe_waves=(3, 4)):
    # Clear waves 1..last_wave with drones; the Fabricator must take no damage in the breaks
    # before wave 5 is cleared, and must take damage in the break after it.
    del FAB_PROBES[:]
    fab_run_to_wave(last_wave, 6000000, probe_waves=probe_waves)
    early = [p for p in FAB_PROBES if p[0] < 5]
    late = [p for p in FAB_PROBES if p[0] >= 5]
    invulnerable = all(p[2][0] == p[2][1] for p in early)
    vulnerable = bool(late) and any(after < before for before, after in zip(late[-1][2][0], late[-1][2][1]))
    if not (invulnerable and vulnerable):
        raise AssertionError('probes: %r' % FAB_PROBES)
    return True


FAB_RUN = {'done': False, 'error': None, 'result': None}


def fab_step_waves_start(last_wave=5, probe_waves=(3, 4)):
    # The waves take longer than one client eval may (300 s), so they run in a tasklet; the
    # scenario polls fab_step_poll() and ends with fab_step_result().
    FAB_RUN.update({'done': False, 'error': None, 'result': None})

    def run():
        try:
            FAB_RUN['result'] = fab_step_waves(last_wave, probe_waves)
        except Exception as error:
            FAB_RUN['error'] = repr(error)[:800]
        FAB_RUN['done'] = True
    uthread.new(run)
    return True


def fab_step_poll(seconds=280):
    # Wait up to seconds for the waves; fail only on an error, never because they are still going.
    end = blue.os.GetWallclockTime() + seconds * 10000000
    while blue.os.GetWallclockTime() < end and not FAB_RUN['done']:
        site_sleep(2000)
    return FAB_RUN['error'] is None


def fab_step_result():
    site_guard(False)
    if FAB_RUN['error']:
        raise AssertionError(FAB_RUN['error'])
    return FAB_RUN['done'] and FAB_RUN['result'] is True
