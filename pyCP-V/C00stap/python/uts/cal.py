"""CAL dispatch: the CAL1 trap, decoding the FPT, the CAL1,1-CAL1,9 tables, monitor
overlays, and the returns. See docs/cal.md.

Translated from c00co/ENTRY.txt (CAL1P, T:CTRAPM), CALPROC.txt (CAL1P11, CAL11M, the
CAL1,1 and CAL1,2 tables, IOSPRTN), ALTCP.txt (CALCK, CAL13-CAL18, CAL1,9, OUT, CALBAD),
T$OV.txt (T:OVERLAY, T:REMEMBER), UCAL.txt (DRIVE, T:WAIT) and TIM.txt (M:TIME).

A stand-in program issues a CAL by yielding ``sched.Cal1(n, Fpt(...))``. The FPT and
the CAL1 instruction are written into the user's word memory (Scheduler.umem) and
decoded as CAL1P11 decodes them, including indirect, index and EXU chains. The
dispatch tables are data, so an unknown code reaches BADCAL as in the source. The
monitor's processing of the CAL is a generator on the user's stack: when an overlay
isn't in core, T:OVERLAY reports E:AP through T:REG and waits for the scheduler to
swap it in, then the routine runs. Translated routines: M:WAIT, M:TIME, M:PC
(T:STPMT), T:CLRERR, and the exits (to hooks: T:EXIT, T:ERROR, T:ABORT). The rest
raise NotTranslated with the routine's name and overlay.

Simplifications: no access-protection checks (T:IACU); DCBs are names and addresses
only (no open state, blocking buffers or AGER); the wait unit is assumed to be 1/50
minute (TIM.txt's 1MIN, BACKUP.txt's MINUTE EQU 50), with a timer standing in for
CLOCK4's wake-up; overlays have invented sizes; M:TRAP records trap control in J:USENT,
but delivering a trap or a bad CAL to the trap entry isn't translated (docs/trapxcon.md).
"""

from dataclasses import dataclass, field, replace

from . import jit
from .coc import ttyout
from .files import EBCDIC
from .monitor import NotTranslated
from .sched import (E_AP, E_CRD, E_IC, E_IIP, E_IP, E_SL, E_WU, PPSWP, RTR, SJAC, TIC, Dcb,
                    Report)

# --- Instruction and FPT layout -------------------------------------------------------

OP_CAL1, OP_EXU = 0x04, 0x25
INDIRECT = 0x80000000
J_JIT = 0x46 * 512              # JIT.txt:272 JJITVP: a PSD at or below this is the monitor
FPT_ADDR, CAL_ADDR = 0xA000, 0xA100   # where a stand-in's FPT and CAL1 go (invented)
M_OC = 0x8E00                                # M:OC, the monitor's (invented: outside the JIT)
M_UC = 0x8C2C                                # M:UC: in the JIT, word 44 (jit.py, JIT.txt:460)
M_XX = jit.XX_ADDRESS                        # M:XX: in the JIT, word 234 (jit.py, JIT.txt:527)
AMBUF = 0x49 * 512                           # SBUF2VPA: the assign/merge window (TEL.txt:95)
KEYBUF = 0x8E40                              # M:KEYIN without a buffer: the reply goes here
WAIT_UNIT = 600                 # clock units (2 ms) per M:WAIT unit: 1/50 minute (assumed)
TMS = 0x00800000                # FPT word 0 flag for M:TIME's binary result (Y008)
NOCR = (0x16, 0x20, 0x15, 0x0D)  # COC.txt:3183-:3184: a record ending so gets no CR LF
SMPSD = 0x00C00000              # STPNR.txt:407: slave, mapped; no masks, CC 0
PSD1 = 0x10000000               # a user's PSD word 1: the write key (JIT.txt's TSTACK)
DMAM = 0x00300000               # PSD bits 10-11: the decimal and arithmetic masks (Y003)
TRAPFLGB = 17                   # TABLES.txt:792: J:USENT's trap flags, bits 7-14 (Y01FE)
BCALMSK = 0x80                  # TABLES.txt:801: a bad CAL goes to the trap entry
JOVVPA = 0x40 * 512             # JIT.txt:271: the first page outside the monitor root


def instruction(op, r=0, address=0, x=0, indirect=False):
    """A Sigma instruction word: * bit 0, opcode 1-7, R 8-11, X 12-14, address 15-31."""
    return (INDIRECT if indirect else 0) | (op << 24) | (r << 20) | (x << 17) | (address & 0x1FFFF)


@dataclass
class Fpt:
    """A function parameter table: code (byte 0), word 0's address part, presence bits
    (word 1) and parameters. ``indirect`` sets word 0's bit 0 (code byte + X'80')."""
    code: int
    word0: int = 0
    presence: int = 0
    params: list = field(default_factory=list)
    indirect: bool = False

    def words(self):
        w0 = (self.code << 24) | (self.word0 & 0xFFFFFF)
        return [w0 | (INDIRECT if self.indirect else 0), self.presence] + list(self.params)


@dataclass
class Ctx:
    """What CAL1P11 leaves in the registers for the routine."""
    u: int
    n: int
    sr1: int                    # FPT code
    r6: int                     # FPT word 0 (DCB or parameter address)
    r7: int                     # FPT+1
    psd: int                    # address of the CAL
    from_monitor: bool


# --- Targets -------------------------------------------------------------------------

@dataclass(frozen=True)
class Res:
    """A resident routine (B name)."""
    name: str


@dataclass(frozen=True)
class Ovl:
    """An overlaid routine: LI,0 index / B T:OVERLAY with R2 = segment."""
    seg: int
    entry: object               # MISOV: a DRIVE name; others: an entry number or name


BADCAL = Res("BADCAL")
TRAPEXIT = Res("TRAPEXIT")

# SEGNAME  T$OV.txt:475
SEGNAMES = ["OPEN", "CLOSE", "LTAPE", "DEBUG", "MULOV", "LDLNK", "MISOV", "OPENTP",
            "STEPOVR", "ENQOV", "RTOV", "RMAOV", "TQOV1", "TQOV2"]
(OPNSEG, CLSSEG, LBLTSEG, DEBUGSEG, MULSEG, LDLNKSEG, MISOVSEG, IODTYSEG, STEPOVRSEG,
 ENQSEG, RTNRRTSEG, RMAOVSEG, TQOV1SEG, TQOV2SEG) = range(14)
DLTSEG = CLSSEG
OVERLAY_PAGES = {OPNSEG: 4, CLSSEG: 3, LBLTSEG: 2, DEBUGSEG: 2, MULSEG: 2, LDLNKSEG: 3,
                 MISOVSEG: 4, IODTYSEG: 2, STEPOVRSEG: 2, ENQSEG: 1, RTNRRTSEG: 2,
                 RMAOVSEG: 2, TQOV1SEG: 2, TQOV2SEG: 2}     # invented (at most 6 pages)
OVLY_BASE = 64                  # processor number of segment 0 (P:NAME index; invented)

# DRIVE  UCAL.txt:151 - MISOV's transfer vector; the index is the AD1 symbol (T$OV.txt:552)
MISOV_DRIVE = [None, "MVNAMDAT", "T:ASSOCIATE", "T:DISASSOCIATE", "T:CHTBL", "T:SAVEGET",
               "T:GHOST", "T:WAIT", "MSTRAP", "MXCON", "MINT", "MSTIMER", "MTTIMER",
               "T:DSMT", "T:JOBENT", "MSRTFILE", "MTIME", "PEOF", "PFIL", "PLEOFRM",
               "PRECORD", "REW", "WEOF", "SEGLD", "T:GDDL", "AVR", "MSRKEY"]


def misov(name):
    return Ovl(MISOVSEG, name)


# CAL1,1: C11CDS (CALPROC.txt:266), searched from the end, and DEVCDS (:283)
C11CDS = [(0x29, TRAPEXIT), (0x29, TRAPEXIT),            # caught by IOCHEK first
          (0x15, Ovl(CLSSEG, 2)), (0x03, Ovl(LBLTSEG, 2)), (0x14, Ovl(OPNSEG, 0)),
          (0x1C, misov("PFIL")), (0x1D, misov("PRECORD")), (0x0D, Ovl(DLTSEG, 4)),
          (0x01, misov("REW")), (0x02, misov("WEOF")), (0x12, Res("TRNC")),
          (0x0F, misov("MSRTFILE")), (0x0C, TRAPEXIT), (0x0E, Ovl(LBLTSEG, 6)),
          (0x2F, misov("T:JOBENT"))]
DEVCDS = [0x24, 0x23, 0x21, 0x26, 0x20, 0x22, 0x04, 0x27, 0x25, 0x28, 0x05, 0x0B, 0x06,
          0x2A, 0x2B]
# CAL1,2: C12CDS (:345)
C12 = {4: misov("MSRKEY"), 0x10: Res("MERC"), 1: Res("MSRTYPR"), 2: Res("MSRTYPR"),
       0: Res("MSROCTY"), 8: Res("ENQ"), 9: Res("ENQ")}
# CAL1,4 (ALTCP.txt:361, CHKPT on)
C14TV = [BADCAL, BADCAL, misov("T:SAVEGET"), misov("T:SAVEGET"), misov("T:ASSOCIATE"),
         misov("T:DISASSOCIATE"), Res("T:CLRERR")]
# CAL1,6 (:532)
C16TV = [Ovl(RMAOVSEG, "T:RDERLOG"), Ovl(RMAOVSEG, "T:WTERLOG"), Ovl(RMAOVSEG, "T:MAP"),
         Ovl(RMAOVSEG, "T:BLIST"), Ovl(RMAOVSEG, "T:LOCK"), Ovl(RMAOVSEG, "T:DOPEN"),
         Res("T:INITJOB"), Ovl(RMAOVSEG, "T:DCLOSE"), Res("T:SYS"), Ovl(RMAOVSEG, "T:BLIST"),
         Ovl(RMAOVSEG, "T:MODPRTRT")]
# CAL1,7 (:555): codes below TQOV2END in TQOV2, the rest in TQOV1
C17TV = ([Ovl(TQOV2SEG, f"CNMPROC{i}") for i in range(5)] + [Res("ECBCHECK")]
         + [Ovl(TQOV1SEG, "TQUEUE")] * 7 + [Res("T:GETID")])
# CAL1,8 (:602), with MMOVRTV's page calls in STEPOVR (:658)
_STEP = {4: "T:GVP", 5: "T:FVP", 7: "T:SAD", 8: "T:GDP", 9: "T:FDP", 0xA: "T:SMP",
         0xB: "T:GL", 0xC: "T:GCP", 0xD: "T:FCP"}
C18TV = ([BADCAL, Res("MSEGLD"), Res("MLNK"), Res("MLNK")]
         + [Ovl(STEPOVRSEG, _STEP[c]) if c != 6 else misov("T:CHTBL") for c in range(4, 0xE)]
         + [misov("MINT"), misov("T:WAIT"), misov("MTIME"), misov("MSTIMER"),
            misov("MTTIMER"), Res("T:SYSLOAD"), Res("MTRAP")] + [Res("RESOURCE")] * 4
         + [misov("MXCON"), Ovl(MULSEG, "T:LDEV"), misov("T:GDDL")])
assert len(C18TV) == 0x1C                          # HICAL18 = X'1B'
# CAL1,9 (:254)
C19TV = [BADCAL, Res("T:EXIT"), Res("T:ERROR"), Res("T:ABORT"), misov("MSTRAP"),
         Res("MTRTN"), Ovl(MULSEG, "CCLOSE"), BADCAL, BADCAL, Res("USERGO"), BADCAL,
         Res("MSTRUNC")]
SLAVECODE, MASTERCODE = 7, 8                       # ALTCP.txt:144 MSCODES

MONTHS = [None, "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT",
          "NOV", "DEC"]                            # TIM.txt:208
CALEN = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]


# Read/write: FPT word 1's presence bits (JHKBIT order, IORT.txt:345-486) and the WAIT
# flag (bit 27 by JHKBIT's and SKIPBLK's shifts: an assumption, docs/rdwr.md).
P_ERR, P_ABN, P_BUF, P_SIZE = 0x80000000, 0x40000000, 0x20000000, 0x10000000
P_KEY, P_BTD, P_ECB, P_BLK = 0x08000000, 0x04000000, 0x02000000, 0x01000000
F_WAIT = 0x10
F_NWK, F_ONWK = 0x20, 0x40                     # NEWKEY bit 26, ONEWKEY bit 25 (BPM.txt:600-:602)
F_REV = 0x10                                   # M:PRECORD's REV, bit 27 (BPM.txt:612; POS.txt SETPOS)
TYCOR = [0, 0, 0, 0, 1, 1, 1, 1]                   # IOQ.txt:763: typewriter read 0, write 1
CODE = {2: 0x07, 3: 0x1D, 4: 0x04, 5: 0x1C, 6: 0x05, 7: 0x06, 8: 0x41, 9: 0x45,
        0xA: 0x57, 0xD: 0x33, 0xE: 0x5B, 0xF: 0x5C, 0x13: 0x4F}   # IORT.txt:1168


class CalAbort(Exception):
    def __init__(self, code):
        self.code = code


# --- a DCB in the user's memory (docs/dcb.md) -------------------------------------------

FUNCTIONS = {1: "IN", 2: "OUT", 3: "INOUT", 4: "UPDATE", 8: "OUTIN"}   # GETFUN: bits 11-14
CODES = {v: k for k, v in FUNCTIONS.items()}

# field: (word, shift, mask) in place (docs/dcb.md, "The words")
DCB_FIELDS = {
    "open": (0, 21, 1),                        # FCD  X'00200000'
    "egv": (0, 12, 1),                         # X'1000'
    "usr": (0, 14, 1),                         # X'4000'
    "btd": (0, 4, 3),                          # X'30'
    "asn": (0, 0, 0xF),
    "tyc": (2, 17, 0x7F),                      # Y00FE
    "buf": (2, 0, 0x1FFFF),
    "rsz": (3, 17, 0x7FFF),
    "era": (3, 0, 0x1FFFF),                    # the error address (UTS.txt:554)
    "ars": (4, 17, 0x7FFF),
    "aba": (4, 0, 0x1FFFF),                    # the abnormal address (UTS.txt:556)
    "flp": (6, 0, 0x1FFFF),                    # the VLP list (FLP)
    "org": (5, 0, 0x30),
    "keym": (12, 24, 0xFF),
    "rstore": (20, 0, 0xFFFFFFFF),
}
PROT_CODES = (0x03, 0x05, 0x06, 0x14, 0x15)


# The organization, ORG's X'30' (OPNF.txt:1015-:1038, :550-:558): X'20' clear is
# consecutive (0, or X'10' "explicit consec"), X'20' keyed, X'30' random.
def consecutive(dcb):
    return not dcb.org & 0x20


def keyed(dcb):
    return dcb.org & 0x30 == 0x20


def random(dcb):
    return dcb.org & 0x30 == 0x30


def vlps_at(mem, a):
    """A VLP list at word ``a`` (a DCB's FLP, or after an FPT's parameters): {code:
    [data words]}: the words used (0: the parameter is not given). Each starts with a control
    word: code, last flag, words used, words reserved."""
    out = {}
    for _ in range(32):
        if not a:
            break
        cw = mem.get(a, 0) & 0xFFFFFFFF
        code, last, used, reserved = cw >> 24, (cw >> 16) & 0xFF, (cw >> 8) & 0xFF, cw & 0xFF
        out[code] = [mem.get(a + 1 + i, 0) & 0xFFFFFFFF for i in range(used)]
        if last:
            break
        a += 1 + reserved
    return out


class MemDcb:
    """A DCB in a user's memory (an interpreted program's own): its fields read and
    written in place (DCB_FIELDS, FUN, WAT), its name, account and protection from its
    VLPs. What the model keeps as Python objects (the CFU, a consecutive file's
    position, the request's key) is kept beside it, as in a sched.Dcb."""

    _SIDE = Dcb()                                      # defaults for the rest

    def __init__(self, cal, u, address):
        object.__setattr__(self, "_cal", cal)
        object.__setattr__(self, "_u", u)
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "_side", {})

    def _w(self, i):
        return self._cal.s.umem[self._u].get(self.address + i, 0) & 0xFFFFFFFF

    def _setw(self, i, v):
        self._cal.s.umem[self._u][self.address + i] = v & 0xFFFFFFFF

    def __getattr__(self, name):
        if name in DCB_FIELDS:
            w, sh, m = DCB_FIELDS[name]
            v = (self._w(w) >> sh) & m
            return bool(v) if name in ("open", "egv", "usr") else v
        if name == "fun":
            return FUNCTIONS.get((self._w(1) >> 17) & 0xF, "IN")
        if name == "wat":
            return bool(self._w(0) & 0x00100400)
        if name == "name":
            return f"DCB X'{self.address:X}'"
        if name == "fname":
            return self._text(0x01)
        if name == "account":
            return self._text(0x02, count=False)
        if name == "prot":                             # a slot with 0 words used: not given
            v = self._vlps()
            return {c: self._ebcdic(c, v[c]) for c in PROT_CODES if v.get(c)}
        side = self._side
        if name in side:
            return side[name]
        return getattr(self._SIDE, name)

    def __setattr__(self, name, value):
        if name in DCB_FIELDS:
            w, sh, m = DCB_FIELDS[name]
            self._setw(w, (self._w(w) & ~(m << sh)) | ((int(value) & m) << sh))
        elif name == "fun":
            self._setw(1, (self._w(1) & ~(0xF << 17)) | (CODES.get(value, 1) << 17))
        elif name == "wat":
            self._setw(0, (self._w(0) | 0x00100400) if value else (self._w(0) & ~0x00100400))
        else:
            self._side[name] = value

    def _vlps(self):
        """The VLP list at FLP: {code: [data words]}, the words used."""
        return vlps_at(self._cal.s.umem[self._u], self._w(6) & 0x1FFFF)

    def set_vlp(self, code, words):
        """MSROPN98B: ``words`` into the DCB's VLP slot for ``code``, at most as many as
        the slot reserves, and the count used. No slot: nothing (MSROPN99A)."""
        mem, a = self._cal.s.umem[self._u], self._w(6) & 0x1FFFF
        for _ in range(32):
            if not a:
                return
            cw = mem.get(a, 0) & 0xFFFFFFFF
            last, reserved = (cw >> 16) & 0xFF, cw & 0xFF
            if cw >> 24 == code:
                n = min(len(words), reserved)
                for i in range(reserved):
                    mem[a + 1 + i] = words[i] if i < n else 0
                mem[a] = (cw & 0xFFFF00FF) | (n << 8)
                return
            if last:
                return
            a += 1 + reserved

    def put_vlp_words(self, code, words):
        """CHKFLACN's STM,R1 *R7,R3 (OBSE.txt:289-:290): ``words`` into the slot for
        ``code``, its used count left as it is. No slot, or one too small: False."""
        mem, a = self._cal.s.umem[self._u], self._w(6) & 0x1FFFF
        for _ in range(32):
            if not a:
                return False
            cw = mem.get(a, 0) & 0xFFFFFFFF
            if cw >> 24 == code:
                if (cw & 0xFF) < len(words):
                    return False
                for i, w in enumerate(words):
                    mem[a + 1 + i] = w
                return True
            if (cw >> 16) & 0xFF:
                return False
            a += 1 + (cw & 0xFF)
        return False

    @staticmethod
    def _ebcdic(code, words):
        """A protection VLP's words: EBCDIC in memory, as the file system keeps them."""
        return list(words)

    def _text(self, code, count=True):
        words = self._vlps().get(code)
        if not words:
            return self._side.get("account", "") if code == 0x02 else ""
        data = b"".join(w.to_bytes(4, "big") for w in words)
        if count:
            data = data[1:1 + data[0]]
        return data.decode(EBCDIC).rstrip(" \0")


class CalProcessor:
    """The CAL1 trap and dispatch for a Scheduler."""

    def __init__(self, sched, date=None):
        self.s = sched
        self.date = date if date is not None else {}   # Monitor.DATE: MO DA YR HR MI
        self.C_CAL = 0
        self.calcnt = {}                               # J:CALCNT per user
        self.dcbs = {}                                 # J:DCBLINK per user: {name: address}
        self.prompt = {}                               # JB:PROMPT per user
        self.priv = {}                                 # JB:PRIV per user
        self.mem_dcbs = {}                             # DCBs in users' memory (MemDcb)
        self.account = {}                              # J:JIT's ACCN per user (:SYS if none)
        self.running = {}                              # M:XX: (name, account) of the program
        self.ended = {}                                # user -> how a CAL ended them
        self.hooks = {}
        self.io = None                                 # io.IOSystem, from attach_io
        self.fs = None                                 # files.FileSystem
        self.dcb_objs = {}                             # user -> {address: Dcb}
        self.uc = {}                                   # user -> M:UC (in the user's JIT)
        self.intent = {}                               # J:INTENT per user: M:INT's address
        self.uname = {}                                # J:UNAME per user (the log-on name)
        self.ccbuf = {}                                # J:CCBUF per user: the command line
        self.amr = {}                                  # the assign/merge record (assign.py)
        self.amr_header = {}                           # its header words, as last written
        self.stdopt = {}                               # JSTDOPT: TEL's options, kept
        self.jopt = {}                                 # J:OPT: the options for the step
        self.common = {}                               # JB:BCP kept across M:LDTRC (jit.build)
        self.step_error = {}                           # the I/O error that ended the step
        self.tcb = {}                                  # J:TCB per user, if M:INT set it
        self.upsd = {}                                 # the user's PSD at its last trap (TSTACK's)
        self.cmap = {}                                 # JX:CMAP per user: the virtual pages mapped
        self.unit_record = None                        # cards.UnitRecord: the card devices
        self.monitor_dcbs = {M_OC: Dcb("M:OC", fcn=0, address=M_OC, dtype="TY"),
                             M_UC: Dcb("M:UC", fcn=0, address=M_UC, coc=True),
                             M_XX: Dcb("M:XX", fcn=0, address=M_XX)}
        self.log = []
        for seg, pages in OVERLAY_PAGES.items():
            p = OVLY_BASE + seg
            sched.PB_PSZ.setdefault(p, pages)

    def trace(self, msg):
        self.s.trace(msg)
        self.log.append(msg)

    # --- memory ------------------------------------------------------------------------

    def fetch(self, u, address):
        """CVREG  CALPROC.txt:367 - a register address means the saved register."""
        a = address & 0x1FFFF
        if not a & 0x1FFF0:
            return self.s.uregs[u][a]
        return self.s.umem[u].get(a, 0)

    def place(self, u, req):
        """Write a stand-in's FPT and CAL1 into its memory; returns the PSD address."""
        mem = self.s.umem[u]
        for r, v in (req.regs or {}).items():
            self.s.uregs[u][r] = v
        if req.fpt is not None:
            for i, w in enumerate(req.fpt.words()):
                mem[FPT_ADDR + i] = w
            address = FPT_ADDR
        else:
            address = req.address or 0
        mem[CAL_ADDR] = instruction(OP_CAL1, req.n, address)
        return CAL_ADDR

    # --- the trap ----------------------------------------------------------------------

    def trap(self, u, req):
        """CAL1P (ENTRY.txt:248) and T:CTRAPM: trap X'48', into the monitor. A stand-in's
        CAL is placed first; an interpreted program's is in its memory already."""
        psd = req.psd if hasattr(req, "psd") else self.place(u, req)
        self.s.S_CLOCK4 = (u, "OVHTIM")                # T:CTRAPM: overhead
        try:
            ctx = self.cal1p11(u, psd)
            result = yield from self.dispatch(ctx)
        except CalAbort as e:
            if self.jword(u, jit.USENT) & (BCALMSK << TRAPFLGB):   # CALBAD  ALTCP.txt:1018
                raise NotTranslated(f"CALBAD X'{e.code:02X}' to the user's trap entry"
                                    " (STKTOTMP)")
            return ("ABORT", e.code)
        return result

    def cal1p11(self, u, psd):
        """CAL1P11  CALPROC.txt:93 - find the FPT and dispatch on n."""
        self.C_CAL += 1
        self.calcnt[u] = self.calcnt.get(u, 0) + 1
        word = self.fetch(u, psd)                      # ANLZSB: GET CAL OR EXU
        n = (word >> 20) & 0xF                         # the R field, the trap CC
        while True:
            if word & INDIRECT:
                d3 = self.fetch(u, word & 0x1FFFF)     # GET DIRECT ADDRESS
            else:
                d3 = word
            x = (word >> 17) & 7
            ea = (d3 + (self.s.uregs[u][x] if x else 0)) & 0x1FFFF
            if (word >> 24) & 0x7F == OP_EXU:          # UNDO EXU CHAIN
                word = self.fetch(u, ea)
                n = (word >> 20) & 0xF
                continue
            break
        r7 = ea
        w0 = self.fetch(u, r7)
        sr1, r6 = (w0 >> 24) & 0xFF, w0
        if r6 & INDIRECT:                              # indirect DCB address
            r6 = self.fetch(u, r6)
            sr1 -= 0x80
        ctx = Ctx(u=u, n=n, sr1=sr1, r6=r6, r7=r7 + 1, psd=psd, from_monitor=psd <= J_JIT)
        self.trace(f"CAL1,{n} user {u}: FPT X'{r7:X}' code X'{sr1:02X}'")
        if n > 2:
            self.calcnt[u] -= 1                        # MTW,-1 J:CALCNT
        return ctx

    def dispatch(self, ctx):
        """C1TV (CALPROC.txt:142) and CALCK (ALTCP.txt:173)."""
        n = ctx.n
        if n == 1:
            return (yield from self.cal11(ctx))
        if n == 2:
            return (yield from self.cal12(ctx))
        ctx.r6 &= 0xFFFFFF                             # CALCK: AND,R6 M24
        if n == 0 or n > 9:
            raise CalAbort(0xAE)
        handler = {3: self.cal13, 4: self.cal14, 5: self.cal15, 6: self.cal16,
                   7: self.cal17, 8: self.cal18, 9: self.cal19}[n]
        return (yield from handler(ctx))

    def code_table(self, ctx, table):
        if ctx.sr1 >= len(table):
            raise CalAbort(0xAE)
        return (yield from self.invoke(ctx, table[ctx.sr1]))

    # --- the families ---------------------------------------------------------------

    def cal11(self, ctx):
        """CAL11M  CALPROC.txt:156 - check the DCB, then dispatch."""
        u, dcb = ctx.u, ctx.r6 & 0x1FFFF
        if dcb == M_UC:
            if not self._online_or_ghost(u):
                return self._bad_dcb(ctx)              # CAL11X2: illegal in batch
        elif dcb != M_XX and dcb not in self.dcbs.get(u, {}).values() and dcb != M_OC:
            return self._bad_dcb(ctx)
        code = ctx.sr1                                 # CAL11N9
        if code == 0x11:                               # WRITE: IORT CAL11N7
            return (yield from self.cal11n7(ctx, self.dcb_at(u, dcb), write=True))
        if code == 0x10:                               # READ: IORT CAL11N7
            return (yield from self.cal11n7(ctx, self.dcb_at(u, dcb), write=False))
        if code in (0x2D, 0x2E):                       # IORT.txt:366: OVERTO T:AMRDWT
            return self.t_amrdwt(ctx, self.dcb_at(u, dcb), code)
        if code == 0x29:                               # CHECK: IORT IOCHEK
            return (yield from self.iochek(ctx, self.dcb_at(u, dcb)))
        for c, target in reversed(C11CDS):             # CHKCAL1, from NC11S down
            if c == code:
                if dcb == M_UC:
                    raise CalAbort(0xAE)               # only read/write/device on M:UC
                return (yield from self.invoke(ctx, target))
        if code == 0x06:                               # M:SETDCB: IOSDEV always does it
            return self.setdcb(ctx, self.dcb_at(u, dcb))
        if code in (0x04, 0x05, 0x22, 0x2A, 0x2B):     # M:DEVICE PAGE, VFC, MODE, NLINES; M:CORRES
            return (yield from self.iosdev(ctx, dcb, code))
        if code in DEVCDS:
            return (yield from self.invoke(ctx, Res("IOSDEV")))
        raise CalAbort(0xAE)

    def iosdev(self, ctx, address, code):
        """IOSDEV  IOD.txt:99 - the device options PAGE, VFC and CORRES. On M:OC nothing
        is done (:104-:105); these options go to their routines with no device check
        (TSTDEV1, :547-:549). The others aren't translated."""
        u = ctx.u
        if address == M_OC:
            return ("CC", 0)                           # IOSDEVX: CLEAR
        dcb = self.dcb_at(u, address)
        if code == 0x2A:                               # IONLINES  :471
            return self.ionlines(u, dcb)
        if code == 0x22:                               # IOMODE  :290
            return self.iomode(u, ctx.r7, dcb)
        if code == 0x04:                               # IOPAGE  :310
            if isinstance(dcb, MemDcb) and not dcb.open:   # TESTOPN: OPEN it first
                yield from self.t_overlay(u, OPNSEG)
                if dcb.asn == 3:
                    self._open_device(u, dcb)
                elif self.fs is not None:
                    self._open(u, dcb)
            line = self.s.coc.line_of(u) if self.s.coc is not None else None
            if getattr(dcb, "device", None) == "ME" and line is not None:
                self.s.coc.finish(line)                # a new page: here, a new line
            return ("CC", 0)
        if code == 0x05:                               # IOVFC  :446: the FRM bit X'100'
            if not (dcb.open and dcb.asn != 3):        # 1A1: not an open non-device DCB
                on = self.fetch(u, ctx.r7) & 0x10      # the FPT's flag, SLS,R2 4: X'100'
                if isinstance(dcb, MemDcb):
                    w0 = self.fetch(u, dcb.address)
                    self.s.umem[u][dcb.address] = (w0 | 0x100) if on else (w0 & ~0x100)
                dcb.vfc = bool(on)
            return ("CC", 0)
        other = self.fetch(u, ctx.r7) & 0x1FFFF        # IOCORRES  :507: DCB2, perhaps indirect
        if self.fetch(u, ctx.r7) & INDIRECT:
            other = self.fetch(u, other) & 0x1FFFF
        same = self._assignment(u, dcb) == self._assignment(u, self.dcb_at(u, other))
        self.s.uregs[u][8] = 1 if same else 0          # SR1 into the user's R8 (NL1)
        return ("CC", 0)
        yield

    def iomode(self, u, fpt, dcb):
        """IOMODE  IOD.txt:290 - M:DEVICE (MODE), for a device or unassigned DCB only
        (TSTDEV, :552): FPT word 1's X'10' into MOD X'20000', X'20' into FCON X'4000',
        and X'40' clear into PCK X'200' (packed is the default); then the record size,
        if the first presence bit is set (JHKBIT1, IORT.txt:396; SAVRSZ)."""
        if dcb.asn & 7 not in (0, 3) or not isinstance(dcb, MemDcb):
            return ("CC", 0)                           # IOSDEVX
        w1 = self.fetch(u, fpt + 1)
        w0 = self.fetch(u, dcb.address) & ~(0x20000 | 0x4000 | 0x200)
        w0 |= (0x20000 if w1 & 0x10 else 0) | (0x4000 if w1 & 0x20 else 0)
        w0 |= 0 if w1 & 0x40 else 0x200
        self.s.umem[u][dcb.address] = w0
        if w1 & 0x80000000:
            take = self._params(u, iter([self.fetch(u, fpt + 2)]))
            dcb.rsz = take() & 0x7FFF
        return ("CC", 0)

    def ionlines(self, u, dcb):
        """IONLINES  IOD.txt:471-:500 - M:DEVICE (NLINES): SR1 = the lines left on the page,
        the DCB's lines per page (LVA, word 10 bits 0-14) less its count (word 12's left
        half, CLK); 0 for a DCB not assigned to a device. A symbiont stream's context
        (CNTXTCHK, SCLINES) isn't modeled."""
        regs = self.s.uregs[u]
        regs[8] = 0                                    # LI,SR1 0
        if dcb.asn != 3 or not isinstance(dcb, MemDcb):
            return ("CC", 0)                           # NOT APPLICABLE IF NOT DEVICE
        w12 = self.fetch(u, dcb.address + 12)
        if w12 & 0xFF:
            raise NotTranslated("M:DEVICE (NLINES) for a symbiont stream (CNTXTCHK)")
        lva = (self.fetch(u, dcb.address + 10) >> 17) & 0x7FFF
        used = w12 >> 16
        used = used - 0x10000 if used & 0x8000 else used   # SH: a signed halfword
        regs[8] = (lva - used) & 0xFFFFFFFF
        return ("CC", 0)

    def _assignment(self, u, dcb):
        """GETDEV's answer, for comparing two DCBs: what the DCB is assigned to."""
        if dcb is None:
            return None
        if dcb.asn == 1:
            return ("file", dcb.fname, dcb.account or self.account.get(u, ":SYS"))
        if getattr(dcb, "device", None):
            return ("device", dcb.device)
        from . import devopen
        word1 = self.fetch(u, dcb.address + 1)
        try:                                           # GETDEV1: never opened
            return ("device", devopen.assigned(self.s, u, word1) or "NO")
        except (devopen.OpenError, NotTranslated):
            return ("device", word1 & 0x1FFFF)

    def mint(self, ctx):
        """MINT  TRAPC.txt:143 - M:INT: the BREAK address into J:INTENT (with X'08'),
        and J:TCB set from register 0 if the user has none. A command processor's own
        break control (INT30) isn't modeled; nor is delivering a BREAK to the address."""
        u = ctx.u
        address = ctx.r6 & 0x1FFFF
        self.intent[u] = (address | 0x08000000) if address else 0
        from . import jit
        self.s.umem[u][jit.J_JIT + jit.INTENT] = self.intent[u]   # STW,6 J:INTENT
        self._tcb_from_r0(u)                           # INT10: USE USER R0 AS TCB
        return ("TRAPEXIT", None)
        yield

    TIMER_UNITS = (500, 30000, 1)                      # MPLRS: seconds, minutes, ticks

    def mstimer(self, ctx):
        """MSTIMER  TRAPC.txt:173-:186 - M:STIMER: J:UTIMER the count (FPT word 1) in
        clock ticks, by the unit in word 0's bits 12-14 (MPLRS: a second is 500); J:TIMENT
        the exit address with X'08000000'. The clock counting it down and the exit taken
        when it runs out aren't modeled (a departure, docs/trapxcon.md)."""
        u = ctx.u
        unit = (ctx.r6 >> 17) & 3                      # SLS,R6 -17; AND,R6 M2
        ticks = (self.TIMER_UNITS[unit] if unit < 3 else 0) * self.fetch(u, ctx.r7)
        self.set_jword(u, jit.UTIMER, ticks)           # STW,D2 UTIMER,R5
        self.set_jword(u, jit.TIMENT, (ctx.r6 & 0x1FFFF) | 0x08000000)   # OR,R1 Y8
        return ("TRAPEXIT", None)
        yield

    def mttimer(self, ctx):
        """MTTIMER  TRAPC.txt:188-:202 - M:TTIMER: the time left, in the unit in word 0's
        bits 30-31, into SR1 (R8); with X'100' (CANCEL), J:TIMENT cleared. Nothing left if
        no exit was set (TIMENT without X'08000000')."""
        u = ctx.u
        entry = self.jword(u, jit.TIMENT)
        if ctx.r6 & 0x100:
            self.set_jword(u, jit.TIMENT, 0)           # XW,R1 TIMENT,R5
        unit = ctx.r6 & 3
        left = self.jword(u, jit.UTIMER) if entry & 0x08000000 else 0
        self.s.uregs[u][8] = left // self.TIMER_UNITS[unit] if unit < 3 else 0   # DW; *TSTACK-7
        return ("TRAPEXIT", None)
        yield

    def jword(self, u, i):
        """Word ``i`` of the user's JIT page (jit.py)."""
        return self.s.umem[u].get(jit.J_JIT + i, 0) & 0xFFFFFFFF

    def set_jword(self, u, i, v):
        self.s.umem[u][jit.J_JIT + i] = v & 0xFFFFFFFF

    def _tcb_from_r0(self, u):
        """J:TCB, if it is 0, from the user's R0 (MINT's INT10, MTRAP's MTRAPX)."""
        if not self.jword(u, jit.TCB):
            self.set_jword(u, jit.TCB, self.s.uregs[u][0])
        self.tcb.setdefault(u, self.jword(u, jit.TCB))

    def psd_at_trap(self, u, address=None):
        """The user's PSD as TSTACK holds it: the CC, the masks and the return address."""
        w0, w1 = self.upsd.get(u, (SMPSD, PSD1))
        if address is not None:
            w0 = (w0 & ~0x1FFFF) | (address & 0x1FFFF)
        return ((self.s.psd_cc[u] & 0xF) << 28) | (w0 & 0x0FFFFFFF), w1

    def mtrap(self, ctx):
        """MTRAP  ALTCP.txt:1170 - M:TRAP: the trap entry address into J:USENT, the trap
        flags in its bits 7-14 reset (ABORT, FPT word 1 bits 1-8) and set (TRAP, bits 9-16),
        and the PSD's decimal and arithmetic masks set (PERMIT, bits 22-23) and cleared
        (IGNORE, bits 30-31). The previous conditions go to SR1 (J:USENT's left half and
        the PSD's) and SR2 (J:USENT). With bit 0, RESTORE: the conditions from the SR1/SR2
        pair at word 0's address. A foreground user's FPDTTF copy isn't kept."""
        s, u = self.s, ctx.u
        w0, w1 = self.psd_at_trap(u)
        d2 = self.fetch(u, ctx.r7)                     # LW,D2 0,R7: FPT word 1
        old = self.jword(u, jit.USENT)
        if d2 & 0x80000000:                            # RSTRTRAP
            a = ctx.r6 & 0x1FFFF
            d1, r2 = self.fetch(u, a), self.fetch(u, a + 1)
            word = (old & ~0x1FFFF) | (r2 & 0x1FFFF)   # STS,R2 USRENT,R5
            word = (word & ~0x01FE0000) | (d1 & 0x01FE0000)   # STS,D1 TRAPFLAG (Y01FE)
            w0 = (w0 & ~DMAM) | ((d1 << 16) & DMAM)    # STH,D1 D1 / STS,D1 D3: DM, AM
        else:
            word = (old & ~0x1FFFF) | (ctx.r6 & 0x1FFFF)      # STS,R6 USRENT,R5
            regs = s.uregs[u]
            regs[8] = (word & 0xFFFF0000) | (w0 >> 16)        # SR1: TRAPFLAG, PSD left halves
            regs[9] = old                                     # SR2
            reset = ((d2 >> 24) & 0x7F) | (BCALMSK if d2 & 0x00800000 else 0)
            word &= ~(reset << TRAPFLGB)               # MTRAP2: EOR,D1 M32 / SCS / AND
            set_ = ((d2 >> 16) & 0x7F) | (BCALMSK if d2 & 0x00008000 else 0)
            word |= set_ << TRAPFLGB                   # MTRAP4
            w0 = (w0 & ~((d2 << 20) & DMAM)) | ((d2 << 12) & DMAM)   # MTRAP6
        self.set_jword(u, jit.USENT, word)             # STW,R2 TRAPFLAG,R5
        self.upsd[u] = (w0 & 0x0FFFFFFF, w1)           # MTRAPX  STD,D3 *R1
        self._tcb_from_r0(u)
        return ("TRAPEXIT", None)
        yield

    def mxcon(self, ctx):
        """MXCON  TRAPC.txt:106 - M:XCON: the exit-control address (and LAST, bit 8) into
        J:EXTENT; the old address to SR1. After LAST, a new one is refused (CC1) unless
        exit control is in progress. Bit 3, exit control set by a command processor, is
        set only when TEL is in control (TIC)."""
        s, u = self.s, ctx.u
        ext = self.jword(u, jit.EXTENT)
        s.uregs[u][8] = ext & 0x1FFFF                  # LS,R2 J:EXTENT / STW,R2 *TSTACK,R1
        if not ext & 0x20000000 and ext & 0x00800000:  # Y2: in progress; Y008: LAST
            return ("CC", 8)                           # CC1SET
        ext = (ext & ~0x0081FFFF) | (ctx.r6 & 0x0081FFFF)   # REPLACE  STS,R6 J:EXTENT
        if s.UH_FLG[u] & TIC:
            ext |= 0x10000000                          # X'10' in byte 0
        else:
            ext &= ~0x10000000                         # NTIC
        self.set_jword(u, jit.EXTENT, ext)
        return ("CC", 0)                               # CC0RST
        yield

    def exit_control(self, u, rnst):
        """XCONSEE  STPNR.txt:583-:719 - at a program's exit with run status ``rnst``: the
        exit-control address, if M:XCON gave one and it is to be taken, with the program's
        state prepared for it (XCONSETUP); otherwise None. The PSD and registers are pushed
        on the user's stack (T:UTSXTS); R8 = the run status, R9 = the limit bits, R10 = the
        abort code, R11 = its subcode, R12 bit 0 = the user's stack was bad, bit 1 = an
        M:LINK exit. The limits (RNST X'04', TIMELMT) aren't modeled."""
        s, j = self.s, self.s.jit[u]
        ext = self.jword(u, jit.EXTENT)
        address = ext & 0x1FFFF
        if not address:
            return None                                # NOXCON
        flags = ext >> 24
        if flags & 0x20 and not rnst & 0x3F:           # in progress: M:EXIT, M:ERR or M:XXX
            return None
        if bool(flags & 0x10) != bool(s.UH_FLG[u] & TIC):   # NOTINPRO / NOTCP
            return None
        if rnst and rnst != 0x04 and rnst & 0x18:      # an X key-in, a hang-up
            if ext & 0x80000000:
                return None                            # KICKOFF
            ext |= 0x80000000                          # THE ABORT/HANGUP BIT
        return self._xcon_setup(u, rnst, ext)

    def _xcon_setup(self, u, rnst, ext):
        """XCONSETUP  STPNR.txt:669-:719, from the exit (XCONSEE) or from M:LINK/M:LDTRC
        (MLNK): returns the exit-control address, the program set to go on there."""
        s, j = self.s, self.s.jit[u]
        address = ext & 0x1FFFF
        regs = s.uregs[u]
        w0, w1 = self.psd_at_trap(u)
        stack = self._push_environment(u, w0, w1)      # XCONSETUP
        if stack is None:                              # TCBMESS
            regs[2], regs[3] = w0, w1
            r12 = 0x80000000
        else:
            regs[0], regs[1] = self.jword(u, jit.TCB), stack
            r12 = 0
        regs[8] = rnst & 0xFF                          # RUNSTATUS FLGS
        regs[9] = (regs[9] & ~0x1FF) | (self.jword(u, jit.ASSIGN) & 0x1FF)
        regs[10] = j.ABC & 0xFF
        regs[11] = j.ERO & 0xFF
        j.RNST = j.ABC = 0
        j.ERO &= ~0xFF
        flags = (ext >> 24) | 0x20                     # SET IN-PROGRESS BIT
        if flags & 0x08:                               # an M:LINK exit
            flags &= ~0x08
            r12 |= 0x40000000
        regs[12] = r12
        self.set_jword(u, jit.EXTENT, (flags << 24) | (ext & 0x00FFFFFF))
        j.INTENT = j.TIMENT = 0                        # XCONENT
        self.intent[u] = 0
        self.set_jword(u, jit.INTENT, 0)
        self.set_jword(u, jit.TIMENT, 0)
        self.upsd[u] = (SMPSD, PSD1)                   # SMPSD around the address
        s.psd_cc[u] = 0
        self.trace(f"XCON user {u}: exit control at X'{address:X}', run status X'{rnst:02X}'")
        return address

    def mlnk(self, ctx):
        """MLNK  ALTCP.txt:1028 - M:LINK (X'02') and M:LDTRC (X'03'). Exit control first:
        if the program has it and it isn't in progress, the exit routine is taken, with the
        M:LINK bit (X'08') set (:1035-:1043); if it is in progress, the address is cleared
        (MLNK2). Then LNKTRC (LDLNKSEG): for M:LDTRC (LDT0, LNKTRC.txt:433), the trap and
        timer entries cleared, M:XX and the program's open DCBs closed, its memory released
        (RELCORE; here the next program's FETCH replaces it), and the name, account and
        password taken from the FPT (L10LNK, :738-:773) for T:ASP,
        which starts a shared processor or a load module in the program's place (the
        "LDTRC" hook, online.py). Not modeled: RTCHK, VALID's checks (:978-:1050: no
        debugger, a module from the overlay loader, no page CALs), the FPOOLs (T:ZBUF), and a
        saved IDN file (:456-:522). M:LINK, which keeps the caller, isn't translated."""
        s, u = self.s, ctx.u
        if ctx.sr1 == 2:
            raise NotTranslated("M:LINK (load and link: LNKTRC LNK0)")
        ext = self.jword(u, jit.EXTENT)
        if ext & 0x1FFFF:                              # HONOUR EXIT CONTROL IF SPECIFIED
            if ext & 0x20000000:
                self.set_jword(u, jit.EXTENT, ext & ~0x1FFFF)   # MLNK2: CLEAR THE ADDRESS
            else:
                self.trace(f"MLNK user {u}: exit control first (the M:LINK bit)")
                return ("XCON", self._xcon_setup(u, 0, ext | 0x08000000))
        flags, at = ctx.r6 & 3, ctx.r7                 # L10LNK: word 0's flags, the name
        n = min(self.read_bytes(u, at, 0, 1)[0], 11)   # TRUNCATE AT 11 CHARS
        name = self.read_bytes(u, at, 1, n).decode(EBCDIC, "replace").strip()
        at += (n >> 2) + 1
        account = self.account.get(u, ":SYS")          # J:ACCN, IN CASE NONE SPEC
        if flags & 2:
            account = self.read_bytes(u, at, 0, 8).decode(EBCDIC, "replace").strip()
            at += 2
        password = self.read_bytes(u, at, 0, 8) if flags & 1 else b""
        yield from self.t_overlay(u, LDLNKSEG)         # OVERLAY LDLNKSEG
        for i in (jit.INTENT, jit.TIMENT, jit.UTIMER, jit.USENT):
            self.set_jword(u, i, 0)
        self.intent[u] = 0
        self._close_all(u)                             # M:XX and the user's DCBs
        self.common[u] = self.jbyte(u, jit.BCP_BYTE)   # the context pages stay (OLAYLIM)
        self.trace(f"M:LDTRC user {u}: {name}.{account}")
        hook = self.hooks.get("LDTRC")
        if hook is None:
            raise NotTranslated(f"M:LDTRC {name}.{account}: T:ASP for this user")
        return ("SE", hook(self, u, name, account, password))

    def _close_all(self, u):
        """LDT0's CLOSE, and CLSDCBS at the step's end (STPNR.txt:1164-:1242): each open
        DCB of the program closed, files saved; M:XX too."""
        mem = self.s.umem[u]
        for address in list(self.dcbs.get(u, {}).values()) + [M_XX]:
            if address in mem and not mem[address] & 0x00200000:
                continue                               # CW,15 Y002: NOT OPEN
            dcb = self.dcb_at(u, address)
            if dcb is not None and dcb.open:
                if getattr(dcb, "cfu", None) is not None and self.fs is not None:
                    self.fs.close(dcb.cfu)
                    dcb.cfu = None
                dcb.open = False

    def _push_environment(self, u, w0, w1):
        """T:UTSXTS  SCHED.txt:1984 - the PSD and registers onto the stack whose pointer
        doubleword J:TCB addresses: 20 words if its top is even, 21 if odd (the PSD
        doubleword-aligned), a 0 or -1 below the PSD, R0 on top. Returns the PSD's address
        in the stack, or None if the stack is bad (CHKPROT: in the monitor's pages, or no
        room; the access codes aren't checked)."""
        mem, regs = self.s.umem[u], self.s.uregs[u]
        spd = self.jword(u, jit.TCB) & 0x1FFFF
        if spd < JOVVPA:
            return None                                # CHKPROT-1: the pointer's page
        top, sp1 = mem.get(spd, 0) & 0xFFFFFFFF, mem.get(spd + 1, 0) & 0xFFFFFFFF
        if ((top + 1) & 0x1FFFF) < JOVVPA:
            return None                                # CHKPROT: the stack's bottom
        n, filler = (21, 0xFFFFFFFF) if top & 1 else (20, 0)
        space, words = (sp1 >> 16) & 0x7FFF, sp1 & 0x7FFF
        if space < n or words + n > 0x7FFF:
            return None                                # MSP: BCS,10 EVIL STACK
        top2 = (top + n) & 0x1FFFF
        if top2 < JOVVPA:
            return None                                # CHKPROT: the stack's top
        mem[spd] = (top & ~0x1FFFF) | top2             # STD,12 *1: the updated pointer
        mem[spd + 1] = (sp1 & 0x80008000) | ((space - n) << 16) | (words + n)
        p = top2 - 18                                  # 2 => PLACE FOR PSD
        mem[p], mem[p + 1] = w0, w1
        mem[p - 1] = filler
        for i in range(16):                            # REGS 0-7, 8-15
            mem[p + 2 + i] = regs[i]
        mem[p + 18] = regs[0]                          # STM,8 with 9: R0 last, on top
        return p

    # --- page calls (MMNR.txt, MM.txt; docs/pages.md) ----------------------------------

    def jbyte(self, u, b):
        """Byte ``b`` of the user's JIT page."""
        return (self.jword(u, b // 4) >> (8 * (3 - b % 4))) & 0xFF

    def set_jbyte(self, u, b, v):
        k = 8 * (3 - b % 4)
        self.set_jword(u, b // 4, (self.jword(u, b // 4) & ~(0xFF << k)) | ((v & 0xFF) << k))

    def _limits(self, u, lower, page):
        """CLM,7 J:xLL: the page within an area's lower and upper limits."""
        return self.jword(u, lower) <= page <= self.jword(u, lower + 1)

    def _area(self, u, page):
        """GVP6/RVP6  MM.txt:780-:792, :963-:976: which page count (JB:PCP + index)."""
        for i, lower in enumerate((jit.PLL, jit.DLL, jit.DDLL, jit.CLL, jit.DCBLL)):
            if self._limits(u, lower, page):
                return i
        if page <= self.jword(u, jit.PUL) or page > self.jword(u, jit.EUP):
            return 3                                   # ASSUME CONTEXT
        return 2                                       # DYNAMIC DATA

    def _count(self, u, page, delta):
        b = jit.PCP_BYTE + self._area(u, page)
        self.set_jbyte(u, b, self.jbyte(u, b) + delta)  # MTB,1 / MTB,-1 JB:PCP,1
        self.s.UB_PCT[u] = max(0, self.s.UB_PCT[u] + delta)   # the user's page count

    def _clean(self, u, page):
        """PAGEZAP (MM.txt:427): the page's words zeroed (here: removed, read as 0)."""
        mem = self.s.umem[u]
        for a in range(page * 512, page * 512 + 512):
            mem.pop(a, None)

    def _gvpi(self, u, page):
        """T:GVPI  MM.txt:540 - the page mapped, if it's free (GVPO otherwise). The size
        limits (T:TOTESZ), the swap granules and the command list, the physical page and
        its chain, and the access codes aren't modeled: a physical page is always there."""
        cmap = self.cmap.setdefault(u, set())
        if page in cmap:
            return False                               # GVPO: not free
        cmap.add(page)                                 # IV10  STORE,3 JX:CMAP,7
        self._count(u, page, +1)
        self._clean(u, page)
        return True

    def _gvpm(self, u, page, gvp):
        """T:GVPM  MMNR.txt:315 - is the page one the call may get? M:GVP: between the
        dynamic data's top and the common's bottom, above the procedure up to J:EUP, or in
        the data. M:GP, M:GCP: in the dynamic data."""
        if gvp:
            if not (self.jbyte(u, jit.TDP_BYTE) <= page <= self.jbyte(u, jit.BCP_BYTE)):
                if not self.jword(u, jit.PUL) < page <= self.jword(u, jit.EUP):
                    if not self._limits(u, jit.DLL, page):
                        if self.s.UH_FLG[u] & SJAC:    # GVP9: a processor's special buffers
                            raise NotTranslated("M:GVP of a special buffer page (GVP9)")
                        return False
        elif not self._limits(u, jit.DDLL, page):      # GVP1
            return False
        return self._gvpi(u, page)

    def _set_cc1(self, u, error):
        """SAD3/SAD4  MMNR.txt:421-:424: CC1 = an error; the other CC bits as they were."""
        s = self.s
        s.psd_cc[u] = (s.psd_cc[u] & ~8) | (8 if error else 0)

    def get_pages(self, step):
        """T:GDP (step 1), T:GCP (-1), T:GVP (0)  MMNR.txt:64-:132 - M:GP, M:GCP: R6 pages
        from JB:TDP up or JB:BCP down, the pointer moved past them; SR1 = the count, SR2 =
        the lowest page's address. M:GVP: the one page of R6's address. CC1 if not all
        were got. A real-time user locked in core (RTCHK) isn't modeled."""
        def routine(self, ctx):
            u = ctx.u
            if step:
                at = jit.TDP_BYTE if step > 0 else jit.BCP_BYTE
                page, n = self.jbyte(u, at), ctx.r6 & 0x1FFFF
            else:
                page, n = (ctx.r6 >> 9) & 0xFF, 1      # SLS,7 -9 / AND,7 M8
            first, got, error = page, 0, False
            for _ in range(n):                         # GAP2
                if not self._gvpm(u, page, step == 0):
                    error = True                       # GAP4
                    break
                page, got = page + step, got + 1       # GAP3
            if step:
                self.set_jbyte(u, at, page)            # STB,7 0,5
                low = first if step > 0 else first - got + 1
                regs = self.s.uregs[u]
                regs[8], regs[9] = got, (low << 9) & 0xFFFFFFFF   # GAP5: SR1, SR2
            self._set_cc1(u, error)
            self.trace(f"M:G{'P' if step > 0 else 'CP' if step else 'VP'} user {u}: {got} of"
                       f" {n} page(s) from X'{first:02X}'")
            return ("TRAPEXIT", None)
            yield
        return routine

    def free_pages(self, step):
        """T:FDP (step -1), T:FCP (1), T:FVP (0)  MMNR.txt:160-:235 - M:FP, M:FCP: R6 pages
        released from the top of the dynamic data down, or the bottom of the common up;
        SR1 = the count. M:FVP: the page of R6's address, not in the procedure or the DCBs
        (SR1 too, through RAP5).
        CC1 if not all were released. SAD and APWP pages (JB:LMAP) aren't modeled."""
        def routine(self, ctx):
            u = ctx.u
            if step:
                at = jit.TDP_BYTE if step < 0 else jit.BCP_BYTE
                page, n = self.jbyte(u, at), ctx.r6 & 0x1FFFF
            else:
                page, n = (ctx.r6 >> 9) & 0x7FFFFF, 1
            released, error = 0, False
            if n:                                      # RAP1
                page = (page + step) & 0xFF
                first = page
                for _ in range(n):                     # RAP2
                    if not self._rvp(u, page, step == 0):
                        error = True                   # RAP4
                        break
                    page, released = page + step, released + 1
                if step:
                    self.set_jbyte(u, at, page - step)  # SW,7 10 / STB,7 0,5
                self.trace(f"M:F{'P' if step < 0 else 'CP' if step else 'VP'} user {u}:"
                           f" {released} of {n} page(s) from X'{first:02X}'")
            self.s.uregs[u][8] = released              # RAP5P1: SR1 (M:FVP's too)
            self._set_cc1(u, error)
            return ("TRAPEXIT", None)
            yield
        return routine

    def _rvp(self, u, page, fvp):
        """RVP0/RVP1 and T:RVPI  MMNR.txt:365-:379, MM.txt:855 - release the page if the
        call may: M:FVP, a user page outside the procedure and the DCBs; M:FP, M:FCP, a
        page in the dynamic data. It must be mapped (RVP3 otherwise)."""
        if fvp:
            if not self._limits(u, jit.BUP, page):
                if self.s.UH_FLG[u] & SJAC:            # RAP9: a special buffer page
                    raise NotTranslated("M:FVP of a special buffer page (RAP9)")
                return False
            if self._limits(u, jit.PLL, page) or self._limits(u, jit.DCBLL, page):
                return False                           # DON'T RELEASE IT
        elif not self._limits(u, jit.DDLL, page):      # RVP1
            return False
        return self._rvpi(u, page)

    def _rvpi(self, u, page):
        """T:RVPI  MM.txt:855 - the page released if it is mapped (RVP3 otherwise). The
        physical page, the swap granule and the access codes aren't modeled."""
        cmap = self.cmap.setdefault(u, set())
        if page not in cmap:
            return False                               # RVP3: not in use
        cmap.discard(page)                             # RVNP  STORE,12 JX:CMAP,7
        self._count(u, page, -1)
        self._clean(u, page)
        return True

    # --- overlays: M:SEGLD (ALTCP.txt MSEGLD, SEGLD.txt; docs/overlays.md) ---------------

    def msegld(self, ctx):
        """MSEGLD  ALTCP.txt:1051 - M:SEGLD: the segment name's address from FPT word 1
        (perhaps indirect, perhaps a register), then SEGLD in MISOV with J:DCBLINK. A
        shared processor's overlays (PB:LNK, T:PROCOV) and RTCHK aren't modeled."""
        u = ctx.u
        sr2 = self.fetch(u, ctx.r7)                    # LW,SR2 0,R7
        if sr2 & INDIRECT:
            sr2 = self.fetch(u, sr2 & 0x1FFFF)         # LW,SR2 *SR2 (a register: J:BASE)
        yield from self.t_overlay(u, MISOVSEG)         # OVERTO MISOVSEG,SEGLD#
        self.trace(f"CAL1,8 user {u}: SEGLD in overlay MISOV")
        return (yield from self.segld(ctx, sr2 & 0x1FFFF))

    def _segld_abort(self, u, code):
        """ABORTIT  SEGLD.txt:502: abort X'B1' with the code as its subcode."""
        self.s.jit[u].ERO = code
        raise CalAbort(0xB1)

    def segld(self, ctx, name_at):
        """SEGLD  SEGLD.txt:62 - load the overlay segment whose TEXTC name is at
        ``name_at``, and every segment on its path to the root not already in memory.
        Tree entry words: 0-2 the name, 3 the flags (bit 0: in memory now, bit 1: was in
        at this call's start) and the parent's link in the right half, 4 the first
        child's link (left) and the next sibling's (right), 5 the data section, 7 the
        procedure. A link is the entry's tree offset less 1; 0 is the root."""
        u = ctx.u
        mem = self.s.umem[u]
        address = self.dcbs.get(u, {}).get("M:SGLD")   # FIND SGLD DCB IN NAME TABLE
        if not address:
            return ("TRAPEXIT", None)                  # MSEGLDEX: back to CAL+1
        dcb = self.dcb_at(u, address)
        if not dcb.open:                               # Y002: OPEN M:SGLD, IN, keyed
            dcb.asn, dcb.org, dcb.fun = 1, 0x20, "IN"  # OPN  :507: X'0F000001', ORG 2, FUN 1
            yield from self.t_overlay(u, OPNSEG)       # OVERLAY OPNSEG,0
            if self._open(u, dcb):
                self._segld_abort(u, 0)                # EREXIT
            yield from self.t_overlay(u, MISOVSEG)
        tree = self.jword(u, jit.TREE) & 0x1FFFF
        end = tree + (mem.get(tree, 0) & 0xFFFFFFFF)   # TREE END+1
        cmap = self.cmap.setdefault(u, set())
        for page in range((end >> 9) & 0xFF, self.jword(u, jit.PLL), -1):
            if page not in cmap:                       # LC JB:LMAP,2: in the user's pages
                self._segld_abort(u, 1)                # BADTREE
        w = lambda e, i: mem.get(e + i, 0) & 0xFFFFFFFF
        count = 0
        for e in range(tree + 1, end, 11):             # MEMLOP: bit 0 to bit 1
            flags = w(e, 3)
            mem[e + 3] = (flags & 0xFFFF) | (0x40000000 if flags & 0x80000000 else 0)
            count += 1
        segs = count                                   # STW,10 *TSTACK: for NXTSEG
        name = self.read_bytes(u, name_at, 0, 1 + self.read_bytes(u, name_at, 0, 1)[0])
        seg = next((e for e in range(tree + 12, end, 11)          # KEYLOOP
                    if self.read_bytes(u, e, 0, len(name)) == name), None)
        if seg is None:
            self._segld_abort(u, 0)                    # EREXIT
        target = seg
        if w(seg, 3) & 0xC0000000:                     # IS REQ SEG IN CORE
            cur, target = seg, None
            while True:                                # NXTBRNCH: mark it, and its first
                mem[cur + 3] = w(cur, 3) | 0xC0000000  # children still in, in
                count -= 1
                if not count:
                    self._segld_abort(u, 2)            # CIRCSEG
                link = w(cur, 4) >> 16                 # FLINK
                if not link:
                    break                              # NONE LEFT: memory as it is
                if link & 0x8000 or tree + link >= end:
                    self._segld_abort(u, 1)            # BADTREE
                child = tree + link + 1
                if w(child, 3) & 0xC0000000:
                    cur = child
                    continue
                back = w(child, 3) & 0xFFFF            # its parent: the last one to stay
                if back & 0x8000 or back >= end:
                    self._segld_abort(u, 1)
                target = tree + back + 1
                break
        ends = {}
        if target is not None:                         # CHKSEG
            for index, lower, code in ((5, jit.DLL, 3), (7, jit.PLL, 4)):
                ends[lower] = self._memset0(u, w(target, index), lower, code)
        cur = seg
        while True:                                    # CHKSEG1
            flags = w(cur, 3)
            mem[cur + 3] = flags | 0x80000000          # IN MEMORY NOW
            if not flags & 0x40000000:                 # not in already: read it
                for kind, index, lower in ((3, 5, jit.DLL), (5, 7, jit.PLL)):
                    self._rdseg(u, dcb, cur, kind, w(cur, index), lower, ends.get(lower))
                self.set_jword(u, jit.ASSIGN, self.jword(u, jit.ASSIGN) & ~0x20000000)
            back = w(cur, 3) & 0xFFFF                  # SEGIN: the parent
            if not back:
                break                                  # the root: done
            cur = tree + 1 + back                      # NXTSEG
            segs -= 1                                  # MTW,-1 *TSTACK
            if segs <= 0:
                self._segld_abort(u, 2)                # CIRCSEG
        self.s.UH_FLG[u] |= PPSWP                      # SET PPSWAP
        text = name[1:].decode(EBCDIC, "replace")
        self.trace(f"SEGLD user {u}: {text}")
        return ("TRAPEXIT", None)

    def _memset0(self, u, word, lower, code):
        """MEMSET0/MEMSET  SEGLD.txt:379-:443 - the area's pages got from its lower limit
        up to the end of the segment's section (``word``: size and bias, doublewords),
        those above it released up to the upper limit. Returns the end page."""
        end = (((word >> 16) + (word & 0xFFFF) - 1) >> 8) & 0xFFFFFF
        lo, hi = self.jword(u, lower), self.jword(u, lower + 1)
        if not lo <= end <= hi:
            self._segld_abort(u, code)                 # BIG: BIGD 3, BIGP 4
        cmap = self.cmap.setdefault(u, set())
        for page in range(lo, end + 1):                # GET: T:GNVPI
            if page not in cmap:
                self._gvpi(u, page)
        for page in range(end + 1, hi + 1):            # RELEASE: T:RVPI
            self._rvpi(u, page)
        return end

    def _rdseg(self, u, dcb, entry, kind, word, lower, end_page):
        """RDSEG  SEGLD.txt:242 - one section of a segment: its record (the key: the name
        and the type byte, 3 data, 5 procedure) read to its address, which must be in its
        area and not past the pages MEMSET got (BADBUF, code 5). A record longer than the
        section is cut (X'07' ignored). No record: paged modules (RD4) aren't modeled, so
        EREXIT. The debugger's replaced instructions (MODLOP) aren't modeled."""
        size = (word >> 13) & 0x7FFF8                  # BYTE COUNT
        if not size:
            return
        address = (word & 0xFFFF) << 1                 # BUF ADDR
        if not self._limits(u, lower, address >> 9):
            self._segld_abort(u, 5)                    # BADBUF
        last = (address + ((size - 1) >> 2)) >> 9
        if end_page is not None and last > end_page:
            self._segld_abort(u, 5)
        self.set_jword(u, jit.ASSIGN, self.jword(u, jit.ASSIGN) | 0x60000000)   # Y6
        n = self.read_bytes(u, entry, 0, 1)[0]
        key = self.read_bytes(u, entry, 1, n) + bytes([kind])
        data = dcb.cfu.file.read(key)
        if data is None:
            self._segld_abort(u, 0)                    # X'43', then EREXIT
        data = bytes(data[:size])
        mem = self.s.umem[u]
        for i in range(0, len(data), 4):
            mem[address + i // 4] = int.from_bytes(data[i:i + 4].ljust(4, b"\0"), "big")
        self.trace(f"SEGLD user {u}: {key[:-1].decode(EBCDIC, 'replace')} type {kind},"
                   f" {len(data)} bytes at X'{address:X}'")

    def t_associate(self, ctx):
        """T:ASSOCIATE / T:DISASSOCIATE  UCAL.txt:644, :794 - M:ASSOC, M:DISASSOC of a
        library or debugger by name. GETNAME (:767): a debugger in control may not (CC1);
        the name (FPT words 1-2) is looked for in P:NAME, and not found is CC1SET. The
        model has no shared processors, so no name is found: always CC1."""
        u = ctx.u
        name = self.read_bytes(u, ctx.r7, 0, 8).decode(EBCDIC, "replace").strip()
        self.trace(f"GETNAME user {u}: {name!r} isn't a processor here (CC1)")
        return ("CC", 8)                               # CC1SET
        yield

    def t_gddl(self, ctx):
        """T:GDDL  UCAL.txt:182-:375 - M:GDDL: SR1 the dynamic data area's first word
        (J:DDLL*512), SR2 its last (J:DDUL*512+511), SR3 the pages the user could still
        get: the least of several limits. Only the one the page calls model is taken
        (GPL257: the area's pages less those got, JB:PCDD); SL:CORE, JB:MNPA/SB:ROMX/
        SB:RBMX, S:PCORE, the FPOOL and COOP reserve and the AJIT page (GPL20-GPL256,
        GPL90) aren't modeled, as the page calls' size limits aren't."""
        u, regs = ctx.u, self.s.uregs[ctx.u]
        lo, hi = self.jword(u, jit.DDLL), self.jword(u, jit.DDUL)
        used = self.jbyte(u, jit.PCP_BYTE + 2)            # JB:PCDD
        regs[8] = (lo << 9) & 0xFFFFFFFF
        regs[9] = ((hi << 9) + 0x1FF) & 0xFFFFFFFF
        regs[10] = max(0, hi - lo + 1 - used)
        return ("TRAPEXIT", None)
        yield

    def t_gl(self, ctx):
        """T:GL  MMNR.txt:240 - M:GL: SR1 = the first word of the common pages got, SR2 =
        the last word of the dynamic data's upper page; with no common pages, both the
        word below the common's bottom."""
        u = ctx.u
        r8 = self.jbyte(u, jit.BCP_BYTE) + 1           # LAST PG OBTAINED
        r9 = (self.jword(u, jit.DDUL) << 9) + 0x1FF
        r8 = (r8 << 9) - 1
        if r8 != r9:
            r8 += 1                                    # RESTORE BOTTOM TO 1ST WD OF PG
        self.s.uregs[u][8], self.s.uregs[u][9] = r8 & 0xFFFFFFFF, r9 & 0xFFFFFFFF
        return ("TRAPEXIT", None)
        yield

    def t_chtbl(self, ctx):
        """T:CHTBL  UCAL.txt:436 - on-line users only (CC1 otherwise). Arming BREAK
        (X'80'), setting a mode (X'20'), resetting the break count (X'10') and changing
        the translation table are accepted without effect here; the terminal status
        (X'40', T:TS) isn't translated."""
        if ctx.u not in self.s.LB_UN:
            return ("CC", 8)                           # CC1SET
        flags = (ctx.r6 >> 16) & 0xFF                  # LH,7 6
        if not flags & 0x80 and flags & 0x40:
            self.t_ts(ctx.u, flags & 0x20)
        return ("CC", 0)                               # CC1RST
        yield

    # COCMINT  COC.txt:4403-:4421: a TTY line's MODE, MODE2, MODE3 after log-on
    COC_MODES = (0x88, 0x20, 0x00)

    def t_ts(self, u, extended):
        """T:TS  UCAL.txt:530 - M:TS: the line's COC bytes into the user's R8-R9 (R10-R11
        too, extended: X'20'), from ADRS (:566-:570): COCTERM, MODE, MODE2, MODE3; CPOS,
        COCOC, BUFCNT, LB:UN; MODE4, CPI, the input flag (COCII); JB:PCW, JB:LPP. The
        modes are COCMINT's (COC keeps no others); COCTERM, MODE4 (MODE4INIT, a SYSGEN
        table) and CPI are 0 here, COCOC and BUFCNT 0 (output isn't queued), and the
        table's dummy entries 0."""
        coc, regs = self.s.coc, self.s.uregs[u]
        number = coc.line_of(u) if coc is not None else None
        line = coc.lines[number] if number is not None else None
        col = line.col if line is not None else 0
        b = [0, *self.COC_MODES, col & 0xFF, 0, 0, u & 0xFF]
        if extended:
            waiting = 1 if line is not None and (line.typed or line.done) else 0
            lpp_word = self.jword(u, 70)               # JB:LPP, JB:LC, JB:PCW, JB:PROMPT
            b += [0, 0, waiting, 0, 0, 0, (lpp_word >> 8) & 0xFF, lpp_word >> 24]
        for i in range(0, len(b), 4):
            regs[8 + i // 4] = int.from_bytes(bytes(b[i:i + 4]), "big")

    def setdcb(self, ctx, dcb):
        """SETDCB  IOD.txt:526 - M:SETDCB: the FPT's error and abnormal addresses into the
        DCB (ERA, ABA), for exits through the DCB (MSR01EXIT, IORT.txt:598-:603)."""
        presence = self.fetch(ctx.u, ctx.r7)
        take = self._params(ctx.u, (self.s.umem[ctx.u].get(ctx.r7 + 1 + i, 0) for i in range(2)))
        if presence & P_ERR:
            dcb.era = take() & 0x1FFFF                 # JHKBIT3 / STS,2 ERA,R6
        if presence & P_ABN:
            dcb.aba = take() & 0x1FFFF                 # JHKBIT / STS,2 ABA,R6
        return ("TRAPEXIT", None)

    def _bad_dcb(self, ctx):
        if ctx.sr1 == 0x2C:                            # M:PC needs no DCB: T:STPMT
            return self.t_stpmt(ctx)
        raise CalAbort(0xAF)                           # ILLEGAL-DCB

    def _online_or_ghost(self, u):
        return u in self.s.LB_UN or u in self.s.SB_GJOBUN   # LC J:JIT / BCS,12

    def cal12(self, ctx):
        """CAL12  CALPROC.txt:307"""
        target = C12.get(ctx.sr1)
        if target is None:
            raise CalAbort(0xAE)
        if target == Res("ENQ"):
            raise CalAbort(0xAE)                       # CHKENQ: QT = 0, no ENQ tables
        return (yield from self.invoke(ctx, target))

    def cal13(self, ctx):
        """CAL13  ALTCP.txt:354 - the debugger overlay, R0 = the code."""
        if ctx.sr1 >= 6:
            raise CalAbort(0xAE)
        return (yield from self.invoke(ctx, Ovl(DEBUGSEG, ctx.sr1)))

    def cal14(self, ctx):
        return (yield from self.code_table(ctx, C14TV))

    def cal15(self, ctx):
        """CAL15  ALTCP.txt:389 - M:EXU, M:MASTER/M:SLAVE, or real-time."""
        if ctx.sr1 == 0x28:
            return (yield from self.invoke(ctx, Res("MEXU")))
        if ctx.sr1 in (SLAVECODE, MASTERCODE):
            return (yield from self.invoke(ctx, Res("MSTRSLV")))
        raise CalAbort(0xAE)                           # RTICBHDR < 0: not real-time

    def cal16(self, ctx):
        """CAL16  ALTCP.txt:494 - privilege X'A0', or TEL in control."""
        if ctx.sr1 >= len(C16TV):
            raise CalAbort(0xAE)
        if self.priv.get(ctx.u, 0) < 0xA0 and not self.s.UH_FLG[ctx.u] & TIC:
            return ("CC", 8)                           # ERCC1
        return (yield from self.invoke(ctx, C16TV[ctx.sr1]))

    def cal17(self, ctx):
        return (yield from self.code_table(ctx, C17TV))

    def cal18(self, ctx):
        return (yield from self.code_table(ctx, C18TV))

    def cal19(self, ctx):
        """CAL1,9  ALTCP.txt:205 - the address field is the exit type."""
        address = ctx.r7 - 1
        presence = address & 0x10000                   # Y0001
        if not presence and address < 16:              # a register address
            t = address
            if t + 1 >= len(C19TV) + 1:
                raise CalAbort(0xAE)
        else:                                          # SCCSTRP / CAL19MOD
            t = address & 0xFF
            if t == 10:
                raise CalAbort(0xAE)                   # M:INTRTN: not real-time
            if t == 0 or (t > 3 and t != 5):
                raise CalAbort(0xAE)
            if presence and t <= 3:
                self.s.jit[ctx.u].STEPCC = (address >> 8) & 0xFF   # JB:STEPCC
        return (yield from self.invoke(ctx, C19TV[t]))

    # --- running a target -------------------------------------------------------------

    def invoke(self, ctx, target):
        """C11TV (CALPROC.txt:243): REMEMBER for a CAL from the monitor, then the routine."""
        if target == BADCAL:
            raise CalAbort(0xAE)
        if target == TRAPEXIT:
            return ("TRAPEXIT", None)
        saved = self.s.UB_OV[ctx.u] if ctx.from_monitor else None
        if isinstance(target, Ovl):
            yield from self.t_overlay(ctx.u, target.seg)
            name = target.entry if isinstance(target.entry, str) else \
                f"{SEGNAMES[target.seg]} entry {target.entry}"
            fn = self.overlaid.get(name)
            where = f"in overlay {SEGNAMES[target.seg]}"
        else:
            name = target.name
            fn = self.resident.get(name)
            where = "(resident)"
        if fn is None:
            raise NotTranslated(f"CAL1,{ctx.n} code X'{ctx.sr1:02X}': {name} {where}")
        self.trace(f"CAL1,{ctx.n} user {ctx.u}: {name} {where}")
        result = yield from fn(self, ctx)
        if saved is not None and self.s.UB_OV[ctx.u] != saved:
            yield from self.t_overlay(ctx.u, saved - OVLY_BASE if saved else None)  # T:REMEMBER
        return result

    def t_overlay(self, u, seg):
        """T:OVERLAY  T$OV.txt:105 - make segment ``seg`` the user's overlay."""
        s = self.s
        p = OVLY_BASE + seg if seg is not None else 0
        if seg is not None and not 0 <= seg < len(SEGNAMES):
            raise NotTranslated(f"SUA X'1D': no overlay {seg}")
        old = s.UB_OV[u]
        if old == p:
            return                                     # OVXIT: already associated
        s.PB_UC[old] = s.PB_UC.get(old, 0) - 1         # NOOV1
        s.UB_OV[u] = p                                 # NOOVA
        if not p:
            return
        s.PB_UC[p] = s.PB_UC.get(p, 0) + 1
        if s.PX_HPP.get(p):
            s.PH_FRQ[p] = s.PH_FRQ.get(p, 0) + 1       # in core: map it (not modeled)
            return
        self.trace(f"T:OVERLAY {SEGNAMES[seg]} for user {u}: not in core, E:AP")
        s.UH_FLG[u] &= ~RTR                            # NOTINCORE
        yield Report(E_AP)                             # T:REG; back when it's in core

    def finish(self, u, result):
        """The CAL's exit: OUT/TRAPEXIT, CALBAD, or a step exit."""
        s = self.s
        kind = result[0] if result else "TRAPEXIT"
        s.S_CLOCK4 = (u, "DELTAT")                     # T:MASTER: back to user time
        if kind in ("TRAPEXIT", "CC"):
            if kind == "CC":                           # OUT  ALTCP.txt:741: mask YE
                s.psd_cc[u] = (s.psd_cc[u] & 1) | (result[1] & 0xE)
            s._send[u] = s.psd_cc[u]
            return s.exit_path(swap=False)             # TRAPEXIT
        if kind == "ABORT":                            # CALBAD  ALTCP.txt:1018
            s.jit[u].ABC = result[1]
            address = self.exit_control(u, 0x01)       # T:ABORTM: RNST 1
            if address is not None:
                kind, result = "XCON", ("XCON", address)
        if kind == "XCON":                             # XCONSETUP: the program goes on there
            s._send[u] = ("ROUTINE", result[1], None, 0)
            return s.exit_path(swap=False)             # SSEMDEST
        if kind == "ABORT":
            self.trace(f"CALBAD user {u}: abort X'{result[1]:02X}' (T:ABORTM)")
            self.ended[u] = ("ABORT", result[1])
            return self._hook("T:ABORTM", u)
        if kind == "IOSPRTN":                          # CALPROC.txt:389
            sr1, sr3 = result[1], result[2]
            if not sr1 or s.jit[u].RNST:               # (any run status taken as EXITBITS)
                s._send[u] = s.psd_cc[u]
                return s.exit_path(swap=False)         # TRAPEXIT
            s.uregs[u][10] = sr3                       # SR3, and the PSD to the routine
            s._send[u] = ("ROUTINE", sr1, sr3)
            return s.exit_path(swap=False)             # T:ACCTOV
        if kind == "SE":                               # the user ended or went elsewhere
            return result[1] if len(result) > 1 else "SE"
        raise ValueError(result)

    def _hook(self, name, u, *args):
        """The step's end: CLOSEDCBS (STPNR.txt:873-:892, CLSDCBS :1164), then the hook."""
        self._close_all(u)
        fn = self.hooks.get(name)
        if fn is not None:
            return fn(self, u, *args)
        return self.s.t_delus(u)

    # --- translated routines -----------------------------------------------------------

    def t_wait(self, ctx):
        """T:WAIT  UCAL.txt:425 - M:WAIT: sleep until the wake-up limit."""
        s, u = self.s, ctx.u
        limit = (ctx.r6 + 1) & 0x1FFFF                 # ROUND UP
        s.U_MISC[u] = limit                            # SAVE WAKE UP LIMIT
        s.after(limit * WAIT_UNIT, E_WU, u)            # (CLOCK4, a stand-in)
        yield Report(E_SL)                             # T:REG with R11 = CC1RST
        return ("CC", 0)

    def mtime(self, ctx):
        """MTIME  TIM.txt:97 - M:TIME: a 4-word text block and, with TMS, SR1-SR3."""
        s, u, d = self.s, ctx.u, self.date
        mo, da, yr = d.get("MO", 1), d.get("DA", 1), d.get("YR", 0)
        hr, mi = d.get("HR", 0), d.get("MI", 0)
        twoms = s.now                                  # 2-ms units since the time was set
        mi_total = hr * 60 + mi + twoms // 30000
        hr, mi = (mi_total // 60) % 24, mi_total % 60
        within = twoms % 30000                         # 2-ms units since the minute
        block = ctx.r6 & 0x1FFFF
        if block:                                      # the four-word block
            text = f"{hr:02d}:{mi:02d} {MONTHS[mo]} {da:02d},'{yr:02d}"
            self.put_text(u, block, text[:16])
        if self.fetch(u, ctx.r7 - 1) & TMS:            # 'TMS': SR1-SR3
            day = da + CALEN[mo]
            if yr % 4 == 0 and mo >= 3:
                day += 1                               # leap year after February
            seconds = within // 500
            regs = s.uregs[u]
            regs[8] = (yr << 16) | day
            regs[9] = (hr << 24) | (mi << 16) | (seconds << 8) | (within % 30)
            regs[10] = within // 30                    # 1/1000 minute since the minute
        return ("TRAPEXIT", None)
        yield

    def t_stpmt(self, ctx):
        """T:STPMT  CALPROC.txt:373 - M:PC: the COC prompt, on-line users only."""
        if ctx.u not in self.s.LB_UN:
            return ("CC", 8)                           # CC1SET
        self.prompt[ctx.u] = ctx.r6 & 0xFF             # JB:PROMPT
        return ("CC", 0)

    def t_clrerr(self, ctx):
        """T:CLRERR  ALTCP.txt:669 - TEL only: clear the run status and abort code."""
        s, u = self.s, ctx.u
        if not s.UH_FLG[u] & TIC:
            return ("CC", 8)
        j = s.jit[u]
        j.RNST = j.ABC = j.ERO = 0
        j.TELFLGS &= ~2
        return ("CC", 0)
        yield

    def exit_cal(self, kind):
        def routine(self, ctx):
            """T:EXIT / T:ERROR / T:ABORT (STPNR.txt:506-549), as hooks."""
            j = self.s.jit[ctx.u]
            if kind == "T:ERROR":
                j.RNST, j.ABC = 0x80, 0xA8
            elif kind == "T:ABORT":
                j.RNST, j.ABC = 0x40, 0xA8
            address = self.exit_control(ctx.u, j.RNST)  # XCONSEE
            if address is not None:
                return ("XCON", address)
            self.ended[ctx.u] = (kind,)
            self.trace(f"{kind} user {ctx.u}")
            return ("SE", self._hook(kind, ctx.u))
            yield
        return routine

    # --- read/write (IORT.txt, WRTD.txt; docs/rdwr.md) ---------------------------------

    def attach_io(self, io, oc):
        """Connect IOQ: the console's DCT index for M:OC, and REQCOM's E:IC reports."""
        self.io = io
        self.monitor_dcbs[M_OC].dct = oc
        io.report_ic = lambda u, dcb: self.s.t_rue(u, E_IC, dcb)    # RC29

    def add_dcb(self, u, name, address, **fields):
        """A user DCB: in the name list (J:DCBLINK) and as an object at its address."""
        self.dcbs.setdefault(u, {})[name] = address
        fields.setdefault("open", fields.get("asn", 3) != 1)   # a file DCB starts closed
        dcb = Dcb(name, fcn=0, address=address, **fields)
        self.dcb_objs.setdefault(u, {})[address] = dcb
        return dcb

    def dcb_at(self, u, address):
        """A DCB: the monitor's, one registered by a stand-in (cpv), or one in the user's
        memory (an interpreted program's: MemDcb, docs/dcb.md)."""
        a = address & 0x1FFFF
        if a == M_UC:
            return self.uc.setdefault(u, Dcb("M:UC", fcn=0, address=M_UC, coc=True))
        dcb = self.monitor_dcbs.get(a) or self.dcb_objs.get(u, {}).get(a)
        if dcb is not None or a < 0x10:
            return dcb
        mem_dcbs = self.mem_dcbs.setdefault(u, {})
        if a not in mem_dcbs:
            w0 = self.s.umem[u].get(a, 0)
            if not w0:
                return None                            # nothing there
            asn = w0 & 0xF
            if asn not in (0, 1, 3):                   # 0: not assigned (yet: a merge, OPEN)
                raise NotTranslated(f"DCB X'{a:X}' in user memory with ASN {asn} (files and devices only)")
            mem_dcbs[a] = MemDcb(self, u, a)
        return mem_dcbs[a]

    def put_text(self, u, address, text, textc=False):
        """Store text in the user's memory in EBCDIC, four characters a word, big-endian
        (TEXTC: the count first). Memory holds 32-bit words only (docs/interpreter.md)."""
        data = text.encode(EBCDIC, errors="replace")
        if textc:
            data = bytes([len(data)]) + data
        data += bytes(-len(data) % 4)
        for i in range(0, len(data), 4):
            self.s.umem[u][address + i // 4] = int.from_bytes(data[i:i + 4], "big")

    def read_bytes(self, u, address, btd, count):
        """Bytes from the user's memory: word ``address`` plus ``btd`` bytes."""
        n = btd + count
        out = b"".join((self.s.umem[u].get(address + i, 0) & 0xFFFFFFFF).to_bytes(4, "big")
                       for i in range((n + 3) // 4))
        return out[btd:n]

    def read_text(self, u, address, btd, count):
        """Text from the user's memory: its bytes as EBCDIC characters."""
        return self.read_bytes(u, address, btd, count).decode(EBCDIC)

    def _params(self, u, words):
        """JHKBIT  IORT.txt:393 - take a parameter word: indirect through memory or a register."""
        def take():
            w = next(words)
            if w & INDIRECT:
                a = w & 0x1FFFF
                return self.s.uregs[u][a] if not a & 0x1FFF0 else self.s.umem[u].get(a, 0)
            return w
        return take

    def t_amrdwt(self, ctx, dcb, code):
        """T:AMRDWT  STPNR.txt:3628-:3700 - CAL1,1 X'2D' reads the user's assign/merge
        record into the FPT's buffer, X'2E' writes it. The fast path first takes the
        FPT's ERR and ABN into the JIT, its buffer and size (IORT.txt:345-:366); errors
        leave through MSR01EXIT, with the DCB's own routines. The size must be 1 to 2048
        bytes (BUFCHK, X'4A'). With no record (J:AMR 0) a read is the end of file, X'06'.
        Only a command processor or the step may write (FLAGCHK; NOWRITE, X'14'). The
        record is assign.py's, made from the user's sets, not a granule on disc."""
        from . import assign
        u, j = ctx.u, self.s.jit[ctx.u]
        presence = self.fetch(u, ctx.r7)
        take = self._params(u, (self.s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(4)))
        given = {}
        for bit, name in ((P_ERR, "ERR"), (P_ABN, "ABN"), (P_BUF, "BUF"), (P_SIZE, "SIZE")):
            if presence & bit:
                given[name] = take()
        if "ERR" in given:
            j.ERO = given["ERR"] & 0x1FFFF              # STS,2 ERO+J:JIT
        if "ABN" in given:
            j.ABO = given["ABN"] & 0x1FFFF
        buf = given.get("BUF", dcb.buf) & 0x1FFFF
        size = given.get("SIZE", 0) & 0xFFFF
        if not 0 < size <= 2048:
            return self.msr012(ctx, dcb, 0x4A, own=True)   # BUFERR
        if u not in self.amr:
            if code == 0x2D:
                return self.msr012(ctx, dcb, 0x06, own=True)   # SEND EOF
        if code == 0x2E:
            if not self.s.UH_FLG[u] & TIC:
                return self.msr012(ctx, dcb, 0x14, own=True)   # NOWRITE
            mem = self.s.umem[u]
            assign.store(self, u, [mem.get(buf + i, 0) & 0xFFFFFFFF for i in range(size // 4)])
            self.trace(f"T:AMRDWT user {u}: the assign/merge record written")
            return self.pullallexit(ctx, 0, 0)
        words = assign.record(self, u)
        n = min(len(words), size // 4)
        for i in range(n):
            self.s.umem[u][buf + i] = words[i]
        dcb.ars = 4 * n
        self.trace(f"T:AMRDWT user {u}: the assign/merge record read, {n} words")
        return self.pullallexit(ctx, 0, 0)

    def cal11n7(self, ctx, dcb, write):
        """CAL11N7  IORT.txt:209 - the fast CAL path for READ and WRITE."""
        presence = self.fetch(ctx.u, ctx.r7)           # FPT word 1
        words = (self.s.umem[ctx.u].get(ctx.r7 + 1 + i, 0) for i in range(16))
        if not dcb.open:                               # MSRRDWTA: A DEFAULT OPN
            if dcb.asn == 3:                           # a device: msrrdwt1 opens it
                return (yield from self.msrrdwt1(ctx, dcb, presence, words,
                                                 "write" if write else "read"))
            if dcb.asn != 1:
                raise NotTranslated(f"default OPEN of a DCB with ASN {dcb.asn}")
            if self.fs is None:
                raise NotTranslated("default OPEN: no file system attached")
            yield from self.t_overlay(ctx.u, OPNSEG)   # OVERTO OPNSEG,0
            code = self._open(ctx.u, dcb)
            if code:                                   # 46 FOR READ OR 47 FOR WRITE,
                self.s.jit[ctx.u].ERO = 0              # OPEN's code as the subcode
                return self.msr012(ctx, dcb, 0x47 if write else 0x46, sub=code)
        return (yield from self.msrrdwt1(ctx, dcb, presence, words,
                                         "write" if write else "read"))

    def msrrdwt1(self, ctx, dcb, presence, words, write):
        """MSRRDWT1  IORT.txt:305 - decode the parameters, then dispatch by ASN.
        ``write`` is True/'write', False/'read', or 'delete' (M:DELREC)."""
        op = write if isinstance(write, str) else ("write" if write else "read")
        write = op == "write"
        u, j, take = ctx.u, self.s.jit[ctx.u], self._params(ctx.u, words)
        if isinstance(dcb, MemDcb) and dcb.asn == 3 and not dcb.open:
            yield from self.t_overlay(u, OPNSEG)       # MSRRDWTA: A DEFAULT OPN
            code = self._open_device(u, dcb)
            if code:
                return self.msr012(ctx, dcb, *code)
        if presence & P_ERR:
            j.ERO = take() & 0x1FFFF                   # ERROR ADDRESS
        if presence & P_ABN:
            j.ABO = take() & 0x1FFFF                   # ABNORMAL ADDRESS
        if presence & P_BUF:
            dcb.buf = take() & 0x1FFFF                 # BUFFER ADDRESS
        dcb.rws = take() & 0xFFFF if presence & P_SIZE else dcb.rsz   # BUFFER SIZE
        if dcb.asn == 1:                               # JFILE  IORT.txt:413
            dcb.kad = take() & 0x1FFFF if presence & P_KEY else 0    # KEY ADDRESS
            if presence & P_BTD:
                dcb.btd = take() & 3
            if presence & P_ECB:
                raise NotTranslated("read/write with an ECB (ECBINIT)")
            dcb.wat = bool(presence & F_WAIT)
            dcb.nwk, dcb.onwk = bool(presence & F_NWK), bool(presence & F_ONWK)
            if op == "read":
                return self.isequb(ctx, dcb)
            if op == "delete":
                return self.delrec(ctx, dcb)
            return self.iosfile(ctx, dcb)
        if dcb.asn != 3:
            raise NotTranslated(f"read/write on ASN {dcb.asn} (labeled tape, journal)")
        if presence & P_KEY:
            take()                                     # DEV:ASN: SKIP P5
        if presence & P_BTD:
            dcb.btd = take() & 3                       # BYTE DISPLACEMENT
        if presence & P_ECB:
            raise NotTranslated("read/write with an ECB (ECBINIT)")
        dcb.wat = bool(presence & F_WAIT)              # WAT (bit position assumed)
        # The buffer check (JOSZE2, X'4A') needs the user's access codes: not modeled.
        if getattr(dcb, "device", None) in ("CR", "CP"):
            return (yield from self.card_io(ctx, dcb, write))   # (the handlers: cards.py)
        if dcb.coc and self.s.coc is not None:
            return (yield from self.cocio(ctx, dcb, write))   # QUEUE: COCIO
        if not write:
            raise NotTranslated("device read (MSRRED / MSROTHR)")
        return (yield from self.msrwrt(ctx, dcb))

    def card_io(self, ctx, dcb, write):
        """A read from the card reader or a write to the punch, at once (a stand-in for
        the queued I/O and the handlers). An empty hopper is end of file, X'06'."""
        u, device = ctx.u, dcb.device
        self.s.jit[u].CTIME += self.s.L.SL_IOTA        # DING
        if write != (device == "CP"):
            raise NotTranslated(f"{'write to the card reader' if write else 'read from the punch'}")
        medium = self.unit_record.media[device]
        if write:
            data = self.read_bytes(u, dcb.buf, dcb.btd, min(dcb.rws, 80))
            medium.punch(data)
            dcb.ars = len(data)
        else:
            card = medium.next()
            if card is None:
                self.trace(f"card reader user {u}: hopper empty")
                return self.msr012(ctx, dcb, 0x06)     # end of file: abnormal
            data = card[:dcb.rws]
            self.write_bytes(u, dcb.buf, dcb.btd, data)
            dcb.ars = len(data)
        dcb.tyc, dcb.last = 1, "write" if write else "read"
        return self.pullallexit(ctx, 0, 0)
        yield

    def cocio(self, ctx, dcb, write):
        """COCIO  COC.txt:3832 - a terminal read or write, for the user's line: COCRD
        (:2272) waits in terminal input (E:CRD) until E:CIC, then moves the line into
        the buffer (COCMU); COCWR (:2851). TYC 1, the ARS, the function count. A BREAK
        during the read ends the program (online.py), so CC2 isn't set here."""
        s, u = self.s, ctx.u
        line = s.coc.line_of(u)
        if line is None:
            raise NotTranslated("terminal I/O with no line (a batch or ghost user's M:UC)")
        s.jit[u].CTIME += s.L.SL_IOTA                  # DING
        if write:
            data = self.read_bytes(u, dcb.buf, dcb.btd, dcb.rws)
            dcb.ars = len(data)
            kept = data.rstrip(b"\x40")                # COCWR5: trailing blanks aren't sent,
            if len(data) - len(kept) > 3:              # if more than 3 (COCWR8)
                data = kept or b"\x40"                 # ALL BLANKS, SEND 1
            w0 = self.fetch(u, dcb.address) if isinstance(dcb, MemDcb) else 0
            before = 0                                 # COCWR38: the spacing less 1 (single)
            if w0 & 0x10100 and data:                  # COCWR30: VFC (X'100') or TOF
                if w0 & 0x10000:
                    self.s.umem[u][dcb.address] = w0 & ~0x10000   # TURN OFF TOF BIT
                # X'C1'-X'CF': that many new lines; X'F1', top of form: here one; any
                # other first character: none, and it's still not sent (COCWR30, COCWR70)
                before = data[0] - 0xC0 if 0xC1 <= data[0] <= 0xCF else 1 if data[0] == 0xF1 else 0
                data = data[1:]                        # COCWR70: the control isn't sent
            after = dcb.address != M_UC and not (data and data[-1] in NOCR)   # COCWR80
            if dcb.rws:                                # MSRWRT: a count of 0 is MSREXIT
                s.coc.write(line, ttyout(data), before, after)   # TTYOUT (WRTD.txt:148-:150)
        else:
            prompt = bytes([self.prompt[u]]).decode(EBCDIC) if self.prompt.get(u) else ""
            while (text := s.coc.read(line, prompt)) is None:
                yield Report(E_CRD)                    # STCRD: blocked in terminal input
            # TTYIN; MUCRLFNL (:2770): the activation character ends the record, counted
            # in the ARS. CR, LF and CR LF all end a line here: X'15', the NL (an assumption
            # for CR and LF, which TEL's EOM in J:CCBUF agrees with)
            data = (text.encode(EBCDIC, errors="replace") + b"\x15")[:min(dcb.rws, 140)]
            self.write_bytes(u, dcb.buf, dcb.btd, data)   # COCMU
            dcb.ars = len(data)
        dcb.tyc, dcb.last = 1, "write" if write else "read"
        self._mirror(u, dcb)
        return self.pullallexit(ctx, 0, 0)

    def _mirror(self, u, dcb):
        """M:UC is in the JIT page, where a program reads its fields (EDIT: the ARS after
        a read), but the monitor keeps it as a Dcb object: its ARS and TYC are written to
        its words too, when the user has the page (a program from FETCH)."""
        if isinstance(dcb, MemDcb) or dcb.address != M_UC or not self.jword(u, jit.M_UC):
            return
        mem = self.s.umem[u]
        for name in ("ars", "tyc"):
            w, sh, m = DCB_FIELDS[name]
            a = dcb.address + w
            mem[a] = (mem.get(a, 0) & ~(m << sh) & 0xFFFFFFFF) | ((getattr(dcb, name) & m) << sh)

    def msrwrt(self, ctx, dcb):
        """MSRWRT  WRTD.txt:140 - device write, by the device's attributes."""
        if dcb.rws == 0:
            return (yield from self.msrexit(ctx, dcb))  # zero BLK: nothing to do
        if dcb.stream:
            raise NotTranslated("write to a symbiont stream (COOP)")
        if dcb.coc:
            raise NotTranslated("write to a terminal DCB (QUEUE: COCIO)")
        if not dcb.dtype:
            return (yield from self.msrexit(ctx, dcb))  # 'NO' device: a no-op
        if dcb.dtype == "TY":
            return (yield from self.msrtype(ctx, dcb))
        raise NotTranslated(f"write to a {dcb.dtype} device (MSRLP, MSRTAPE, MSROTHR)")

    def msrtype(self, ctx, dcb):
        """MSRTYPE  WRTD.txt:713 - NL, the user's ID, tabs if a program runs, the record."""
        s, u = self.s, ctx.u
        line = "\n"                                    # X'15'
        sysid = u & 0xFFFF                             # J:JIT's ID (assumed: the user number)
        if sysid:
            line += f"{sysid:X}: "
            if not s.UH_FLG[u] & TIC:                  # (and the processor isn't LOGON)
                line += "\x05\x05"                     # TAB IT OUT
        line += self.read_text(u, dcb.buf, dcb.btd, dcb.rws)
        dcb.qbuf, dcb.mbg = line[:136], True           # RECTRAN, 136 at most; QBUF
        yield from self.ioqueue(ctx, dcb, write=True)  # IOCONT (unmapped for M:OC)
        dcb.wat = False                                # BUFX: CLEAR WAIT BIT
        return (yield from self.msrexit(ctx, dcb))

    def ioqueue(self, ctx, dcb, write):
        """IOQUEUE / IOQUEUE1  IORT.txt:1407 - an earlier error, count it, COOP, QUEUE."""
        s, u = self.s, ctx.u
        if dcb.fcn == 0 and not dcb.egv and dcb.tyc >= 8 and dcb.tyc != 0xB:
            j = s.jit[u]                               # IOQUEUE4
            if u not in s.SB_GJOBUN:
                j.RNST = 0x02                          # DONT ABORT GHOSTS
            j.ABC = CODE.get(dcb.tyc, 0)
        dcb.fcn += 1                                   # MTB,1 *R6,R1
        # COOP: a device DCB without a stream goes straight to QUEUE.
        if self.io is None:
            raise NotTranslated("QUEUE: no I/O system attached")
        yield from self.frontend(u)                    # QUEUE's FRONTEND
        func = TYCOR[4 if write else 0]                # TYPCOR for a typewriter
        self.trace(f"QUEUE user {u}: {dcb.name} {'write' if write else 'read'} {dcb.qbuf!r}")
        self.io.queue(dcb, func, dcb.qbuf, user=u, priority=s.UB_PRIO[u], write=write)

    def frontend(self, u):
        """FRONTEND  IOQ.txt:183 - the ding, and the limit on I/O outstanding."""
        s = self.s
        s.jit[u].CTIME += s.L.SL_IOTA                  # DING
        if u not in s.SB_GJOBUN:                       # ghosts have no limit
            limit = s.L.SL_OXMF if u in s.LB_UN else s.L.SL_BXMF
            while s.UB_MF[u] >= limit:
                yield Report(E_IP)                     # I/O PERMISSION REQUEST: SIOMF
        s.UB_MF[u] += 1                                # SKIPREG

    def msrexit(self, ctx, dcb):
        """MSREXIT / CHKWAT  IORT.txt:831 - wait if there is an error or abnormal
        address, or the WAIT flag; then check the completion type."""
        j = self.s.jit[ctx.u]
        if not ((j.ERO | j.ABO) & 0x1FFFF or dcb.wat):
            return self.pullallexit(ctx, 0, 0)         # MSRWRTX
        return (yield from self.iochek1(ctx, dcb))

    def iochek1(self, ctx, dcb):
        """IOCHEK1 / IOSPIN / CKEGV  IORT.txt:846, :1201"""
        s, u = self.s, ctx.u
        while dcb.fcn & 0x7F:                          # IOSPIN
            yield Report(E_IIP, dcb)                   # XPSD REGIPSD: T:IOREG
            if s.UB_MF[u] == 0:
                break
        if dcb.egv:
            return self.pullallexit(ctx, 0, 0)         # TYC HAS BEEN CHKD
        dcb.egv = True
        code = CODE.get(dcb.tyc, 0)
        if not code:
            return self.pullallexit(ctx, 0, 0)
        return self.msr012(ctx, dcb, code)

    def msr012(self, ctx, dcb, code, sub=0, own=False):
        """MSR012 / MERC  IORT.txt:896, :1557 - to the user's routine, or the run status.
        The routine is the JIT's ERO or ABO (IOCHEK3, :893); own=True takes the DCB's
        own ERA or ABA instead, as MSR01EXIT does (:598-:603) for OPEN (OBSE.txt:87)."""
        j = self.s.jit[ctx.u]
        error = bool(code & 0xC0)
        sr3 = (code << 24) | (dcb.address & 0x1FFFF)
        if own:
            routine = getattr(dcb, "era" if error else "aba", 0) & 0x1FFFF
        else:
            routine = (j.ERO if error else j.ABO) & 0x1FFFF
        self.trace(f"{'error' if error else 'abnormal'} X'{code:02X}'"
                   + (f"-{sub:02X}" if sub else "") + f" on {dcb.name}"
                   + (f": routine X'{routine:X}'" if routine else ""))
        if not routine and error:                      # MERC
            j.ABC = code
            j.RNST = 0x01 if code & 0x80 else 0x02     # I/O ERROR
            name = next((n for n, a in self.dcbs.get(ctx.u, {}).items()
                         if a == getattr(dcb, "address", None)), dcb.name)
            self.step_error[ctx.u] = (code, sub, name)       # for TEL's report (online.py)
        return self.pullallexit(ctx, routine, sr3)

    def pullallexit(self, ctx, sr1, sr3):
        """PULLALLEXIT  IORT.txt:971 - clear the error and abnormal addresses, IOSPRTN."""
        j = self.s.jit[ctx.u]
        if j.ERO & 0x1FF80:
            j.ERO = 0                                  # (a small value is a code: kept)
        j.ABO = 0
        return ("IOSPRTN", sr1, sr3)

    def iochek(self, ctx, dcb):
        """IOCHEK  IORT.txt:1094 - M:CHECK: wait for the DCB's I/O, check the TYC."""
        if dcb is None or not dcb.open:
            return self.pullallexit(ctx, 0, 0)
        presence = self.fetch(ctx.u, ctx.r7)
        words = (self.s.umem[ctx.u].get(ctx.r7 + 1 + i, 0) for i in range(4))
        take, j = self._params(ctx.u, words), self.s.jit[ctx.u]
        if presence & P_ERR:
            j.ERO = take() & 0x1FFFF
        if presence & P_ABN:
            j.ABO = take() & 0x1FFFF
        if presence & P_BUF:                           # (the third bit here is the ECB)
            raise NotTranslated("M:CHECK with an ECB (ECBCHCK1)")
        return (yield from self.iochek1(ctx, dcb))

    def msrkey(self, ctx):
        """MSRKEYIN  UCAL.txt:1157 - M:KEYIN: type a message on the console and read the
        operator's reply into the user's buffer (byte 0: the length, then the text)."""
        s, u = self.s, ctx.u
        presence = self.fetch(u, ctx.r7)               # FPT word 1
        oc_only = bool(presence & 0x10)                # OCONLY FLAG
        yield from self.msrtypr(replace(ctx, sr1=0 if oc_only else 2))   # MSROCTY / MSRTYPR
        take = self._params(u, (s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(4)))
        take()                                         # the message (CHKBIT1)
        buf = take() & 0x1FFFF if presence & 0x40000000 else 0
        size = take() & 0xFFFF if presence & 0x20000000 else 60   # USE DEFAULT FOR LIMIT
        if presence & 0x10000000:
            raise NotTranslated("M:KEYIN with an ECB")
        if u in s.LB_UN and not oc_only and s.coc is not None:   # the reply from M:UC
            uc = self.dcb_at(u, M_UC)
            saved = uc.buf, uc.btd, uc.rws
            uc.buf, uc.btd, uc.rws = buf or KEYBUF, 1, size - 1   # after the count byte
            try:
                yield from self.cocio(ctx, uc, write=False)
                reply = self.read_text(u, uc.buf, 1, uc.ars)
            finally:
                uc.buf, uc.btd, uc.rws = saved                    # RESTORE BTD
            if buf:
                self.write_bytes(u, buf, 0, bytes([len(reply)]))
            self.trace(f"M:KEYIN user {u}: reply {reply!r} (terminal)")
            return self.pullallexit(ctx, 0, 0)
        oc = self.monitor_dcbs[M_OC]                   # a copy of M:OC on the user's stack
        dcb = Dcb("M:OC", fcn=1, address=M_OC, dct=oc.dct, dtype="TY", btd=1, rws=size)
        console = self.io.m.console if self.io else None
        if console is not None and not console.interactive and console.at_end():
            reply = ""                                 # end of the console script: as a timeout
            self.trace(f"M:KEYIN user {u}: no more console input, empty reply")
        else:
            yield from self.frontend(u)                # QUEUE's FRONTEND
            req = self.io.queue(dcb, TYCOR[0], "", count=size, user=u,
                                priority=s.UB_PRIO[u], write=False)   # a read with editing
            while dcb.fcn & 0x7F:                      # IOSPIN
                yield Report(E_IIP, dcb)
                if s.UB_MF[u] == 0:
                    break
            reply = (req.buffer if req is not None else "").rstrip("\n")
        reply = reply[:size - 1]
        if buf:
            self.write_bytes(u, buf, 0, bytes([len(reply)]) + reply.encode(EBCDIC, errors="replace"))
        self.trace(f"M:KEYIN user {u}: reply {reply!r}")
        return self.pullallexit(ctx, 0, 0)             # DESTRUCT MSRWRTX

    def msrtypr(self, ctx):
        """MSRTYPR / MSROCTY  WRTD.txt - M:PRINT (1), M:TYPE (2), M:MESSAGE (0)."""
        s, u = self.s, ctx.u
        if ctx.sr1 == 1:                               # PRINT: the user's M:LL, or nothing
            address = self.dcbs.get(u, {}).get("M:LL")
            if address is None:
                return ("TRAPEXIT", None)              # NO M:LL :=> NOP
            dcb = self.dcb_at(u, address)
        elif ctx.sr1 == 2 and u in s.LB_UN:
            dcb = self.dcb_at(u, M_UC)                 # TYPE, on-line: M:UC
        else:
            dcb = self.monitor_dcbs[M_OC]              # MESSAGE, or TYPE for batch/ghost
        take = self._params(u, (self.s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(2)))
        message = take() & 0x1FFFF                     # CHKBIT1: the TEXTC
        size = self.read_bytes(u, message, 0, 1)[0]        # LB,D2 *D1
        saved, dcb.btd = dcb.btd, 1                    # skip the count byte
        try:
            return (yield from self.msrrdwt1(ctx, dcb, P_BUF | P_SIZE,
                                             iter([message, size]), write=True))
        finally:
            dcb.btd = saved                            # RESTORE BTD

    # --- files (OPEN, CLOSE, keyed READ/WRITE/DELETE; docs/files.md) ---------------------

    def _open(self, u, dcb):
        """OPNF: open the DCB's file (its name and account VLPs). Returns 0 or the code."""
        from .files import FileError
        from .files import ConsecutiveFile, Opener, Position, RandomFile, account_key
        who = Opener(self.account.get(u, ":SYS"), self.priv.get(u, 0), self.running.get(u))
        if not dcb.account:
            dcb.account = who.account                  # CHKFLACN: the user's own account
            if isinstance(dcb, MemDcb):                # J:ACCN into the DCB's account VLP
                dcb.put_vlp_words(0x02, jit.text_words(who.account.encode(EBCDIC), 2))
        dcb.usr = account_key(dcb.account) != account_key(who.account)   # USR X'4000'
        try:
            cfu = self.fs.open(dcb.fname, dcb.account, dcb.fun, dcb.keym,
                               org={0x30: 3, 0x20: 2}.get(dcb.org & 0x30, 1), size=dcb.rstore,
                               who=who, password=dcb.prot.get(0x03), prot=dcb.prot)
        except FileError as e:
            self.trace(f"OPEN {dcb.fname}.{dcb.account} {dcb.fun}: X'{e.code:02X}' ({e})")
            return e.code
        dcb.cfu, dcb.open, dcb.kbuf = cfu, True, None
        dcb.special = self.fs.access == "special"      # SEC97: X'100'
        # An existing file keeps its organization (OPNF reads the X'09' VLP); the DCB
        # follows it. Whether OPEN overrides the DCB's ORG this way wasn't traced.
        if isinstance(cfu.file, ConsecutiveFile):
            dcb.cpos = Position()
            if dcb.org & 0x20:
                dcb.org = 0
        elif isinstance(cfu.file, RandomFile):
            dcb.org, dcb.rgran = 0x30, 0
        else:
            dcb.org = 0x20
        return 0

    def file_open(self, ctx):
        """M:OPEN (CAL1,1 X'14', overlay OPEN entry 0)."""
        u, dcb = ctx.u, self.dcb_at(ctx.u, ctx.r6)
        fpt_asn = self.fetch(u, ctx.r7) & 7            # CHKASN: FPT:ASN, else DCB:ASN
        if dcb is not None and fpt_asn and fpt_asn != dcb.asn:
            self.trace(f"OPEN {dcb.name} user {u}: ASN {dcb.asn} -> {fpt_asn} (the FPT's)")
            dcb.asn = fpt_asn                          # MSROPN09  OPN.txt:283-:289
        if dcb is not None and dcb.asn == 3:
            return (yield from self.device_open(ctx, dcb))
        if dcb is not None and dcb.asn == 0:
            return self.msr012(ctx, dcb, 0x01, own=True)   # OPENER01: BAD ASN, NOT SET
        if self.fs is None:
            raise NotTranslated("M:OPEN: no file system attached")
        params, j = self._open_params(ctx, dcb), self.s.jit[u]
        if isinstance(dcb, MemDcb) and not dcb.open:
            self._merge_open(ctx, dcb, params)
        if not dcb.open:
            code = self._open(u, dcb)
            if code:
                return self.msr012(ctx, dcb, code, own=True)  # X'03': no such file (abnormal)
        return self.pullallexit(ctx, 0, 0)
        yield

    # MSROPN's FPT parameters, by presence bit from bit 0 (OPN.txt:109-:146)
    OPEN_PARAMS = ("ERR", "ABN", "BUF", "RSZ", "NRA", "ORG", "ACS", "FUN", "GEN", "FOPT",
                   "USELB", "TLB", "KEYM", "DEVOPT", "BTD")

    def _fpt_layout(self, u, r7):
        """MSROPN  OPN.txt:107-:114, :258-:270 - an OPEN FPT's flags word (word 1), the
        address of its presence bits, and whether VLPs follow the parameters. The "A"
        form (X'2000', as TEL's assign/merge sets are built) has the presence bits in
        the next word and VLPs if X'4000' is set; the standard form has them in word 1
        and VLPs if its low 10 bits aren't 0."""
        flags = self.fetch(u, r7)
        if flags & 0x2000:                             # CI,4 X'22000' / AI,7 1: NON-STANDARD
            return flags, r7 + 1, bool(flags & 0x4000)
        return flags, r7, bool(flags & 0x3FF)

    def _open_params(self, ctx, dcb):
        """MSROPN's FPT parameters, by presence bit (OPN.txt:109-:146): {name: value}.
        The error and abnormal addresses go into the JIT and the DCB (ERA, ABA)."""
        u, j = ctx.u, self.s.jit[ctx.u]
        _, at, _ = self._fpt_layout(u, ctx.r7)
        presence = self.fetch(u, at)
        take = self._params(u, (self.s.umem[u].get(at + 1 + i, 0) for i in range(22)))
        params = {}
        for i, name in enumerate(self.OPEN_PARAMS):
            if presence & (0x80000000 >> i):
                params[name] = take()
        if "ERR" in params:
            j.ERO = params["ERR"] & 0x1FFFF
            if dcb is not None:
                dcb.era = j.ERO                        # STS,D1 ERA,R6  (OPN.txt:111)
        if "ABN" in params:
            j.ABO = params["ABN"] & 0x1FFFF
            if dcb is not None:
                dcb.aba = j.ABO                        # STS,D1 ABA,R6  (:113)
        return params

    def _merge_open(self, ctx, dcb, params):
        """MSROPN for a file DCB in memory: the organization (MSROPN51, :671), function
        (SETFUNC), key length (BAKEYM) and buffer; then the FPT's VLPs, which follow
        its parameters when its flags' low 10 bits are set (:261-:268), merged into the
        DCB's own: each code the DCB has a slot for, as many words as the slot holds
        (MSROPN10-MSROPN98B, :300-:351); a code with no slot is skipped (MSROPN99A)."""
        u = ctx.u
        if "ORG" in params:
            dcb.org = (params["ORG"] << 4) & 0x30      # 1 consecutive, 2 keyed, 3 random
        if "FUN" in params and params["FUN"] & 0xF in FUNCTIONS:
            dcb.fun = FUNCTIONS[params["FUN"] & 0xF]
        if "KEYM" in params:
            dcb.keym = params["KEYM"] & 0xFF
        if "BUF" in params:
            dcb.buf = params["BUF"] & 0x1FFFF
        if "RSZ" in params:
            dcb.rsz = params["RSZ"] & 0x7FFF
        _, at, vlps = self._fpt_layout(u, ctx.r7)
        if not vlps or not dcb.flp:
            return
        presence = self.fetch(u, at)
        a = at + 1 + bin(presence >> 10).count("1")    # the VLPs follow the parameters
        for code, words in vlps_at(self.s.umem[u], a).items():
            dcb.set_vlp(code, words)

    def step_merge(self, u, address, plist):
        """ASM8  STPNR.txt:2719-:2737 - an assign/merge set's OPEN parameter list merged
        into the program's DCB at ``address`` through MSROPN. The list goes in the
        assign/merge window (J:ABUF, SBUF2VPA) with the DCB in word 0. It is in the "A"
        form without X'1000', so MSROPN merges and returns without opening (MSROPN7,
        MSROPN7P: OPNPXIT, OPN.txt:388-:403): the program's own M:OPEN opens the DCB.
        A device option (MSROPN5, :689) puts the operational label in the DSI as a name."""
        from types import SimpleNamespace
        mem = self.s.umem[u]
        for i, w in enumerate(plist):
            mem[AMBUF + i] = w & 0xFFFFFFFF
        mem[AMBUF] = (mem[AMBUF] & 0xFF000000) | address   # STS,12 0,6: DCB ADR INTO PLIST
        ctx = SimpleNamespace(u=u, r6=address, r7=AMBUF + 1, sr1=0)
        dcb = self.dcb_at(u, address)
        if dcb.open or not isinstance(dcb, MemDcb):
            return
        fpt_asn = self.fetch(u, ctx.r7) & 7            # CHKASN
        if fpt_asn:
            dcb.asn = fpt_asn                          # MSROPN09
        params = self._open_params(ctx, dcb)
        if "DEVOPT" in params:                         # MSROPN5: AI,D1 X'10000', a name
            label = params["DEVOPT"] & 0xFFFF
            w1 = self.fetch(u, address + 1)
            mem[address + 1] = (w1 & ~0x1FFFF) | 0x10000 | label
            dcb.asn = 3
            return
        self._merge_open(ctx, dcb, params)

    def device_open(self, ctx, dcb):
        """M:OPEN of a device DCB: MSROPN's parameters into the DCB (the error and
        abnormal addresses, buffer, record size, device option, byte displacement),
        then OPENDEV (devopen.py). A DCB that is open already: X'2E' (OPN.txt:91-:94)."""
        u, params = ctx.u, self._open_params(ctx, dcb)
        if dcb.open:
            return self.msr012(ctx, dcb, 0x2E, own=True)   # OPEN AN OPEN DCB
        if "BUF" in params:
            dcb.buf = params["BUF"] & 0x1FFFF
        if "RSZ" in params:
            dcb.rsz = params["RSZ"] & 0xFFFF
        if "BTD" in params:
            dcb.btd = params["BTD"] & 3
        code = self._open_device(u, dcb, params.get("DEVOPT"))
        if code:
            return self.msr012(ctx, dcb, *code, own=True)
        return self.pullallexit(ctx, 0, 0)
        yield

    def _open_device(self, u, dcb, option=None):
        """OPENDEV: the device, then the DCB open (SETOPN). Returns 0 or (code, sub)."""
        from . import devopen
        try:
            device = devopen.resolve(self.s, u, self.fetch(u, dcb.address + 1), option)
        except devopen.OpenError as e:
            self.trace(f"OPEN {dcb.name} user {u}: device error {e}")
            return (e.code, e.sub)
        dcb.device, dcb.coc, dcb.dtype = device, device == "ME", "TY" if device == "TY" else ""
        dcb.open, dcb.tyc = True, 0
        self.trace(f"OPEN {dcb.name} user {u}: device {device}")
        return 0

    def file_close(self, ctx):
        """M:CLOSE (CAL1,1 X'15', overlay CLOSE entry 2): CLSFIL. The first parameter,
        if present (CHKBIT1), is the disposition: 1 REL (delete the file), 2 SAVE."""
        dcb = self.dcb_at(ctx.u, ctx.r6)
        code = 0
        if self.fetch(ctx.u, ctx.r7) & 0x80000000:
            code = self._params(ctx.u, iter([self.fetch(ctx.u, ctx.r7 + 1)]))()
        release = bool(code & 1)                       # CI,SR1 K1: RELEASE
        if dcb.fun == "IN" and self.priv.get(ctx.u, 0) < 0xC0 and dcb.usr:
            release = False                            # ONLY C0 DELETES OTHERS (CLSFIL2M)
        if dcb.open and dcb.cfu is not None:
            self.fs.close(dcb.cfu, release=release)
        dcb.open, dcb.cfu = False, None
        return ("TRAPEXIT", None)
        yield

    def cal_delrec(self, ctx):
        """M:DELREC (CAL1,1 X'D', overlay CLOSE entry 4): the FPT as for a read."""
        dcb = self.dcb_at(ctx.u, ctx.r6)
        if not dcb.open:
            return self.msr012(ctx, dcb, 0x15)         # operation error
        presence = self.fetch(ctx.u, ctx.r7)
        words = (self.s.umem[ctx.u].get(ctx.r7 + 1 + i, 0) for i in range(16))
        return (yield from self.msrrdwt1(ctx, dcb, presence, words, "delete"))

    def _key(self, u, dcb):
        """KEYTRAN: the user's key, a TEXTC at KAD, in EBCDIC."""
        n = self.read_bytes(u, dcb.kad, 0, 1)[0]
        return self.read_bytes(u, dcb.kad, 1, n)

    def write_bytes(self, u, address, btd, data):
        """RECTRAN into the user's buffer: ``data`` at word ``address`` + ``btd`` bytes;
        the other bytes of the first and last words are kept."""
        mem = self.s.umem[u]
        for i, c in enumerate(bytes(data)):
            a, k = address + (btd + i) // 4, 3 - (btd + i) % 4
            mem[a] = (mem.get(a, 0) & ~(0xFF << 8 * k) & 0xFFFFFFFF) | (c << 8 * k)

    def isequb(self, ctx, dcb):
        """ISEQUB  RDF.txt:2443 - a keyed read (KAD) or the next record (after KBUF)."""
        from .files import EBCDIC
        kf, u = dcb.cfu.file, ctx.u
        if consecutive(dcb):
            return self.seq_read(ctx, dcb)             # BAZ SEQ0: CONSECUTIVE
        if random(dcb):
            return self.rwrand(ctx, dcb, write=False)  # BANZ RWRAND: IT'S RANDOM
        trn, dcb.trn = getattr(dcb, "trn", False), False   # CLR TRN (RDF.txt:1917)
        if dcb.kad:
            key = self._key(u, dcb)
            data = kf.read(key)
            if data is None:
                return self.msr012(ctx, dcb, 0x43)     # KEYER3: RETURN1--DIDNT FIND
        elif trn and dcb.kbuf is not None and kf.read(dcb.kbuf) is not None:
            key, data = dcb.kbuf, kf.read(dcb.kbuf)    # positioned before KBUF: read it
        else:
            nxt = kf.read_next(dcb.kbuf)
            if nxt is None:
                dcb.tyc, dcb.egv = 7, True             # end of file: TYC 7
                return self.msr012(ctx, dcb, CODE[7])
            key, data = nxt
        dcb.kbuf = key                                 # the key goes into KBUF
        self._keytran(u, dcb, key)
        n = min(len(data), dcb.rws)
        self.write_bytes(u, dcb.buf, dcb.btd, data[:n])
        dcb.ars, dcb.tyc, dcb.last = len(data), 1, "read"
        self.trace(f"READ {dcb.name} key {key.decode(EBCDIC)!r}: {len(data)} bytes")
        return self.pullallexit(ctx, 0, 0)

    def rew(self, ctx):
        """REW  POS.txt:351-:384 - M:REW. A DCB that isn't open and isn't a device: nothing
        (REW3: JASN, DESTRUCT). An open file: to its beginning (REW5 with PTL, PFIL1,
        PFILB :257-:267): a keyed file's position cleared (SETCMD1 0), a consecutive file
        back to record 0 (SEQ3), TYC 0. A device: a magnetic tape is rewound (REWTP),
        which isn't modeled; others have nothing to do here. Labeled and ANS tapes
        (CHKANS1, PFIL4) aren't translated."""
        from .files import Position
        u = ctx.u
        dcb = self.dcb_at(u, ctx.r6 & 0x1FFFF)
        if dcb.asn == 2:
            raise NotTranslated("M:REW of a labeled tape (PFIL4)")
        if dcb.asn == 3:
            if getattr(dcb, "dtype", "") == "MT":
                raise NotTranslated("M:REW of a magnetic tape (REWTP)")
            return self.pullallexit(ctx, 0, 0)
        if not dcb.open:
            return ("TRAPEXIT", None)                  # REW3: DESTRUCT
        if keyed(dcb):
            dcb.kbuf, dcb.trn = None, False            # SETCMD1: CMD = 0
        elif random(dcb):
            dcb.rgran = 0
        else:
            dcb.cpos = Position()                      # SEQ3: back to record 0
        dcb.tyc, dcb.last = 0, "position"              # PFILB2: SETTYC 0
        self.trace(f"REW {dcb.name}")
        return self.pullallexit(ctx, 0, 0)
        yield

    def _keytran(self, u, dcb, key):
        """KEYTRAN  RDF.txt:323-:331: the key, TEXTC, into the DCB's key buffer (the address
        in its word 10), where a program reads it (EDIT: the line number just read)."""
        if not isinstance(dcb, MemDcb):
            return
        a = self.fetch(u, dcb.address + 10) & 0x1FFFF
        if a:
            self.write_bytes(u, a, 0, bytes([len(key) & 0x1F]) + bytes(key))

    def precord(self, ctx):
        """PRECORD  POS.txt:467 - M:PRECORD: N records (FPT bit 0, default 1) forward, or
        back with REV (bit 27, SETPOS); ABN (bit 1) into J:ABO. A keyed file is positioned
        by PRDCRD11 (RDF.txt:239): N keys from the current position, the key reached into
        KBUF with TRN set, i.e. positioned before it (RDF.txt:392). Running off the end:
        TYC 7, X'06' forward, TYC 4, X'04' back, the ARS the records not skipped
        (SETBOFEOF, POS.txt:598). Consecutive and tape files aren't translated."""
        u, j = ctx.u, self.s.jit[ctx.u]
        dcb = self.dcb_at(u, ctx.r6 & 0x1FFFF)
        presence = self.fetch(u, ctx.r7)
        take = self._params(u, (self.s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(2)))
        n = take() & 0x1FFFF if presence & 0x80000000 else 1        # CHKBIT1: N, else K1
        if presence & 0x40000000:
            j.ABO = take() & 0x1FFFF                   # CHKBIT: STS,D1 ABO,R5
        back = bool(presence & F_REV)                  # SETPOS: DIR
        if not dcb.open:
            raise NotTranslated("M:PRECORD of a DCB not open (TESTOPN)")
        if dcb.asn == 1 and consecutive(dcb):
            return self.precord_seq(ctx, dcb, n, back)
        if dcb.asn != 1 or not keyed(dcb):
            raise NotTranslated(f"M:PRECORD of {dcb.name}: ASN {dcb.asn}, ORG X'{getattr(dcb, 'org', 0):02X}' (JASN)")
        import bisect
        keys = [k.encode(EBCDIC) for k in dcb.cfu.file.keys()]    # in key (byte) order
        if dcb.kbuf is None:
            p = 0                                      # BOF
        elif getattr(dcb, "trn", False):
            p = bisect.bisect_left(keys, dcb.kbuf)     # before KBUF
        else:
            p = bisect.bisect_right(keys, dcb.kbuf)    # after KBUF, the last one read
        q = p - n if back else p + n
        short = -q if q < 0 else max(0, q - len(keys))
        q = min(max(q, 0), len(keys))
        if q < len(keys):
            dcb.kbuf, dcb.trn = keys[q], True          # KEYTRANM: the key, TRN set
        elif keys:
            dcb.kbuf, dcb.trn = keys[-1], False        # after the last
        if keys:
            self._keytran(u, dcb, dcb.kbuf)
        dcb.ars, dcb.last = short, "position"
        self.trace(f"PRECORD {dcb.name} {'back' if back else 'forward'} {n}: position {q}"
                   f" of {len(keys)}" + (f", {short} short" if short else ""))
        if short or not keys:                          # SETBOFEOF
            dcb.tyc = 4 if back else 7
            return self.msr012(ctx, dcb, CODE[dcb.tyc])
        dcb.tyc = 0
        return self.pullallexit(ctx, 0, 0)
        yield

    def precord_seq(self, ctx, dcb, n, back):
        """PRECORD2 / SEQ2-SEQ9  POS.txt:516-:546 - a consecutive file: the record W14
        +-N, kept within 0..TDA; the records not skipped into CDA and the ARS, then
        SETBOFEOF (:590): TYC 7 forward, 4 back, if any weren't."""
        f = dcb.cfu.file
        p = dcb.cpos.rec
        q = p - n if back else p + n
        short = -q if q < 0 else max(0, q - f.TDA)
        q = min(max(q, 0), f.TDA)
        dcb.cpos = f.seek_record(q)
        dcb.ars, dcb.last = short, "position"
        self.trace(f"PRECORD {dcb.name} {'back' if back else 'forward'} {n}: record {q}"
                   f" of {f.TDA}" + (f", {short} short" if short else ""))
        if short:
            dcb.tyc = 4 if back else 7
            return self.msr012(ctx, dcb, CODE[dcb.tyc])
        dcb.tyc = 0
        return self.pullallexit(ctx, 0, 0)

    def iosfile(self, ctx, dcb):
        """IOSFILE / IOSEQUB  WRTF.txt:153, :236 - a keyed write; without a key, the key
        of the record just read (the implied key), else an operation error."""
        from .files import FileError, EBCDIC
        kf, u = dcb.cfu.file, ctx.u
        if dcb.fun == "IN":
            return self.msr012(ctx, dcb, 0x15)         # (writing a file opened IN)
        if consecutive(dcb):
            return self.seq_write(ctx, dcb)            # BAZ SEQ0: IT'S CONSEC
        if random(dcb):
            return self.rwrand(ctx, dcb, write=True)   # B RWRAND: IT'S A RANDOM
        if dcb.kad:
            key = self._key(u, dcb)
        elif getattr(dcb, "last", None) == "read" and dcb.kbuf:
            key = dcb.kbuf                             # PREVIOUS OPN MUST BE READ
        else:
            return self.msr012(ctx, dcb, 0x15)         # OPERATION ERROR
        data = self.read_bytes(u, dcb.buf, dcb.btd, dcb.rws)
        try:
            kf.write(key, data, newkey=dcb.nwk, onewkey=dcb.onwk)
        except FileError as e:
            return self.msr012(ctx, dcb, e.code)
        dcb.kbuf, dcb.last = key, "write"
        self.trace(f"WRITE {dcb.name} key {key.decode(EBCDIC)!r}: {len(data)} bytes")
        return self.pullallexit(ctx, 0, 0)

    def delrec(self, ctx, dcb):
        from .files import EBCDIC
        if consecutive(dcb):                               # DELSET: BAZ SEQ0 CONSECUTIVE
            if dcb.last != "read" or not dcb.cfu.file.delete_record(dcb.cpos):
                return self.msr012(ctx, dcb, 0x15)     # DELER: K15
            dcb.last = "delete"
            self.trace(f"DELREC {dcb.name} record {dcb.cpos.rec + 1}")
            return self.pullallexit(ctx, 0, 0)
        if not dcb.kad:
            return self.msr012(ctx, dcb, 0x17)         # KEY WASNT SPECIFIED
        key = self._key(ctx.u, dcb)
        if not dcb.cfu.file.delete(key):
            return self.msr012(ctx, dcb, 0x43)
        self.trace(f"DELREC {dcb.name} key {key.decode(EBCDIC)!r}")
        return self.pullallexit(ctx, 0, 0)

    def seq_read(self, ctx, dcb):
        """SEQ0  RDF.txt:3136 - the next record of a consecutive file: end of file is
        TYC 7, a record longer than the buffer TYC 2, lost data (SEQ6)."""
        data = dcb.cfu.file.read(dcb.cpos)
        if data is None:
            dcb.tyc, dcb.egv = 7, True
            return self.msr012(ctx, dcb, CODE[7])
        n = min(len(data), dcb.rws)
        self.write_bytes(ctx.u, dcb.buf, dcb.btd, data[:n])
        dcb.ars, dcb.last = n, "read"                  # IMAGE3: ARS = what was moved
        self.trace(f"READ {dcb.name} record {dcb.cpos.rec}: {len(data)} bytes")
        if n < len(data):
            dcb.tyc, dcb.egv = 2, True
            return self.msr012(ctx, dcb, CODE[2])
        dcb.tyc = 1
        return self.pullallexit(ctx, 0, 0)

    def seq_write(self, ctx, dcb):
        """SEQ0  WRTF.txt:273 - a record at the end of a consecutive file, or, before
        the end, the file cut at the position first."""
        from .files import FileError
        data = self.read_bytes(ctx.u, dcb.buf, dcb.btd, dcb.rws)
        try:
            dcb.cfu.file.write(dcb.cpos, data)
        except FileError as e:
            return self.msr012(ctx, dcb, e.code)
        dcb.last = "write"
        self.trace(f"WRITE {dcb.name} record {dcb.cpos.rec}: {len(data)} bytes")
        return self.pullallexit(ctx, 0, 0)

    def rwrand(self, ctx, dcb, write):
        """RWRAND  WRTF.txt:1928 - a random file by granule number: the key word (KBUF;
        from the FPT's key, else where the last request ended). Up to RWS bytes, no
        further than the end of the file; then the granule number moves past them."""
        from .files import FileError, GRAN
        f, u = dcb.cfu.file, ctx.u
        if dcb.kad:
            dcb.rgran = self.s.umem[u].get(dcb.kad, 0)
        if dcb.rws == 0:
            dcb.rgran += 1                             # ZERO LENGTH, UPDATE KEY
            dcb.ars = 0
            return self.pullallexit(ctx, 0, 0)
        try:
            if write:
                data = self.read_bytes(u, dcb.buf, dcb.btd, dcb.rws)
                n = f.write(dcb.rgran, data)
            else:
                data = f.read(dcb.rgran, dcb.rws)
                n = len(data)
                self.write_bytes(u, dcb.buf, dcb.btd, data)
        except FileError as e:
            dcb.ars = 0
            return self.msr012(ctx, dcb, e.code)       # ERR01: X'42'
        self.trace(f"{'WRITE' if write else 'READ'} {dcb.name} granule {dcb.rgran}: {n} bytes")
        dcb.rgran += (n + GRAN - 1) // GRAN            # RWRDUN: INCREMENT RELGRAN
        dcb.ars, dcb.last = n, "write" if write else "read"
        if n != dcb.rws:
            return self.msr012(ctx, dcb, 0x44)         # E5744 (the code as read: open question)
        return self.pullallexit(ctx, 0, 0)

    resident = {}
    overlaid = {}


CalProcessor.overlaid.update({"T:WAIT": CalProcessor.t_wait, "MTIME": CalProcessor.mtime,
                              "MINT": CalProcessor.mint, "T:CHTBL": CalProcessor.t_chtbl,
                              "OPEN entry 0": CalProcessor.file_open,
                              "CLOSE entry 2": CalProcessor.file_close,
                              "CLOSE entry 4": CalProcessor.cal_delrec,
                              "MSRKEY": CalProcessor.msrkey})
CalProcessor.overlaid["MXCON"] = CalProcessor.mxcon
CalProcessor.overlaid["PRECORD"] = CalProcessor.precord
CalProcessor.overlaid["REW"] = CalProcessor.rew
CalProcessor.overlaid.update({"T:GDP": CalProcessor.get_pages(None, 1),
                              "T:GCP": CalProcessor.get_pages(None, -1),
                              "T:GVP": CalProcessor.get_pages(None, 0),
                              "T:FDP": CalProcessor.free_pages(None, -1),
                              "T:FCP": CalProcessor.free_pages(None, 1),
                              "T:FVP": CalProcessor.free_pages(None, 0),
                              "T:GL": CalProcessor.t_gl, "T:GDDL": CalProcessor.t_gddl,
                              "T:ASSOCIATE": CalProcessor.t_associate,
                              "T:DISASSOCIATE": CalProcessor.t_associate})
CalProcessor.resident.update({"T:CLRERR": CalProcessor.t_clrerr, "MTRAP": CalProcessor.mtrap,
                              "MSEGLD": CalProcessor.msegld, "MLNK": CalProcessor.mlnk,
                              "MSRTYPR": CalProcessor.msrtypr, "MSROCTY": CalProcessor.msrtypr})
for _kind in ("T:EXIT", "T:ERROR", "T:ABORT"):
    CalProcessor.resident[_kind] = CalProcessor.exit_cal(None, _kind)
CalProcessor.overlaid["MSTIMER"] = CalProcessor.mstimer
CalProcessor.overlaid["MTTIMER"] = CalProcessor.mttimer
