"""The scheduler's tunable settings."""

from dataclasses import dataclass

from ..glossary import cpv


@cpv("SL:QUAN", "SL:QMIN", source="CONMAIN.txt:1037-1047",
     note="SYSGEN values that the operator can change through CONMAIN (0-5000)")
@dataclass(frozen=True)
class SchedulerSettings:
    """Times are in clock-4 ticks of 2 ms. CP-V doesn't set these in the source, so the
    defaults here are only illustrative: a quantum of 200 ms, and 20 ms before a user can
    be preempted."""
    quantum: int = 100
    minimumRun: int = 10

    cpvNames = {
        "quantum": cpv("SL:QUAN", source="ACCT.txt:27-43",
                       note="T:ACCTEX gives a new quantum; a batch partition can set its own "
                            "(PLH:QN)"),
        "minimumRun": cpv("SL:QMIN", "S:RTIR", source="SCHED.txt:794-800",
                          note="How long a user runs before a more urgent one can preempt "
                               "them; 0 while a real-time user waits"),
    }
