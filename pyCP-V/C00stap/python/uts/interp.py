"""Interpreted programs as ghost jobs (docs/interpreter.md sections 5-7): a Sigma
program's words run on cpu.Cpu, a slice at a time under the scheduler, and every trap
goes to the Python monitor: CAL1 through cal.py, anything else ends the program.

A program comes from a load module: FETCH (fetch.py) reads it into the words this
runs, and the assembler's output is written as one (fetch.write_load_module).
"""

from .cal import PSD1, SMPSD, TRAPFLGB
from .cpu import Cpu, VAMASK
from .jit import USENT
from .sched import CalAt, Compute

SLICE = 2000                    # instructions per clock unit (2 ms; a guess, see the doc)
MODEL = "sigma9"                # the machine's instruction set (cpu.Cpu ``model``)
ABORT = 3                       # CAL1,9 exit type: M:XXX
# J:USENT's trap flags by trap: NAO, UI, PS, FP, DEC, FX are bits 2-7 (ALTCP.txt:1177;
# TABLES.txt:791-:798's NAOMASK, PSMASK, FLTMASK, DECMASK, FXMASK)
TRAP_FLAGS = {0x40: 0x20, 0x41: 0x10, 0x42: 0x08, 0x43: 0x01, 0x44: 0x04, 0x45: 0x02}


def save_psd(sched, u, cpu, address):
    """The PSD's word 0 the monitor sees in TSTACK (without the CC: sched.psd_cc)."""
    w0 = (SMPSD | ((cpu.FPC & 0xF) << 24) | (0x00200000 if cpu.DM else 0)
          | (0x00100000 if cpu.AM else 0) | (address & 0x1FFFF))
    sched.cal.upsd[u] = (w0, PSD1)


def load_psd(sched, u, cpu):
    """The floating controls and masks back from the PSD (M:TRAP may change them)."""
    w0 = sched.cal.upsd.get(u, (SMPSD, PSD1))[0]
    cpu.FPC = (w0 >> 24) & 0xF
    cpu.DM, cpu.AM = bool(w0 & 0x00200000), bool(w0 & 0x00100000)


def program(sched, u, words, start, dcbs=None, name="", type_line=None, before=None):
    """The ghost: the image into the user's memory, then slices of instructions. A CAL1
    goes to the monitor (CalAt) and its answer comes back: the CC (resume after the
    CAL) or ('ROUTINE', address, SR3), the user's error or abnormal address."""
    mem = sched.umem[u]
    mem.update(words)
    sched.cal.dcbs[u] = dict(dcbs or {})               # J:DCBLINK: this program's DCB table
    sched.cal.mem_dcbs[u] = {}                         # (none of the last program's DCBs)
    if before is not None:
        before()                                       # the step's work with memory in place
    cpu = Cpu(sched.uregs[u], mem, pc=start, cc=sched.psd_cc[u], model=MODEL)
    sched.trace(f"LOAD {name}: {len(words)} words, start X'{start:X}' (interpreted)")
    done = 0
    while True:
        n, trap = cpu.run(SLICE - done)
        done += n
        if done >= SLICE or (trap is None and n == 0):
            yield Compute(1)                           # a clock unit of instructions
            done = 0
        if trap is None:
            continue
        if trap.vector == 0x48:                        # CAL1: into the Python monitor
            sched.psd_cc[u] = cpu.CC
            save_psd(sched, u, cpu, trap.pc + 1)       # the PSD in TSTACK: after the CAL
            result = yield CalAt(trap.pc)
            if isinstance(result, tuple) and result and result[0] == "ROUTINE":
                cpu.PC = result[1] & VAMASK            # IOSPRTN: the error/abnormal routine
                if len(result) > 3:                    # exit control: a new PSD (SMPSD)
                    cpu.CC = result[3]
            else:
                cpu.CC = result if isinstance(result, int) else sched.psd_cc[u]
                cpu.PC = (trap.pc + 1) & VAMASK
            load_psd(sched, u, cpu)
            continue
        if sched.cal.jword(u, USENT) & (TRAP_FLAGS.get(trap.vector, 0) << TRAPFLGB):
            from .monitor import NotTranslated         # M:TRAP asked for it: TRAP, not abort
            raise NotTranslated(f"trap X'{trap.vector:02X}' at X'{trap.pc:05X}' to the"
                                " user's trap entry (M:TRAP)")
        what = (f"TRAP X'{trap.vector:02X}' CC {trap.cc:X} AT X'{trap.pc:05X}':"
                f" {trap.name.upper()}")
        sched.trace(f"user {u}: {what}")
        if type_line is not None:
            yield from type_line(f"{name} {what}")
        sched.psd_cc[u] = cpu.CC
        save_psd(sched, u, cpu, trap.pc)               # the trapped instruction
        from .sched import Cal1
        yield Cal1(9, address=ABORT, regs={6: 0})      # no user trap handling: M:XXX
        return
