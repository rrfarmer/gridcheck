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
    # The drones this ship controls (michelle's drone state), not every drone the pilot owns:
    # drones left behind by a lost ship stay owned but take no orders.
    bp = site_bp()
    return [i for i in sm.GetService('michelle').GetDrones().keys() if i in bp.slimItems]


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
    while blue.os.GetWallclockTime() < end and targetID in site_bp().slimItems:
        site_sleep(1000)
    return targetID not in site_bp().slimItems


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


# ---------- Observatory Flashpoint (EvEJS PR 388) ----------

def fp_values():
    d = site_dungeon()
    return d and d['values']


def fp_gm_destroy(itemID):
    # gridutils' GM destroy (/heal <id> 0): the server's normal destruction owner, so the
    # Flashpoint's own kill hook still decides (and refuses an invulnerable role).
    return site_slash('/heal %d 0' % itemID)


def fp_hostiles(include=None, exclude=()):
    rows = site_npcs(exclude=exclude)
    if include:
        rows = [row for row in rows if any(part in row[2] for part in include)]
    return rows


def fp_clear(include=None, exclude=(), real=1, timeout_ms=600000):
    # Kill the first `real` hostiles with drones, then GM-destroy the rest one by one; answer
    # what each did. A refused destroy (an invulnerable role) is recorded, not retried.
    record = []
    refused = set()
    end = blue.os.GetWallclockTime() + timeout_ms * 10000
    while blue.os.GetWallclockTime() < end:
        rows = [row for row in fp_hostiles(include, exclude) if row[1] not in refused]
        if not rows:
            return record
        distance, itemID, name, slim = rows[0]
        if real > 0:
            site_tank()
            ok = site_kill(itemID, 240000)
            record.append((name, 'drones', ok))
            real -= 1
            continue
        reply = fp_gm_destroy(itemID)
        try:
            gone = site_wait(lambda: itemID not in site_bp().slimItems, 8000)
        except AssertionError:
            gone = False
        record.append((name, 'gm', gone, None if gone else str(reply)[:120]))
        if not gone:
            refused.add(itemID)
    raise AssertionError('not cleared: %r' % record)


def fp_gate():
    rows = [row for row in site_entities() if 'Conduit' in row[2] or row[3].groupID == const.groupWarpGate]
    return rows[0][1] if rows else None


def fp_take_gate(timeout_ms=120000):
    from eve.client.script.ui.services.menuSvcExtras import movementFunctions
    gate = fp_gate()
    if not gate:
        raise AssertionError('no gate on grid')
    before = site_bp().GetBall(session.shipid)
    uthread.new(sm.GetService('menu').ActivateAccelerationGate, gate)
    site_sleep(5000)
    site_wait(lambda: site_bp().GetBall(session.shipid).mode != 3 and fp_gate() != gate, timeout_ms, 2000)
    site_sleep(5000)
    return True


def fp_roles():
    # What is on grid now, by name, with health (the panel shows no slot roles).
    out = {}
    for distance, itemID, name, slim in site_entities():
        if slim.categoryID in (const.categoryEntity, const.categoryStructure, const.categoryStarbase, const.categoryDeployable) or 'Pylon' in name or 'Observatory' in name:
            out.setdefault(name, []).append((int(distance), itemID, [round(x, 3) for x in site_bp().GetDamageState(itemID)[:3]] if site_bp().GetDamageState(itemID) else None))
    return out


def fp_site_id(systemID):
    # EvEJS numbers regional Flashpoints 85000000000NN; take the one in this system from the
    # sensor suite (it lists them as signatures before scanning).
    sites = [s.siteID for s in sm.GetService('sensorSuite').siteController.GetVisibleSites() if str(s.siteID).startswith('850000000')]
    if not sites:
        raise AssertionError('no Flashpoint visible in %d' % systemID)
    return min(sites)


def fp_step_lobby(systemID, typeName='Ishtar'):
    # Board, fly in, clear the gate camp (GM), warp to the site: the lobby panel, the gate
    # unlocks once the Triglavian lobby wave is dead (one by drones, the rest GM-destroyed).
    site_board_type(typeName)
    site_undock()
    site_goto_system(systemID)
    for row in site_npcs():
        if row[0] < 150000:
            fp_gm_destroy(row[1])
    site_warp_to(fp_site_id(systemID))
    site_guard(True)
    site_tank()
    objectives = site_wait(lambda: (fp_values() or {}).get('objectives'), 30000)
    fp_clear(include=('Liminal',), real=1, timeout_ms=280000)
    return 'lobby_activate_gate' in objectives


def fp_step_pocket():
    # Gate into the pocket; the Werpost and the Observatory refuse destruction in phase 1;
    # the guards die (GM) and phase 2 brings the enemy dreadnought with the siege timer.
    g = fp_gate()
    uthread.new(sm.GetService('menu').ActivateAccelerationGate, g)
    site_wait(lambda: g not in site_bp().slimItems, 250000, 2000)
    site_wait(lambda: site_bp().GetBall(session.shipid).mode != 3, 60000, 2000)
    site_wait(lambda: (fp_values() or {}).get('dungeon_state') == 'Phase 1', 30000)
    roles = fp_roles()
    refused = [str(fp_gm_destroy(roles[name][0][1])) for name in ('Threshold Werpost', 'CONCORD Stellar Observatory')]
    if not all('FLASHPOINT_INVULNERABLE' in reply for reply in refused):
        raise AssertionError('phase 1 destroy not refused: %r' % refused)
    site_repair()
    fp_clear(include=('Navy',), real=0, timeout_ms=250000)
    values = site_wait(lambda: (fp_values() or {}).get('dungeon_state') == 'Phase 2' and fp_values(), 30000)
    return values.get('enemy_dread_on_grid') == 1 and values.get('siege_counter') is not None


def fp_step_observatory():
    # The dreadnought dies (GM) -> phase 3 with subpylons; at a subpylon the counter reads 1
    # and the client gets the Damage Bonus dbuff (2103); drones damage the Observatory.
    from eve.client.script.ui.services.menuSvcExtras import droneFunctions, movementFunctions
    dread = fp_values()['enemy_dread']['item_id']
    fp_gm_destroy(dread)
    site_wait(lambda: (fp_values() or {}).get('dungeon_state') == 'Phase 3', 30000)
    fp_clear(include=('Navy',), real=0, timeout_ms=200000)
    pylon = [row for row in site_entities() if 'Subpylon' in row[2]][0][1]
    movementFunctions.KeepAtRange(pylon, 1000)
    site_wait(lambda: (fp_values() or {}).get('subpylon_counter') == 1, 250000, 2000)
    dbuffs = dict(sm.GetService('dbuffClient').incomingDbuffTracker.incomingDbuffs)
    observatory = fp_values()['structure']['item_id']
    uthread.new(droneFunctions.EngageTarget, site_launch_drones())
    site_sleep(2000)
    site_answer_yes()
    before = site_bp().GetDamageState(observatory)[0]
    site_sleep(40000)
    after = site_bp().GetDamageState(observatory)[0]
    if 2103 not in dbuffs or not after < before:
        raise AssertionError('dbuffs %r, observatory shield %r -> %r' % (dbuffs, before, after))
    return True


def fp_step_complete():
    # A subpylon and the Observatory die (GM): "Success", the reward pays the pilot and the
    # Observatory wreck holds Stellar Surveillance Data.
    from eve.client.script.ui.services.menuSvcExtras import movementFunctions
    pylon = [row for row in site_entities() if 'Subpylon' in row[2]][0][1]
    fp_gm_destroy(pylon)
    site_wait(lambda: (fp_values() or {}).get('subpylons_destroyed') == 1, 20000)
    wealth = sm.GetService('wallet').GetWealth()
    fp_gm_destroy(fp_values()['structure']['item_id'])
    site_wait(lambda: (fp_values() or {}).get('dungeon_state') == 'Success', 30000)
    site_wait(lambda: sm.GetService('wallet').GetWealth() > wealth, 30000)
    wreck = site_wait(lambda: [row[1] for row in site_entities() if row[2] == 'CONCORD Stellar Observatory Wreck'], 30000)[0]
    movementFunctions.KeepAtRange(wreck, 1000)
    site_wait(lambda: site_bp().DistanceBetween(session.shipid, wreck) < 2400, 200000, 2000)
    loot = [evetypes.GetName(i.typeID) for i in sm.GetService('invCache').GetInventoryFromId(wreck).List()]
    site_guard(False)
    return 'Stellar Surveillance Data' in loot


# ---------- agent missions (the conversation window's own calls) ----------

def agent_do(agentID, actionID=None):
    # agentDialogueWindow.ExecuteAgentAction: ((agentSays, [(actionID, buttonID)]), info).
    return sm.GetService('agents').GetAgentMoniker(agentID).DoAction(actionID)


def agent_press(agentID, buttons, first=None):
    # Press the first offered action whose button ID is in buttons (appConst
    # agentDialogueButton*: 2 request/view mission, 3 accept, 6 complete, 9 decline...).
    (says, actions), info = agent_do(agentID, first)
    for actionID, button in actions:
        if button in buttons:
            return agent_do(agentID, actionID)
    raise AssertionError('no button %r among %r (%r)' % (buttons, actions, says))


def agent_journal(agentID):
    return sm.GetService('agents').GetAgentMoniker(agentID).GetMissionJournalInfo()


def agent_bookmark(agentID, locationType='dungeon'):
    bms = sm.GetService('bookmarkSvc').GetAgentBookmarks()
    rows = [b for b in (bms.values() if hasattr(bms, 'values') else bms)
            if getattr(b, 'agentID', 0) == agentID and getattr(b, 'locationType', None) == locationType]
    return rows[0] if rows else None


def agent_warp(agentID, locationType='dungeon', warpRange=0.0, timeout_ms=240000):
    # The journal's Warp To: movementFunctions.WarpToBookmark on the agent's bookmark.
    from eve.client.script.ui.services.menuSvcExtras import movementFunctions
    bm = agent_bookmark(agentID, locationType)
    if bm is None:
        raise AssertionError('no %s bookmark from agent %d' % (locationType, agentID))
    site_goto_system(bm.locationID if bm.locationID and bm.locationID < 40000000 else bm.solarsystemID)
    movementFunctions.WarpToBookmark(bm, warpRange)
    site_sleep(4000)
    site_wait(lambda: site_bp().GetBall(session.shipid).mode != 3, timeout_ms, 2000)
    site_sleep(5000)
    return bm


def arc_step(agentIDs, log, complete_with_gm=True):
    # One move through an epic arc by the agents' own conversation actions: accept an offer
    # (button 3), turn in (6), or, for an accepted mission, mark its objective done with the
    # GM /missioncomplete (setup help) and turn in. A talk-to mission names its target agent
    # in the journal; that agent joins agentIDs. Answers the move made, or None.
    for agentID in list(agentIDs):
        sm.GetService('agents').agentMonikers.pop(agentID, None)
        try:
            (says, actions), info = agent_do(agentID)
        except Exception as error:
            log.append((agentID, 'error', repr(error)[:200]))
            continue
        choices = [(actionID, button) for actionID, button in actions if isinstance(button, dict)]
        if choices:
            # A branch choice (a mission picked from the offered alternatives): the
            # scenario decides, so stop here.
            log.append((agentID, 'choice', choices))
            return ('choice', agentID, choices)
        buttons = dict((button, actionID) for actionID, button in actions)
        contentID = says[1] if isinstance(says, tuple) and len(says) > 1 else None
        if 2 in buttons and len(buttons) == 1:
            (says, actions), info = agent_do(agentID, buttons[2])
            buttons = dict((button, actionID) for actionID, button in actions)
            contentID = says[1] if isinstance(says, tuple) and len(says) > 1 else contentID
        if 3 in buttons:
            agent_do(agentID, buttons[3])
            journal = agent_journal(agentID) or {}
            for kind, data in (journal.get('objectives') or {}).get('objectives') or []:
                if kind == 'agent' and isinstance(data[0], (int, long)) and data[0] not in agentIDs:
                    agentIDs.append(data[0])
            log.append((agentID, 'accepted', contentID))
            return ('accepted', agentID, contentID)
        if 6 in buttons:
            result = agent_do(agentID, buttons[6])
            if result[1].get('missionCompleted'):
                log.append((agentID, 'completed', contentID))
                return ('completed', agentID, contentID)
            sm.GetService('agents').agentMonikers.pop(agentID, None)
        journal = agent_journal(agentID) or {}
        if journal.get('missionState') == 2 and complete_with_gm:
            site_slash('/missioncomplete %d' % agentID)
            site_sleep(1000)
            stationID = getattr(sm.GetService('agents').GetAgentByID(agentID), 'stationID', None)
            if stationID and session.stationid != stationID:
                # A station agent hands in only to a pilot docked with them.
                site_slash('/tr me %d' % stationID)
                site_wait(lambda: session.stationid == stationID, 60000)
                site_sleep(4000)
            elif not stationID:
                agent_fly_to(agentID)
            sm.GetService('agents').agentMonikers.pop(agentID, None)
            (says, actions), info = agent_do(agentID)
            buttons = dict((button, actionID) for actionID, button in actions)
            if 6 in buttons:
                agent_do(agentID, buttons[6])
                log.append((agentID, 'gm-completed', journal.get('contentID')))
                return ('completed', agentID, journal.get('contentID'))
            log.append((agentID, 'stuck', journal.get('contentID'), actions))
    return None



def agent_fly_to(agentID, rangeMeters=2500, timeout_ms=280000):
    # An agent in space talks only to a pilot near their ship: warp to their homebase
    # bookmark (the journal's), then approach the ship the agent flies.
    from eve.client.script.ui.services.menuSvcExtras import movementFunctions
    if not site_in_space():
        site_undock()
    bm = agent_bookmark(agentID, 'agenthomebase')
    if bm is None:
        raise AssertionError('no homebase bookmark for agent %d' % agentID)
    site_goto_system(bm.solarsystemID)
    ships = lambda: [row for row in site_entities() if getattr(row[3], 'ownerID', None) == agentID or getattr(row[3], 'charID', None) == agentID]
    if not ships():
        movementFunctions.WarpToBookmark(bm, 0.0)
        site_sleep(4000)
        site_wait(lambda: site_bp().GetBall(session.shipid).mode != 3, timeout_ms, 2000)
        site_sleep(5000)
    rows = ships()
    if not rows:
        raise AssertionError('agent %d not on grid' % agentID)
    target = rows[0][1]
    movementFunctions.KeepAtRange(target, 1000)
    for button in site_hud_buttons():
        if evetypes.GetName(button.moduleinfo.typeID).startswith('10MN Afterburner') and not (button.def_effect and button.def_effect.isActive):
            uthread.new(button.ActivateModule)
    site_wait(lambda: site_bp().DistanceBetween(session.shipid, target) < rangeMeters, timeout_ms, 2000)
    return target


# ---------- The Blood-Stained Stars (EvEJS PRs 372, 382) ----------

BSS_ALITURA, BSS_CALDARI_COMMANDER = 3019356, 3019368
BSS_RUN = {'agents': [BSS_ALITURA], 'log': [], 'moves': [], 'done': False, 'error': None}


def site_dock_home_at(stationID):
    if session.stationid != stationID:
        site_slash('/tr me %d' % stationID)
        site_wait(lambda: session.stationid == stationID, 60000)
        site_sleep(5000)
    return True


def bss_run(choices, stop_at=None):
    # Step the arc in a tasklet until it stops (a mission needing real play, a choice not in
    # choices, or stop_at accepted); BSS_RUN records each move.
    BSS_RUN.update({'done': False, 'error': None})

    def run():
        try:
            for _ in range(160):
                move = arc_step(BSS_RUN['agents'], BSS_RUN['log'])
                if move and move[0] == 'choice':
                    agentID, offered = move[1], move[2]
                    missionID = offered[0][1]['Mission ID']
                    act = choices.get(missionID)
                    if act is None:
                        BSS_RUN['moves'].append(('unknown choice', missionID))
                        break
                    agent_do(agentID, act)
                    BSS_RUN['moves'].append(('chose', missionID, act))
                    continue
                BSS_RUN['moves'].append(move and move[:3])
                if move is None or (stop_at and move[0] == 'accepted' and move[2] == stop_at):
                    break
                site_sleep(500)
        except Exception as error:
            BSS_RUN['error'] = repr(error)[:400]
        BSS_RUN['done'] = True
    uthread.new(run)
    return True


def bss_poll(seconds=280):
    end = blue.os.GetWallclockTime() + seconds * 10000000
    while blue.os.GetWallclockTime() < end and not BSS_RUN['done']:
        site_sleep(2000)
    return True


def bss_last():
    return [move for move in BSS_RUN['moves'] if move][-1]


def bss_chose(missionID):
    return [move[2] for move in BSS_RUN['moves'] if move and move[0] == 'chose' and move[1] == missionID]


def bss_step_courier():
    # 14413 A Stranger's Face: carry the Altered Identity Records to their station.
    site_dock_home_at(60012607)
    hangar = sm.GetService('invCache').GetInventory(const.containerHangar)
    ship = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    for item in [i for i in hangar.List(const.flagHangar) if i.typeID == 30826]:
        ship.Add(item.itemID, item.locationID, qty=item.stacksize, flag=const.flagCargo)
    site_sleep(1500)
    site_dock_home_at(60011317)
    sm.GetService('agents').agentMonikers.pop(BSS_ALITURA, None)
    return agent_press(BSS_ALITURA, (6,))[1].get('missionCompleted') is True


def bss_dagan_container():
    for row in site_entities():
        if row[2] == 'Cargo Container' and row[0] < 100000:
            if any(i.typeID == 30827 for i in sm.GetService('invCache').GetInventoryFromId(row[1]).List()):
                return row[1]
    return None


def bss_step_dagan():
    # 14445 Our Man Dagan (Caldari): clear wave 1, the Society of Conscious Thought cruiser
    # leaves Dagan in a cargo container; hand in to the Caldari commander, who returns him.
    from eve.client.script.ui.services.menuSvcExtras import movementFunctions
    site_guard(True)
    agent_warp(BSS_CALDARI_COMMANDER, 'dungeon')
    site_tank()
    fp_clear(include=None, real=1, timeout_ms=230000)
    site_sleep(10000)
    containers = [row[1] for row in site_entities() if row[2] == 'Cargo Container']
    if not containers:
        raise AssertionError('no cargo container on grid')
    container = containers[0]
    movementFunctions.KeepAtRange(container, 1000)
    site_wait(lambda: site_bp().DistanceBetween(session.shipid, container) < 2400, 200000, 2000)
    dagan = [i for i in sm.GetService('invCache').GetInventoryFromId(container).List() if i.typeID == 30827][0]
    ship = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    ship.Add(dagan.itemID, container, qty=1, flag=const.flagCargo)
    site_sleep(2000)
    sm.GetService('agents').agentMonikers.pop(BSS_CALDARI_COMMANDER, None)
    done = agent_press(BSS_CALDARI_COMMANDER, (6,))[1].get('missionCompleted') is True
    kept = any(i.typeID == 30827 for i in ship.List(const.flagCargo))
    return done and kept


def bss_step_finale():
    # 14469 Dal Segno al Fine: the final acceleration gate, Dagan into the Cargo Wreathe,
    # turn in; the arc status records 14469 completed.
    from eve.client.script.ui.services.menuSvcExtras import movementFunctions
    sm.GetService('agents').agentMonikers.pop(BSS_CALDARI_COMMANDER, None)
    agent_press(BSS_CALDARI_COMMANDER, (3,))
    agent_warp(BSS_CALDARI_COMMANDER, 'dungeon')
    gate = site_wait(lambda: [r[1] for r in site_entities() if r[2] == 'Acceleration Gate'], 30000)[0]
    uthread.new(sm.GetService('menu').ActivateAccelerationGate, gate)
    site_wait(lambda: gate not in site_bp().slimItems, 150000, 2000)
    site_wait(lambda: site_bp().GetBall(session.shipid).mode != 3, 60000, 2000)
    site_sleep(5000)
    wreathe = site_wait(lambda: [r[1] for r in site_entities() if r[2] == 'Cargo Wreathe'], 30000)[0]
    movementFunctions.KeepAtRange(wreathe, 800)
    site_wait(lambda: site_bp().DistanceBetween(session.shipid, wreathe) < 2400, 200000, 2000)
    ship = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    dagan = [i for i in ship.List(const.flagCargo) if i.typeID == 30827][0]
    sm.GetService('invCache').GetInventoryFromId(wreathe).Add(dagan.itemID, session.shipid, qty=1)
    site_wait(lambda: (agent_journal(BSS_CALDARI_COMMANDER) or {}).get('objectives', {}).get('completionStatus') == 1, 30000)
    sm.GetService('agents').agentMonikers.pop(BSS_CALDARI_COMMANDER, None)
    done = agent_press(BSS_CALDARI_COMMANDER, (6,))[1].get('missionCompleted') is True
    status = sm.RemoteSvc('agentMgr').GetMyEpicArcStatus()
    site_guard(False)
    return done and status[29][14469].completedDate is not None


def site_board_type_here(typeName):
    # The hangar's Make Active on the newest assembled hull of this type in this station,
    # answering the client's question about leaving the current ship.
    rows = [i for i in sm.GetService('invCache').GetInventory(const.containerHangar).List(const.flagHangar)
            if i.categoryID == const.categoryShip and i.singleton and evetypes.GetName(i.typeID) == typeName]
    if not rows:
        raise AssertionError('no %s in this hangar' % typeName)
    row = max(rows, key=lambda i: i.itemID)
    if session.shipid != row.itemID:
        uthread.new(sm.GetService('station').TryActivateShip, row)
        site_sleep(3000)
        site_answer_yes()
        site_wait(lambda: session.shipid == row.itemID, 30000)
    return True
