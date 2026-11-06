# Multiple Character Training checks for a real EVE client (scenario mct-certificate.json).
#
# What the client does (build 3396210):
#  - menucheckers/itemCheckers.OfferActivateMultiTraining offers "Activate" for a Multiple Pilot
#    Training Certificate (type 34133); menusvc opens activateMultiTraining.ActivateMultiTraining.
#  - ActivateMultiTrainingWindow.Reload reads userSvc.GetUpdatedMultiCharacterTraining and draws
#    every entry as a running queue ("Additional training queue active", Extend). With no
#    entry, the second row's Activate is disabled. A button press turns it into Confirm for
#    3 s (CONFIRM_DELAY); a second press calls userSvc.ActivateMultiTraining(itemID,
#    trainingID=None to open a queue, or the queue's ID to extend it). One certificate is 30
#    days.
#  - skillQueueSvc.GetMultipleCharacterTraining is userSvc.GetMultiCharactersTrainingSlots, the
#    dict the character sheet and IsAllCharacterTrainingSlotsUsed read. TQ answers {} for an
#    account without MCT.
#
# Each mct_step_* returns True or raises AssertionError with what it saw.
import uthread
from menucheckers.itemCheckers import ItemChecker
from eve.client.script.ui.shared.activateMultiTraining import ActivateMultiTraining, ActivateMultiTrainingWindow

CERTIFICATE = 34133  # Multiple Pilot Training Certificate
DAY = 864000000000


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


def _certificates():
    return [i for i in sm.GetService('invCache').GetInventory(const.containerHangar).List() if i.typeID == CERTIFICATE]


def _days():
    # The character sheet's own source, fetched fresh.
    now = blue.os.GetWallclockTime()
    slots = sm.GetService('skillqueue').GetMultipleCharacterTraining(force=True)
    return dict((k, round((v - now) / float(DAY), 2)) for k, v in slots.items())


def _open(itemID):
    window = ActivateMultiTrainingWindow.GetIfOpen()
    if window:
        window.Close()
    uthread.new(ActivateMultiTraining, itemID)
    window = _wait(lambda: ActivateMultiTrainingWindow.GetIfOpen(), 10000, 'the activation window')
    _wait(lambda: not window.reloading and window.slot1Button.text, 10000, 'the window to load')
    return window


def _rows(window):
    return [(window.slot1Title.text, window.slot1Button.text),
            (window.slot2Title.text, window.slot2Button.text, bool(window.slot2Button.disabled))]


def _press_twice(button):
    # Activate (or Extend), then Confirm within the 3 s the button holds it.
    uthread.new(button.OnClick)
    _wait(lambda: button.text == 'Confirm', 2000, 'the Confirm label')
    uthread.new(button.OnClick)


def _give(count):
    have = sum(i.stacksize for i in _certificates())
    reply = sm.GetService('slash').SlashCmd('/giveitem %d %d' % (CERTIFICATE, count))
    _wait(lambda: sum(i.stacksize for i in _certificates()) == have + count, 10000,
          'the certificates in the hangar (%s)' % reply)


def mct_step_setup():
    if not session.stationid:
        sm.GetService('slash').SlashCmd('/dock')
        _wait(lambda: session.stationid, 30000, 'docking')
        _sleep(11000)  # the client's session-change delay
    days = _days()
    assert days == {}, 'the account already has MCT queues %r; run with a new clientLaunch user' % (days,)
    _give(3)
    item = _certificates()[0]
    assert ItemChecker(item).OfferActivateMultiTraining(), 'the certificate offers no Activate'
    return True


def mct_step_dialog_empty():
    window = _open(_certificates()[0].itemID)
    rows = _rows(window)
    assert rows == [(u'Additional training queue not active', u'Activate'),
                    (u'Additional training queue not active', u'Activate', True)], rows
    assert window.numberOfDays == 30, window.numberOfDays
    window.Close()
    return True


def mct_step_activate():
    window = _open(_certificates()[0].itemID)
    _press_twice(window.slot1Button)
    _wait(lambda: window.confirmed and not window.reloading and window.expireDate1, 15000, 'the queue to open')
    days = _days()
    assert list(days) == [2] and 29.9 < days[2] <= 30, days
    assert sum(i.stacksize for i in _certificates()) == 2, 'one certificate is spent'
    assert window.slot1Title.text == u'Additional training queue active', window.slot1Title.text
    window.Close()
    return True


def mct_step_extend():
    window = _open(_certificates()[0].itemID)
    rows = _rows(window)
    assert rows[0] == (u'Additional training queue active', u'Extend'), rows
    assert rows[1][1:] == (u'Activate', False), 'the second queue can now be opened: %r' % (rows,)
    _press_twice(window.slot1Button)
    _wait(lambda: window.confirmed and not window.reloading and _days().get(2, 0) > 59, 15000, 'the extension')
    days = _days()
    assert list(days) == [2] and 59.9 < days[2] <= 60, days
    window.Close()
    return True


def mct_step_second_queue():
    window = _open(_certificates()[0].itemID)
    _press_twice(window.slot2Button)
    _wait(lambda: window.confirmed and not window.reloading and window.expireDate2, 15000, 'the second queue')
    days = _days()
    assert sorted(days) == [2, 3] and 59.9 < days[2] <= 60 and 29.9 < days[3] <= 30, days
    assert _certificates() == [], 'all three certificates are spent'
    assert window.slot2Title.text == u'Additional training queue active', window.slot2Title.text
    window.Close()
    return True
