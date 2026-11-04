"""Interpreted programs as ghost jobs (docs/interpreter.md sections 5-7): a Sigma
program's words run on cpu.Cpu, a slice at a time under the scheduler, and every trap
goes to the Python monitor: CAL1 through cal.py, anything else ends the program.

An absolute image is kept in the file system as a keyed file, so that GJOB NAME finds
it as it finds a Python program (pyprog.py), and a disc image keeps it: a header
record (key X'FFFFFF': the start address, 'SIGMA ABS', then the DCB table, 8 name
bytes and a word address a DCB) and records of words (key X'FE' + a block number:
the first word's address, then the words). The loader stand-in puts the DCB table in
the user's J:DCBLINK, as CP-V's loader does from a load module (CAL11M checks a CAL's
DCB against it). Real load modules come later.
"""

from .cpu import Cpu, VAMASK
from .files import FileError
from .sched import CalAt, Compute

HEADER, MAGIC, BLOCK = b"\xff\xff\xff", b"SIGMA ABS", 500
SLICE = 2000                    # instructions per clock unit (2 ms; a guess, see the doc)
MODEL = "sigma9"                # the machine's instruction set (cpu.Cpu ``model``)
ABORT = 3                       # CAL1,9 exit type: M:XXX


def store_image(fs, name, account, words, start, dcbs=None):
    """An absolute image as a keyed file (a host-side stand-in for a loader's output),
    replacing any old contents (as pyprog.store_source does)."""
    fs.add_account(account)
    cfu = fs.open(name, account, "OUT", keym=3)
    kf = cfu.file
    for k in kf.keys():
        kf.delete(k)
    table = b"".join(n.encode("latin-1")[:8].ljust(8) + a.to_bytes(4, "big")
                     for n, a in (dcbs or {}).items())
    kf.write(HEADER, (start or 0).to_bytes(4, "big") + MAGIC + table)
    run, block = [], 0
    for a in sorted(words) + [None]:
        if run and (a is None or a != run[-1][0] + 1 or len(run) == BLOCK):
            data = run[0][0].to_bytes(4, "big") + b"".join(w.to_bytes(4, "big") for _, w in run)
            kf.write(b"\xfe" + block.to_bytes(2, "big"), data)
            run, block = [], block + 1
        if a is not None:
            run.append((a, words[a] & 0xFFFFFFFF))
    fs.close(cfu)


def read_image(fs, name, account):
    """(words, start, dcbs) if NAME.ACCOUNT is an absolute image, else None."""
    try:
        cfu = fs.open(name, account, "IN")
    except FileError:
        return None
    try:
        kf = cfu.file
        if not hasattr(kf, "read") or getattr(kf, "KEYM", 0) != 3:
            return None
        head = kf.read(HEADER)
        if head is None or head[4:4 + len(MAGIC)] != MAGIC:
            return None
        table, dcbs = head[4 + len(MAGIC):], {}
        for i in range(0, len(table) - 11, 12):
            dcbs[table[i:i + 8].decode("latin-1").rstrip()] = int.from_bytes(table[i + 8:i + 12], "big")
        words, block = {}, 0
        while (data := kf.read(b"\xfe" + block.to_bytes(2, "big"))) is not None:
            a = int.from_bytes(data[:4], "big")
            for i in range(4, len(data), 4):
                words[a + (i - 4) // 4] = int.from_bytes(data[i:i + 4], "big")
            block += 1
        return words, int.from_bytes(head[:4], "big"), dcbs
    finally:
        fs.close(cfu)


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
