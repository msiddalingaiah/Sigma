"""Operator key-ins on a running system. See docs/keyin.md.

Translated from c00co/IOQ.txt (OCINT, CTRIG, CTIOP, TP20, TP30-TP33, TP50,
OCQUEUE) and c00co/KEYN.txt (KEYIN1, GKIFLD, NXKICHR, KITBL, KEYERR, and the
handlers that change only a few cells). Comments of the form ``# FILE:NNN``
point at the source.

Simplification: TP50 starts the KEYIN ghost with T:GJOBSTRT, which needs the
scheduler, a ghost slot and the file system. Here KEYIN is called directly.
Handlers that need users, ghosts, symbionts or devices raise NotTranslated.
"""

from dataclasses import dataclass, field

from .devices import ConsoleExhausted
from .io import (ConsoleHandler, ConsoleUnit, IOSystem, PrinterHandler, PrinterUnit,
                 TY_READ, TY_WRITE, TY_WRITE_NAME, LP_PRINT)
from .monitor import NotTranslated
from .sched import CC1, CC2, CC3, E_ABRT, SNULL, Compute

NL = "\n"
TP25 = NL + "!"                                         # DATA X'02155A00': NL, '!'
KEYINBUF_SIZE = 72
KEOB = "\x26"                                           # end of buffer
KIDL = ":/(),. "                                        # KEYN.txt:341 delimiters
KMAXKIFL = 12
KEYIN_UNITS = 2                                         # 10 s of IOCLOCK per key-in (assumed)
SLICE = KEYIN_UNITS * 2500                              # the same 10 s in scheduler clock units (2 ms)

# OCQUEUE canned messages (MSGBASE, IOQ.txt:2151).
OC53 = NL + "  EH? " + NL
OC52 = NL + "\x05LATER" + NL                            # X'05' (HT) as in the source
MSGBASE = {0: OC53, 1: OC53, 2: NL + "!!AVRERR" + NL, 3: OC52, 4: OC53, 5: " AVAIL" + NL,
           6: OC53, 7: OC53}

# Control-task codes (TPBASE, IOQ.txt:1898).
CT_DEVICE, CT_CONSOLE, CT_AVR, CT_KEYIN, CT_CHECK, CT_PFSR = range(6)


class KeyinError(Exception):
    """KEYERR: the handler found an error."""


@dataclass
class OperatorState:
    """The cells the translated key-ins read and write."""
    S_OUAIS: int = 0          # on-line users allowed
    S_BUAIS: int = 0          # batch users allowed
    S_GUAIS: int = 0          # ghost users allowed
    SMUIS: int = 0            # maximum users in the system
    RAD1ST: int = 0
    SSTAT: int = 0            # byte 0
    COC: int = 0              # 0: no character-oriented communications (no terminals)
    S_CUIS: int = 0           # current users in the system
    GOODNGT: int = 0          # TABLES.txt:382; -2 after ZAP
    users: list = field(default_factory=list)          # on-line/batch users (none modeled)
    symbionts_busy: bool = False                        # any SSTAT = 1 or SSIG = 'I'
    log: list = field(default_factory=list)           # (key-in, outcome)


class OperatorConsole:
    """The control task and KEYIN, attached to a booted machine and monitor."""

    def __init__(self, m, mon, sysgen, state=None, screech=None, lp_faults=None):
        self.m, self.mon, self.sysgen = m, mon, sysgen
        self.io = IOSystem(m, mon)
        self.oc = self.io.oc_index()
        self.io.attach(self.oc, ConsoleUnit(m.console), ConsoleHandler())
        self.lp = self._index("LP")
        self.io.attach(self.lp, PrinterUnit(m.printer, lp_faults), PrinterHandler())
        self.state = state or OperatorState(
            S_OUAIS=sysgen.S_OUAIS, S_BUAIS=sysgen.S_BUAIS, S_GUAIS=sysgen.S_GUAIS,
            SMUIS=sysgen.SMUIS, COC=sysgen.COC, S_CUIS=sysgen.S_CUIS)
        self.ioctq = []                                # IOCTQ: control-task stack
        self.keyinbuf = ""
        self.screech = screech                         # SCREECH on this system -> (m, mon, outcome)
        self.shutdown = None                           # the result, after SCREECH X'404'
        self.sched = getattr(mon, "sched", None)       # from INITIAL; None: no scheduler
        if self.sched is not None:
            self.sched.screech_cb = self._sched_screech
            self.sched.ghost_programs["KEYIN"] = self._keyin_ghost
            self.state.S_CUIS = self.sched.S_CUIS
            if self.sched.cal is not None:
                self.sched.cal.attach_io(self.io, self.oc)   # M:OC is this console

    # --- I/O control task -----------------------------------------------------

    def ctrig(self, code):
        """CTRIG  IOQ.txt:1075 - push a control word."""
        self.ioctq.append(code)

    def interrupt(self):
        """OCINT  IOQ.txt:1846 - the operator pressed INTERRUPT."""
        self.ctrig(CT_CONSOLE)                         # LW,R8 Y01 / BAL,R11 CTRIG
        self.ctiop()

    def ctiop(self):
        """CTIOP / TP5  IOQ.txt:1871 - pop control words until the stack is empty.
        With a scheduler, the exit then goes to T:SE, which runs the ghosts (KEYIN)
        until they wait; anything they pushed (KEYERR's new prompt) is popped next."""
        while True:
            while self.ioctq:
                code = self.ioctq.pop()                # PLW,R8 IOCTQ
                if code == CT_CONSOLE:
                    self.tp20()
                elif code == CT_KEYIN:
                    self.tp50()
                else:
                    raise NotTranslated(f"control-task code {code}")
            if self.sched is None or self.shutdown is not None:
                return
            self.run_sched()
            if not self.ioctq:
                return

    # --- the scheduler --------------------------------------------------------

    def start(self):
        """Let the system finish starting: GHOST1 and the ghosts it starts run."""
        if self.sched is not None:
            self.run_sched()

    def run_sched(self):
        """T:SE until every user waits (or the idle check shuts the system down)."""
        s, st = self.sched, self.state
        s.GOODNGT = st.GOODNGT
        s.symbionts_busy = st.symbionts_busy
        outcome = s.run(until=s.now + SLICE)           # time passes while the operator types
        st.S_CUIS = s.S_CUIS
        return outcome

    def _sched_screech(self, code, why):
        if self.screech is None:
            raise NotTranslated(f"SCREECH X'{code:X}': no recovery attached")
        self.m.trace(f"T:SE idle: S:CUIS {self.sched.S_CUIS} + GOODNGT {self.sched.GOODNGT}"
                     f" <= 0, SCREECH X'{code:X}'")
        self.shutdown = self.screech(code, 0)
        return self.shutdown

    def _keyin_ghost(self, sched, u):
        """The KEYIN ghost: KEYIN1 on the buffer, then B T:DELUS (KEYINR)."""
        yield Compute(1)
        try:
            self.keyin()
        except NotTranslated as e:
            self.ioctq.clear()
            self.state.log.append((self.keyinbuf.rstrip(NL), f"not translated: {e}"))

    def _index(self, dtype):
        for index, entry in enumerate(self.mon.DCT):
            if entry is not None and entry.type == dtype:
                return index
        raise KeyError(dtype)

    def ocqueue(self, code, index=0):
        """OCQUEUE  IOQ.txt:2120 - canned message; with a DCT index, write with the
        device name (Y02), the index passed in the seek-address field."""
        text = MSGBASE.get(code, OC53)
        if index:
            self.io.newq(self.oc, TY_WRITE_NAME, text, seek=index)
        else:
            self.io.newq(self.oc, TY_WRITE, text)

    def ocqueue_text(self, text):
        """OCQUEUE with a message address (a code above NMSG): the TEXTC's text."""
        self.io.newq(self.oc, TY_WRITE, text)

    def tp20(self):
        """TP20  IOQ.txt:1923 - type NL '!', read 72 bytes into KEYINBUF, end action TP30."""
        self.io.newq(self.oc, TY_WRITE, TP25)                       # OCWRITE TP25
        # TP26: function 0 (read with editing), priority X'F0', 15 tries.
        self.io.newq(self.oc, TY_READ, count=KEYINBUF_SIZE, priority=0xF0, tries=15,
                     end_action=self.tp30_ea)

    def tp30_ea(self, req, tyc):
        """The read's end action: KEYINBUF holds the line."""
        if self.m.console.eof:
            raise ConsoleExhausted("end of console input")
        self.keyinbuf = req.buffer
        self.tp30()

    def tp30(self):
        """TP30  IOQ.txt:1067 - device key-in, else hand the buffer to KEYIN."""
        buf = self.keyinbuf
        for index in range(len(self.mon.DCT) - 1, 0, -1):
            entry = self.mon.DCT[index]
            if buf[1:5] == entry.name[1:5]:            # CW,R9 DCT16,R1: the name's 'YNDD'
                return self.tp31(index)
        self.ctrig(CT_KEYIN)                           # TP30A: LW,R8 Y03

    def tp31(self, index):
        """TP31/TP33  IOQ.txt:2107 - ',C', ',R' or ',E' for a device with a key-in pending."""
        buf = self.keyinbuf
        letter = buf[6:7]
        dev = self.io.devices.get(index)
        if buf[5:6] != "," or letter not in ("C", "R", "E") or dev is None or not dev.keyin:
            self.state.log.append((buf.rstrip(NL), "EH?"))
            return self.ocqueue(4)                     # TP32: EH (no new prompt)
        result = self.io.device_keyin(dev, letter)
        self.state.log.append((buf.rstrip(NL), f"device {dev.name}: {result}"))
        self.m.trace(f"TP33: {dev.name} {result}")
        return result

    def tp50(self):
        """TP50  IOQ.txt:1944 - T:GJOBSTRT 'KEYIN'; if it can't start, LATER."""
        if self.sched is None:
            self.m.trace("TP50: T:GJOBSTRT KEYIN (no scheduler: called directly)")
            return self.keyin()
        cc, user = self.sched.t_gjobstrt("KEYIN")
        self.m.trace(f"TP50: T:GJOBSTRT KEYIN: user {user}, CC X'{cc:X}'")
        if cc & CC1:                                   # BCR,8 TP5
            self.state.log.append((self.keyinbuf.rstrip(NL), "LATER"))
            self.ocqueue(3)

    def print_line(self, text):
        """A monitor print request to the line printer (NEWQ, print without format)."""
        return self.io.newq(self.lp, LP_PRINT, text, tries=3)

    def waiting(self):
        """Devices with a key-in pending."""
        return [d.name for d in self.io.devices.values() if d.keyin]

    def idle(self):
        """T:SE with no user to run: the idle check  SCHED.txt:1065. With a scheduler
        it is Scheduler.idle, reached by running T:SE."""
        if self.sched is not None:
            if self.shutdown is None:
                self.run_sched()
            return
        st = self.state
        if st.S_CUIS + st.GOODNGT > 0:
            return                                     # BG IDL1: wait for interrupts
        if st.symbionts_busy:
            return                                     # IDL0: a symbiont is still busy
        # LW,R5 Y004 / BDR,R5 %: about 5 seconds, so COC output can finish.
        self.m.trace(f"T:SE idle: S:CUIS {st.S_CUIS} + GOODNGT {st.GOODNGT} <= 0, SCREECH X'404'")
        if self.screech is None:
            raise NotTranslated("SCREECH X'404': no recovery attached")
        self.shutdown = self.screech(0x404, 0)

    # --- KEYIN ------------------------------------------------------------

    def keyin(self):
        """KEYIN1  KEYN.txt:361"""
        buf = self.keyinbuf
        if buf.startswith(NL):
            return self.keyinr("")                     # empty key-in
        p = Fields(buf)
        name, delim = p.gkifld()
        try:
            if name is None:
                raise KeyinError
            handler = KITBL.get(name[:4])
            if handler is None:
                if name[0] == "S":                     # DEVKEYIN: symbiont key-in (SKIN)
                    raise NotTranslated(f"symbiont key-in '{name.strip()}'")
                raise KeyinError
            if isinstance(handler, str):
                raise NotTranslated(f"key-in {name.strip()} ({handler})")
            outcome = handler(self, p, delim)
        except KeyinError:
            return self.keyerr()
        return self.keyinr(outcome or name.strip())

    def keyinr(self, outcome):
        """KEYINR  KEYN.txt:324 - B T:DELUS: the ghost logs itself off."""
        self.state.log.append((self.keyinbuf.rstrip(NL), outcome or "empty"))

    def keyerr(self):
        """KEYERR  KEYN.txt:313 - EH?, then another copy of KEYIN (a fresh '!')."""
        self.state.log.append((self.keyinbuf.rstrip(NL), "EH?"))
        self.ocqueue(4)
        self.ctrig(CT_CONSOLE)                         # LW,8 Y01 / BAL,11 CTRIG


class Fields:
    """KIPL and GKIFLD/NXKICHR  KEYN.txt:227-299."""

    def __init__(self, buf):
        self.buf = buf
        self.kccp = 0
        self.blank_active = False
        self.delims = KIDL                             # KIPL's delimiter list

    def nxkichr(self):
        """Next character and whether it is a delimiter."""
        while True:
            if self.kccp >= KEYINBUF_SIZE:
                return KEOB, True
            ch = self.buf[self.kccp] if self.kccp < len(self.buf) else NL
            if ch == NL:
                return ch, True                        # KCRET: position not advanced
            self.kccp += 1
            if ch == " " and not self.blank_active:
                continue                               # leading blank: skip
            return ch, ch in self.delims

    def gkifld(self):
        """Returns (field padded to 12, delimiter); field is None for an empty or
        over-long field (CC1)."""
        self.blank_active = False
        text, r0 = "", KMAXKIFL + 1
        while True:
            ch, delim = self.nxkichr()
            if delim:
                break
            r0 -= 1
            if r0 == 0:
                self.blank_active = False
                return None, ch                        # more than 12 characters
            text += ch
            self.blank_active = True
        self.blank_active = False
        return (text.ljust(KMAXKIFL) if text else None), ch


# --- handlers ---------------------------------------------------------------

def gdtkival(p, lo, hi):
    """GDTKIVAL  KEYN.txt:1147 - one or two EBCDIC digits, within lo..hi."""
    text, _ = p.gkifld()
    if text is None:
        raise KeyinError
    digits = text.strip()
    if not 1 <= len(digits) <= 2 or not all("0" <= c <= "9" for c in digits):
        raise KeyinError                               # DTVALCK / field length
    value = int(digits)
    if not lo <= value <= hi:                          # CLM against MAX..VAL
        raise KeyinError
    return value


def kitime(con, p, delim):
    """KITIME  KEYN.txt:1102 - !T HH:MM"""
    date = con.mon.DATE
    date["HR"] = gdtkival(p, 0, 23)                    # STH,R2 TIME (stored at once)
    date["MI"] = gdtkival(p, 0, 59)
    return f"TIME {date['HR']:02d}:{date['MI']:02d}"


def kidate(con, p, delim):
    """KIDATE  KEYN.txt:1116 - !D MM/DD/YY (no BADATES or leap-year check)."""
    date = con.mon.DATE
    date["MO"] = gdtkival(p, 1, 12)
    date["DA"] = gdtkival(p, 1, 31)
    date["YR"] = gdtkival(p, 0, 99)
    return f"DATE {date['MO']:02d}/{date['DA']:02d}/{date['YR']:02d}"


def users_allowed(con, p, delim, batch):
    """KIGUP / KIGBUP  KEYN.txt:844 - number of on-line or batch users allowed."""
    st = con.state
    if not batch and not st.COC:
        raise KeyinError                               # B/NOT ON-LINE SYSTEM
    text, _ = p.gkifld()
    if text is None:
        raise KeyinError
    value = 0
    for ch in text[:4]:                                # DCV20: four characters
        if ch >= "0" and ch <= "9":
            value = value * 10 + int(ch)
        elif ch == " ":
            break
        else:
            raise KeyinError
    other = st.S_OUAIS if batch else st.S_BUAIS
    if other + value + st.S_GUAIS > st.SMUIS:          # MAY NOT EXCEED TOTAL
        raise KeyinError
    if batch:
        st.S_BUAIS = value
    else:
        st.S_OUAIS = value
    return f"{'ONB' if batch else 'ON'} {value}"


def kigdown(con, p, delim):
    """KIGDOWN  KEYN.txt:826 - gentle down: no more on-line or batch users."""
    con.state.S_OUAIS = con.state.S_BUAIS = 0
    # NSCPU = 0 (no slave CPUs) and no remote batch (OFFBIT = 0) in this model.
    return "OFF"


def kifdown(con, p, delim):
    """KIFDOWN  KEYN.txt:805 - force down: abort the users, then as OFF."""
    st = con.state
    st.GOODNGT = -2                                    # ***SAVE SYMB FILES
    s = con.sched
    if s is None:
        for user in list(st.users):
            raise NotTranslated(f"ZAP: aborting user {user} (T:RUE)")
    else:
        s.GOODNGT = st.GOODNGT
        for u in range(s.SMUIS, 0, -1):                # ZAP10
            if s.UB_US[u] == SNULL or u <= s.MING - 1:   # KEYN, ALLOCAT, RBBAT
                continue
            s.trace(f"ZAP: abort user {u}")
            s.t_rue(u, E_ABRT)                         # ABORT HIM
    kigdown(con, p, delim)
    return "ZAP"


GJOBUSY = "\x05**TASK CURRENTLY ACTIVE"                 # KEYN.txt:783: TEXTC, X'05', X'5C5C'
GJOBWAKE = "\x05**TASK AWAKENED"
GJOBFULL = "\x05**TASK TABLES FULL"


def kigjob(con, p, delim):
    """KIGJOB  KEYN.txt:715 - GJOB NAME[.ACCOUNT][,RESOURCE]: start a ghost job."""
    s = con.sched
    if s is None:
        raise NotTranslated("GJOB: no scheduler")
    p.delims = KIDL.replace(":", "")                  # REMOVE ':' AS DELIMITER
    field, d = p.gkifld()                              # GET TASK NAME
    if field is None:
        raise KeyinError
    name = field.strip()
    if len(name) > 7 or name == "KEYIN":               # NAME:7 / DONT START OURSELF
        raise KeyinError
    account = ":SYS"
    if d != NL:
        if d == ".":                                   # KIGJOB4: GATHER ACCOUNT NUMBER
            acct, d = p.gkifld()
            if acct is None:
                raise KeyinError
            account = acct.strip()
        if d == ",":                                   # a resource: the tables aren't modeled
            raise KeyinError
        if d != NL:
            raise KeyinError                           # CANT FIGURE OUT WHAT TO DO HERE
    cc, user = s.t_gjobstrt(name, account=account)     # T:GJOBSTRT / T:GJOBR
    con.m.trace(f"KIGJOB: {name}.{account}: user {user}, CC X'{cc:X}'")
    if cc & CC3:
        con.ocqueue_text(GJOBUSY)
    elif cc & CC2:
        con.ocqueue_text(GJOBWAKE)
    elif cc & CC1:
        con.ocqueue_text(GJOBFULL)
    return f"GJOB {name}.{account}" + ("" if cc == 0 else f" CC X'{cc:X}'")


def kirad1st(con, p, delim):
    """KIRAD1ST  KEYN.txt:2077 - 1 if the delimiter after PREF is a blank."""
    con.state.RAD1ST = 1 if delim == " " else 0
    return f"PREF RAD1ST={con.state.RAD1ST}"


def kobn(con, p, delim):
    con.state.SSTAT = 0                                # KOBN: STB 0 SSTAT
    return "OBON"


def kobf(con, p, delim):
    con.state.SSTAT = (con.state.SSTAT + 1) & 0xFF     # KOBF: MTB,1 SSTAT
    return "OBOF"


def keyerr(con, p, delim):
    raise KeyinError


def kisend(con, p, delim):
    """KISEND  KEYN.txt:910 - message to the on-line users, via the COC buffer."""
    if not con.state.COC:
        raise KeyinError                               # B/NOT ON-LINE SYSTEM
    raise NotTranslated("SEND: COC message buffer")


# KITBL / KIJMPTBL (KEYN.txt:386, :465), UTS assembly. A string marks a handler
# that isn't translated; the string says what it needs.
KITBL = {
    "ERSE": "error log", "ABOR": "users", "DATE": kidate, "D   ": kidate,
    "ERRO": "users", "STAR": "symbionts", "TIME": kitime, "T   ": kitime,
    "SYST": keyerr, "MOUN": "devices, AVR", "INT ": "users",
    "ON  ": lambda c, p, d: users_allowed(c, p, d, batch=False),
    "ONB ": lambda c, p, d: users_allowed(c, p, d, batch=True),
    "OFF ": kigdown, "ZAP ": kifdown, "SEND": kisend, "GJOB": lambda c, p, d: kigjob(c, p, d),
    "DELE": "symbionts", "PRIO": "symbionts", "FORM": "symbionts, devices",
    "SCPU": "multiprocessor", "XCPU": "multiprocessor",
    "RBSE": "remote batch", "RBBD": "remote batch", "RBX ": "remote batch",
    "RBS ": "remote batch", "RBDI": "remote batch", "RBSW": "remote batch",
    "RBLO": "remote batch", "RBCO": "remote batch",
    "E   ": "users", "S   ": "symbionts", "SS  ": "symbionts", "REQU": "devices",
    "DISP": "system tables (DISPLAY)", "X   ": "users", "SCRA": "devices",
    "PREF": kirad1st, "ANSS": "devices", "ANSM": "devices", "OVER": "devices",
    "READ": "devices", "DIAG": "users", "OBON": kobn, "OBOF": kobf,
}


def session(con):
    """Interrupt, key-in, repeat, until the console has no more input. A key-in
    that reaches untranslated code is logged and the session goes on."""
    console = con.m.console
    con.start()                                        # the start-up ghosts run first
    while not console.at_end():
        con.io.tick(KEYIN_UNITS)                       # time passes while the operator types
        try:
            con.interrupt()
        except ConsoleExhausted:
            return
        except NotTranslated as e:
            con.ioctq.clear()
            con.state.log.append((con.keyinbuf.rstrip(NL), f"not translated: {e}"))
        con.idle()                                     # KEYIN has logged off: T:SE
        if con.shutdown is not None:
            return
