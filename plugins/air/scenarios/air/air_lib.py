# AIR tutorial driver helpers, loaded into the client agent's namespace.
# Untracked (D-17): gridcheck scenarios and their files never enter a commit.
import blue, uthread
def _ng():
    return sm.GetService('node_graph')
def air_bb():
    ng = _ng()
    for k in ng.get_active_node_graphs():
        if k.endswith(':client:716'):
            return dict(ng.get_active_node_graph(k).context.values)
    return {}
def air_task():
    return air_bb().get('active_task')
def air_graphs():
    ng = _ng(); out = []
    for k in ng.get_active_node_graphs():
        g = ng.get_active_node_graph(k)
        out.append(getattr(g, 'graph_id', None))
    return out
def walk(n, pred, out):
    try:
        if pred(n): out.append(n)
    except Exception:
        pass
    for c in getattr(n, 'children', []) or []:
        walk(c, pred, out)
    return out
def find_text(sub):
    sub = sub.lower()
    return walk(uicore.desktop, lambda n: sub in (getattr(n, 'text', '') or '').lower() and getattr(n, 'display', True), [])
agent.air_bb = air_bb; agent.air_task = air_task; agent.air_graphs = air_graphs; agent.find_text = find_text; agent.walk = walk
result = (air_task(), air_graphs())

def conv_windows():
    return [w for w in uicore.registry.GetWindows() if getattr(w, 'name', '') == 'TaskConversationWindow' and not w.destroyed and getattr(w, 'display', True)]
def conv_window():
    ws = conv_windows()
    return ws[-1] if ws else None
def conv_buttons():
    out = []
    for w in conv_windows():
        out += walk(w, lambda n: n.__class__.__name__ == 'Button' and getattr(n, 'display', True) and n.name != 'previous_button' and getattr(n.parent, 'name', '') == 'navigation_button_container', [])
    return out
def conv_text():
    w = conv_window()
    return w and getattr(w, 'caption', None) or (w and ' '.join([getattr(n, 'text', '') for n in walk(w, lambda n: bool(getattr(n, 'text', None)), [])])[:300])
def conv_next(max_clicks=20, pause=1500):
    # Clicks the conversation's navigation button (Next / Continue / Close) until none is left.
    clicked = []
    for i in range(max_clicks):
        btns = [b for b in conv_buttons() if not getattr(b, 'disabled', False)]
        if not btns: break
        b = btns[0]; clicked.append((b.name, getattr(b, 'text', '') or getattr(b, 'label', '')))
        uthread.new(b.OnClick)
        blue.pyos.synchro.SleepWallclock(pause)
    return clicked
agent.conv_window = conv_window; agent.conv_buttons = conv_buttons; agent.conv_next = conv_next

def conv_lines(n=3):
    ws = conv_windows()
    if not ws: return None
    out = []
    for w in ws: out += [getattr(x, 'text', '') for x in walk(w, lambda m: bool(getattr(m, 'text', None)), [])]
    return out[-n:]
def wait_until(fn, timeout_ms=60000, every=500):
    t0 = blue.os.GetWallclockTime()
    while True:
        try:
            v = fn()
        except Exception:
            v = None
        if v: return v
        if (blue.os.GetWallclockTime() - t0) / 10000 > timeout_ms: return v
        blue.pyos.synchro.SleepWallclock(every)
def wait_task_change(old, timeout_ms=60000, click=True):
    # Waits for the active AIR task to leave `old`, clicking the conversation's Next/Continue
    # button whenever one shows (the player reading the dialogue).
    def poll():
        if click:
            btns = [b for b in conv_buttons() if not getattr(b, 'disabled', False)]
            if btns: uthread.new(btns[0].OnClick); blue.pyos.synchro.SleepWallclock(800)
        t = air_task()
        return t if t != old else None
    return wait_until(poll, timeout_ms)
def status():
    return {'task': air_task(), 'ship': session.shipid, 'station': session.stationid, 'system': session.solarsystemid2, 'conv': conv_lines(2), 'buttons': [b.name for b in conv_buttons()]}
agent.wait_task_change = wait_task_change; agent.status = status; agent.conv_lines = conv_lines; agent.wait_until = wait_until

from eve.client.script.parklife import states as _st
from eve.client.script.ui.services.menuSvcExtras import movementFunctions as _mv
def select_item(i):
    sm.GetService('stateSvc').SetState(i, _st.selected, 1)
def do_target_command():
    # The graph names the instruction's target and the Selected Item button it highlights:
    # select the target and press that command, as the player is told to.
    bb = air_bb(); t = bb.get('target_item_id'); blink = bb.get('target_ui_blink_id') or ''
    if not t: return None
    select_item(t); blue.pyos.synchro.SleepWallclock(800)
    if 'Orbit' in blink: _mv.Orbit(t, 500)
    elif 'Approach' in blink: _mv.Approach(t)
    elif 'KeepAtRange' in blink: _mv.KeepAtRange(t, 1000)
    elif 'Warp' in blink: _mv.WarpToItem(t, 0)
    return (t, blink)
agent.select_item = select_item; agent.do_target_command = do_target_command

def hud_buttons():
    out = []
    def w(n):
        mi = getattr(n, 'moduleinfo', None)
        if mi is not None and hasattr(n, 'ActivateModule'): out.append(n)
        for c in getattr(n, 'children', []) or []: w(c)
    try: w(uicore.layer.shipui)
    except Exception: pass
    return out
def hostiles(typeIDs=None):
    bp = sm.GetService('michelle').GetBallpark(); out = []
    if not bp: return out
    for b, s in bp.slimItems.items():
        if b == session.shipid or s.categoryID != const.categoryEntity and s.categoryID != const.categoryShip: continue
        if typeIDs and s.typeID not in typeIDs: continue
        if typeIDs is None and not (s.categoryID == const.categoryEntity): continue
        out.append((int(bp.DistanceBetween(session.shipid, b)), b, s.typeID))
    return sorted(out)
def engage(itemID):
    # Lock the target, then switch on every high-slot weapon and the mid-slot modules
    # (web, ECM, afterburner) through their HUD buttons, as the player's clicks do.
    ts = sm.GetService('target')
    if itemID not in ts.GetTargets():
        select_item(itemID); uthread.new(ts.TryLockTarget, itemID)
        wait_until(lambda: itemID in ts.GetTargets(), 20000)
    bp = sm.GetService('michelle').GetBallpark()
    wait_until(lambda: bp.DistanceBetween(session.shipid, itemID) < 9000, 120000)
    for b in hud_buttons():
        try:
            if not b.def_effect.isActive: uthread.new(b.ActivateModule)
        except Exception: pass
def fight(typeIDs, timeout_ms=300000, orbit=1000):
    t0 = blue.os.GetWallclockTime(); kills = 0
    while (blue.os.GetWallclockTime() - t0) / 10000 < timeout_ms:
        h = hostiles(typeIDs)
        if not h: return kills
        d, b, typeID = h[0]
        try: _mv.Orbit(b, orbit)
        except Exception: pass
        engage(b)
        wait_until(lambda: b not in (sm.GetService('michelle').GetBallpark() or {}).slimItems if hasattr(sm.GetService('michelle').GetBallpark(), 'slimItems') else True, 30000)
        bp = sm.GetService('michelle').GetBallpark()
        if bp and b not in bp.slimItems: kills += 1
    return kills
agent.hostiles = hostiles; agent.engage = engage; agent.fight = fight; agent.hud_buttons = hud_buttons

def start_recorder():
    # Logs every change of the AIR blackboard's active_task, with the wall clock, to agent.air_log.
    if getattr(agent, 'air_rec_on', False): return
    agent.air_rec_on = True
    if not hasattr(agent, 'air_log'): agent.air_log = []
    def loop():
        last = None
        while agent.air_rec_on:
            try:
                t = air_task()
            except Exception:
                t = None
            if t and t != last:
                agent.air_log.append((blue.os.GetWallclockTime(), t)); last = t
            blue.pyos.synchro.SleepWallclock(200)
    uthread.new(loop)
agent.start_recorder = start_recorder

def close_window(name):
    for w in uicore.registry.GetWindows():
        if w.name == name and not w.destroyed:
            uthread.new(w.CloseByUser) if hasattr(w, 'CloseByUser') else uthread.new(w.Close)
            return True
def wait_new_target(old, timeout_ms=120000):
    def poll():
        bt = [x for x in conv_buttons() if not getattr(x, 'disabled', False)]
        if bt: uthread.new(bt[0].OnClick); blue.pyos.synchro.SleepWallclock(1500)
        return air_bb().get('target_item_id') not in (None, old)
    return wait_until(poll, timeout_ms)
def mine_target(task, timeout_ms=400000):
    # Approach the rock the graph names, lock it, and run the miner (HUD button) until the task moves on.
    bb = air_bb(); rock = bb.get('target_item_id'); rng = bb.get('target_lock_range') or 10000
    bp = sm.GetService('michelle').GetBallpark()
    do_target_command()
    wait_until(lambda: bp.DistanceBetween(session.shipid, rock) < min(rng, 9000), 200000)
    ts = sm.GetService('target')
    if rock not in ts.GetTargets():
        uthread.new(ts.TryLockTarget, rock); wait_until(lambda: rock in ts.GetTargets(), 30000)
    for b in hud_buttons():
        if b.moduleinfo.typeID == 3651 and not b.def_effect.isActive:
            uthread.new(b.ActivateModule)
    return wait_task_change(task, timeout_ms, click=True)
agent.close_window = close_window; agent.mine_target = mine_target; agent.wait_new_target = wait_new_target

def cargo_qty(typeID):
    return sum(i.stacksize for i in sm.GetService('invCache').GetInventoryFromId(session.shipid).List(const.flagCargo) if i.typeID == typeID)
def mine_until(oreTypeID, qty, timeout_ms=1500000):
    # Mines the nearest asteroid of the ore with every fitted mining laser until the hold has qty.
    t0 = blue.os.GetWallclockTime(); ts = sm.GetService('target')
    while cargo_qty(oreTypeID) < qty and (blue.os.GetWallclockTime() - t0) / 10000 < timeout_ms:
        bp = sm.GetService('michelle').GetBallpark()
        rocks = sorted([(bp.DistanceBetween(session.shipid, b), b) for b, s in bp.slimItems.items() if s.typeID == oreTypeID])
        if not rocks: return cargo_qty(oreTypeID)
        rock = rocks[0][1]
        if bp.DistanceBetween(session.shipid, rock) > 8000:
            _mv.Approach(rock); wait_until(lambda: bp.DistanceBetween(session.shipid, rock) < 8000, 200000)
            _mv.KeepAtRange(rock, 4000) if hasattr(_mv, 'KeepAtRange') else None
        if rock not in ts.GetTargets():
            uthread.new(ts.TryLockTarget, rock); wait_until(lambda: rock in ts.GetTargets(), 30000)
        for b in hud_buttons():
            if b.def_effect is not None and b.def_effect.effectName in ('miningLaser', 'mining') and not b.def_effect.isActive:
                uthread.new(b.ActivateModule)
        blue.pyos.synchro.SleepWallclock(5000)
    return cargo_qty(oreTypeID)
agent.cargo_qty = cargo_qty; agent.mine_until = mine_until

def next_gate():
    # The stargate in this system that leads to the next system on the set route.
    path = sm.GetService('starmap').GetDestinationPath()
    bp = sm.GetService('michelle').GetBallpark()
    if not path or not bp: return None
    for b, s in bp.slimItems.items():
        if s.groupID == const.groupStargate:
            for j in (s.jumps or []):
                if getattr(j, 'locationID', None) == path[0]:
                    return b
    return None
agent.next_gate = next_gate
