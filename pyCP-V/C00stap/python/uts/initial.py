"""INITIAL: where the monitor starts executing. Translated from c00co/INITIAL.txt."""

from .machine import MachineType, SYSVERS_LOC, INITIAL_VEC, PAGE_WORDS
from .monitor import SystemUp
from . import bootsubr, ghosts

# XPSDS table (INITIAL.txt:238): what INITIAL installs at X'40'-X'5F'.
XPSDS = [
    "NOPPSD", "UNIMPPSD", "STKLPSD", "FIXOVPSD", "FLTFPSD", "DECFPSD",
    "CSED%PSD%T46", "IPT47", "CAL1PSD", "CAL2PSD", "CAL3PSD", "CAL4PSD",
    "CSED%PSD%T4C", "CSED%PSD%T4D", "LEE20", "CJOB",
    "POWRON", "POWROFF", "MTW,0 0", "MTW,0 0 (CLOCK2)", "MTW,-1 TINC",
    "MTW,1 *S:CLOCK4", "CSED%PSD%I56", "CSED%PSD%I57", "MTW,0 0 (CLOCK1)",
    "MTW,0 0 (CLOCK2)", "CLK3PSD", "CLK4PSD", "AIOPSD", "OCPSD",
    "DATA 0", "DATA INITIAL",
]

# Interrupt enables written to WD X'1200' before T:SE (INITIAL.txt:128).
INTERRUPT_ENABLE = {
    MachineType.SIGMA7: 0x38F0,   # MPI
    MachineType.SIGMA9: 0x34F0,   # MFI, CPU fault left armed
    MachineType.X560: 0x3CF0,     # MFI and PFI
}

# Write-lock codes (LOADWL).
WL_00, WL_01, WL_11 = 0, 1, 3


def initial(m, mon, sysgen):
    """INITIAL  INITIAL.txt:49"""
    # INIT2: on a Sigma 7, a big-memory (:BIG) system can't run.
    # (Our model never assembles :BIG, so the check always passes.)

    # Fill X'60'..MONORG-1 with MTW,0 0, then install the trap XPSDs.
    m.low_core = {a: "MTW,0 0" for a in range(0x60, sysgen.MONORG)}
    m.low_core.update({0x40 + i: name for i, name in enumerate(XPSDS)})
    m.mem[INITIAL_VEC] = 0x5E               # stands in for the INITIAL address

    # DEBUG PACHER (XPSD TRP51) would offer card patches here; not translated.

    m.interrupt_mask = 0x2020                # arm and enable I/O and clock 3
    bootsubr.moninit(m, mon, sysgen)
    lma(m, mon, sysgen)

    # Build the monitor JIT stack (TSTACK) - nothing to model yet.
    # Release the boot-time swap space for GHOST1 (BOOTSBAND / T:SGRNU).
    psa_end = sysgen.PSA_END
    mon.BOOTSBAND = psa_end - 8 if psa_end >= 0x1480 else psa_end
    m.trace(f"INITIAL: BOOTSBAND=X'{mon.BOOTSBAND:X}', released {mon.SL_CORE} swap granules")

    m.mem[SYSVERS_LOC] = mon.SYSVERS        # LW,0 SYSVERS (built by TBOOT:, kept in the root)
    m.low_core[0x5C] = "IOXPSD (for GHOST1)"
    mon.CSED_PATH = 0                        # tell trap handlers INITIAL is done

    mon.sched = ghosts.boot_scheduler(m, mon, sysgen)
    for slot in (2, sysgen.MING):            # LD,0 S:GJOBTBL+4 / S:GJOBTBL+MING+MING
        name = mon.sched.S_GJOBTBL[slot][0]
        cc, user = mon.sched.t_gjobstrt(name)  # BAL,10 T:GJOBSTRT
        mon.ghosts_started.append(name)
        m.trace(f"INITIAL: T:GJOBSTRT {name}: user {user}, CC X'{cc:X}'")

    m.interrupt_mask = INTERRUPT_ENABLE[m.model]
    m.clock3_running = True                  # fire clock 3 zero
    m.trace(f"INITIAL: interrupts X'{m.interrupt_mask:04X}', B T:SE")
    raise SystemUp("T:SE")


def lma(m, mon, sysgen):
    """LMA  INITIAL.txt:142 - LOADWL (write locks) then LOADMAP."""
    pages = mon.CORED // PAGE_WORDS
    mon.LKIMG = [WL_00] * pages

    def lwl(first, last, code):
        for p in range(first // PAGE_WORDS, last // PAGE_WORDS + 1):
            if p < pages:
                mon.LKIMG[p] = code

    lwl(0, sysgen.PPSTART - 1, WL_01)                     # monitor data
    lwl(sysgen.JIT, sysgen.JIT + 511, WL_01)              # JIT
    lwl(sysgen.PPSTART + 511, sysgen.TOPROOT - 1 - 256, WL_11)  # pure procedure
    lwl(sysgen.JIT + 512, mon.PB_HVA[mon.UMOV_] * PAGE_WORDS - 1, WL_11)  # UMOV (UMOV#)
    if m.model is MachineType.X560:
        lwl(sysgen.IOLOW, sysgen.IOHIGH - 1, WL_00)       # I/O buffers
    # LOADMAP: identity map and access codes - not modeled.
    m.trace("LMA: write locks and map loaded")
