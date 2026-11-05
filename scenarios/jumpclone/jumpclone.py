# Jump clone checks for a real EVE client (scenario jumpclone-implants.json).
#
# The player report this guards (EveJS PR #305):
#  1. After the Augmentations tab had been opened, a clone jump left the old body's implants shown
#     as fitted, and Plug In Implant was not offered, until the player relogged. From a ship and
#     from the pod alike.
#  2. A named clone lost its name after the player jumped into it and out again.
#
# What the client does (build 3396210):
#  - skillsvc.GetImplants caches the implants the first time it is called (the Augmentations tab
#    calls it). Only OnServerImplantsChanged -> GetCharacterAttributes(True) refreshes the cache.
#  - menucheckers/itemCheckers.OfferPlugInImplant hides Plug In Implant while the implant's slot is
#    in that cache.
#  - jumpClonesPanel.validate_jump_to checks the cooldown only for a clone elsewhere or in a ship;
#    a swap inside one station neither waits for it nor starts it.
#  - clonejumpsvc.CloneJump asks AskAcceptJumpCloneCost, unboards a ship first, and retries
#    lm.CloneJump with confirmed=True after JumpCheckWillLoseExistingClone.
#
# Each jc_step_* returns True or raises AssertionError with what it saw.
import evetypes
import uthread
from menucheckers.itemCheckers import ItemChecker

OCULAR = 'Ocular Filter - Basic'
MEMORY = 'Memory Augmentation - Basic'
REMOTE_STATION = 60003760  # Jita IV - Moon 4 - Caldari Navy Assembly Plant
REMOTE_STATION_ALT = 60008494  # Amarr VIII (Oris) - Emperor Family Academy
SETTLE_MS = 11000  # the client's session-change delay is 10 s


def _sleep(ms):
    blue.pyos.synchro.SleepWallclock(ms)


def _wait(fn, ms, what):
    waited = 0
    while waited < ms:
        value = fn()
        if value:
            return value
        _sleep(250)
        waited += 250
    raise AssertionError('timed out waiting for %s' % what)


def _slash(text):
    return sm.GetService('slash').SlashCmd(text)


def _lm():
    return sm.GetService('clonejump').GetLM()


def _clones():
    kv = _lm().GetCloneState()
    implants = {}
    for row in kv.implants:
        implants.setdefault(row.jumpCloneID, []).append(evetypes.GetName(row.typeID))
    return [{'id': c.jumpCloneID, 'location': c.locationID, 'name': getattr(c, 'cloneName', None) or '',
             'implants': sorted(implants.get(c.jumpCloneID, []))} for c in kv.clones], kv.timeLastJump


def _clone_at(locationID):
    rows = [c for c in _clones()[0] if c['location'] == locationID]
    return rows[0] if len(rows) == 1 else None


def _cached():
    # What the Augmentations tab and Plug In Implant read: the skills service's cache.
    svc = sm.GetService('skills')
    return None if svc.implants is None else sorted(evetypes.GetName(i.typeID) for i in svc.implants.values())


def _server_implants():
    return sorted(evetypes.GetName(i.typeID) for i in sm.GetService('skills').GetSkillHandler().GetImplants().values())


def _prime():
    # The Augmentations tab's own call.
    return sm.GetService('skills').GetImplants()


def _hangar_implants(name):
    inv = sm.GetService('invCache').GetInventory(const.containerHangar)
    return [i for i in inv.List(const.flagHangar) if evetypes.GetName(i.typeID) == name]


def _offered(name):
    items = _hangar_implants(name)
    if not items:
        raise AssertionError('no %s in the hangar to offer' % name)
    return bool(ItemChecker(items[0]).OfferPlugInImplant())


def _plug(name):
    item = _hangar_implants(name)[0]
    sm.StartService('godma').GetDogmaLM().InjectImplant(item.itemID)
    _wait(lambda: name in _server_implants(), 10000, '%s plugged in' % name)


def _rename(cloneID, name):
    _lm().SetJumpCloneName(cloneID, name)
    sm.GetService('clonejump').jumpClones = None


def _press_yes():
    for w in uicore.registry.GetWindows():
        if w.name != 'modal':
            continue
        found = []

        def walk(n):
            if n.__class__.__name__ == 'Button' and getattr(n, 'label', None) == u'Yes':
                found.append(n)
            for c in getattr(n, 'children', []) or []:
                walk(c)
        walk(w)
        if found:
            uthread.new(found[0].OnClick)
            return True
    return False


def _jump_like_player(locationID, cloneID, until):
    # clonejumpsvc.CloneJump, as the Jump button calls it; Yes to each dialog it asks.
    uthread.new(sm.GetService('clonejump').CloneJump, locationID, cloneID)
    waited = 0
    while waited < 60000:
        _sleep(500)
        waited += 500
        _press_yes()
        if until():
            _sleep(2000)
            return
    raise AssertionError('the clone jump did not finish: station %s, ship %s' % (session.stationid, session.shipid))


def _ship_name():
    return evetypes.GetName(sm.GetService('invCache').GetInventoryFromId(session.shipid).GetItem().typeID)


def _expect(ok, what, seen):
    if not ok:
        raise AssertionError('%s; saw %r' % (what, seen))


def jc_step_setup():
    if _clones()[0]:
        raise AssertionError('the character already has jump clones; run on a fresh world (%r)' % (_clones(),))
    _slash('/giveskill me 24242 5')
    _slash('/addisk 100000000')
    if not session.stationid:
        _slash('/dock')
        _wait(lambda: session.stationid, 30000, 'docking')
        _sleep(SETTLE_MS)
    agent.jc_home = session.stationid
    agent.jc_remote = REMOTE_STATION if session.stationid != REMOTE_STATION else REMOTE_STATION_ALT
    _slash('/giveitem "%s" 2' % OCULAR)
    _slash('/giveitem "%s" 2' % MEMORY)
    _wait(lambda: len(_hangar_implants(OCULAR)) and len(_hangar_implants(MEMORY)), 10000, 'the implants in the hangar')
    _plug(OCULAR)
    _lm().InstallCloneInStation()
    _wait(lambda: _clone_at(agent.jc_home), 10000, 'the installed clone')
    return True


def jc_step_local_swap():
    # Report item 1, in a station: Augmentations open, swap into an empty named clone.
    clone = _clone_at(agent.jc_home)
    _rename(clone['id'], 'Industry')
    _prime()
    _expect(_cached() == [OCULAR], 'before the swap the cache holds the Ocular Filter', _cached())
    _expect(not _offered(OCULAR), 'the second Ocular Filter is not offered while one is fitted', _offered(OCULAR))
    _, before = _clones()
    _lm().CloneJump(agent.jc_home, clone['id'], _lm().GetPriceForClone(), True)
    _wait(lambda: _cached() == [], 10000, 'the cached implants to clear after the swap (stale cache: %r)' % (_cached(),))
    _expect(_offered(OCULAR), 'Plug In Implant is offered in the new body', _offered(OCULAR))
    left = _clone_at(agent.jc_home)
    _expect(left and left['implants'] == [OCULAR], 'the old body stays here with its implant', left)
    _expect(_clones()[1] == before, 'a swap in one station leaves the cooldown as it was', (_clones()[1], before))
    agent.jc_old_body = left['id']
    return True


def jc_step_swap_back():
    # Report item 2: name the old body, fit the new body, swap back; the named body keeps its name.
    _rename(agent.jc_old_body, 'Combat')
    _plug(OCULAR)
    _sleep(SETTLE_MS)
    _lm().CloneJump(agent.jc_home, agent.jc_old_body, _lm().GetPriceForClone(), True)
    _sleep(3000)
    stored = _clone_at(agent.jc_home)
    _expect(stored and stored['name'] == 'Industry', 'the clone left behind is still named Industry', stored)
    _expect(stored['implants'] == [OCULAR], 'and keeps the implant fitted in it', stored)
    _expect(_server_implants() == [OCULAR], 'the Combat body is back with its own Ocular Filter', _server_implants())
    return True


def jc_step_remote_from_pod():
    # Report item 1 from the pod at another station, with different implants in each body.
    _plug(MEMORY)
    _sleep(SETTLE_MS)
    _slash('/tr me %d' % agent.jc_remote)
    _wait(lambda: session.stationid == agent.jc_remote, 30000, 'arrival at the remote station')
    _sleep(SETTLE_MS)
    _expect(_ship_name() == 'Capsule', 'the character is in its pod', _ship_name())
    _prime()
    _expect(_cached() == [MEMORY, OCULAR], 'before the jump the cache holds both implants', _cached())
    target = _clone_at(agent.jc_home)
    _jump_like_player(agent.jc_home, target['id'], lambda: session.stationid == agent.jc_home)
    _wait(lambda: _cached() == [OCULAR], 10000, 'the cache to hold the Industry body\'s implants (saw %r)' % (_cached(),))
    left = _clone_at(agent.jc_remote)
    _expect(left and left['name'] == 'Combat' and left['implants'] == [MEMORY, OCULAR],
            'the Combat body stays at the remote station, named, with both implants', left)
    _expect(_clones()[1], 'a jump to another station starts the cooldown', _clones()[1])
    return True


def jc_step_swap_from_ship():
    # Report item 1 from inside a ship: the Jump button unboards first. A swap in the same station,
    # so the cooldown from the remote jump does not stop it.
    _sleep(SETTLE_MS)  # boarding right after the jump's session change is refused
    _plug(MEMORY)
    _lm().InstallCloneInStation()
    _wait(lambda: _clone_at(agent.jc_home), 10000, 'the second installed clone')
    _slash('/ship Ibis')
    ship = _wait(lambda: [i for i in sm.GetService('invCache').GetInventory(const.containerHangar).List(const.flagHangar)
                          if evetypes.GetName(i.typeID) == 'Ibis'], 10000, 'the Ibis')[0]
    uthread.new(sm.GetService('station').TryActivateShip, ship)
    _wait(lambda: session.shipid == ship.itemID, 20000, 'boarding the Ibis')
    _prime()
    _expect(_cached() == [MEMORY, OCULAR], 'before the jump the cache holds both implants', _cached())
    _, before = _clones()
    _sleep(SETTLE_MS)
    empty = _clone_at(agent.jc_home)
    _jump_like_player(agent.jc_home, empty['id'], lambda: _clone_at(agent.jc_home) and _clone_at(agent.jc_home)['name'] == 'Industry')
    _wait(lambda: _cached() == [], 10000, 'the cached implants to clear after the swap (stale cache: %r)' % (_cached(),))
    _expect(_ship_name() == 'Capsule', 'the jump left the ship', _ship_name())
    stored = _clone_at(agent.jc_home)
    _expect(stored['implants'] == [MEMORY, OCULAR], 'the Industry body stays here with both implants', stored)
    _expect(_clones()[1] == before, 'the swap leaves the cooldown as it was', (_clones()[1], before))
    return True


def jc_step_cooldown_refuses_remote():
    _sleep(SETTLE_MS)
    remote = _clone_at(agent.jc_remote)
    try:
        _lm().CloneJump(agent.jc_remote, remote['id'], _lm().GetPriceForClone(), True)
    except UserError as error:
        _expect('JumpCooldownError' in repr(error.dict), 'the refusal is the cooldown', error)
        return True
    raise AssertionError('a jump to another station went through during the cooldown')


result = 'loaded'
