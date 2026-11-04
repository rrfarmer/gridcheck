# AIR NPE driver: plays the active AIR tutorial task in the real client the way a player does,
# through the client's own UI nodes, services and the gridcheck agent's click, menu and pointer.
# Load air_lib.py first. Untracked on purpose (D-17: nothing gridcheck is committed).
#
# Each handler was worked out from the client graph that owns the step (fsd nodegraphs, graph IDs in
# doc/AIR_TUTORIAL_E2E.md) and checked by hand in the real client on 2026-11-03.
#
#   air_step()  plays the current task until it moves on, at most ~270 s per call; a long task keeps
#               running in a tasklet and the next call carries on waiting for it.
import blue, uthread, evetypes

def _click(**kw):
    kw.setdefault('wait', 5)
    return agent.op_click(kw)
def _menu(entries, **kw):
    kw['entries'] = entries; kw.setdefault('wait', 5)
    return agent.op_menu(kw)
def _pointer(action, points, **kw):
    kw['action'] = action; kw['points'] = points
    return agent.op_pointer(kw)
def _sleep(ms):
    blue.pyos.synchro.SleepWallclock(ms)
def _window(name):
    for w in uicore.registry.GetWindows():
        if w.name == name and not w.destroyed: return w
def _node(win, name):
    w = _window(win)
    found = walk(w, lambda m: getattr(m, 'name', '') == name, []) if w else []
    return found[0] if found else None
def _text():
    return ' '.join(conv_lines(4) or [])
def _wait_text(sub, ms=60000):
    return wait_until(lambda: (cont_once() or True) and sub.lower() in _text().lower(), ms)
def cont_once():
    b = [x for x in conv_buttons() if not getattr(x, 'disabled', False)]
    if b: uthread.new(b[0].OnClick); _sleep(1200); return True
    return False
def _bp():
    return sm.GetService('michelle').GetBallpark()
def _dist(i):
    bp = _bp()
    return bp.DistanceBetween(session.shipid, i) if bp and i in bp.slimItems else 1e12
def _mode():
    ball = sm.GetService('michelle').GetBall(session.shipid)
    return ball.mode if ball else None
def _wait_out_of_warp(ms=180000):
    _sleep(4000)
    return wait_until(lambda: _mode() not in (None, 3), ms)
def _close(name):
    w = _window(name)
    if w: uthread.new(w.CloseByUser) if hasattr(w, 'CloseByUser') else uthread.new(w.Close)
def npe_skip_guard():
    # uicore.cmd.CmdExitStation (and other off-path actions) ask "Performing this action will take
    # you outside the AIR New Player Experience ... unable to restart it". Never answer Yes: that
    # skips the tutorial for good. Answer No and fail the step.
    w = _window('modal')
    if w and walk(w, lambda m: 'New Player Experience' in (getattr(m, 'text', '') or ''), []):
        _click(window='modal', name='no_dialog_button')
        raise AssertionError('the client asked to leave the AIR New Player Experience; answered No')
# The client's own session-change delay (carbon/common/script/sys/basesession.py:18,
# SESSIONCHANGEDELAY = 10 s): after a dock, undock or jump, wait it out before acting, as a player
# does, so the new ballpark, lobby and windows are in place.
SETTLE_MS = 10000
def _undock(asked=True):
    # The lobby's Undock button, as the player presses it. During the tutorial the client asks
    # "leave the AIR NPE?" (ConfirmActionWhileTutorialActive) for an undock the current step has not
    # asked for yet, so wait for the dialogue to ask (asked=False for the career missions).
    if session.stationid:
        if asked: _wait_text('undock', 120000)
        wait_until(lambda: _shown('undockButton'), 60000)
        _click(name='undockButton', wait=5)
        _sleep(2000); npe_skip_guard()
        wait_until(lambda: session.solarsystemid and not session.stationid and _bp(), 90000); _sleep(SETTLE_MS)
def _dock(stationID):
    if session.stationid == stationID: return
    wait_until(lambda: _bp() and stationID in _bp().slimItems, 30000)
    select_item(stationID); _sleep(500)
    uthread.new(_mv.DockOrJumpOrActivateGate, stationID)
    wait_until(lambda: session.stationid == stationID, 240000); _sleep(SETTLE_MS)
def _warp_to(itemID, tries=8):
    # A warp asked for in the seconds after an undock is refused; ask again until the ship warps.
    for i in range(tries):
        select_item(itemID); _sleep(800)
        uthread.new(_mv.WarpToItem, itemID, 0)
        if wait_until(lambda: _mode() == 3, 12000): break
    _wait_out_of_warp()
def _home():
    bb = air_bb()
    return bb.get('air_station_id') or bb.get('birth_station_id')
def _open_cargo_and_loot(itemID):
    _menu(['Open Cargo'], itemID=itemID); _sleep(2500)
    _click(text='Loot All'); _sleep(2500)
    for w in uicore.registry.GetWindows():
        if not w.destroyed and w.name in ('InventorySpace',) or (not w.destroyed and 'nventory' in w.__class__.__name__ and w.name != 'InventoryStation'):
            uthread.new(w.CloseByUser)
    _sleep(1500)

# --- Act 1 -------------------------------------------------------------------------------------
def h_board_ship():
    # Camera rotate and zoom out (OnClientMouseSpinInSpace / ZoomOutSpace), each when asked.
    for i in range(20):
        t = _text().lower()
        if 'highlighted ship' in t or air_bb().get('target_selected') or 'approach' in t: break
        if 'rotate' in t: _pointer('drag', [[1300, 800], [1400, 820], [1500, 840], [1600, 860]], durationMs=800)
        elif 'zoom' in t: _pointer('wheel', [[1300, 800]], delta=600)
        cont_once(); _sleep(1500)
    ship = air_bb().get('target_item_id')
    select_item(ship); _sleep(1500)
    _mv.Approach(ship)
    wait_until(lambda: _dist(ship) < 2400, 150000)
    _menu(['Board Ship'], itemID=ship)
def _repeat_until_moved(task, action, every_ms=15000, total_ms=260000):
    # Commands are only heard while the step's listener is up, so a command given early is lost:
    # give it again until the task moves on.
    t0 = blue.os.GetWallclockTime()
    while air_task() == task and (blue.os.GetWallclockTime() - t0) / 10000 < total_ms:
        action(); wait_until(lambda: air_task() != task, every_ms)
def h_start_repairing():
    _wait_text('Click <b>Approach', 90000)
    balin = air_bb().get('balin_item_id') or air_bb().get('target_item_id')
    def act():
        select_item(balin); _sleep(800); _mv.Approach(balin)
    _repeat_until_moved('start_repairing', act)
def h_target_command():
    task = air_task()
    wait_until(lambda: air_bb().get('target_item_id') and air_bb().get('target_ui_blink_id'), 120000)
    _repeat_until_moved(task, do_target_command, 20000)
def h_fight(typeIDs=None):
    tid = typeIDs or [air_bb().get('target_type_id')]
    wait_until(lambda: hostiles(tid), 120000)
    first = hostiles(tid)[0][1]
    select_item(first); _mv.Orbit(first, 1000)
    fight(tid, 260000, 1000)
def h_cruiser():
    h_fight([57802])
def h_battleship():
    tid = [57803]
    wait_until(lambda: hostiles(tid), 120000)
    b = hostiles(tid)[0][1]
    select_item(b); _mv.Orbit(b, 1000)
    engage(b)
def h_acp_claim_all():
    if not _window('careerPortal') or not _window('careerPortal').display:
        uthread.new(uicore.cmd.CmdToggleAirCareerProgram); _sleep(4000)
    _portal_ready()
    for i in range(3):
        w = _window('careerPortal')
        btn = walk(w, lambda m: m.__class__.__name__ == 'Button' and getattr(m, 'text', '') == 'Claim All', [])
        if not btn:
            # Claim All sits in the careers view: back out of a remembered goal or activity view,
            # one level per click of the selected path's centre node (careerNode.OnClick).
            from eve.client.script.ui.shared.careerPortal import careerConst
            for back in range(3):
                if careerConst.CAREER_WINDOW_STATE_SETTING.get() == careerConst.CareerWindowState.CAREERS_VIEW: break
                sel = [m for m in walk(_window('careerPortal'), lambda m: getattr(m, 'name', '').startswith('careerNode_'), []) if getattr(m, 'display', True)]
                if len(sel) != 1: break
                uthread.new(sel[0].OnClick); _sleep(2500)
            btn = walk(_window('careerPortal'), lambda m: m.__class__.__name__ == 'Button' and getattr(m, 'text', '') == 'Claim All', [])
        agent.air_claim_log = getattr(agent, 'air_claim_log', []) + [(i, bool(btn), _goal_ctrl().get_claimable_rewards_count())]
        if btn:
            uthread.new(btn[0].OnClick); _sleep(2000)
            wait_until(lambda: not _goal_ctrl().get_claimable_rewards_count(), 8000)
        try:
            if not _goal_ctrl().get_claimable_rewards_count(): break
        except Exception: break
    cont_once(); _sleep(1500)
    uthread.new(uicore.cmd.CmdToggleAirCareerProgram); _sleep(3000)
def _shown(name):
    return walk(uicore.desktop, lambda m: getattr(m, 'name', '') == name and getattr(m, 'display', True), [])
def _shown_on_screen(name):
    # Displayed with every parent displayed too: walk() also descends into hidden containers, so a
    # node whose own display is True can still sit in a hidden parent, which op_click ("no displayed
    # node matches") does not count. Untested guess for the 1.3.04 first-play failure (2026-11-04).
    def chain_shown(m):
        while m is not None:
            if not getattr(m, 'display', True): return False
            m = getattr(m, 'parent', None)
        return True
    return [m for m in _shown(name) if chain_shown(m)]
def h_board_corvette():
    wait_until(lambda: _shown_on_screen('corvetteButton'), 90000)
    _click(name='corvetteButton', wait=15)
def h_undock():
    _undock()
def h_item_retrieval():
    _undock()
    _wait_text('sun', 60000)
    # The task moves on as the undock lands, before the new ballpark's state has arrived: wait for
    # the sun to be in it (reading it at once failed every act 1 run on 2026-11-04).
    suns = wait_until(lambda: [b for b, s in _bp().slimItems.items() if s.groupID == const.groupSun], 60000)
    _warp_to(suns[0])
    wait_until(lambda: [b for b, s in _bp().slimItems.items() if s.groupID == 306], 60000)
    wrecks = sorted((_dist(b), b) for b, s in _bp().slimItems.items() if s.groupID == 306)
    w = wrecks[0][1]
    select_item(w); _mv.Approach(w); wait_until(lambda: _dist(w) < 2300, 150000)
    _open_cargo_and_loot(w)
    _dock(_home())
def h_fitting():
    from eve.client.script.ui.shared.fitting import fittingUtil
    uthread.new(uicore.cmd.OpenFitting); _sleep(3000)
    item = [i for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List() if i.typeID == 78677]
    if not item: item = [i for i in sm.GetService('invCache').GetInventory(const.containerHangar).List(const.flagHangar) if i.typeID == 78677]
    uthread.new(fittingUtil.TryFit, [item[0]])
def _upgrade_id():
    return [i.itemID for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List() if i.typeID == 78677][0]
def h_online_attempt():
    if not _window('fittingWnd'): uthread.new(uicore.cmd.OpenFitting); _sleep(3000)
    uthread.new(sm.GetService('clientDogmaIM').GetDogmaLocation().OnlineModule, _upgrade_id())
def h_skill_intro():
    if not _window('fittingWnd'): uthread.new(uicore.cmd.OpenFitting); _sleep(3000)
    _wait_text('warning icon', 60000)
    icon = _node('fittingWnd', 'SkillWarningIcon')
    l, t, w, h = icon.GetAbsolute()
    x, y = l + w / 2, t + h / 2
    _pointer('move', [[x - 20, y - 10], [x, y], [x, y], [x + 1, y]], durationMs=1500); _sleep(2500)
    uthread.new(sm.GetService('skillqueue').AddSkillAndRequirementsToQueue, 22578, 1)
def h_skill_points():
    uthread.new(uicore.cmd.OpenSkillsWindow); _sleep(4000)
    _click(name='ApplySkillPointsButtonIcon'); _sleep(2500)
    _click(name='confirm_skill_injection'); _sleep(3000)
    _click(name='close_skill_injection')
def h_skill_plan():
    if not _window('SkillPlanner'): uthread.new(uicore.cmd.OpenSkillsWindow); _sleep(4000)
    if 'close the windows' not in _text():
        _skill_plan_start()
    _wait_text('close the windows', 60000)
    _click(window='SkillPlanner', name='DockPanel_HeaderButton_Close')
def _skill_plan_start():
    _wait_text('Skill Plan', 60000)
    _click(window='SkillPlanner', cls='FloatingToggleButtonGroupButton', text='Skill Plans')
    _click(window='SkillPlanner', cls='ToggleButtonGroupButton', text='Certified Plans')
    _click(window='SkillPlanner', name='SkillPlanEntry_AIR'); _sleep(1500)
    _click(window='SkillPlanner', name='startTrainingButton', wait=10); _sleep(3000)
    if _window('modal'): _click(window='modal', name='yes_dialog_button')
def h_online_module():
    uthread.new(sm.GetService('clientDogmaIM').GetDogmaLocation().OnlineModule, _upgrade_id())
    _wait_text('close the Fitting', 60000)
    _close('fittingWnd')
def h_opportunities_intro():
    uthread.new(uicore.cmd.OpenJobBoardWindow); _sleep(4000)
    _click(window='job_board', name='feature_introductions_entry'); _sleep(1500)
    _click(window='job_board', name='entry_storylines:AIR_NPE_ACT_2'); _sleep(1500)
    _click(window='job_board', name='accept_opportunity_button', wait=10); _sleep(3000)
    _close('job_board')

# --- Act 2 -------------------------------------------------------------------------------------
def h_enter_mining_site():
    _undock()
    wait_until(lambda: walk(uicore.desktop, lambda m: getattr(m, 'name', '') == 'objective_task_button' and getattr(m, 'display', True), []), 60000)
    _click(name='objective_task_button', wait=10)
    _wait_out_of_warp()
def h_mine():
    t = air_task()
    rock = air_bb().get('target_item_id')
    if t != '2.1.02_mine_asteroid_1':
        wait_new_target(agent.air_last_rock, 120000) if getattr(agent, 'air_last_rock', None) == rock else None
    agent.air_last_rock = air_bb().get('target_item_id')
    mine_target(t, 260000)
def h_loot_wreck():
    _mv.StopMyShip() if hasattr(_mv, 'StopMyShip') else uthread.new(sm.GetService('michelle').GetRemotePark().CmdStop)
    for b in hud_buttons():
        if b.def_effect is not None and b.def_effect.isActive: uthread.new(b.DeactivateModule)
    wait_until(lambda: air_bb().get('wreck_item_id'), 120000)
    w = air_bb().get('wreck_item_id')
    wait_until(lambda: w in _bp().slimItems, 60000)
    select_item(w); _mv.Approach(w); wait_until(lambda: _dist(w) < 2300, 150000)
    _open_cargo_and_loot(w)
def h_back_to_station():
    _dock(_home())
def h_move_ore():
    hangar = sm.GetService('invCache').GetInventory(const.containerHangar)
    for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List(const.flagCargo):
        if i.typeID == 60771: hangar.Add(i.itemID, session.shipid, qty=i.stacksize)
def h_sell_ore():
    if not _window('InventoryStation'): uthread.new(uicore.cmd.OpenInventory); _sleep(3000)
    _click(window='InventoryStation', name='topCont_ItemHangar'); _sleep(2000)
    _menu(['Sell This Item'], window='InventoryStation', name='ItemEntry_60771'); _sleep(2500)
    _click(window='SellItemsWindow', name='confirm_sell_button', wait=2); _sleep(1500)
    for i in range(3):
        if not _window('modal'): break
        for name in ('ok_dialog_button', 'yes_dialog_button'):
            if _node('modal', name): _click(window='modal', name=name, wait=3); _sleep(1500); break
    _sleep(2000); _close('SellItemsWindow'); _close('InventoryStation')
def h_wallet():
    # Graph 699: wallet open on its overview, then Market Transactions, then Transactions, then close,
    # each when the dialogue asks for it.
    if not _window('walletWindow'): uthread.new(uicore.cmd.OpenWallet); _sleep(3000)
    # The lesson starts from the ISK overview tab; the client remembers the last tab used.
    _click(window='walletWindow', name='PersonalWalletTab_mywallet'); _sleep(1000)
    _click(window='walletWindow', name='IskPanelTab_overview'); _sleep(2000)
    _wait_text('market transactions', 90000)
    _click(window='walletWindow', name='IskPanelTab_marketTransactions'); _sleep(2000)
    _wait_text('wealth of information', 60000)
    _click(window='walletWindow', name='IskPanelTab_transactions'); _sleep(2000)
    _wait_text('close your wallet', 60000)
    _close('walletWindow')
# --- Career paths --------------------------------------------------------------------------------
# The pilot's career path for 2.2.04 to 2.5.01; act 2 scenarios set it with air_set_path(name).
#   careerNode: careerView.py names nodes careerNode_<careerPathID> (careerpaths.fsdbinary: 4 Explorer,
#               5 Industrialist, 6 Enforcer, 7 Soldier of Fortune).
#   activity:   the path's highlighted career-agent activity (careerConst.HIGHLIGHTED_ACTIVITIES:
#               101 Explorer, 201 Industrialist, 301 Enforcer, 401 Soldier of Fortune).
#   division:   the agent row's division label in the station's Agents tab (divisions 26, 25, 27, 28, 29).
#   button:     CareerPathButton_<careerpath internalName> (careerPathToggleButtonGroup.py).
#   plan:       the end of the certified plan's name (SkillPlanEntry_AIR <Faction> <Path>, plans 34-47).
CAREER_PATHS = {
    'producer': {'careerNode': 5, 'activity': 201, 'division': 'Industrialist - Producer', 'button': 'Industrialist', 'plan': 'Industrialist - Producer'},
    'entrepreneur': {'careerNode': 5, 'activity': 201, 'division': 'Industrialist - Entrepreneur', 'button': 'Industrialist', 'plan': 'Industrialist - Entrepreneur'},
    'explorer': {'careerNode': 4, 'activity': 101, 'division': 'Explorer', 'button': 'Explorer', 'plan': 'Explorer'},
    'enforcer': {'careerNode': 6, 'activity': 301, 'division': 'Enforcer', 'button': 'Enforcer', 'plan': 'Enforcer'},
    'soldier': {'careerNode': 7, 'activity': 401, 'division': 'Soldier of Fortune', 'button': 'Soldier of Fortune', 'plan': 'Soldier of Fortune'},
}
def air_set_path(name):
    assert name in CAREER_PATHS, name
    agent.air_path = name
    return name
def _path():
    return CAREER_PATHS[getattr(agent, 'air_path', None) or 'producer']
agent.air_set_path = air_set_path

def _portal_ready():
    # The first build of the portal in a session can stop at the activities circle (client
    # ZeroDivisionError in circleView.GetOuterCircleVariables), leaving no ActivityView or goal
    # view; build it again.
    if not walk(_window('careerPortal'), lambda m: m.__class__.__name__ == 'ActivityView', []):
        agent.air_portal_rebuilt = getattr(agent, 'air_portal_rebuilt', 0) + 1
        _window('careerPortal').Close(); _sleep(2000)
        uthread.new(uicore.cmd.CmdToggleAirCareerProgram); _sleep(5000)
def h_acp_goal():
    if not _window('careerPortal') or not _window('careerPortal').display:
        uthread.new(uicore.cmd.CmdToggleAirCareerProgram); _sleep(4000)
    _wait_text('Choose the path', 90000)
    _portal_ready()
    # The portal opens on the path chosen last (a char setting, careerConst.SELECTED_CAREER_PATH_SETTING;
    # a new character on a fresh data root can reuse an earlier run's ID and settings). Clicking the
    # selected path's centre node goes back a view (careerNode.OnClick), as a player does.
    want = 'careerNode_%d' % _path()['careerNode']
    def shown():
        return [m for m in walk(_window('careerPortal'), lambda m: getattr(m, 'name', '').startswith('careerNode_'), []) if getattr(m, 'display', True)]
    for i in range(3):
        s = shown()
        # Back out to the careers view even when the wanted path is the one remembered: the portal
        # reopened straight into its activities view draws no activity nodes (LoadActivities runs on
        # the view change).
        if len(s) != 1: break
        uthread.new(s[0].OnClick); _sleep(2500)
    if len(shown()) > 1:
        _click(window='careerPortal', name=want); _sleep(2500)
    _wait_text('Track the goal', 60000)
    _click(window='careerPortal', name='activityNode_%d' % _path()['activity']); _sleep(2000)
    _click(window='careerPortal', path='/Desktop/l_viewstate/l_view_overlays/l_sidePanels/careerPortal/content/main/career_portal/central_container/GoalView/GoalCircleView/nodeParent/GoalNode[0]'); _sleep(2000)
    _click(window='careerPortal', name='trackButton'); _sleep(2500)
    _wait_text('Agency', 60000)
    btn = walk(_window('careerPortal'), lambda m: m.__class__.__name__ == 'Button' and getattr(m, 'text', '') == 'Find Career Agents', [])
    uthread.new(btn[0].OnClick); _sleep(4000)
    _click(window='AgencyWndNew', name='Agency_CareerAgents_InteractionButton', wait=8); _sleep(2500)
    _close('AgencyWndNew'); _sleep(1500)
    if _window('careerPortal') and _window('careerPortal').display: uthread.new(uicore.cmd.CmdToggleAirCareerProgram)
def h_close_acp_and_undock():
    if _window('careerPortal') and _window('careerPortal').display: uthread.new(uicore.cmd.CmdToggleAirCareerProgram); _sleep(2500)
    _undock()
def _follow_route(dock=True):
    # Jump along the set route; when only the destination station is left, dock there.
    for hop in range(20):
        path = sm.GetService('starmap').GetDestinationPath()
        if not path: break
        if len(path) == 1 and session.solarsystemid2 and path[0] not in (session.solarsystemid2,) and next_gate() is None:
            if dock: _dock(path[0])
            break
        g = next_gate()
        if not g: break
        select_item(g); _sleep(1500)
        here = session.solarsystemid2
        uthread.new(_mv.DockOrJumpOrActivateGate, g)
        wait_until(lambda: session.solarsystemid2 != here and _bp(), 240000); _sleep(SETTLE_MS)
def h_navigation():
    _undock()
    _follow_route()
def _go_to(locationID, dock=True):
    # Set the destination (as "Set Destination" does: careerAgentEntry.SetDestination) and fly the route.
    if session.stationid == locationID or session.solarsystemid2 == locationID: return
    if session.stationid: _undock(asked=False)
    sm.StartService('starmap').SetWaypoint(locationID, clearOtherWaypoints=True); _sleep(2500)
    _follow_route(dock)
    if dock and session.stationid != locationID and _bp() and locationID in _bp().slimItems: _dock(locationID)
def _career_agent_id():
    am = sm.RemoteSvc('agentMgr')
    for m in am.GetMyJournalDetails()[0]:
        return m[4]
def h_agent_intro():
    _click(name='stationInformationTabAgents'); _sleep(2000)
    label = _path()['division']
    texts = lambda f: walk(_window('lobbyWnd'), lambda m: f((getattr(m, 'text', '') or '').strip()), [])
    entry = texts(lambda t: t == label) or texts(lambda t: label in t)
    agent.air_agent_rows = [getattr(m, 'text', '') for m in texts(lambda t: ' - ' in t or t in ('Explorer', 'Enforcer', 'Soldier of Fortune'))][:20]
    row = entry[0]
    while row is not None and row.parent is not None and row.parent.name != '__content': row = row.parent
    uthread.new(row.OnDblClick); _sleep(4000)
    _click(name='AcceptMission_Button', wait=10)
def h_skill_plan_reminder():
    uthread.new(uicore.cmd.OpenSkillsWindow); _sleep(4000)
    _click(window='SkillPlanner', cls='FloatingToggleButtonGroupButton', text='Skill Plans')
    _click(window='SkillPlanner', cls='ToggleButtonGroupButton', text='Certified Plans')
    _click(window='SkillPlanner', name='CareerPathButton_%s' % _path()['button']); _sleep(2500)
    suffix = ' ' + _path()['plan']
    entry = walk(_window('SkillPlanner'), lambda m: getattr(m, 'name', '').startswith('SkillPlanEntry_AIR ') and getattr(m, 'name', '').endswith(suffix), [])
    agent.air_plan_entries = [m.name for m in walk(_window('SkillPlanner'), lambda m: getattr(m, 'name', '').startswith('SkillPlanEntry_'), [])]
    uthread.new(entry[0].OnClick); _sleep(2500)
    _click(window='SkillPlanner', name='startTrainingButton', wait=3); _sleep(2000)
    if _window('modal'): _click(window='modal', name='yes_dialog_button')
    _wait_text('close any windows', 60000)
    _click(window='SkillPlanner', name='DockPanel_HeaderButton_Close')
    for w in uicore.registry.GetWindows():
        if not w.destroyed and w.name.startswith('AgentConversation_'): _close(w.name)
def h_opportunities_reminder():
    uthread.new(uicore.cmd.OpenJobBoardWindow); _sleep(4000)
    _click(window='job_board', text='Active'); _sleep(2000)
    card = walk(_window('job_board'), lambda m: getattr(m, 'name', '').startswith('entry_agent_missions:'), [])
    uthread.new(card[0].OnClick); _sleep(3000)
    _wait_text('close the window', 60000)
    _close('job_board')
def _agent_window(agentID):
    for w in uicore.registry.GetWindows():
        if not w.destroyed and w.name.startswith('AgentConversation_') and w.name.endswith(str(agentID)): return w
    uthread.new(sm.GetService('agents').OpenDialogueWindow, agentID); _sleep(4000)
    return _agent_window(agentID) if False else [w for w in uicore.registry.GetWindows() if not w.destroyed and w.name.startswith('AgentConversation_')][0]
def _agent_button(agentID, name):
    # The button's own OnClick on a tasklet: the agent's click helper waited on Complete Mission and
    # stalled the client agent (2026-11-04).
    w = _agent_window(agentID)
    b = wait_until(lambda: walk(w, lambda m: getattr(m, 'name', '') == name and not getattr(m, 'disabled', False), []), 20000)
    if not b: raise AssertionError('no %s in the agent window' % name)
    uthread.new(b[0].OnClick); _sleep(5000)
def _objective(agentID):
    return sm.GetService('agents').GetAgentMoniker(agentID).GetMissionObjectiveInfo()
def _hangar_qty(typeID):
    return sum(i.stacksize for i in sm.GetService('invCache').GetInventory(const.containerHangar).List(const.flagHangar) if i.typeID == typeID)
def play_producer_part1(agentID):
    # Making Mountains of Molehills: 1,000 Veldspar from the mission's deadspace pocket. Mine 1,100
    # so one reprocessing batch (100) is left for part 2.
    station = session.stationid
    mission = [m for m in sm.RemoteSvc('agentMgr').GetMyJournalDetails()[0] if m[4] == agentID][0]
    bm = [b for b in mission[6] if b.locationType == 'dungeon'][0]
    _undock(asked=False)
    uthread.new(_mv.WarpToBookmark, bm, 0.0); _wait_out_of_warp()
    mine_until(1230, 1100, 1500000)
    for b in hud_buttons():
        if b.def_effect is not None and b.def_effect.isActive: uthread.new(b.DeactivateModule)
    _go_to(station)
    _agent_button(agentID, 'CompleteMission_Button')
def play_producer_part2(agentID):
    # Tritanium x100: reprocess the Veldspar left from part 1.
    hangar = sm.GetService('invCache').GetInventory(const.containerHangar)
    for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List(const.flagCargo):
        if i.typeID == 1230: hangar.Add(i.itemID, session.shipid, qty=i.stacksize)
    _sleep(2000); hangar.StackAll(const.flagHangar); _sleep(2000)
    items = [i for i in hangar.List(const.flagHangar) if i.typeID == 1230]
    uthread.new(sm.GetService('reprocessing').ReprocessDlg, items); _sleep(4000)
    _click(window='reprocessingWindow', name='reprocessButton', wait=10); _sleep(3000)
    _close('reprocessingWindow')
    _agent_button(agentID, 'CompleteMission_Button')
def _agent_station(agentID):
    return sm.GetService('agents').GetAgentByID(agentID).stationID
def _mission_row(agentID):
    rows = [m for m in sm.RemoteSvc('agentMgr').GetMyJournalDetails()[0] if m[4] == agentID]
    return rows[0] if rows else None
def _mission_done(agentID):
    try:
        return _objective(agentID)['completionStatus'] > 0
    except Exception:
        return False
def _stop_modules():
    for b in hud_buttons():
        try:
            if b.def_effect is not None and b.def_effect.isActive: uthread.new(b.DeactivateModule)
        except Exception: pass
def _warp_to_site(agentID):
    # The mission's deadspace bookmark ("Warp to Location" in the agent window), in its own system.
    bm = [b for b in _mission_row(agentID)[6] if b.locationType == 'dungeon'][0]
    agent.air_site_bm = (getattr(bm, 'itemID', None), getattr(bm, 'locationID', None), getattr(bm, 'solarsystemID', None))
    sysID = getattr(bm, 'solarsystemID', None) or getattr(bm, 'locationID', None)
    if sysID and sysID != session.solarsystemid2: _go_to(sysID, dock=False)
    if session.stationid: _undock(asked=False)
    # Already in the site (a deadspace pocket or beside its gate): a warp to it is refused.
    if _bp() and [b for b, s in _bp().slimItems.items() if s.groupID == 366 or getattr(s, 'dunObjectID', None)]: return
    for i in range(8):
        uthread.new(_mv.WarpToBookmark, bm, 0.0)
        if wait_until(lambda: _mode() == 3, 12000): break
    _wait_out_of_warp(); _sleep(3000)
    dismiss_info_box(15000)
def dismiss_info_box(ms=10000):
    # A site's arrival or warp popup (agents.MessageBox, e.g. the Anomaly Training Site's "Incoming
    # Transmission") is a modal the player reads and closes with OK. Left open it holds the session
    # lock of the server's call, so the next session change (a dock) never completes.
    def box():
        w = _window('modal') or _window('message')
        if not w: return None
        if walk(w, lambda m: 'New Player Experience' in (getattr(m, 'text', '') or ''), []): return None
        return w
    w = wait_until(box, ms, 500)
    if not w: return False
    agent.air_popups = getattr(agent, 'air_popups', []) + [[getattr(m, 'text', '')[:80] for m in walk(w, lambda q: bool(getattr(q, 'text', None)), [])][:3]]
    for name in ('ok_dialog_button', 'close_dialog_button'):
        b = walk(w, lambda m: getattr(m, 'name', '') == name, [])
        if b: uthread.new(b[0].OnClick); _sleep(1500); return True
    b = walk(w, lambda m: m.__class__.__name__ == 'Button', [])
    if b: uthread.new(b[0].OnClick); _sleep(1500); return True
    return False
NPC_SHIP_WORDS = ('Frigate', 'Destroyer', 'Cruiser', 'Battleship', 'Battlecruiser', 'Industrial', 'Drone', 'Rookie', 'Officer', 'Commander', 'Sentry', 'Hauler', 'Elite', 'Threat', 'Pirate')
def site_hostiles():
    # NPC ships of the site: entity-category items whose group is a ship class. Spawn containers
    # (306) and site structures are entities too, and are not shot.
    bp = _bp(); out = []
    if not bp: return out
    for b, s in bp.slimItems.items():
        if b == session.shipid or s.categoryID != const.categoryEntity or s.groupID == 306: continue
        g = evetypes.GetGroupNameByGroup(s.groupID) or ''
        if not [w for w in NPC_SHIP_WORDS if w in g]: continue
        out.append((int(bp.DistanceBetween(session.shipid, b)), b, s.typeID))
    return sorted(out)
WEAPON_EFFECTS =('targetAttack', 'projectileFired', 'useMissiles', 'emp', 'targetDisintegratorAttack')
def _weapons():
    return [b for b in hud_buttons() if b.def_effect is not None and b.def_effect.effectName in WEAPON_EFFECTS]
def _shoot(itemID, orbit=1500):
    # Orbit the target, lock it, make it the active target and fire every weapon at it.
    ts = sm.GetService('target')
    select_item(itemID)
    try: _mv.Orbit(itemID, orbit)
    except Exception: pass
    if itemID not in ts.GetTargets():
        uthread.new(ts.TryLockTarget, itemID); wait_until(lambda: itemID in ts.GetTargets(), 30000)
    try: ts.SetActiveTarget(itemID) if hasattr(ts, 'SetActiveTarget') else None
    except Exception: pass
    for b in _weapons():
        if not b.def_effect.isActive: uthread.new(b.ActivateModule)
def clear_site(agentID, timeout_ms=1500000, quiet_ms=90000, until=None):
    # Kill the site's pirates as they come (waves included) until the agent says the objective is met,
    # `until()` is true, or nothing hostile shows for quiet_ms.
    t0 = blue.os.GetWallclockTime(); quiet = None; kills = 0
    while (blue.os.GetWallclockTime() - t0) / 10000 < timeout_ms:
        if until and until(): break
        h = site_hostiles()
        if not h:
            if _mission_done(agentID): break
            quiet = quiet or blue.os.GetWallclockTime()
            if (blue.os.GetWallclockTime() - quiet) / 10000 > quiet_ms: break
            _sleep(3000); continue
        quiet = None
        b = h[0][1]
        _shoot(b)
        wait_until(lambda: not _bp() or b not in _bp().slimItems, 45000)
        if _bp() and b not in _bp().slimItems: kills += 1
    _stop_modules()
    agent.air_kills = getattr(agent, 'air_kills', 0) + kills
    return kills
def _turn_in(agentID):
    dismiss_info_box(1000)
    _stop_modules()
    _go_to(_agent_station(agentID))
    _agent_button(agentID, 'CompleteMission_Button')
def play_combat(agentID):
    # Enforcer (Cash Flow for Capsuleers) and Soldier of Fortune (The Swap): warp to the site and
    # destroy the pirates, every wave of them, with the ship's own guns.
    _warp_to_site(agentID)
    for pocket in range(4):
        clear_site(agentID, quiet_ms=45000)
        if _mission_done(agentID) or not _take_gate(): break
    if not _mission_done(agentID): raise AssertionError('combat site not cleared: %r' % (_objective(agentID).get('dungeons'),))
    _turn_in(agentID)
def _site_item(typeID, ms=60000):
    found = wait_until(lambda: [b for b, s in _bp().slimItems.items() if s.typeID == typeID], ms)
    return sorted((_dist(b), b) for b in found)[0][1] if found else None
def play_explorer(agentID):
    # Cosmic Anomalies: open the site's Training Container - Anomalies (32353) and take its Proof of
    # Discovery (32350) to the agent.
    _warp_to_site(agentID)
    clear_site(agentID, quiet_ms=3000)
    c = _site_item(32353)
    if not c: raise AssertionError('no Training Container on the site')
    select_item(c); _mv.Approach(c); wait_until(lambda: _dist(c) < 2300, 200000)
    _open_cargo_and_loot(c)
    if cargo_qty(32350) < 1: raise AssertionError('Proof of Discovery not in cargo')
    _turn_in(agentID)
def play_courier(agentID, detail):
    # Balancing the Books part 1: put the agent's cargo in the hold, fly to the dropoff, hand it in
    # there (the agent window opens remotely, as the client's Complete Mission does from the dropoff).
    pickup, dropoff, cargo = detail[1], detail[3], detail[4]
    if session.stationid != pickup['locationID']: _go_to(pickup['locationID'])
    shipinv = sm.GetService('invCache').GetInventoryFromId(session.shipid)
    for i in sm.GetService('invCache').GetInventory(const.containerHangar).List(const.flagHangar):
        if i.typeID == cargo['typeID']: shipinv.Add(i.itemID, session.stationid, qty=i.stacksize, flag=const.flagCargo)
    _sleep(2500)
    if cargo_qty(cargo['typeID']) < cargo['quantity']: raise AssertionError('courier cargo not loaded')
    _go_to(dropoff['locationID'])
    if session.stationid != dropoff['locationID']: raise AssertionError('not docked at the dropoff')
    _agent_button(agentID, 'CompleteMission_Button')
def _fit_from_hangar(typeID, unfit_first=None):
    from eve.client.script.ui.shared.fitting import fittingUtil
    # Already fitted (the HUD shows no module buttons while docked, so read the ship's own items).
    if [i for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List() if i.typeID == typeID and i.flagID != const.flagCargo]: return
    item = [i for i in sm.GetService('invCache').GetInventory(const.containerHangar).List(const.flagHangar) if i.typeID == typeID]
    if not item: raise AssertionError('type %d is not in the hangar' % typeID)
    # The AIR Ibis's two high slots hold the railgun and the Civilian Miner: take the miner off to
    # the hangar, as a player makes room for the salvager.
    if unfit_first:
        hangar = sm.GetService('invCache').GetInventory(const.containerHangar)
        for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List():
            if i.typeID == unfit_first: hangar.Add(i.itemID, session.shipid, qty=1); _sleep(3000)
    uthread.new(fittingUtil.TryFit, [item[0]]); _sleep(5000)
    if _window('modal'): _click(window='modal', name='yes_dialog_button'); _sleep(2000)
    fitted = [i for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List() if i.typeID == typeID]
    if not fitted: raise AssertionError('type %d did not fit' % typeID)
    dl = sm.GetService('clientDogmaIM').GetDogmaLocation()
    if not dl.GetDogmaItem(fitted[0].itemID).IsOnline(): uthread.new(dl.OnlineModule, fitted[0].itemID); _sleep(3000)
def _take_gate():
    gates = [b for b, s in _bp().slimItems.items() if s.groupID == 366]
    if not gates: return False
    g = sorted((_dist(b), b) for b in gates)[0][1]
    select_item(g); _mv.Approach(g); wait_until(lambda: _dist(g) < 2400, 200000)
    for i in range(5):
        uthread.new(_mv.DockOrJumpOrActivateGate, g)
        if wait_until(lambda: _dist(g) > 100000 or g not in _bp().slimItems, 30000): break
    _wait_out_of_warp(); _sleep(3000)
    dismiss_info_box(8000)
    return True
def play_salvage(agentID, blackbox):
    # Balancing the Books part 2: fit the agent's Civilian Salvager (26983), take the site's gate, kill
    # the Guristas Rookie, then salvage the Civilian Transport Ship Wreck (27275) for the Black Box.
    if session.stationid != _agent_station(agentID): _go_to(_agent_station(agentID))
    _fit_from_hangar(26983, unfit_first=3651)
    _warp_to_site(agentID)
    for hop in range(3):
        clear_site(agentID, quiet_ms=8000)
        if [b for b, s in _bp().slimItems.items() if s.typeID == 27275]: break
        if not _take_gate(): break
    clear_site(agentID, quiet_ms=15000)
    w = _site_item(27275, 60000)
    if not w: raise AssertionError('no Civilian Transport Ship Wreck')
    select_item(w); _mv.Approach(w); wait_until(lambda: _dist(w) < 4000, 200000)
    _mv.KeepAtRange(w, 2000) if hasattr(_mv, 'KeepAtRange') else None
    ts = sm.GetService('target')
    t0 = blue.os.GetWallclockTime()
    while cargo_qty(blackbox) < 1 and w in _bp().slimItems and (blue.os.GetWallclockTime() - t0) / 10000 < 600000:
        if w not in ts.GetTargets():
            uthread.new(ts.TryLockTarget, w); wait_until(lambda: w in ts.GetTargets(), 30000)
        for b in hud_buttons():
            if b.moduleinfo.typeID == 26983 and not b.def_effect.isActive: uthread.new(b.ActivateModule)
        _sleep(5000)
    _stop_modules()
    if cargo_qty(blackbox) < 1: raise AssertionError('no Black Box after salvaging')
    _turn_in(agentID)
# --- Career chain parts after the tutorial ---------------------------------------------------------
def hack_game(timeout_ms=300000):
    # Plays the open hacking minigame through hackingUI's own OnTileClicked (what a tile click does):
    # attack the core once seen, attack defence software in reach, otherwise flip the reachable hidden
    # tile next to the revealed tile with the lowest distance hint.
    svc = sm.GetService('hackingUI')
    from hackingcommon import hackingConstants as hc
    agent.hack_log = []; t0 = blue.os.GetWallclockTime()
    wait_until(lambda: svc.tileDataByCoord and not svc.gameEnded, 30000)
    while not svc.gameEnded and (blue.os.GetWallclockTime() - t0) / 10000 < timeout_ms:
        tiles = svc.tileDataByCoord.values()
        seen = [t for t in tiles if not t.hidden]
        reach = lambda t: t.IsFlippable()
        core = [t for t in seen if t.type == hc.TYPE_CORE and t.coherence > 0 and reach(t)]
        # Defence software next to the revealed area can be attacked even though the tiles beside it
        # are blocked (IsFlippable counts only unblocked neighbours).
        ds = [t for t in seen if t.type == hc.TYPE_DEFENSESOFTWARE and t.coherence > 0
              and [n for n in t.GetNeighbours() if not n.hidden]]
        ue = [t for t in seen if t.type == hc.TYPE_UTILITYELEMENTTILE]
        if ue:
            agent.hack_log.append(('pick', ue[0].coord))
            uthread.new(svc.OnTileClicked, ue[0].coord); _sleep(1200); continue
        flip = [t for t in tiles if t.hidden and not t.blocked and t.IsFlippable()]
        def hint(t):
            d = [n.distanceIndicator for n in t.GetNeighbours() if not n.hidden and n.distanceIndicator]
            return min(d) if d else 99
        if core: pick, why = core[0], 'core'
        elif flip: pick, why = sorted(flip, key=hint)[0], 'flip'
        elif ds: pick, why = sorted(ds, key=lambda t: t.coherence)[0], 'defence'
        else: break
        agent.hack_log.append((why, pick.coord))
        uthread.new(svc.OnTileClicked, pick.coord); _sleep(1200)
    return (svc.gameEnded, svc.virusCoherence, agent.hack_log[-5:], len(agent.hack_log))
def play_career_part(agentID):
    row = _mission_row(agentID)
    if row is None or row[0] != 2: _accept_next(agentID)
    info = _objective(agentID)
    agent.air_objectives = repr(info.get('objectives'))[:600]
    kinds = dict((k, d) for k, d in info['objectives'])
    if 'transport' in kinds: return play_courier(agentID, kinds['transport'])
    fetch = kinds.get('fetch')
    cargo = fetch[2] if fetch and len(fetch) > 2 else {}
    t = cargo.get('typeID')
    if t == 1230: return play_producer_part1(agentID)
    if t == 34: return play_producer_part2(agentID)
    if t == 32350: return play_explorer(agentID)
    if t == 27276: return play_salvage(agentID, t)
    if not fetch and info.get('dungeons'): return play_combat(agentID)
    raise AssertionError('unexpected career objective %r' % (info['objectives'],))
PATH_GOALS = {'explorer': '7d202e65-ab0c-4a88-9016-a672aa1b7870', 'enforcer': 'bca73ce6-d2fd-4812-8a7f-def9b9f158d1',
    'soldier': 'b0091c33-48f3-46fe-8a6c-6449d9f1a969', 'entrepreneur': '99d018db-8a11-4097-a102-4d9b7e600978',
    'producer': '9b88fc7a-dd03-4746-8937-d3f796c4d284'}
def _path_goal():
    return PATH_GOALS[getattr(agent, 'air_path', None) or 'producer']
def _goal_completed():
    try:
        import uuid
        g = _goal_ctrl().get_goal(uuid.UUID(_path_goal()))
        return bool(g and g.is_completed())
    except Exception:
        return False
def _goal_done_claimed():
    # The path goal already completed and claimed (a re-run after the claim).
    try:
        import uuid
        g = _goal_ctrl().get_goal(uuid.UUID(_path_goal()))
        return bool(g and g.is_completed() and not g.has_unclaimed_rewards())
    except Exception:
        return False
def _goal_ctrl():
    from careergoals.client.career_goal_svc import get_career_goals_svc
    return get_career_goals_svc().get_goal_data_controller()
def h_acp_reward_reminder():
    # The graph waits for one of the five "complete a career agent mission" ACP goals: part 1 of the
    # Explorer, Enforcer and Soldier of Fortune chains, part 2 of the Industrialist chains (careerCatalog:
    # 7d202e65, bca73ce6, b0091c33 = career-agent-26-1, 28-1, 29-1; 99d018db, 9b88fc7a = 25-2, 27-2). The
    # pilot plays those parts here, then claims the reward and closes the program.
    agentID = _career_agent_id()
    parts = 2 if _path()['button'] == 'Industrialist' else 1
    agent.air_parts = getattr(agent, 'air_parts', [])
    # Play by part count, not by Aura's "via your NEOCOM" line: that line shows for any claimable
    # reward, and Entrepreneur part 1 completes a career-points goal of its own (seen 2026-11-04).
    done_goal = lambda: str(_path_goal()) in [str(g.goal_id) for g in _goal_ctrl().get_goals_with_claimable_rewards()]
    for part in range(parts):
        if done_goal() or _goal_done_claimed() or _goal_completed(): break
        play_career_part(agentID)
        agent.air_parts.append((part + 1, agent.air_objectives))
        _sleep(3000)
        if part + 1 < parts and not done_goal():
            _accept_next(agentID)
    for w in uicore.registry.GetWindows():
        if not w.destroyed and w.name.startswith('AgentConversation_'): _close(w.name)
    # The goal's reward reaches the career portal a moment after the turn-in: wait for it before
    # pressing Claim All, or the press claims nothing and the step waits for good.
    wait_until(lambda: done_goal() or _goal_done_claimed(), 120000)
    _wait_text('NEOCOM', 30000)
    h_acp_claim_all()
def _accept_next(agentID):
    # At the agent's station (a gift lands there), take the chain's next part: the window shows the
    # new offer at once after a turn-in, or a Request Mission button.
    if session.stationid != _agent_station(agentID): _go_to(_agent_station(agentID))
    row = _mission_row(agentID)
    if row is not None and row[0] == 2: return
    w = _agent_window(agentID)
    if not walk(w, lambda m: getattr(m, 'name', '') == 'AcceptMission_Button', []):
        _agent_button(agentID, 'RequestMission_Button')
    _agent_button(agentID, 'AcceptMission_Button')
def h_help():
    uthread.new(uicore.cmd.OpenAgencyNew); _sleep(4000)
    tab = _node('AgencyWndNew', '69')
    uthread.new(tab.OnClick); _sleep(3000)
    _wait_text('close the Agency', 60000)
    _close('AgencyWndNew')

HANDLERS = {
    'board_ship': h_board_ship, 'ship_hud': None, 'start_repairing': h_start_repairing, 'balin_warping': None,
    'frigates_arrived': h_target_command, 'orbiting_balin': h_target_command, 'fleet_arrived': None,
    'frigates_destroyed': h_fight, 'cruiser_destroyed': h_cruiser, 'player_engaged_battleship': h_battleship,
    'player_in_pod': None, 'player_dead': None,
    '1.3.01_wake-up': None, '1.3.02_acp_reward_introduction': h_acp_claim_all, '1.3.03_redeeming_introduction': None,
    '1.3.04_board_corvette': h_board_corvette, '1.3.05_undock': h_undock,
    '1.4.01_item_retrieval': h_item_retrieval,
    '1.5.01_fitting_introduction': h_fitting, '1.5.02_online_module_attempt': h_online_attempt,
    '1.5.03_skill_introduction': h_skill_intro, '1.5.04_skill_point_introduction': h_skill_points,
    '1.5.05_skill_plan_introduction': h_skill_plan, '1.5.06_online_module': h_online_module,
    '1.5.07_opportunities_mission_introduction': h_opportunities_intro,
    '2.1.01_enter_mining_site': h_enter_mining_site, '2.1.02_mine_asteroid_1': h_mine, '2.1.03_mine_asteroid_2': h_mine,
    '2.1.04_mine_asteroid_3': h_mine, '2.1.05_loot_wreck': h_loot_wreck, '2.1.06_back_to_station': h_back_to_station,
    '2.2.01_move_ore': h_move_ore, '2.2.02_market_introduction': h_sell_ore, '2.2.03_wallet_introduction': h_wallet,
    '2.2.04_acp_goal_introduction': h_acp_goal, '2.2.05_undock': h_close_acp_and_undock,
    '2.3.01_system_navigation_introduction': h_navigation,
    '2.4.01_agent_introduction': h_agent_intro, '2.4.02_skill_plan_reminder': h_skill_plan_reminder,
    '2.4.03_opportunities_mission_reminder': h_opportunities_reminder,
    '2.5.01_acp_reward_reminder': h_acp_reward_reminder, '2.5.02_help_section_introduction': h_help,
    '2.5.03_handoff': None,
}

def air_state():
    return sm.RemoteSvc('air_npe').get_air_npe_state()
def _job_runner(task, fn):
    job = agent.air_job
    try:
        if fn: fn()
    except Exception as e:
        import traceback
        job['error'] = traceback.format_exc()[-800:]
    job['done'] = True
def air_step(budget_ms=270000):
    start_recorder()
    if air_state() == 2 and not air_task():
        return {'done': True, 'state': 2}
    task = wait_until(air_task, 60000)
    if not task:
        return {'done': air_state() == 2, 'state': air_state(), 'task': None}
    if task not in HANDLERS:
        raise AssertionError('no handler for AIR task %r' % task)
    job = getattr(agent, 'air_job', None)
    if not job or job.get('task') != task or job.get('done'):
        tries = (job.get('tries', 0) + 1) if job and job.get('task') == task else 1
        if tries > 3:
            raise AssertionError('AIR task %s did not move on after 3 plays; last error %s; conversation: %r' % (task, job.get('error'), conv_lines(3)))
        agent.air_job = {'task': task, 'done': False, 'error': None, 'tries': tries, 'startedAt': blue.os.GetWallclockTime()}
        uthread.new(_job_runner, task, HANDLERS[task])
    # A handler that fails (an exception) cannot move the task on, so stop waiting at once and let
    # the next call play it again, instead of sitting out the rest of the budget (up to 4.5 minutes
    # lost per failure, as at 1.3.04 and 1.4.01 in the 2026-11-04 Enforcer run).
    job = agent.air_job
    new = wait_until(lambda: wait_task_change(task, 1000, click=True) or (job.get('error') and 'failed'), budget_ms)
    if new == 'failed':
        new = wait_task_change(task, 5000, click=True)
    npe_skip_guard()
    if new:
        return {'from': task, 'to': new}
    return {'working': task, 'try': agent.air_job.get('tries'), 'error': agent.air_job.get('error'), 'conversation': conv_lines(2)}
TASK_ORDER = ['board_ship', 'ship_hud', 'start_repairing', 'balin_warping', 'frigates_arrived', 'orbiting_balin',
    'fleet_arrived', 'frigates_destroyed', 'cruiser_destroyed', 'player_engaged_battleship', 'player_in_pod', 'player_dead',
    '1.3.01_wake-up', '1.3.02_acp_reward_introduction', '1.3.03_redeeming_introduction', '1.3.04_board_corvette',
    '1.3.05_undock', '1.4.01_item_retrieval', '1.5.01_fitting_introduction', '1.5.02_online_module_attempt',
    '1.5.03_skill_introduction', '1.5.04_skill_point_introduction', '1.5.05_skill_plan_introduction',
    '1.5.06_online_module', '1.5.07_opportunities_mission_introduction', '2.1.01_enter_mining_site',
    '2.1.02_mine_asteroid_1', '2.1.03_mine_asteroid_2', '2.1.04_mine_asteroid_3', '2.1.05_loot_wreck',
    '2.1.06_back_to_station', '2.2.01_move_ore', '2.2.02_market_introduction', '2.2.03_wallet_introduction',
    '2.2.04_acp_goal_introduction', '2.2.05_undock', '2.3.01_system_navigation_introduction',
    '2.4.01_agent_introduction', '2.4.02_skill_plan_reminder', '2.4.03_opportunities_mission_reminder',
    '2.5.01_acp_reward_reminder', '2.5.02_help_section_introduction', '2.5.03_handoff']
def air_reached(until):
    if air_state() == 2: return True
    t = air_task()
    return bool(until and t in TASK_ORDER and TASK_ORDER.index(t) >= TASK_ORDER.index(until))
def air_play(until=None, budget_ms=280000):
    # One eval's worth of air_step calls: stops at the end of the tutorial, at `until` (or anything
    # after it), or on budget. Safe to call again: it carries on from the current task.
    t0 = blue.os.GetWallclockTime(); steps = []
    while (blue.os.GetWallclockTime() - t0) / 10000 < budget_ms - 20000 and not air_reached(until):
        r = air_step(min(270000, budget_ms - 20000 - (blue.os.GetWallclockTime() - t0) / 10000))
        steps.append(r)
        if r.get('done') or (until and r.get('to') == until): break
    return {'steps': steps, 'task': air_task(), 'state': air_state(), 'log': [t for _, t in getattr(agent, 'air_log', [])]}
agent.air_step = air_step; agent.air_play = air_play; agent.air_state = air_state; agent.air_reached = air_reached
result = (air_task(), air_state())
