"""The model's transition table is CP-V's: parse the ESTS lines in SCHED.txt and check every
entry against TransitionTable.lookup, with CP-V's paired states merged as the model merges
them. The symbol-to-model mapping comes from the glossary refs, so this also checks those."""

import pytest

from cpvmodel import (Event, EventRouter, InconsistentEvent, NotModelledYet, PriorityBoost,
                      TransitionTable, UserState)
from cpvmodel.glossary import SOURCE_ROOT

# The CP-V listings (c00co/) are kept out of the repository, so these tests need a local copy.
needsSource = pytest.mark.skipif(not (SOURCE_ROOT / "SCHED.txt").exists(),
                                 reason="the CP-V source listings (c00co/) aren't here")

FIRST_LINE, LAST_LINE = 513, 668        # E:IIP through E:QFI
EXECUTABLE = ["SRT"] + [f"SC{n}" for n in range(11)]
CPV_STATES = EXECUTABLE + ["SCU", "STOB", "STOBO", "SIOW", "SIOMF", "SW", "SQA", "SQR", "SQRO",
                           "STI", "STIO", "SQFI", "SNULL"]


def cpvEntries():
    """[(event symbol, action symbol, [CP-V states])] in source order."""
    lines = (SOURCE_ROOT / "SCHED.txt").read_text(encoding="latin-1").splitlines()
    entries, event, pending = [], None, None
    for line in lines[FIRST_LINE - 1:LAST_LINE]:
        if not line.strip() or line.startswith("*"):
            continue
        fields = line.split()
        if pending is not None:                 # continuation of the operand field
            operands = pending + fields[0]
        elif "ESTS" in fields[:2] or "ESTS1" in fields[:2]:
            if not line[0].isspace():
                event = fields[0].split(",")[0]
                fields = fields[1:]
            operands = fields[1]
        else:
            continue
        if operands.endswith(";"):
            pending = operands[:-1]
            continue
        pending = None
        action, *states = operands.split(",")
        entries.append((event, action, states))
    return entries


def cpvTable():
    """{(event symbol, CP-V state): action symbol}, first match winning as in RCE0."""
    table = {}
    for event, action, states in cpvEntries():
        expanded = []
        for state in states:
            expanded += {"ALL": CPV_STATES, "EXECUTE": EXECUTABLE}.get(state, [state])
        for state in expanded:
            table.setdefault((event, state), action)
    return table


def symbolMap(enumClass):
    mapping = {}
    for name, ref in enumClass.cpvNames.items():
        for symbol in ref.symbols:
            mapping[symbol] = enumClass[name]
    return mapping


EVENTS = symbolMap(Event)
STATES = symbolMap(UserState) | {state: UserState.READY for state in EXECUTABLE}
ACTIONS = symbolMap(PriorityBoost) | symbolMap(UserState)
for name, value in vars(EventRouter).items():
    ref = getattr(value, "cpvRef", None)
    if ref is not None and callable(value):
        ACTIONS.setdefault(ref.symbols[0], name)


@needsSource
def testTheParserFindsEveryEvent():
    events = {event for event, _, _ in cpvEntries()}
    assert len(events) == len(Event)
    assert events <= set(EVENTS)


@needsSource
def testEveryCpvEntryMatchesTheModel():
    table = TransitionTable()
    mismatches = []
    for (event, state), action in cpvTable().items():
        expected = ACTIONS[action]
        try:
            got = table.lookup(EVENTS[event], STATES[state])
        except InconsistentEvent:
            got = None
        if got != expected:
            mismatches.append(f"{event} in {state}: CP-V {action}, model {got}")
    assert mismatches == []


@needsSource
def testTheModelInventsNoEntries():
    """A model entry needs a CP-V entry for at least one of the merged states."""
    covered = {(EVENTS[event], STATES[state]) for event, state in cpvTable()}
    table = TransitionTable()
    invented = []
    for event in Event:
        for state in UserState:
            try:
                table.lookup(event, state)
            except InconsistentEvent:
                continue
            if (event, state) not in covered:
                invented.append(f"{event.name} in {state.name}")
    assert invented == []


def testAnInconsistentEventIsAnError():
    with pytest.raises(InconsistentEvent):
        TransitionTable().lookup(Event.SLEEP, UserState.ASLEEP)


def testEveryHandlerNamedInTheTableExists():
    for rule in TransitionTable().rules:
        if isinstance(rule.action, str):
            assert callable(getattr(EventRouter, rule.action)), rule.action


def testUnmodelledTransitionsSaySo():
    from cpvmodel import System
    system = System()
    user = system.startUser("alpha", iter(()), priority=0xF8)
    system.scheduler.dispatch()
    with pytest.raises(NotModelledYet):
        system.scheduler.report(user, Event.WAIT_FOR_ACCESS)
