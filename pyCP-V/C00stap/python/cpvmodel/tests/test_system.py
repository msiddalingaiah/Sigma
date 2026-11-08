"""The shallow System: starting users, dispatch order, priority boost and decay, shutdown."""

import pytest

from cpvmodel import Compute, NoFreeSlot, StateQueues, System, UserState
from cpvmodel.statequeues import BACKGROUND_BAND, FIRST_LEVEL_BAND, REAL_TIME_BAND


def cruncher(steps, ticks=10):
    for _ in range(steps):
        yield Compute(ticks)


def dispatchOrder(system):
    return [entry.user for entry in system.trace if entry.what.startswith("dispatched")]


def testStartUserTakesTheFirstFreeSlot():
    system = System(userSlots=2)
    user = system.startUser("alpha", cruncher(1), priority=0xF8)
    assert user.number == 1
    assert user.state is UserState.READY
    assert system.usersInSystem == 1


def testStartUserWithNoFreeSlotFails():
    system = System(userSlots=1)
    system.startUser("alpha", cruncher(1), priority=0xF8)
    with pytest.raises(NoFreeSlot):
        system.startUser("beta", cruncher(1), priority=0xF8)


def testNewUserGetsTheInteractiveBoost():
    system = System()
    user = system.startUser("alpha", cruncher(1), priority=0xF8)
    assert user.priority == 0xF8 - 6


def testPriorityBandsFollowChse1():
    assert StateQueues.bandFor(0x40) == REAL_TIME_BAND           # SRT
    assert StateQueues.bandFor(0xBF) == REAL_TIME_BAND
    assert StateQueues.bandFor(0xC0) == BACKGROUND_BAND          # SC0
    assert StateQueues.bandFor(0xF5) == BACKGROUND_BAND
    assert StateQueues.bandFor(0xF6) == FIRST_LEVEL_BAND         # SC1
    assert StateQueues.bandFor(0xFF) == FIRST_LEVEL_BAND + 9     # SC10


def testMoreUrgentUserRunsFirst():
    system = System()
    system.startUser("slow", cruncher(1), priority=0xFC)
    system.startUser("fast", cruncher(1), priority=0xF0)
    assert system.dispatch().name == "fast"


def testEqualPrioritiesTakeTurns():
    system = System()
    system.startUser("alpha", cruncher(2), priority=0xF8)
    system.startUser("beta", cruncher(2), priority=0xF8)
    system.run()
    assert dispatchOrder(system)[:4] == ["alpha", "beta", "alpha", "beta"]


def testBoostDecaysOneNotchPerDispatchAndQuantumEndRestoresBase():
    system = System()
    user = system.startUser("alpha", cruncher(2), priority=0xF8)
    system.dispatch()
    assert user.priority == 0xF8 - 5
    system.execute(user)
    assert user.priority == 0xF8
    assert user.state is UserState.READY


def testBoostedNewcomerRunsBeforeLessUrgentUsersAtBase():
    system = System()
    system.startUser("alpha", cruncher(3), priority=0xF8)
    system.run(tickLimit=10)                        # alpha is back at its base, 0xF8
    system.startUser("gamma", cruncher(1), priority=0xFC)   # starts at 0xF6
    system.run()
    assert dispatchOrder(system)[:3] == ["alpha", "gamma", "alpha"]


def testUserEndsAndFreesTheSlot():
    system = System(userSlots=1)
    user = system.startUser("alpha", cruncher(1), priority=0xF8)
    system.run()
    assert user.state is UserState.FREE_SLOT
    assert system.usersInSystem == 0
    assert system.startUser("beta", cruncher(1), priority=0xF8).number == 1


def testRunEndsInShutdownWhenTheLastUserEnds():
    system = System()
    system.startUser("alpha", cruncher(2, 40), priority=0xF8)
    assert system.run() == "shutdown"
    assert system.clock == 80


def testGhostsKeptAtShutdownLetTheSystemShutDownEarly():
    system = System()
    system.ghostsKeptAtShutdown = 1
    system.startUser("ghost", cruncher(1), priority=0xF0)
    assert system.isShutDown()


def testTickLimitStopsTheRun():
    system = System()
    system.startUser("alpha", cruncher(100, 10), priority=0xF8)
    assert system.run(tickLimit=50) == "tickLimit"
    assert system.clock == 50
