"""Interpreted programs as ghost jobs (docs/interpreter.md sections 5-7): a Sigma
program's words run on cpu.Cpu, a slice at a time under the scheduler, and every trap
goes to the Python monitor: CAL1 through cal.py, anything else ends the program.

A program comes from a load module: FETCH (fetch.py) reads it into the words this
runs, and the assembler's output is written as one (fetch.write_load_module).
"""

from .cpu import Cpu, VAMASK
from .sched import CalAt, Compute

SLICE = 2000                    # instructions per clock unit (2 ms; a guess, see the doc)
MODEL = "sigma9"                # the machine's instruction set (cpu.Cpu ``model``)
ABORT = 3                       # CAL1,9 exit type: M:XXX


def program(sched, u, words, start, dcbs=None, name="", type_line=None):
    """The ghost: the image into the user's memory, then slices of instructions. A CAL1
    goes to the monitor (CalAt) and its answer comes back: the CC (resume after the
    CAL) or ('ROUTINE', address, SR3), the user's error or abnormal address."""
    mem = sched.umem[u]
    mem.update(words)
    sched.cal.dcbs.setdefault(u, {}).update(dcbs or {})   # J:DCBLINK, from the DCB table
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
            result = yield CalAt(trap.pc)
            if isinstance(result, tuple) and result and result[0] == "ROUTINE":
                cpu.PC = result[1] & VAMASK            # IOSPRTN: the error/abnormal routine
            else:
                cpu.CC = result if isinstance(result, int) else sched.psd_cc[u]
                cpu.PC = (trap.pc + 1) & VAMASK
            continue
        what = (f"TRAP X'{trap.vector:02X}' CC {trap.cc:X} AT X'{trap.pc:05X}':"
                f" {trap.name.upper()}")
        sched.trace(f"user {u}: {what}")
        if type_line is not None:
            yield from type_line(f"{name} {what}")
        sched.psd_cc[u] = cpu.CC
        from .sched import Cal1
        yield Cal1(9, address=ABORT, regs={6: 0})      # no user trap handling: M:XXX
        return
