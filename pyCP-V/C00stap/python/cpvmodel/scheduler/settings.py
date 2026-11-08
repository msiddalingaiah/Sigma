"""The scheduler's tunable settings."""

from dataclasses import dataclass

from ..glossary import cpv, modelOnly


@cpv("SL:QUAN", "SL:QMIN", source="CONMAIN.txt:1037-1047",
     note="SYSGEN values that the operator can change through CONMAIN (0-5000)")
@dataclass(frozen=True)
class SchedulerSettings:
    """Times are in clock-4 ticks of 2 ms. CP-V doesn't set the quantum, minimum run or swap
    quantum in the source, so those defaults are only illustrative: a quantum of 500 ms,
    20 ms before a user can be preempted, and 400 ms of running before a swapped-in user can
    be swapped out again. ``swapQuantumNear`` and ``swapPenalty`` are CP-V's own values.
    The swap quantum is only checked past ``swapQuantumNear`` (300 ms), so a quantum shorter
    than that leaves a swapped-in compute user protected for good.

    ``swapTime`` is how long the swap device takes for each user swapped in or out. It is 0
    by default, so swaps finish at once unless a scenario asks for more."""
    quantum: int = 250
    minimumRun: int = 10
    swapQuantum: int = 200
    swapQuantumNear: int = 150
    swapPenalty: int = 2
    swapTime: int = 0

    cpvNames = {
        "quantum": cpv("SL:QUAN", source="ACCT.txt:27-43",
                       note="T:ACCTEX gives a new quantum; a batch partition can set its own "
                            "(PLH:QN)"),
        "minimumRun": cpv("SL:QMIN", "S:RTIR", source="SCHED.txt:794-800",
                          note="How long a user runs before a more urgent one can preempt "
                               "them; 0 while a real-time user waits"),
        "swapQuantum": cpv("SL:SQUAN", source="CONMAIN.txt:1039",
                           note="Run time after a swap-in before the user can be swapped out"),
        "swapQuantumNear": cpv("SL:SQNT", source="SSDAT.txt:294", note="150, \"300 MS\""),
        "swapPenalty": cpv("SL:SQPB", source="SSDAT.txt:293",
                           note="2, \"BOOST TWO NOTCHES\", but added to the priority value"),
        "swapTime": modelOnly("Swap device time per user; CP-V's comes from the RADs and "
                              "disc packs"),
    }
