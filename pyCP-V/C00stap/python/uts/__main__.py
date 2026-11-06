"""Run a boot: python -m uts [options]

Examples:
    python -m uts --replies 06/15/76 13:45 N               # disc boot (installs a disc first)
    python -m uts --tape --replies IP 06/15/76 13:45 YES -
    python -m uts -i                                       # answer the prompts yourself
    python -m uts --disc sys.json.gz --tape --replies ...  # install onto a disc image
    python -m uts --disc sys.json.gz --replies ...         # disc-boot it in a later run
    python -m uts --replies 06/15/76 13:45 N --terminals 4 # then: telnet localhost 2323
"""

import argparse
import os

from .bootsubr import bootent, dboot, mtboot
from .config import Sysgen
from .devices import CardReader, Console, ConsoleExhausted, DeviceError, Disc, LinePrinter
from .files import Disc as FilesDisc
from .initial import initial
from .machine import BOOT_NAMES, BOOTTYPE, LOADDEV, Machine, MachineType, boot_type
from .monitor import Halted, Monitor, NotTranslated, SystemUp
from .reconfig import ndd_address
from .sched import demo as sched_demo
from . import image, keyin, pyprog, recovery
from .writemon import WriteMonError, writemon

MODELS = {"sigma7": MachineType.SIGMA7, "sigma9": MachineType.SIGMA9, "x560": MachineType.X560}
INSTALL_REPLIES = ["", "06/15/76", "13:45"]   # options (default T), date, time


def make_machine(model, memory_k, sysgen, console, disc=None, tape=None, cards=(),
                 extra_devices=None, public_disc=None):
    """Wire the stubs to the addresses the SYSGEN'd DCT gives them."""
    m = Machine(model=model, memory_words=memory_k * 1024, console=console,
                printer=LinePrinter(), tape=tape, card_reader=CardReader(cards))
    disc = disc if disc is not None else Disc()
    by_type = {"OC": console, "LP": m.printer, "CR": m.card_reader, "MT": tape, "DC": disc}
    for entry in sysgen.dct[1:]:
        m.devices[ndd_address(entry.ndd, model)] = by_type[entry.type]
    m.devices.update(extra_devices or {})
    m.swap_disc = disc
    m.public_disc = public_disc
    return m


def _run(m, mon, start):
    try:
        start()
    except SystemUp:
        return "up"
    except (NotTranslated, ConsoleExhausted, Halted, DeviceError) as e:
        return f"stopped: {e}"
    return "returned without reaching T:SE"


def install(model=MachineType.SIGMA9, memory_k=128, replies=None, interactive=False,
            sense_switches=(), sysgen=None, echo=False, deck=(), cards=(), disc=None,
            extra_devices=None, root=None, public_disc=None):
    """Tape-boot a system tape that WRITEMON writes from ``sysgen`` and ``deck``.
    Returns (machine, monitor, outcome)."""
    sysgen = sysgen or Sysgen()
    if replies is None:                       # default answers; RESDF '' keeps the SYSGEN values
        replies = [] if interactive else INSTALL_REPLIES[:1] + [""] * sysgen.realtime + INSTALL_REPLIES[1:]
    tape = writemon(sysgen, deck, root)
    m = make_machine(model, memory_k, sysgen, Console(replies, interactive, echo), disc, tape,
                     cards, extra_devices, public_disc)
    m.sense_switches = set(sense_switches)
    m.mem[LOADDEV] = ndd_address(sysgen.dct[4].ndd, model)
    mon = Monitor()
    return m, mon, _run(m, mon, lambda: mtboot(m, lambda mach: initial(mach, mon, sysgen)))


def boot(model=MachineType.SIGMA9, memory_k=128, replies=(), interactive=False,
         sense_switches=(), sysgen=None, echo=False, disc=None, public_disc=None):
    """Disc-boot a system. Without ``disc``, one is installed first from tape with
    default answers. ``public_disc`` holds the files (a new one if None).
    Returns (machine, monitor, outcome)."""
    sysgen = sysgen or Sysgen()
    if disc is None:
        im, _, outcome = install(model, memory_k, sysgen=sysgen, public_disc=public_disc)
        if outcome != "up":
            raise RuntimeError(f"install failed: {outcome}")
        disc = im.swap_disc
    m = make_machine(model, memory_k, sysgen, Console(replies, interactive, echo), disc,
                     public_disc=public_disc)
    m.sense_switches = set(sense_switches)
    m.mem[LOADDEV] = ndd_address(sysgen.dct[sysgen.MB_SDI].ndd, model)
    mon = Monitor()
    return m, mon, _run(m, mon, lambda: dboot(m, mon, lambda mach: initial(mach, mon, sysgen)))


def _recover(m, mon, sysgen, code, subcode):
    """SCREECH on the running system; returns (machine, new monitor, outcome)."""
    if not mon.RCVRDSZ:
        # SYSMAK sets the dump-area size (SYSMAK0.txt:594); assume it got what it
        # wants for a dump, HIGH+3 granules.
        mon.RCVRDSZ = mon.HIGH + 3
    new = Monitor()
    reboot = lambda: bootent(m, new, lambda mach: initial(mach, new, sysgen))
    return m, new, _run(m, new, lambda: recovery.screech(m, mon, sysgen, code, subcode, reboot))


def crash(m, mon, sysgen=None, code=0, subcode=0, replies=()):
    """SCREECH code-subcode on a system that is up: recovery, dump, reboot from disc."""
    m.console.replies.extend(replies)
    return _recover(m, mon, sysgen or Sysgen(), code, subcode)


def operator_recovery(m, mon, sysgen=None, replies=()):
    """The operator sets sense switch 3 and boots from the swap disc while the
    (hung) monitor is still in memory: DBOOT executes SCREECH -1."""
    sysgen = sysgen or Sysgen()
    m.console.replies.extend(replies)
    m.sense_switches.add(3)
    result = {}

    def screech(code, subcode):
        result["r"] = _recover(m, mon, sysgen, code, subcode)
        return result["r"]

    outcome = _run(m, mon, lambda: dboot(m, mon, None, screech))
    return result.get("r", (m, mon, outcome))


def parse_faults(specs):
    """'error:2', 'notop' ... -> {'error': 2, 'notop': 1}"""
    faults = {}
    for spec in specs or ():
        name, _, count = spec.partition(":")
        faults[name] = int(count or 1)
    return faults


def import_files(mon, specs):
    """--file HOST=NAME[.ACCOUNT]: put Python source into the CP-V file system as an
    EDIT-style keyed file (a host-side stand-in for an editor or a card deck)."""
    for spec in specs or ():
        host, _, target = spec.partition("=")
        name, _, account = (target or host.rsplit("/", 1)[-1].split(".")[0].upper()).partition(".")
        with open(host, encoding="utf-8") as f:
            text = f.read()
        if host.lower().endswith((".s", ".asm")):       # assembly: an absolute image
            from .asm import assemble
            from .fetch import write_load_module
            dcbs = {}
            words, start = assemble(text, dcbs)
            write_load_module(mon.sched.cal.fs, name[:7].upper(), (account or ":SYS").upper(), words,
                        start if start is not None else min(words), dcbs)
        else:
            pyprog.store_source(mon.sched.cal.fs, name[:7].upper(), (account or ":SYS").upper(),
                                text)


def restore_tapes(mon, paths):
    """--restore TAPE: a labeled tape's files into the file system, in the tape's
    account (labtape.py, a host-side stand-in for copying the tape to disc)."""
    from . import labtape
    for path in paths or ():
        with open(path, "rb") as f:
            tape = labtape.read_tape(f.read())
        names = labtape.restore(mon.sched.cal.fs, tape)
        print(f"(tape {path}: reel {tape.reel}, {len(names)} files restored to {tape.account})")


def load_cards(mon, reader=None, punch=None):
    """--reader DECK, --punch FILE: the card devices' media (cards.py, a stand-in)."""
    from .cards import CardPunch, CardReader, UnitRecord
    if reader is None and punch is None:
        return
    if punch is not None:
        open(punch, "w", encoding="utf-8").close()     # a fresh punch file each run
    deck = CardReader.load(reader) if reader else None
    mon.sched.cal.unit_record = UnitRecord(deck, CardPunch(punch) if punch else None)
    if deck is not None:
        print(f"(card reader: {len(deck.cards)} cards from {reader})")


def operator(m, mon, sysgen=None, keyins=(), lp_faults=None, prints=(), files=(), tapes=(),
             reader=None, punch=None):
    """Key-ins on a system that is up. ``lp_faults`` makes the line printer fail
    (see io.Unit); ``prints`` are lines queued to it first; ``files`` are --file
    imports, ``tapes`` --restore tapes, ``reader`` and ``punch`` the card devices'
    media. Returns the OperatorConsole."""
    sysgen = sysgen or Sysgen()
    restore_tapes(mon, tapes)
    import_files(mon, files)
    load_cards(mon, reader, punch)
    con = keyin.OperatorConsole(m, mon, sysgen, lp_faults=lp_faults,
                                screech=lambda code, sub: _recover(m, mon, sysgen, code, sub))
    for line in prints:
        con.print_line(line)
    m.console.replies.extend(keyins)
    keyin.session(con)
    return con


def operator_report(con):
    st = con.state
    lines = [f"  !{k:<20} {outcome}" for k, outcome in st.log]
    d = con.mon.DATE
    lines += [
        f"date/time      {d.get('MO', 0):02d}/{d.get('DA', 0):02d}/{d.get('YR', 0):02d} "
        f"{d.get('HR', 0):02d}:{d.get('MI', 0):02d}",
        f"users allowed  on-line S:OUAIS={st.S_OUAIS}  batch S:BUAIS={st.S_BUAIS}"
        f"  ghosts S:GUAIS={st.S_GUAIS}  max SMUIS={st.SMUIS}",
        f"RAD1ST={st.RAD1ST}  SSTAT={st.SSTAT}  devices waiting: "
        + (", ".join(con.waiting()) or "none"),
        "printer        " + (" | ".join(con.m.printer.lines) or "(nothing printed)"),
    ]
    s = con.sched
    if s is not None:
        running = [f"{name}={u}:{s.state_of(u)}" for slot, u in enumerate(s.SB_GJOBUN)
                   if u for name in [s.S_GJOBTBL[slot][0]]]
        lines.append(f"scheduler      S:CUIS={s.S_CUIS}  ghosts {', '.join(running) or 'none'}"
                     f"  at {s.now} clock units")
    return "\n".join(lines)


def summary(m, mon):
    locks = {0: 0, 1: 0, 3: 0}
    for c in mon.LKIMG:
        locks[c] = locks.get(c, 0) + 1
    word = m.mem[BOOTTYPE]
    lines = [
        f"machine        {m.model.name}  CSED%MACHINE=X'{mon.CSED_MACHINE:02X}'",
        f"boot type      {boot_type(word)} {BOOT_NAMES[boot_type(word)]}  (X'2A'=X'{word:08X}')",
        f"memory         CORED=X'{mon.CORED:X}' words, HIGH page X'{mon.HIGH:X}'",
        f"BOOTFLG        X'{m.mem.get_byte(0x27):02X}'",
        f"date/time      {mon.DATE}",
        f"free pages     M:FPPC={mon.M_FPPC} head X'{mon.M_FPPH:X}' tail X'{mon.M_FPPT:X}'",
        f"monitor pages  MP:UPPC={mon.MP_UPPC} head X'{mon.MP_UPPH:X}' tail X'{mon.MP_UPPT:X}'",
        f"RESDF pages    PP:UPPC={mon.PP_UPPC}",
        f"SL:CORE        X'{mon.SL_CORE:X}'  S:ACORE={mon.S_ACORE}  S:PCORE={mon.S_PCORE}",
        f"SPOOL buffer   X'{mon.SPOOL:X}'",
        f"write locks    00:{locks[0]} 01:{locks[1]} 11:{locks[3]} pages",
        f"SYSVERS        X'{mon.SYSVERS:08X}'",
        f"ghosts         {', '.join(mon.ghosts_started)}",
        f"interrupts     X'{m.interrupt_mask:04X}'" if m.interrupt_mask else "interrupts     -",
    ]
    if mon.DABOOT[0]:
        lines += [
            f"swap disc      ROOTSA={mon.DABOOT}  XDELTA@{mon.DLTDSC}  UMOV@{mon.UMOVSA}"
            f"  RECOVER@{mon.RCVDISC}  RCVRAD={mon.RCVRAD}",
            f"MONCHK         X'{mon.MONCHK:08X}'",
        ]
    return "\n".join(lines)


def read_deck(path):
    with open(path, encoding="ascii") as f:
        return [line.rstrip("\n").upper().ljust(80)[:80] for line in f if line.strip()]


def main(argv=None):
    p = argparse.ArgumentParser(prog="uts", description="Boot the translated UTS monitor.")
    p.add_argument("--machine", choices=MODELS, default="sigma9")
    p.add_argument("--memory", type=int, default=128, help="installed memory, K words")
    p.add_argument("--sense", type=int, nargs="*", default=[], help="sense switches set (1-4)")
    p.add_argument("--realtime", action="store_true", help="SYSGEN as a real-time system")
    p.add_argument("--version", default="C00 ", help="WRITEMON version (4 characters)")
    p.add_argument("--tape", action="store_true", help="tape boot: install from a WRITEMON tape")
    p.add_argument("--disc", metavar="PATH",
                   help="disc image: load the swap and public discs from PATH (if it exists)"
                        " and save them there when the run ends")
    p.add_argument("--reboot", action="store_true",
                   help="after --tape comes up, disc-boot from the disc it wrote")
    p.add_argument("--crash", metavar="CC[-SS]",
                   help="after the boot comes up, SCREECH with this hex code and subcode")
    p.add_argument("--oprec", action="store_true",
                   help="after the boot comes up, operator recovery (sense switch 3 + disc boot)")
    p.add_argument("--keyins", nargs="*", metavar="K",
                   help="after the boot comes up, operator key-ins, in order ('-' is an empty line)")
    p.add_argument("--console", action="store_true",
                   help="after the boot comes up, an interactive '!' key-in session (with -i)")
    p.add_argument("--print", nargs="*", default=[], metavar="LINE", dest="prints",
                   help="lines the monitor prints on the line printer before the key-ins")
    p.add_argument("--lp-fault", nargs="*", default=[], metavar="FAULT[:N]",
                   help="make the line printer fail N times: notop, manual, error, parity, hang")
    p.add_argument("--patches", help="patch deck file for WRITEMON's M:PATCH (one card per line)")
    p.add_argument("--replies", nargs="*", default=[],
                   help="console replies, in order; '-' means Enter (no input)")
    p.add_argument("-i", "--interactive", action="store_true", help="read replies from stdin")
    p.add_argument("--trace", action="store_true", help="print the boot trace")
    p.add_argument("--file", nargs="*", default=[], metavar="HOST=NAME[.ACCOUNT]", dest="files",
                   help="Python programs to import into the file system; start one with GJOB NAME")
    p.add_argument("--restore", nargs="*", default=[], metavar="TAPE.tap", dest="tapes",
                   help="labeled tapes (simh .tap) whose files are restored into the file system,"
                        " in the tape's account")
    p.add_argument("--mount", nargs="*", default=[], metavar="TAPE.tap",
                   help="labeled tapes mounted for the terminals' TAPE command (list and copy"
                        " files into one's own account; not CP-V)")
    p.add_argument("--reader", metavar="DECK.txt",
                   help="a text file loaded into the card reader: a card a line (EBCDIC, 80 columns)")
    p.add_argument("--punch", metavar="FILE.txt",
                   help="a text file the card punch writes, a card a line")
    p.add_argument("--terminals", type=int, default=0, metavar="N",
                   help="after the boot comes up, N terminal lines on a TCP port (telnet), in"
                        " real time; Ctrl-C ends")
    p.add_argument("--port", type=int, default=2323, help="the terminals' TCP port")
    p.add_argument("--bind", default="127.0.0.1", metavar="ADDRESS",
                   help="the address the terminals listen on (no authentication: trusted"
                        " networks only)")
    p.add_argument("--sched", action="store_true",
                   help="run the scheduler demo (sched.py) instead of a boot: ghosts and an on-line user")
    args = p.parse_args(argv)
    if args.sched:
        s, outcome = sched_demo()
        print("\n".join(s.log))
        print(f"\n--- scheduler {outcome} at {s.now} clock units: users ended {s.ended},"
              f" swap giveups {s.C['NSP']} ---")
        return
    args.replies = ["" if r == "-" else r for r in args.replies]

    sysgen = Sysgen(realtime=args.realtime, version=args.version.ljust(4)[:4])
    if args.terminals:
        sysgen.COC = sysgen.S_OUAIS = args.terminals   # an on-line system with N lines
    model = MODELS[args.machine]
    swap = public = None
    if args.disc and os.path.exists(args.disc):
        swap, public = image.load(args.disc)
        print(f"(disc image {args.disc}: {len(swap.sectors)} sectors, "
              f"{len(public.g)} granules in use)")
    elif args.disc:
        public = FilesDisc(2048)
    machines = []
    try:
        run(args, sysgen, model, swap, public, machines)
    finally:
        if args.disc and machines:
            m = machines[-1]
            image.save(args.disc, m.swap_disc, m.public_disc or public)
            print(f"\n(disc image saved to {args.disc})")


def run(args, sysgen, model, swap, public, machines):
    """The boot and what follows it; each machine used goes onto ``machines``."""
    try:
        deck = read_deck(args.patches) if args.patches else ()
        if args.tape:
            m, mon, outcome = install(model, args.memory, list(args.replies), args.interactive,
                                      args.sense, sysgen, deck=deck, disc=swap,
                                      public_disc=public)
        else:
            m, mon, outcome = boot(model, args.memory, args.replies, args.interactive,
                                   args.sense, sysgen, disc=swap, public_disc=public)
    except WriteMonError as e:
        print(f"WRITEMON: {e}\n*****  DEF PROCESSOR ABORTED  *****")
        return
    machines.append(m)
    report(m, mon, outcome, args)
    if args.tape and args.reboot and outcome == "up":
        print("\n=== disc boot from the installed swap disc ===")
        rest = list(m.console.replies)
        m, mon, outcome = boot(model, args.memory, rest, args.interactive, args.sense,
                               sysgen, disc=m.swap_disc, public_disc=m.public_disc)
        machines.append(m)
        report(m, mon, outcome, args)
    if (args.crash or args.oprec) and outcome == "up":
        m.console.transcript.clear()
        m.log.clear()
        crashed = mon
        if args.oprec:
            print("\n=== operator recovery: SSW3 set, boot from the swap disc ===")
            m, mon, outcome = operator_recovery(m, mon, sysgen)
        else:
            code, _, sub = args.crash.partition("-")
            print(f"\n=== SCREECH {args.crash} ===")
            m, mon, outcome = crash(m, mon, sysgen, int(code, 16), int(sub or "0", 16))
        report(m, mon, outcome, args)
        if crashed.TRCVRAD:
            print(f"crash          RCVCODE=X'{crashed.RCVCODE:08X}'  recovery buffer@{crashed.TRCVRAD}"
                  f"  dump@{crashed.TRCVRAD + 4}..{crashed.RCVRAD - 1}  X'4000'@{crashed.SEEK4000}")
    if (args.keyins is not None or args.console or args.terminals or args.tapes
            or args.reader or args.punch) and outcome == "up":
        m.console.transcript.clear()
        print("\n=== operator console ===")
        if args.console and args.interactive and not args.terminals:
            print("(type key-ins at the ! prompt; end of input, Ctrl-Z Enter or Ctrl-D, ends)")
        keyins = ["" if k == "-" else k for k in (args.keyins or [])]
        if args.terminals:
            m.console.interactive = False              # the scripted key-ins first
        con = operator(m, mon, sysgen, keyins, parse_faults(args.lp_fault), args.prints,
                       args.files, args.tapes, args.reader, args.punch)
        if not args.interactive or args.terminals:
            print(m.console.text())
        if args.terminals and con.shutdown is None and con.sched is not None:
            terminals(con, args)
        print(operator_report(con))
        if args.trace and con.sched is not None:
            print("\nscheduler (clock units, T:SE and T:SS):\n" + "\n".join(con.sched.log))
        if con.shutdown is not None:
            m, mon, outcome = con.shutdown
            print("\n=== shutdown: SCREECH X'404' from the idle check, recovery and reboot ===")
            report(m, mon, outcome, args)


def terminals(con, args):
    """--terminals: COC lines on a TCP port, LOGON and TEL, in real time (docs/online.md).
    With -i --console, key-ins typed on the host console go to the operator's KEYIN."""
    import queue
    import threading
    from .coc import Coc
    from .online import Online
    from .terminals import TerminalServer, realtime
    s = con.sched
    coc = Coc(s, lines=min(args.terminals, len(s.LB_UN)))
    online = Online(s)
    from . import labtape
    for path in args.mount:                            # tapes for TEL's TAPE (not CP-V)
        with open(path, "rb") as f:
            tape = labtape.read_tape(f.read())
        online.mount(tape)
        print(f"(tape {path} mounted: reel {tape.reel}, {len(tape.files)} files)")
    try:
        server = TerminalServer(coc, args.port, args.bind, log=lambda msg: print(f"({msg})"))
    except OSError as e:
        print(f"(terminals: can't listen on {args.bind}:{args.port}: {e})")
        return
    host, port = server.address
    print(f"\n=== terminals: {len(coc.lines)} lines on telnet {host} {port}; Ctrl-C ends ===")
    keyins = None
    console = con.m.console
    console.echo = True                                # the console's output, as it happens
    if args.interactive and args.console:
        print("(type key-ins here; they go to the operator's KEYIN)")
        keyins = queue.Queue()

        def read_stdin():
            while True:
                try:
                    keyins.put(input())
                except (EOFError, KeyboardInterrupt):
                    keyins.put(None)
                    return
        threading.Thread(target=read_stdin, daemon=True, name="operator").start()
    realtime(con, server, keyins)
    console.echo = False
    print(f"\n(terminals closed at {s.now} clock units)")


def report(m, mon, outcome, args):
    if not args.interactive:
        print(m.console.text())
    print(f"\n--- boot {outcome} ---")
    if args.trace:
        print("\n".join(m.log))
        if m.printer.lines:
            print("\nLP:\n" + "\n".join(m.printer.lines))
        print()
    print(summary(m, mon))


if __name__ == "__main__":
    main()
