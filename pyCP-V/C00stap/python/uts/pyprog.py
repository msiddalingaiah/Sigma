"""Python programs as ghost jobs. See docs/python-programs.md.

NOT a translation: this stands in for the step code and loader (a ghost's load
module) and for the program's own machine code. Everything a program does goes
through translated code: each ``cpv`` call builds an FPT and a CAL1, which the
scheduler runs as the ghost's CAL.

- A program file is a keyed file in the account, keyed like an EDIT file: the line
  number times 1000 as a 3-byte binary key, KEYM = 3 (EDIT.txt:495, :1524); the
  records are the lines, in EBCDIC.
- ``loader(sched)`` is the scheduler's program_loader: for a ghost name not known
  otherwise, the ghost's program loads NAME.ACCOUNT and runs its ``main(cpv)``.
- The program runs in a thread. A ``cpv`` call hands its request to the ghost's
  generator, which yields it to the scheduler and hands back the result: so each
  service call is a switch point, and only one side ever runs at a time.
"""

import queue
import threading

from .cal import (F_NWK, F_ONWK, P_ABN, P_BTD, P_BUF, P_ERR, P_KEY, P_SIZE, Fpt)
from .files import EBCDIC, GRAN, FileError, protection
from .sched import Cal1, Compute

EXIT, ERROR, ABORT = 1, 2, 3            # CAL1,9 exit types: M:EXIT, M:ERR, M:XXX


def line_key(n):
    """EDIT's key: the sequence number times 1000, 3 bytes."""
    return (int(n) * 1000).to_bytes(3, "big")


def store_source(fs, name, account, text):
    """The host-side import (a stand-in for an editor or a card deck): the source as
    an EDIT-style keyed file NAME.ACCOUNT, replacing any old contents."""
    fs.add_account(account)
    cfu = fs.open(name, account, "OUT", keym=3)
    kf = cfu.file
    for k in kf.keys():
        kf.delete(k)
    for i, line in enumerate(text.splitlines(), 1):
        kf.write(line_key(i), line.encode(EBCDIC, errors="replace"))
    fs.close(cfu)


def read_source(fs, name, account):
    cfu = fs.open(name, account, "IN")
    lines, after = [], None
    while True:
        nxt = cfu.file.read_next(after)
        if nxt is None:
            break
        after = nxt[0]
        lines.append(nxt[1].decode(EBCDIC))
    fs.close(cfu)
    return "\n".join(lines) + "\n"


def loader(sched):
    """The scheduler's program_loader: the ghost's first step loads NAME.ACCOUNT."""
    def find(name, account):
        return lambda s, u: program(s, u, name, account)
    return find


def program(sched, u, name, account):
    """The ghost: load, then run main(cpv) in a thread, then M:EXIT or M:XXX."""
    cal = sched.cal
    from . import fetch, interp
    if fetch.is_load_module(cal.fs, name, account):    # a load module: FETCH, interpreted
        from . import jit
        try:
            lm = fetch.read_load_module(cal.fs, name, account)
            tree = lm.limits[jit.PLL] << 9             # TREE IS IN FIRST PAGE OF PROCEDURE
            lm.words.update(jit.build(sched, u, lm.tcb, lm.dcblink, tree, lm.start, name,
                                      lm.limits, account))
            fetch.init_sgld(lm, lm.words, jit.XX_ADDRESS)
        except fetch.LoadModuleError as e:
            sched.trace(f"FETCH {name}.{account}: {e}")
            yield from _type(cal, u, f"{name}: LOAD MODULE ERROR {e}")
            sched.jit[u].ABC, sched.jit[u].ERO = e.abc, e.code
            yield Cal1(9, address=ABORT, regs={6: 0})
            return
        if u not in sched.LB_UN:
            cal.account[u] = account
        cal.running[u] = (name, account)
        sched.uregs[u][0] = lm.tcb                     # XIT38: TO USERS R0
        cal.cmap[u] = fetch.pages(lm)                  # JX:CMAP: the program's pages
        sched.trace(f"FETCH {name}.{account}: start X'{lm.start:X}', TCB X'{lm.tcb:X}',"
                    f" DCBs {', '.join(lm.dcbs)}")
        yield from interp.program(sched, u, lm.words, lm.start, lm.dcbs, name=name,
                                  type_line=lambda text: _type(cal, u, text))
        return
    try:
        source = read_source(cal.fs, name, account)   # the step's load (a stand-in)
        code = compile(source, f"{name}.{account}", "exec")
        space = {"__name__": name}
        exec(code, space)
        main = space["main"]
    except (FileError, SyntaxError, KeyError, Exception) as e:
        sched.trace(f"LOAD {name}.{account}: {e}")
        yield from _type(cal, u, f"LOAD {name}: {_short(e)}")
        yield Cal1(9, address=ABORT, regs={6: 0})
        return
    sched.trace(f"LOAD {name}.{account}: {len(source.splitlines())} lines")
    yield Compute(1)                                   # loading takes a moment
    if u not in sched.LB_UN:                           # an on-line user keeps their own
        cal.account[u] = account                       # the ghost's account (GJOB NAME.ACCOUNT)
    cal.running[u] = (name, account)                   # M:XX, for an execute vehicle
    cpv = Cpv(sched, u, name)
    bridge = Bridge(main, cpv)
    yield from bridge.run()


def _short(e):
    return f"{type(e).__name__}: {e}"[:100]


def _type(cal, u, text):
    cal.put_text(u, Cpv.MSG, text[:120], textc=True)
    yield Cal1(2, Fpt(2, presence=P_ERR, params=[Cpv.MSG]))


# --- the bridge between the program's thread and the ghost's generator -----------------

class Killed(BaseException):
    """The ghost was deleted (ZAP, abort): the program's thread stops."""


class Bridge:
    def __init__(self, main, cpv):
        self.main, self.cpv = main, cpv
        self.to_monitor, self.to_program = queue.Queue(), queue.Queue()
        cpv._bridge = self

    def run(self):
        thread = threading.Thread(target=self._thread, daemon=True,
                                  name=f"cpv-{self.cpv.name}")
        thread.start()
        try:
            while True:
                kind, value = self.to_monitor.get()    # the program runs until its next call
                if kind == "call":
                    result = yield value               # the service call: a switch point
                    self.to_program.put(("result", result))
                elif kind == "done":
                    yield Cal1(9, address=EXIT, regs={6: 0})       # M:EXIT
                    return
                else:                                  # an uncaught exception
                    yield from _type(self.cpv.s.cal, self.cpv.u,
                                     f"{self.cpv.name} ABORTED: {_short(value)}")
                    yield Cal1(9, address=ABORT, regs={6: 0})      # M:XXX
                    return
        finally:
            if thread.is_alive():
                self.to_program.put(("kill", None))

    def _thread(self):
        try:
            self.main(self.cpv)
        except Killed:
            return
        except Exception as e:
            self.to_monitor.put(("error", e))
            return
        self.to_monitor.put(("done", None))

    def call(self, request):
        """From the program's thread: hand a request over and wait for its result."""
        self.to_monitor.put(("call", request))
        kind, value = self.to_program.get()
        if kind == "kill":
            raise Killed
        return value


# --- the library programs use --------------------------------------------------------------

class CpvError(Exception):
    """A service ended at its error or abnormal routine: ``code`` is the CP-V code."""

    def __init__(self, code, what=""):
        super().__init__(f"X'{code:02X}' {what}".rstrip())
        self.code = code


class Cpv:
    """The services a Python program asks for. Each method is one (or a few) CAL1s."""
    MSG, BUF, KEY = 0xBE00, 0xB000, 0xBF00             # parameter areas in the user's memory
    EBCDIC = EBCDIC                                    # for an EDIT file's lines
    line_key = staticmethod(line_key)                  # EDIT's 3-byte key for a line number
    ERRR, ABNR = 0xC000, 0xC100                        # error and abnormal "routines"
    CpvError = CpvError

    def __init__(self, sched, u, name):
        self.s, self.u, self.name = sched, u, name
        self.cal = sched.cal
        self._bridge = None
        self._dcbs = 0

    def _call(self, request):
        result = self._bridge.call(request)
        if isinstance(result, tuple) and result and result[0] == "ROUTINE":
            raise CpvError(result[2] >> 24)            # SR3: the code in byte 0
        return result

    # console and time
    def type(self, text):
        """M:TYPE: a line on the operator's console (MSRTYPE puts the ID in front)."""
        self.cal.put_text(self.u, self.MSG, str(text)[:120], textc=True)
        self._call(Cal1(2, Fpt(2, presence=P_ERR, params=[self.MSG])))

    def message(self, text):
        """M:MESSAGE: always the operator's console."""
        self.cal.put_text(self.u, self.MSG, str(text)[:120], textc=True)
        self._call(Cal1(2, Fpt(0, presence=P_ERR, params=[self.MSG])))

    def keyin(self, question, size=60, oc_only=False):
        """M:KEYIN: ask the operator; returns the reply (the console's next line, or ''
        if the read times out). The reply buffer holds a TEXTC: length, then the text."""
        self.cal.put_text(self.u, self.MSG, str(question)[:120], textc=True)
        presence = 0xE0000000 | (0x10 if oc_only else 0)    # message, buffer, size
        self._call(Cal1(2, Fpt(4, presence=presence, params=[self.MSG, self.BUF, size])))
        n = self.cal.read_bytes(self.u, self.BUF, 0, 1)[0]    # the reply's count byte
        return self.cal.read_text(self.u, self.BUF, 1, n)

    def readline(self, size=80):
        """M:READ on M:UC: the next line typed at the user's terminal (on-line users
        only; COCIO waits for it)."""
        from .cal import M_UC
        self._call(Cal1(1, Fpt(0x10, word0=M_UC, presence=P_BUF | P_SIZE | P_BTD,
                               params=[self.BUF, int(size), 0])))
        return self.cal.read_text(self.u, self.BUF, 0, self.cal.dcb_at(self.u, M_UC).ars)

    def prompt(self, c=""):
        """M:PC: the character COC sends at the start of each terminal read ('' none)."""
        self._call(Cal1(1, Fpt(0x2C, word0=c.encode(EBCDIC)[0] if c else 0)))

    def wait(self, units=1):
        """M:WAIT: sleep for ``units`` (1/50 minute each, assumed)."""
        self._call(Cal1(8, Fpt(0x0F, word0=int(units))))

    def time(self):
        """M:TIME: 'HH:MM MON DD,'YY'."""
        self._call(Cal1(8, Fpt(0x10, word0=self.MSG)))
        return self.cal.read_text(self.u, self.MSG, 0, 16)

    def compute(self, n):
        """Charge n clock units of CPU time (no CAL: the program 'computes')."""
        self._bridge.call(Compute(int(n)))

    # files
    def open(self, name, account=None, fun="IN", keym=11, org="keyed", size=0,
             password=None, read=None, write=None, execute=None, vehicle=None,
             binary_keys=False):
        """M:OPEN on a new file DCB. ``org`` ("keyed", "consec" or "random", with
        ``size`` granules) is for a new file; an existing one keeps its own. Without
        ``account``, the program's own. ``password`` opens a protected file and, with
        the account lists ``read``, ``write`` and ``execute`` (accounts, "ALL" or
        "NONE") and ``vehicle`` (a processor), protects a new one. With
        ``binary_keys``, a keyed file's iteration and ``next()`` give keys as bytes
        (KBUF as it is) instead of EBCDIC text. Returns a File, a ConsecFile or a
        RandomFile."""
        self._dcbs += 1
        address = 0x9000 + 16 * self._dcbs
        dcb = self.cal.add_dcb(self.u, f"F:{self._dcbs}", address, asn=1, fname=name,
                               account=account, fun=fun, keym=keym, rstore=size,
                               prot=protection(password, read, write, execute, vehicle),
                               org={"keyed": 0x20, "consec": 0, "random": 0x10}[org])
        self._call(Cal1(1, Fpt(0x14, word0=address, presence=P_ERR | P_ABN,
                               params=[self.ERRR, self.ABNR])))
        if dcb.org == 0:
            return ConsecFile(self, dcb)
        return RandomFile(self, dcb) if dcb.org == 0x10 else File(self, dcb, binary_keys)


class Record(bytes):
    """A record's data: its bytes exactly as stored, whose decode() is EBCDIC by default,
    since text in CP-V's memory and files is EBCDIC (docs/python-programs.md)."""

    def decode(self, encoding=EBCDIC, errors="strict"):
        return bytes.decode(self, encoding, errors)

    def __getitem__(self, i):
        part = bytes.__getitem__(self, i)
        return Record(part) if isinstance(i, slice) else part


class File:
    """An open file DCB."""

    def __init__(self, cpv, dcb, binary_keys=False):
        self.cpv, self.dcb, self.binary_keys = cpv, dcb, binary_keys

    def _key(self, key):
        """The key as a TEXTC at KEY. Text is EBCDIC'd by KEYTRAN (cal._key); a bytes
        key goes in as the characters KEYTRAN's EBCDIC encoding turns back into those
        very bytes (cp037 maps all 256 values one to one), so any binary key works."""
        data = bytes(key) if isinstance(key, (bytes, bytearray)) else str(key).encode(EBCDIC)
        self.cpv.cal.write_bytes(self.cpv.u, Cpv.KEY, 0, bytes([len(data)]) + data)

    def read(self, key=None, size=2048):
        """M:READ: by key (text or bytes), or (no key) the next record. Returns the data,
        or None at the end of the file."""
        c, presence = self.cpv, P_ERR | P_ABN | P_BUF | P_SIZE
        params = [Cpv.ERRR, Cpv.ABNR, Cpv.BUF, size]
        if key is not None:
            self._key(key)
            presence |= P_KEY
            params.append(Cpv.KEY)
        try:
            c._call(Cal1(1, Fpt(0x10, word0=self.dcb.address, presence=presence, params=params)))
        except CpvError as e:
            if e.code == 0x06 and key is None:
                return None                            # end of file
            raise
        n = min(self.dcb.ars, size)
        return Record(c.cal.read_bytes(c.u, Cpv.BUF, 0, n))

    def next(self):
        data = self.read()
        if data is None:
            return None
        key = bytes(self.dcb.kbuf)
        return (key if self.binary_keys else key.decode(EBCDIC)), data

    def __iter__(self):
        while True:
            item = self.next()
            if item is None:
                return
            yield item

    def write(self, key, data, new=False):
        """M:WRITE by key: ONEWKEY, or NEWKEY with ``new``."""
        c = self.cpv
        if isinstance(data, str):
            data = data.encode(EBCDIC, errors="replace")     # text is EBCDIC
        c.cal.write_bytes(c.u, Cpv.BUF, 0, data)
        self._key(key)
        flags = F_NWK if new else F_ONWK
        c._call(Cal1(1, Fpt(0x11, word0=self.dcb.address,
                            presence=P_ERR | P_ABN | P_BUF | P_SIZE | P_KEY | flags,
                            params=[Cpv.ERRR, Cpv.ABNR, Cpv.BUF, len(data), Cpv.KEY])))

    def delete(self, key):
        """M:DELREC."""
        self._key(key)
        self.cpv._call(Cal1(1, Fpt(0x0D, word0=self.dcb.address, presence=P_ERR | P_ABN | P_KEY,
                                   params=[Cpv.ERRR, Cpv.ABNR, Cpv.KEY])))

    def close(self, release=False):
        """M:CLOSE; with ``release``, the disposition REL: the file is deleted."""
        if release:
            fpt = Fpt(0x15, word0=self.dcb.address, presence=0x80000000, params=[1])
        else:
            fpt = Fpt(0x15, word0=self.dcb.address)
        self.cpv._call(Cal1(1, fpt))


class ConsecFile(File):
    """An open consecutive file DCB: records one after another, no keys."""

    def read(self, size=2048):
        """M:READ: the next record, or None at the end of the file. A record longer
        than ``size`` raises CpvError X'07' (lost data)."""
        return super().read(None, size)

    def next(self):
        return self.read()

    def __iter__(self):
        while (data := self.read()) is not None:
            yield data

    def write(self, data):
        """M:WRITE: a record after the current one. Before the end of the file, the
        file is cut there first."""
        c = self.cpv
        if isinstance(data, str):
            data = data.encode(EBCDIC, errors="replace")     # text is EBCDIC
        c.cal.write_bytes(c.u, Cpv.BUF, 0, data)
        c._call(Cal1(1, Fpt(0x11, word0=self.dcb.address,
                            presence=P_ERR | P_ABN | P_BUF | P_SIZE,
                            params=[Cpv.ERRR, Cpv.ABNR, Cpv.BUF, len(data)])))

    def delete(self):
        """M:DELREC: the record just read."""
        self.cpv._call(Cal1(1, Fpt(0x0D, word0=self.dcb.address, presence=P_ERR | P_ABN,
                                   params=[Cpv.ERRR, Cpv.ABNR])))


class RandomFile(File):
    """An open random file DCB: whole granules by number (docs/files.md section 6)."""

    def _gran(self, gran, presence, params):
        if gran is not None:
            self.cpv.cal.s.umem[self.cpv.u][Cpv.KEY] = int(gran)   # the key word
            presence |= P_KEY
            params.append(Cpv.KEY)
        return presence, params

    def read(self, gran=None, size=GRAN):
        """M:READ of ``size`` bytes from granule ``gran`` (default: where the last
        request ended). Past the end of the file: CpvError X'42'. A request cut short
        by the end of the file: CpvError X'44'."""
        c = self.cpv
        presence, params = self._gran(gran, P_ERR | P_ABN | P_BUF | P_SIZE,
                                      [Cpv.ERRR, Cpv.ABNR, Cpv.BUF, size])
        c._call(Cal1(1, Fpt(0x10, word0=self.dcb.address, presence=presence, params=params)))
        return Record(c.cal.read_bytes(c.u, Cpv.BUF, 0, self.dcb.ars))

    def write(self, data, gran=None):
        """M:WRITE of ``data`` from granule ``gran`` (default: where the last request
        ended)."""
        c = self.cpv
        if isinstance(data, str):
            data = data.encode(EBCDIC, errors="replace")     # text is EBCDIC
        c.cal.write_bytes(c.u, Cpv.BUF, 0, data)
        presence, params = self._gran(gran, P_ERR | P_ABN | P_BUF | P_SIZE,
                                      [Cpv.ERRR, Cpv.ABNR, Cpv.BUF, len(data)])
        c._call(Cal1(1, Fpt(0x11, word0=self.dcb.address, presence=presence, params=params)))

    @property
    def granule(self):
        """The next granule (the key word in KBUF)."""
        return self.dcb.rgran
