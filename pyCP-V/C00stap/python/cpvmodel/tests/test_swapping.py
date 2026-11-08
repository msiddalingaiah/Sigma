"""Swapping: who comes into core, who goes out, the swap quantum, and swap time."""

import pytest

from cpvmodel import (Compute, DoIo, ImpossibleSwap, SchedulerSettings, Sleep, System,
                      UserState)


def program(*steps):
    yield from steps


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def testANewUserIsSwappedInBeforeRunning():
    system = System()
    user = system.startUser("alpha", program(Compute(10)), priority=0xF8, pages=4)
    assert not user.inCore
    system.scheduler.dispatch()
    assert user.inCore
    assert system.memory.freePages == 64 - 4
    assert system.run() == "shutdown"
    assert system.memory.freePages == 64


def testASleeperIsSwappedOutWhenNobodyNeedsToComeIn():
    system = System()
    user = system.startUser("sleeper", program(Sleep(100), Compute(1)), priority=0xF8)
    system.run(tickLimit=50)
    assert user.state is UserState.ASLEEP
    assert not user.inCore
    assert system.run() == "shutdown"
    assert happened(system, "sleeper", "swapped in") == [0, 100]


def testAUserWaitingForIoIsNeverSwappedOut():
    system = System(memoryPages=8)
    reader = system.startUser("reader", program(DoIo(100), Compute(1)), priority=0xF8, pages=4)
    system.startUser("big", program(Compute(10)), priority=0xF8, pages=8)
    system.run(tickLimit=50)
    assert reader.state is UserState.IO_WAIT and reader.inCore
    assert happened(system, "big", "no room to swap in") == [0]
    system.run()
    # At 100 the reader is ready, more urgent than big and still within its swap quantum,
    # so big comes in only when the reader ends.
    assert happened(system, "big", "swapped in") == [101]


def testAReadyUserIsProtectedUntilTheSwapQuantumIsMet():
    """Two crunchers that can't both be in core. The first is swapped out only at its
    quantum end, when it has met the swap quantum."""
    settings = SchedulerSettings(quantum=250, swapQuantum=200)
    system = System(settings=settings, memoryPages=6)
    system.startUser("alpha", program(Compute(400)), priority=0xF8, pages=5)
    system.startUser("beta", program(Compute(400)), priority=0xF8, pages=5)
    system.run()
    assert happened(system, "alpha", "swap quantum met") == [250]
    assert happened(system, "alpha", "swapped out") == [250]
    assert happened(system, "beta", "swapped in") == [250, 650]
    assert happened(system, "beta", "swapped out") == [500]
    assert happened(system, "alpha", "swapped in") == [0, 500]


def swapChoice(incomingPriority):
    """A ready user in core at X'F2' that has met its swap quantum, and a newcomer that
    needs its pages."""
    system = System(memoryPages=10)
    resident = system.startUser("resident", program(Compute(1)), priority=0xF8, pages=6)
    system.scheduler.swapSchedule()
    resident.swapQuantumPending = False
    newcomer = system.startUser("newcomer", program(Compute(1)), priority=incomingPriority,
                                pages=6)
    return system.scheduler.swapScheduler.chooseUsersToSwapOut(newcomer, 2), resident


def testAMoreUrgentNewcomerCanSwapOutALessUrgentUser():
    chosen, resident = swapChoice(0xE0)         # the newcomer is at X'DA'
    assert chosen == [resident]


def testALessUrgentNewcomerCantSwapOutAMoreUrgentUser():
    """The walk runs from the least urgent band and gives up when it reaches the newcomer."""
    chosen, _ = swapChoice(0xFC)                # the newcomer is at X'F6'
    assert chosen is None


def testARunningUserIsNeverSwappedOut():
    system = System(memoryPages=10)
    system.startUser("cruncher", program(Compute(300)), priority=0xFC, pages=6)
    system.run(tickLimit=10)
    system.startUser("urgent", program(Compute(1)), priority=0x80, pages=6)
    system.scheduler.swapSchedule()
    assert happened(system, "urgent", "no room to swap in") == [10]


def testAUserTooBigForMemoryIsAnImpossibleSwap():
    system = System(memoryPages=8)
    system.startUser("huge", program(Compute(1)), priority=0xF8, pages=9)
    with pytest.raises(ImpossibleSwap):
        system.run()


def testSwapsTakeTheSwapDevicesTime():
    system = System(settings=SchedulerSettings(swapTime=10))
    system.startUser("alpha", program(Compute(5)), priority=0xF8)
    system.startUser("beta", program(Compute(5)), priority=0xF8)
    system.run()
    assert happened(system, "alpha", "swapped in") == [10]
    assert happened(system, "beta", "swapped in") == [20]      # one swap at a time (S:SIP)


def testPreemptedNearTheSwapQuantumGoesBackLessUrgent():
    """CP-V quirk: SL:SQPB, the "boost", is added to the priority value. A is preempted at
    200, between swapQuantumNear (150) and swapQuantum (250), so it goes back 2 notches
    less urgent."""
    settings = SchedulerSettings(quantum=300, swapQuantum=250, minimumRun=10)
    system = System(settings=settings)
    system.startUser("b", program(DoIo(200), Compute(5)), priority=0xE0)
    a = system.startUser("a", program(Compute(1000)), priority=0xF8)
    system.run(tickLimit=201)
    assert happened(system, "a", "preempted") == [200]
    assert a.priority == 0xF3 + 2
