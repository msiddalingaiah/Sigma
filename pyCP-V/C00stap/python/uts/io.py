"""Monitor I/O: IOQ queueing and scheduling, with the console and printer handlers.

Translated from c00co/IOQ.txt and c00co/HANDLERS.txt. See docs/io.md. Comments of
the form ``# FILE:NNN`` point at the source.

Translated: NEWQ/GETQ, the channel queue, DRIVEIO/DSERV/IOSCHED/REQSERV,
STARTIO/COMLIST/IOSST/IOSTRT/IOREJECT, IOINT, CLEANUP1/IOSCU/SETKEYIN, REQCOM,
CLOCKIO/INTSIM, MSGOUT, IOSERCK/PRE%CU, and the typewriter (KBTIO/KBTCU) and line
printer (PRTOUT/PRTCU) handlers.

Simplifications: DCB requests only from cal.py's device path (no ECBs, files or COC); single access,
with one channel per device; no DEFER to the control task; command lists are
Python tuples. The hardware is the ``Unit`` classes below: a unit accepts or
rejects an SIO, and later completes it, which raises the I/O interrupt.
"""

from collections import deque
from dataclasses import dataclass, field

NL = "\n"
EOM = "\x08"

# Flags a handler returns in R12 (IOQ.txt:1527).
F_RETRY, F_FOLLOW, F_INTEROP = 0x8000, 0x4000, 0x2000
F_KEYIN, F_KEYIN_NC, F_HOLD = 0x1000, 0x0800, 0x0400
TYC_NORMAL, TYC_LOST, TYC_EOD, TYC_ERROR = 1, 2, 6, 8

# Device messages (IOQ.txt:2085), typed after the device name.
MSG1, MSG2, MSG3, MSG4 = " MANUAL", " ERROR", " TIMED OUT", " NOT OPERATIONAL"
MSG5, MSG6, MSG7 = " WRITE PROTECTED", " PLEASE RESPOND", " CODE DISC ERR"
CR, CR3T = NL, NL + "\t\t\t"                        # CR3T DATA X'15050505'

# Console function steps (KBTIO's DOT) and printer steps (DOTCR).
TY_READ, TY_WRITE, TY_WRITE_NAME, TY_READ_RAW, TY_READ_RETRY, TY_WRITE_NL, TY_WRITE_NAME_TAB = range(7)
LP_PRINT, LP_PRINT_FORMAT, LP_FORMAT = 1, 3, 4


@dataclass
class Dot:
    """One DOT entry (:DOT, HANDLERS.txt:79): commands, timeout, retry step, follow-on step."""
    commands: tuple
    timeout: int        # 5-second units, 0 = no limit
    retry: int
    follow: int


@dataclass
class Request:
    """An IOQ entry."""
    index: int
    dct: int
    function: int                       # IOQ4
    step: int                           # IOQ5
    buffer: str = ""                    # IOQ8 (write data, or what a read returned)
    count: int = 0                      # IOQ9
    seek: int = 0                       # IOQ12 (for a device-name write: the DCT index)
    end_action: object = None           # IOQ13
    ea_info: object = None
    tries: int = 1                      # IOQ10
    tries_left: int = 1                 # IOQ11
    priority: int = 0xFF                # IOQ14
    busy: bool = False                  # IOQ3 X'80'
    tyc: int = 0
    rbc: int = 0
    done: bool = False
    dcb: object = None                  # IOQ6: a DCB request (QUEUE), None for NEWQ
    user: int = 0                       # IOQ15
    write: bool = False                 # the DCB function's write bit


@dataclass
class Device:
    """The IOQ fields of one DCT entry (docs/io.md section 1)."""
    index: int
    name: str
    unit: object
    handler: object
    busy: bool = False                  # DCT5 X'80'
    cleanup: bool = False               # X'40'
    interop: bool = False               # X'20'
    data_xfer: bool = False             # X'10'
    keyin: bool = False                 # X'08'
    manual: bool = False                # X'02'
    sio_fail: bool = False              # DCT3 X'08'
    timed_out: bool = False             # DCT3 X'10'
    current: object = None              # DCT6
    deadline: int = 0                   # DCT11
    increment: int = 0                  # DCT18
    retry_step: int = 0                 # DCT17
    follow_step: int = 0
    keyin_flags: int = 0                # kept in DCT13 while a key-in is pending
    status: dict = field(default_factory=dict)   # AIO/TIO/TDV status
    rbc: int = 0                                 # residual byte count
    data: str = ""                               # what the last read transferred
    queue: list = field(default_factory=list)    # CIT1..CIT2: one channel per device


# --- hardware --------------------------------------------------------------

class Unit:
    """A device on the I/O bus. ``faults`` maps a condition to how many times it
    happens: 'notop' (SIO rejected), 'manual' (in manual mode: the count is how
    many timeout checks it stays manual), 'error' (bad status), 'parity'
    (code-disc parity, printer only), 'hang' (never interrupts)."""

    def __init__(self, faults=None):
        self.faults = dict(faults or {})
        self.commands = None
        self.manual = 0

    def _take(self, fault):
        if self.faults.get(fault, 0) > 0:
            self.faults[fault] -= 1
            return True
        return False

    def sio(self, commands):
        """Returns 'rejected', 'manual' or 'accepted'."""
        if self._take("notop"):
            return "rejected"
        self.commands = commands
        if self.faults.get("manual", 0) > 0:
            self.manual = self.faults.pop("manual")
            return "manual"
        return "accepted"

    def tio_manual(self):
        """TIO during CLOCKIO: still manual? Each check uses up one of the count."""
        if self.manual:
            self.manual -= 1
        return self.manual > 0

    def ready(self):
        """Will the operation finish (raise its interrupt) now?"""
        if self.manual:
            return False
        return not self._take("hang")

    def hio(self):
        self.commands = None

    def complete(self):
        """Carry out the command list. Returns (status, residual count, data read)."""
        commands, self.commands = self.commands, None
        status = {"error": self._take("error"), "parity": self._take("parity")}
        data = ""
        for order, text, count in commands:
            data += self.execute(order, text, count, status)
        return status, 0, data

    def execute(self, order, text, count, status):
        return ""


class ConsoleUnit(Unit):
    """The operator console. A read takes the next line typed."""

    def __init__(self, console, faults=None):
        super().__init__(faults)
        self.console = console

    def execute(self, order, text, count, status):
        if order == "write":
            self.console.write(text[:count] if count else text)
            return ""
        line = self.console.read()                      # ConsoleExhausted ends a session
        line = line.upper()
        return line[:count] if len(line) >= count else line + NL


class PrinterUnit(Unit):
    def __init__(self, printer, faults=None):
        super().__init__(faults)
        self.printer = printer

    def execute(self, order, text, count, status):
        if order == "write" and not status["error"] and not status["parity"]:
            self.printer.print(text.rstrip(NL))
        return ""


# --- handlers ----------------------------------------------------------------

class ConsoleHandler:
    """The typewriter handler, KBTIO/KBTCU  HANDLERS.txt:86, :130."""
    DOT = {
        TY_READ: Dot((("read", "buffer"),), 12, 4, 5),                         # RDTYE
        TY_WRITE: Dot((("write", "buffer"),), 4, 0, 0),                        # WRBNC
        TY_WRITE_NAME: Dot((("write", CR), ("write", "name"), ("write", "buffer")), 4, 0, 0),
        TY_READ_RAW: Dot((("read", "buffer"),), 12, 0, 0),                     # RDBNC
        TY_READ_RETRY: Dot((("write", NL), ("read", "buffer")), 12, 4, 5),     # WRNLC, RDTYE
        TY_WRITE_NL: Dot((("write", NL),), 1, 0, 0),                           # WRNLNC
        TY_WRITE_NAME_TAB: Dot((("write", CR3T), ("write", "name"), ("write", "buffer")), 4, 0, 0),
    }

    def post(self, io, dev, req, status, rbc, data):
        """KBTCU: editing reads look for EOM, NL and !EOD."""
        io.m.trace(f"KBTCU: alarm {'on' if dev.sio_fail or dev.timed_out else 'off'}")  # WD X'41'/X'40'
        if req.step & 3:                                # not a read with editing
            return 0, TYC_NORMAL, None
        if dev.sio_fail or dev.timed_out:
            data = NL                                   # timeout: an NL in the buffer
        req.buffer = data
        for ch in data[:req.count]:
            if ch == EOM:
                return F_RETRY | F_FOLLOW, 0, None      # KBTIO5: X'C000' retry
            if ch == NL:
                tyc = TYC_EOD if data[:4] == "!EOD" else TYC_NORMAL   # 4CHAR / XEOD
                return 0, tyc, None
        return F_FOLLOW | F_INTEROP, 0, None            # X'6000': follow-on, type an NL


class PrinterHandler:
    """The buffered line printer, PRTOUT/PRTCU  HANDLERS.txt:242, :269."""
    DOT = {
        LP_PRINT: Dot((("write", "buffer"),), 1, LP_PRINT, 0),                # WRLP
        LP_PRINT_FORMAT: Dot((("write", "buffer"),), 1, LP_PRINT_FORMAT, 0),  # WRLPF
        LP_FORMAT: Dot((("format", "buffer"),), 1, LP_FORMAT, 0),
    }

    def post(self, io, dev, req, status, rbc, data):
        result = io.ioserck(dev, req, status)
        if result is not None:
            return result                               # normal completion
        if status.get("parity"):                        # X'C000': buffer or code-disc parity
            return F_FOLLOW | F_KEYIN_NC, 0, MSG7       # X'4800'
        return F_RETRY | F_FOLLOW, TYC_ERROR, MSG2      # retry (RMARET's R12 and R13)


class PreCU(Exception):
    """IOSERCK's SIO-failure and timeout path: B PRE%CU, straight to IOSCU."""

    def __init__(self, flags, msg):
        self.flags, self.msg = flags, msg


# --- IOQ -------------------------------------------------------------------

class IOSystem:
    def __init__(self, m, mon, nentries=20):
        self.m, self.mon = m, mon
        self.qfree = deque(range(1, nentries + 1))    # QFREE
        self.devices = {}                              # DCT index -> Device
        self.pending = deque()                         # devices with an interrupt to deliver
        self.ioclock = 0                               # IOCLOCK, 5-second units
        self.in_run = False
        self.completed = []                            # (request, tyc) in completion order
        self.report_ic = None                          # (user, dcb): T:RUE E:IC, the scheduler's

    def attach(self, index, unit, handler):
        name = self.mon.DCT[index].name
        self.devices[index] = Device(index, name, unit, handler)
        return self.devices[index]

    def by_name(self, name):
        for dev in self.devices.values():
            if dev.name == name:
                return dev
        raise KeyError(name)

    # NEWQ ---------------------------------------------------------------------

    def newq(self, dct, function, buffer="", count=None, seek=0, end_action=None,
             ea_info=None, tries=1, priority=0xF0, dcb=None, user=0, write=False):
        """NEWQ  IOQ.txt:298 - queue a monitor request and drive the device."""
        if not self.qfree:
            for index in list(self.devices):           # GQ10: drive all I/O, try again
                self.forceio(index)
            if not self.qfree:
                raise RuntimeError("GETQ: no free IOQ entries")
        req = Request(self.qfree.popleft(), dct, function, function, buffer,
                      len(buffer) if count is None else count, seek, end_action, ea_info,
                      tries, tries, priority)
        req.dcb, req.user, req.write = dcb, user, write
        dev = self.devices[dct]
        pos = len(dev.queue)                           # Q20-Q30: after equal priorities
        while pos > 0 and dev.queue[pos - 1].priority > priority:
            pos -= 1
        dev.queue.insert(pos, req)
        self.driveio(dct)                              # Q50
        self.run()
        return req

    def queue(self, dcb, function, buffer="", count=None, user=0, priority=0xF0, write=False):
        """QUEUE  IOQ.txt:604, after FRONTEND (done by the caller, cal.py): a DCB request.
        ``function`` is the handler's (TYPCOR); the tries are the DCB's NRA."""
        if dcb.fcn == 0:
            return None                                # BISR4: no function counted
        req = self.newq(dcb.dct, function, buffer, count, tries=dcb.nra, priority=priority,
                        dcb=dcb, user=user, write=write)
        return req

    # scheduler ----------------------------------------------------------------

    def forceio(self, dct):
        self.driveio(dct)

    def driveio(self, dct):
        """DRIVEIO / DSERV  IOQ.txt:801"""
        dev = self.devices[dct]
        if dev.busy or dev.keyin:
            return self.clockio(dev)
        if dev.cleanup:
            return self.cleanup1(dev)
        self.iosched(dev)

    def iosched(self, dev):
        """IOSCHED / REQSERV: start the first startable request."""
        if dev.busy or dev.keyin:
            return
        if dev.cleanup:
            return self.cleanup1(dev)
        if dev.interop:                                # REQSERV 1: the waiting request
            return self.startio(dev, dev.current)
        for req in dev.queue:
            if not req.busy:
                return self.startio(dev, req)

    def startio(self, dev, req):
        """STARTIO  IOQ.txt:1113 -> handler pre-processor -> COMLIST -> IOSST."""
        dot = dev.handler.DOT[req.step]
        commands = []
        for order, source in dot.commands:              # COMLIST, HANDLERS.txt:314
            if source == "buffer":
                commands.append((order, req.buffer, req.count))
            elif source == "name":                      # CLTV 3: DCT16 of the index in IOQ12
                commands.append((order, "   " + self.mon.DCT[req.seek].name, 8))
            else:
                commands.append((order, source, len(source)))
        self.iostrt(dev, req, commands, dot)

    def iostrt(self, dev, req, commands, dot):
        """IOSTRT  IOQ.txt:1143"""
        dev.increment, dev.retry_step, dev.follow_step = dot.timeout, dot.retry, dot.follow
        dev.current, req.busy, dev.interop = req, True, False
        result = dev.unit.sio(commands)
        message = None
        if result == "rejected":                       # IOREJECT: SIO-FAIL, cleanup pending
            dev.sio_fail = True
            dev.cleanup = dev.data_xfer = True
            self.m.trace(f"IOSTRT: SIO rejected on {dev.name}")
            return self.driveio(dev.index)
        increment = dot.timeout
        if result == "manual":                         # IOSTRT2
            dev.manual = True
            message, increment = MSG1, 3               # 15-second timeout
        dev.deadline = self.ioclock + increment
        dev.busy = dev.data_xfer = True
        self.m.trace(f"IOSTRT: SIO {dev.name} step {req.step} ({result})")
        if result != "manual" and dev.unit.ready():
            self.pending.append(dev)
        if message:
            self.msgout(dev, message)

    # interrupt and cleanup -----------------------------------------------------

    def run(self):
        """Deliver I/O interrupts until there are none (IOINT for each)."""
        if self.in_run:
            return
        self.in_run = True
        try:
            while self.pending:
                self.ioint(self.pending.popleft())
        finally:
            self.in_run = False

    def ioint(self, dev):
        """IOINT  IOQ.txt:1358"""
        if not dev.busy:
            self.m.trace(f"IOINT: unexpected interrupt from {dev.name}")
            return
        status, rbc, data = dev.unit.complete()
        dev.status = status
        dev.busy, dev.cleanup = False, True            # busy -> cleanup pending
        dev.rbc, dev.data = rbc, data
        self.driveio(dev.index)

    def cleanup1(self, dev):
        """CLEANUP1  IOQ.txt:1546 - the handler post-processor, then IOSCU."""
        req = dev.current
        try:
            flags, tyc, message = dev.handler.post(self, dev, req, dev.status, dev.rbc, dev.data)
        except PreCU as p:
            flags, tyc, message = p.flags, 0, p.msg
        self.ioscu(dev, req, flags, tyc, message)

    def ioscu(self, dev, req, flags, tyc, message):
        """IOSCU  IOQ.txt:1562"""
        dev.sio_fail = dev.timed_out = False
        dev.cleanup = False
        if not flags & 0xD800:                          # REQCOM
            self.reqcom(dev, req, tyc or TYC_NORMAL, message)
        elif flags & (F_KEYIN | F_KEYIN_NC):            # SETKEYIN
            dev.keyin = True
            dev.keyin_flags = flags
            dev.deadline = self.ioclock + 6             # 30 seconds
            self.m.trace(f"IOSCU: {dev.name} key-in pending")
            if message:
                self.msgout(dev, message)
        else:
            req.busy = False
            if flags & F_RETRY:
                if req.tries_left == 0:                 # MTB,-1 IOQ11 / BNC REQERR
                    return self.reqcom(dev, req, TYC_ERROR, message)
                req.tries_left -= 1
                req.step = dev.retry_step
            else:
                req.step = dev.follow_step
            dev.interop = bool(flags & F_INTEROP)
            # LI,R13 0: no message for a retry or follow-on.
        self.iosched(dev)

    def reqcom(self, dev, req, tyc, message=None):
        """REQCOM  IOQ.txt:1649 - unlink, free the entry, end action, then the message."""
        req.tyc, req.done, req.busy = tyc, True, False
        dev.queue.remove(req)
        dev.current = None
        dev.interop = dev.data_xfer = False
        self.qfree.append(req.index)
        self.completed.append((req, tyc))
        self.m.trace(f"REQCOM: {dev.name} step {req.step} TYC {tyc}")
        dcb = req.dcb
        if dcb is not None:                             # the DCB branch  IOQ.txt:1656
            if tyc == TYC_ERROR and req.write:
                tyc = 9                                 # write error
            if dcb.asn == 3:
                dcb.nra = req.tries_left                # tries left to the DCB
            dcb.tyc = max(dcb.tyc, tyc)                 # new peak value
            dcb.fcn -= 1                                # DECREMENT FUNCTION COUNT
            dcb.egv = False                             # clear EGV
            dcb.ars = req.count - req.rbc               # ARS = BC - RBC
            # A monitor buffer (write) goes back to MPOOL: buffers aren't modeled.
        if req.end_action:
            req.end_action(req, tyc)
        if dcb is not None and req.user and req.user != 0xFF and self.report_ic:
            self.report_ic(req.user, dcb)               # RC29: E:IC
        if message:                                     # IOCUEXIT: MSGOUT
            self.msgout(dev, message)
        self.iosched(dev)

    def ioserck(self, dev, req, status):
        """IOSERCK  HANDLERS.txt:444 - returns completion flags, or None for an error."""
        if dev.sio_fail:
            raise PreCU(F_INTEROP | F_KEYIN_NC, MSG4)  # X'2800' NOT OPERATIONAL
        if dev.timed_out:
            raise PreCU(F_INTEROP | F_KEYIN, MSG3)     # X'3000' TIMED OUT
        if status.get("error") or status.get("parity"):
            self.m.trace(f"IOSEREC: error logged for {dev.name}")
            return None
        return 0, TYC_NORMAL, None

    # timeouts -----------------------------------------------------------------

    def tick(self, units=1):
        """IOCLOCK advances; TP60 forces I/O on every busy or key-in-pending device."""
        self.ioclock += units
        for dev in list(self.devices.values()):
            if dev.busy or dev.keyin:
                self.forceio(dev.index)
        self.run()

    def clockio(self, dev):
        """CLOCKIO  IOQ.txt:938"""
        if dev.deadline >= self.ioclock or not dev.increment:
            return
        if dev.manual:
            if dev.unit.tio_manual():                  # still manual: type it again
                dev.deadline = self.ioclock + 10
                return self.msgout(dev, MSG1)
            dev.manual = False                          # now automatic
            dev.deadline = self.ioclock + dev.increment
            if dev.unit.ready():
                self.pending.append(dev)
            return
        if not dev.busy:                                # key-in pending: TYPERSP
            dev.deadline = self.ioclock + 10
            return self.msgout(dev, MSG6)
        dev.unit.hio()                                  # HIO, timed out, INTSIM
        dev.status, dev.data = {}, ""
        dev.timed_out = True
        dev.busy, dev.cleanup = False, True
        self.m.trace(f"CLOCKIO: {dev.name} timed out")
        self.driveio(dev.index)

    # messages -----------------------------------------------------------------

    def msgout(self, dev, message):
        """MSGOUT  IOQ.txt:2067 - OCWRITE1 with Y06: the device name, tabbed."""
        oc = self.oc_index()
        self.newq(oc, TY_WRITE_NAME_TAB, message + NL, seek=dev.index)

    def oc_index(self):
        for index, entry in enumerate(self.mon.DCT):
            if entry is not None and entry.type == "OC":
                return index
        raise KeyError("OC")

    # device key-ins (TP33) ------------------------------------------------------

    def device_keyin(self, dev, letter):
        """TP33/KEYDV  IOQ.txt:2020 - the operator's answer to a key-in pending device.
        Returns the action taken, or None if no key-in is pending (EH)."""
        if not dev.keyin:
            return None
        dev.keyin = False
        req = dev.current
        req.busy = False                                # reset request busy
        if letter == "C" and dev.keyin_flags & F_KEYIN_NC:
            letter = "R"                                # continue not allowed
        if letter == "C":
            self.reqcom(dev, req, TYC_NORMAL)
        elif letter == "E":
            self.reqcom(dev, req, TYC_ERROR)
        else:
            self.forceio(dev.index)                     # RKEYN: FORCEIO
        self.run()
        return {"C": "continue", "R": "retry", "E": "error"}[letter]
