"""The scheduler: user states, events, the exit path, T:SE and T:SS. See docs/scheduler.md.

Translated from c00co/SCHED.txt, with its data from c00co/SSDAT.txt. Comments of the
form ``# FILE:NNN`` or ``# :NNN`` (SCHED.txt) point at the source.

This is a translation on its own tables, not on Machine.mem: queue heads, links and
flags are Python lists indexed by state or user number, as the source's byte and
halfword tables are. Users are *stand-ins*: a Python generator per user plays the
program (a ghost, or an on-line user), and yields what it wants the monitor to do
(compute, sleep, wait for I/O, block on a resource, report an event, end). The
generator only runs when the scheduler does a T:PULLE for that user, so who runs,
in what order and for how long is decided by the translated code.

Simplifications (also in python/README.md):

- Time is in clock units (SL:SQNT = 150 is "300 MS", SSDAT.txt:294, so 2 ms each).
  ``Compute(n)`` adds n to the cell S:CLOCK4 points at, then the clock-4 interrupt
  (CLK4, :2091) takes the user through the exit path. Interrupts that fall due
  during a compute (timers, I/O completions) are reported first, as T:SSE would.
- Wake-ups (E:WU, reported by CLOCK4) and I/O completions (E:IC, IOQ REQCOM) come
  from a timer list in the driver, not from translated clock or I/O code.
- T:SS works on page counts, not on MX:PPUT chains, and SWAPIN/SWAPOUT (SWAPPER.txt)
  are stand-ins that complete at once: they move the counts and set or clear RTR/JIC.
- The GIVEUP8 return after a failed swap is translated as evidently intended
  (R6 = GIVEUPA), not as read: see docs/scheduler.md, Open questions.
- The DO list is a Python list per user; UH:DL keeps only the four flags. Types 1
  and 7 run Python callables; the COC and real-time types raise NotTranslated.
- What the exit path hands to code outside SCHED (T:TELDELCCI, SETRNST, T:DELUSZAP,
  T:SCRATCH%USER, COCOFF, T:DELUS) goes to hooks. By default they end the user with a
  T:DELUS stand-in, which puts the slot back in SNULL.
"""

from dataclasses import dataclass, field

from .monitor import NotTranslated


class Screech(Exception):
    """SCREECH from the scheduler, when no ``screech`` callback is attached."""

    def __init__(self, code, why=""):
        super().__init__(f"SCREECH X'{code:02X}' {why}".rstrip())
        self.code = code


# --- States  :275 -------------------------------------------------------------------
# STATE numbers from 1 (ST% SET 0, then ST% SET ST%+1 before each EQU).

(SRT, SC0, SC1, SC2, SC3, SC4, SC5, SC6, SC7, SC8, SC9, SC10, SCU,
 STOB, STOBO, SIOW, SIOMF, SW, SQA, SQR, SQRO, STI, STIO, SQFI) = range(1, 25)
SEXU = SC10                     # :289 last executable state
SNULL = 30                      # :317 empty user slots
SNSTS = 31                      # :318
EXECUTE = list(range(SRT, SC10 + 1))
ALL = "ALL"
STATE_NAMES = {v: k for k, v in dict(
    SRT=SRT, SC0=SC0, SC1=SC1, SC2=SC2, SC3=SC3, SC4=SC4, SC5=SC5, SC6=SC6, SC7=SC7,
    SC8=SC8, SC9=SC9, SC10=SC10, SCU=SCU, STOB=STOB, STOBO=STOBO, SIOW=SIOW,
    SIOMF=SIOMF, SW=SW, SQA=SQA, SQR=SQR, SQRO=SQRO, STI=STI, STIO=STIO, SQFI=SQFI,
    SNULL=SNULL).items()}
assert SIOW % 4 == 0 and SIOMF == SIOW + 1                       # :297
assert STOBO == STOB + 1 and SQRO == SQR + 1 and STIO == STI + 1  # :270


def mask(*states):
    """MASK  :329 - bit 2**n for each state n."""
    return sum(1 << s for s in states)


EXU_MASK = mask(*EXECUTE, SCU)                                    # :341
WAIT_MASK = mask(SW, SQFI)
IOWAIT_MASK = mask(STOB, STOBO, SIOW, STI, STIO)
BLCKD_MASK = mask(SIOMF, SQA, SQR, SQRO)

# --- Flags  UTS.txt:192, SCHED.txt:243 ----------------------------------------------

RTR, INHIBIT, SPECFILE, OPNCLSUSR, PPSWP, INTERACTIVE = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20
DIC, TIC, BAT, JIC, DELA, INIT, SJAC, DCBS = 0x40, 0x80, 0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000
EARLY = 0x4000                  # step in progress, or "unblock received before block"
BYPASS = 0x8000
OPNBOOST = 0x04                 # :245

# UH:FLG2  :711
JITERR, CTXERR, USRERR, SQUAN, SWAPD, HANGUP = 0x1, 0x2, 0x4, 0x8, 0x10, 0x20
CALINT, RTHOLD, RMAHOLD = 0x200, 0x800, 0x2000
XFDFF = 0xFFFF & ~(1 << 13)     # :241 NB31TO0+14 is not X'FDFF': it clears RMAHOLD

# UH:DL flags  :743, and SH:RFLG flags  :476
DL_ABRT, DL_ERR, DL_EC, DL_BRK = 0x8000, 0x4000, 0x2000, 0x1000
SPECIFIC, FLUSH, NULL = 0x100, 0x200, 0x400

CONT = 0x80000000               # ESTS1: continued in the next word
ALL_BITS = 0x7FFFFFFF

# --- Transition tables  :398-676 -------------------------------------------------------
# (event names, [(action, states), ...]). An action is a state number (plain change,
# RCE4) or the name of a special transition in S:TRNSVEC. All but the last entry of an
# event are ESTS1 (continuation).

EVENTS = [
    (("E_IIP",), [("STIIP", [SCU])]),                                          # :513
    (("E_QMF", "E_IP"), [("STIOMF", [SCU])]),
    (("E_CRD",), [("STCRD", [SCU])]),                                          # :520
    (("E_CIC",), [("STIRC", [STI, STIO]), ("STIRCU", [SCU])]),
    (("E_CBL",), [(STOB, [SCU])]),
    (("E_CUB",), [("STOC", [STOB, STOBO]),
                  ("STNOP", EXECUTE + [SCU, STI, SW, SIOW, SIOMF, SQA, SQR, STIO, SQFI])]),
    (("E_CBK",), [("STBEEA", [SCU, SIOW, SIOMF, SQA, SQR, SQRO, SNULL]),       # :566
                  ("STBEEAC", EXECUTE + [SW, STI, STIO, STOB, STOBO, SQFI])]),
    (("E_CEC",), [("STBEEA", [SCU, SIOW, SIOMF, SQA, SQR, SQRO, SNULL]),
                  ("STBEEAC", EXECUTE + [SW, STI, STIO, STOBO, SQFI, STOB])]),
    (("E_ERR",), [("STBEEAC", EXECUTE + [SW, SQFI]),
                  ("STBEEA", [SCU, SIOW, STOB, STOBO, SIOMF, SQA, SQR, SQRO, SNULL, STIO, STI])]),
    (("E_OFF", "E_ABRT"), [("STBEEAC", EXECUTE + [SW, STI, STIO, SQFI, SQA]),
                           ("STBEEA", [SCU, SIOMF, SIOW, STOB, STOBO, SQR, SQRO, SNULL])]),
    (("E_WU",), [("STSC", [SW, SQFI]), ("STNOP", ALL)]),                       # :607
    (("E_SL",), [(SW, [SCU])]),
    (("E_QA",), [("STQA", [SCU])]),
    (("E_ART",), [("STNOP", [SCU, SIOW, SIOMF, SQR, SQRO, SQA, STI, STOB, STIO, STOBO, SNULL]),
                  ("STSCOM", [SQFI, SW] + EXECUTE)]),
    (("E_UQA",), [("STUQA", [SQA, SIOW, SCU] + EXECUTE), ("STNOP", ALL)]),
    (("E_KO",), [("STKO", [SW, SQFI] + EXECUTE + [SQA, SIOMF, SIOW]),          # :646
                 ("STKOT", [STOB, STI, SQR])]),
    (("E_AP", "E_NC"), [("STASP", [SCU])]),
    (("E_QE",), [("STSCOM", [SCU])]),
    (("E_IC",), [("STIOC", ALL)]),                                             # :667
    (("E_QFI",), [(SQFI, [SCU])]),
]

# RESOURCE  :670 - (block event, release event, name, release routine, flags)
RESOURCES = [
    ("E_NSYMF", "E_SYMF", "R_SYMF", None, FLUSH),
    ("E_NSYMD", "E_SYMD", "R_SYMD", None, FLUSH),
    ("E_OCR", "E_NOCR", "R_OCR", "OPNUNBLOCK", 0),
    ("E_CFB", "E_CBA", "R_CBA", None, FLUSH),
    ("E_ND", "E_DPA", None, None, FLUSH),
    ("E_QFAC", "E_UQFAC", None, "UQFAC", FLUSH | NULL),
    ("E_NQW", "E_NQR", "R_NQW", None, DL_ERR | DL_ABRT | DL_EC | DL_BRK | SPECIFIC),
]
NRSRC = 17                      # SSDAT.txt:396


def build_tables():
    """Assemble S:SET, SB:SET, SH:RFLG and the event numbers the way ESTS does."""
    s_set, sb_set, numbers, rflg, rnames = [], [], {}, [], {}

    def ests(entries):
        start = len(s_set)
        for k, (action, states) in enumerate(entries):
            word = ALL_BITS if states == ALL else mask(*states)
            if k < len(entries) - 1:
                word |= CONT
            s_set.append(word)
            sb_set.append(action)
        return start

    for names, entries in EVENTS:
        n = ests(entries)
        for name in names:
            numbers[name] = n
    numbers["E_REL"] = len(s_set)                                  # :669 E:REL EQU E:NSYMF
    for index, (blk, rel, name, routine, flags) in enumerate(RESOURCES):
        numbers[blk] = ests([("T_RES", [SCU])])
        numbers[rel] = ests([("T_RES", ALL)])
        rflg.append((routine, flags))
        if name:
            rnames[name] = index
    return s_set, sb_set, numbers, rflg, rnames


S_SET, SB_SET, EVENT_NUMBERS, SH_RFLG, RESOURCE_NAMES = build_tables()
globals().update(EVENT_NUMBERS)
EVENT_NAMES = {}
for _name, _n in EVENT_NUMBERS.items():
    EVENT_NAMES.setdefault(_n, _name)
assert E_CBK % 2 == 0, "E:CBK MUST BE AN EVEN NUMBERED EVENT"               # :569
assert (E_CEC - E_CBK, E_ERR - E_CEC, E_OFF - E_ERR) == (2, 2, 2)           # :600

SH_PINC = (0, 3, 2, 6)          # SSDAT.txt:421 compute, special compute, I/O complete, interactive
STSCOM_I, STSC_I, STIOCC_I, STIRC_I = range(4)

# SB:SWP  :763 - the order USERSOUT looks for users to swap out (index 0 unused, 0 ends)
SB_SWP = [0, SW, STI, SC10, STOB, SQR, SQFI, SQA, SC9, SC8, SC7, SC6, SC5, SC4, SC3,
          SC2, SC1, SC0, SRT, 0]
SMAXOUT = 20                    # SSDAT.txt:92


# --- What a user (a stand-in program) can ask for ------------------------------------

@dataclass
class Compute:
    """Run for n clock units, then the clock-4 interrupt."""
    n: int


@dataclass
class Sleep:
    """E:SL through T:REG. With n, a stand-in for CLOCK4 reports E:WU after n units."""
    n: int = None


@dataclass
class Io:
    """Start I/O (UB:MF + 1) and wait for it: T:IOREG, E:IIP. It completes after n units."""
    n: int
    dcb: object = None


@dataclass
class Report:
    """T:REG with any event (a block, E:QA, E:QFI, ...); with ``dcb``, T:IOREG."""
    event: int
    dcb: object = None


@dataclass
class Release:
    """T:RE with a release event, then back to the user through the exit path (a CAL)."""
    event: int
    user: int = None            # for a SPECIFIC resource: the user to release


@dataclass
class Cal1:
    """A CAL1,n instruction (cal.py). ``fpt`` (a cal.Fpt) is placed in the user's
    memory and the CAL's address points at it; or ``address`` is the CAL's address field
    itself (CAL1,9: the exit type). ``regs`` are the user's registers at the CAL.
    The yield returns the condition codes the CAL leaves in the PSD."""
    n: int
    fpt: object = None
    address: int = None
    regs: dict = None


@dataclass
class CalAt:
    """A CAL1 already in the user's memory at ``psd`` (an interpreted program,
    interp.py): trap X'48' with that PSD. Returns as Cal1 does."""
    psd: int


@dataclass
class Call:
    """A CAL into monitor code outside SCHED, run as ``fn(sched, user)``; then the
    user goes back through the exit path (TRAPEXIT)."""
    fn: object
    what: str = ""


def _no_program(sched, u):
    """A ghost with no stand-in: it runs once and logs itself off."""
    yield Compute(1)


@dataclass
class Dcb:
    """A DCB: the function count (FCN byte) and its bit 0 'waiting', which the I/O
    transitions read, and the fields the read/write path uses (docs/rdwr.md)."""
    name: str = "DCB"
    fcn: int = 1
    waiting: bool = False
    address: int = 0
    asn: int = 3                # 1 file, 2 labeled tape, 3 device, 4 common journal
    dct: int = 0                # DSI: the device's DCT index
    dtype: str = ""             # device type (DCT4 / TB:FLGS): 'TY', 'LP', ...
    open: bool = True           # FCD
    stream: int = 0             # CLK byte: a symbiont stream
    tyc: int = 0                # highest completion type so far
    egv: bool = False           # TYC checked
    ars: int = 0                # actual record size
    rsz: int = 0                # default record size
    buf: int = 0
    rws: int = 0                # buffer size (bytes)
    btd: int = 0                # byte displacement
    wat: bool = False           # the WAIT flag
    mbg: bool = False           # monitor buffer used
    qbuf: str = ""              # what is queued (the monitor buffer's contents)
    nra: int = 1                # tries
    coc: bool = False           # a COC terminal DCB (DSI X'90xx')
    # A file DCB (ASN 1): the file name and account VLPs, the function, the key length
    fname: str = ""
    account: str = ""
    fun: str = "IN"             # IN, OUT, INOUT, UPDATE
    keym: int = 11
    org: int = 0x20             # ORG: X'20' keyed, X'10' random, 0 consecutive
    cfu: object = None          # the open file's CFU
    cpos: object = None         # files.Position in a consecutive file
    rstore: int = 0             # RSTORE: a new random file's size in granules
    rgran: int = 0              # KBUF's word in a random file: the next granule
    prot: dict = field(default_factory=dict)   # protection VLPs (X'03', X'05', X'06', X'14', X'15')
    usr: bool = False           # USR X'4000': not the user's own file
    special: bool = False       # X'100': special (execute) access
    kad: int = 0                # key address for this CAL
    kbuf: bytes = None          # KBUF: the key of the last record
    nwk: bool = False           # NEWKEY
    onwk: bool = False          # ONEWKEY
    last: str = ""              # the last operation (EOP)


M_OC = Dcb("M:OC", fcn=0)       # SSDAT.txt:255


def is_moc(dcb):
    """CI,1 M:OC - the operator console's DCB is never flagged as waited on."""
    return getattr(dcb, "name", None) == "M:OC"


@dataclass
class DoEntry:
    """A 4-word DO-list block: priority (byte 0), type (byte 1), the routine for type 7."""
    type: int
    prio: int = 0
    routine: object = None


@dataclass
class Jit:
    """The JIT cells the scheduler reads and writes."""
    DELTAT: int = 0
    IDELTAT: int = 0
    OVHTIM: int = 0
    CTIME: int = 0
    UTIME: int = 0
    RNST: int = 0
    FRS: int = 0
    ERO: int = 0
    INTENT: int = 0
    TIMENT: int = 0
    UTIMER: int = 0
    TELFLGS: int = 0
    ABO: int = 0                # abnormal address (the error address is ERO)
    ABC: int = 0                # abort code (J:ABC)
    STEPCC: int = 0             # JB:STEPCC


@dataclass
class Limits:
    """SYSGEN limits. Invented unless marked; CONMAIN.txt:1031-1087 gives their ranges."""
    SL_QUAN: int = 300          # quantum (T:ACCTEX); above SL:SQUAN, or no one could be swapped out
    SL_QMIN: int = 10           # 0-5000
    SL_SQUAN: int = 200         # 0-5000
    SL_SQNT: int = 150          # SSDAT.txt:294
    SL_SQPB: int = 2            # SSDAT.txt:293
    S_PRIODEC: int = 1          # SSDAT.txt:284
    SL_OPRIO: int = 0xF8        # 192-255
    SL_OIMF: int = 4
    SL_BIMF: int = 4
    S_OUAIS: int = 8
    SL_RSVP: int = 0
    SL_GPRIO: int = 0xF0        # default ghost priority, 192-255 (CONMAIN.txt:1089)
    SL_IOTA: int = 2            # SSDAT.txt:290 I/O time allowance ("DING")
    SL_BXMF: int = 4            # batch / on-line limit on I/O outstanding (FRONTEND)
    SL_OXMF: int = 4
    BIG: int = 1                # :BIG, 1 on a Sigma 9


# T:GJOBSTRT's condition codes (LCI n: CC1-CC4 = 8, 4, 2, 1)
CC1, CC2, CC3, CC4 = 8, 4, 2, 1
GJ_STARTED, GJ_WOKEN, GJ_RUNNING, GJ_FAILED = 0, CC2, CC1 | CC3, CC1


@dataclass
class Buffer:
    """One of ALLOCAT's four buffers, as STUQFAC updates it (files.Stack is the one
    the file system uses)."""
    BUFLAGS: int = 0
    BOTTOM: int = 0
    TEMPBOT: int = 0
    WORDCNT: int = 0
    ADJSTCNT: int = 0
    BUFMASK: int = 0x3FF

    def unqueue(self):
        """STUQFAC's work on one buffer  SCHED.txt:1711-:1735: make ALLOCAT's fill or
        emptying real. Returns False for a count past the buffer (SCREECH X'88')."""
        if self.BUFLAGS & 0x4000:                      # just emptied
            self.TEMPBOT = self.BOTTOM
        elif self.BUFLAGS & 0x2000:                    # just filled
            self.BOTTOM = self.TEMPBOT
        self.BUFLAGS &= 0x9FFE                         # X9FFF is DATA X'9FFE'
        self.WORDCNT += self.ADJSTCNT
        ok = self.WORDCNT - 1 <= self.BUFMASK
        self.ADJSTCNT = 0
        return ok


@dataclass
class Ctx:
    """The registers a transition works with."""
    u: int                      # R4 user
    event: int                  # R6 event (after continuations)
    r3: int                     # old state
    r12: int                    # its bit
    r15: int                    # UH:FLG
    dcb: object = None          # R1
    head: bool = False          # R4 bit 0: queue to head
    change: bool = False        # R6 bit 0 in STBEEAC
    seo: bool = False           # R11 changed to T:SEO
    flag: int = 0               # R14 in STBEEA


PULLE = "PULLE"                 # a transition that goes to T:PULLE: the user continues


class Scheduler:
    def __init__(self, smuis=16, ming=4, limits=None, pages=64, swap_granules=(100,),
                 trace=None, screech=None, lines=4, maxg=8, ghost_names=(), bootflg=None):
        self.L = limits or Limits()
        self.SMUIS, self.MING = smuis, ming
        n = smuis + 1
        self.UB_US = [0] * n
        self.UB_FL = [0] * n
        self.UB_BL = [0] * n
        self.UB_PRIO = [0] * n
        self.UB_PRIOB = [0] * n
        self.UH_FLG = [0] * n
        self.UH_FLG2 = [0] * n
        self.UH_DL = [0] * n
        self.U_MISC = [0] * n
        self.UB_MF = [0] * n
        self.UB_PCT = [0] * n
        self.JBPPC = [0] * n            # pages the user has in core (JBPPC in the JIT)
        self.UH_AJIT = [0] * n
        self.UB_SWAPI = [0] * n
        self.UB_ACP = [0] * n
        self.UB_APR = [0] * n
        self.UB_APO = [0] * n
        self.UB_ASP = [0] * n
        self.UB_DB = [0] * n
        self.UB_OV = [0] * n
        self.jit = [Jit() for _ in range(n)]
        self.do_list = [[] for _ in range(n)]
        self.SB_HQ = [0] * 32
        self.SB_TQ = [0] * 32
        self.SB_RQ = [0] * NRSRC
        # SSDAT.txt:390: the null queue runs from MING to SMUIS. Every slot is in SNULL,
        # but the reserved ones below MING (system ghosts) aren't linked into its queue
        # until T:GJOBSTRT starts them (ADDGJOB, T$OV.txt:404). The SYSGEN'd UB:FL/UB:BL
        # aren't in the source, so this is what ADDGJOB implies.
        for u in range(1, smuis + 1):
            self.UB_US[u] = SNULL
        for u in range(ming, smuis + 1):
            self.UB_BL[u] = u - 1 if u > ming else 0
            self.UB_FL[u] = u + 1 if u < smuis else 0
        self.SB_HQ[SNULL], self.SB_TQ[SNULL] = ming, smuis
        # Processors (PX:HPP: pages in core, 0 = not in core). Slot 0 is the source's
        # "no processor", whose use count the DECR/INCR routines still step.
        self.PX_HPP, self.PB_PSZ, self.PB_UC, self.PH_FRQ, self.PB_LCT = {}, {}, {0: 0}, {}, {}
        # Scheduler cells (SSDAT.txt)
        self.S_CUN = 0
        self.S_CUP = 0xFF
        self.S_HIR = 0
        self.S_EVF = 0
        self.S_SEVF = 0
        self.S_FSEVF = 0
        self.S_ISUNF = 0
        self.S_ISUN = 0
        self.S_SIP = 0
        self.S_CUIS = 0
        self.S_OUIS = 0
        self.S_RTIR = 0                 # SSDAT.txt:286 starts at 0
        self.S_RTCORE = 0
        self.S_STL_ = 0                 # S:STL#
        self.S_STLC = 0
        self.GOODNGT = 0
        self.ALLOOUT = 0
        self.OPNCLSUS = 0
        self.symbionts_busy = False
        # Pages (counts only)
        self.M_FPPC = pages
        self.S_PCORE = pages
        self.S_ACORE = pages
        self.S_FPPC = 0
        self.S_PCT = 0
        self.S_OSS = 0
        self.S_PRPC = 0
        self.S_FPL = []                 # (frequency, processor)
        self.SB_PNL = []
        self.SB_OSUL = []
        self.SB_FPN = []
        # Swap devices for JITs (M:FREE#GRAN, M:JITPAGE, MB:SPACEJIT)
        self.M_FREE_GRAN = list(swap_granules)
        self.M_JITPAGE = [0] * len(swap_granules)
        self.MB_SPACEJIT = [1] * len(swap_granules)
        # COC lines and ghosts. S:GJOBTBL holds (name, account) per slot 1..MAXG, and
        # SB:GJOBUN the slot's user number (0 while the ghost isn't running).
        self.LB_UN = [0] * lines
        self.coc = None                 # coc.Coc: the lines' input and output
        self.on_logon = None            # (sched, u, line): the new user's command processor
        self.breaks = set()             # users with a BREAK (or Ctrl-Y) not yet acted on
        self.not_translated = {}        # user -> the NotTranslated their program reached
        self.hangups = set()            # users whose line dropped
        self.MAXG = maxg
        self.S_GJOBTBL = [None] * (maxg + 1)
        for slot, name in enumerate(ghost_names, 1):
            if name:
                self.S_GJOBTBL[slot] = (name, ":SYS")
        self.SB_GJOBUN = [0] * (maxg + 1)
        self.S_GUIS = 0
        self.ghost_programs = {}        # name -> program(sched, user), the stand-ins
        self.program_loader = None      # (name, account) -> program: the step's load (pyprog)
        self.bootflg = bootflg or (lambda: 0)
        self.buffers = [Buffer() for _ in range(4)]
        # Counters and the clock-4 cell
        self.C = dict(NOPROC=0, NSP=0, IDLE=0, IDLES=0, IDLEW=0, IDLESW=0)
        self.S_CLOCK4 = ("C", "IDLE")
        # Driver
        self.now = 0
        self.timers = []                # (time, seq, event, user, dcb)
        self._seq = 0
        self.programs = {}
        self._next = "SE"                 # where run() goes on
        # Per user: what T:PULLE resumes (the program, with monitor CAL processing
        # pushed above it while a CAL is in progress), the value it gets back (the
        # CAL's CCs), the saved PSD's CC, registers and a small word memory.
        self.stacks = {}
        self._send = {}
        self.psd_cc = [0] * n
        self.uregs = [[0] * 16 for _ in range(n)]
        self.umem = [dict() for _ in range(n)]
        self.cal = None                   # cal.CalProcessor, made on the first CAL
        self.ended = []
        self.log = trace if trace is not None else []
        self.screech_cb = screech
        self.hooks = {}

    # --- helpers ---------------------------------------------------------------------

    def trace(self, msg):
        self.log.append(f"{self.now:6d} {msg}")

    def screech(self, code, why=""):
        self.trace(f"SCREECH X'{code:02X}' {why}")
        if self.screech_cb is not None:
            return self.screech_cb(code, why)
        raise Screech(code, why)

    def hook(self, name, u):
        """Code outside SCHED. The default ends the user (T:DELUS stand-in)."""
        fn = self.hooks.get(name)
        self.trace(f"{name} user {u}")
        if fn is not None:
            return fn(self, u)
        return self.t_delus(u)

    def queue(self, state):
        """The users in a state's queue, head first."""
        out, u, n = [], self.SB_HQ[state], 0
        while u and n <= self.SMUIS:
            out.append(u)
            u, n = self.UB_FL[u], n + 1
        return out

    def state_of(self, u):
        return STATE_NAMES.get(self.UB_US[u], str(self.UB_US[u]))

    def clock(self, n):
        """Advance the clock: n units into the cell S:CLOCK4 points at."""
        owner, cell = self.S_CLOCK4
        target = self.C if owner == "C" else self.jit[owner]
        if owner == "C":
            target[cell] += n
        else:
            setattr(target, cell, getattr(target, cell) + n)
        self.now += n

    def after(self, n, event, user, dcb=None):
        self._seq += 1
        self.timers.append((self.now + n, self._seq, event, user, dcb))
        self.timers.sort()

    def interrupts(self):
        """Report the events that are due (the interrupt routines); True if any."""
        fired = False
        while self.timers and self.timers[0][0] <= self.now:
            _, _, event, user, dcb = self.timers.pop(0)
            self.trace(f"interrupt: {EVENT_NAMES[event]} for user {user}")
            self.t_rue(user, event, dcb)
            fired = True
        return fired

    # --- Event reporting  :1342-1433 -------------------------------------------------

    def t_rue(self, u, event, dcb=None):
        """T:RUE  :2574 - report an event for a user and return."""
        return self.rce0(u, event, dcb)

    def t_re(self, event, dcb=None):
        """T:RE  :1360 - report for the current user."""
        return self.rce0(self.S_CUN, event, dcb)

    def rce0(self, u, event, dcb=None):
        """RCE0  :1371 - find the action for the user's state and the event, and do it."""
        self.S_EVF += 1
        r3 = self.UB_US[u]
        bit = 1 << r3
        i = event
        while not S_SET[i] & bit:
            if not S_SET[i] & CONT:
                return self.screech(0x02, f"state {self.state_of(u)} event {EVENT_NAMES.get(event, event)}"
                                    f" user {u}")
            i += 1                                     # RCE2
        action = SB_SET[i]
        ctx = Ctx(u=u, event=i, r3=r3, r12=bit, r15=self.UH_FLG[u], dcb=dcb)
        if isinstance(action, int):
            return self.rce4(ctx, action)
        return getattr(self, action.lower())(ctx)

    def _unlink(self, u, old):
        bl, fl = self.UB_BL[u], self.UB_FL[u]
        if fl == 0:
            self.SB_TQ[old] = bl
        if bl == 0:
            self.SB_HQ[old] = fl
        self.UB_BL[fl] = bl                            # index 0 is scratch, as user 0 is
        self.UB_FL[bl] = fl

    def rce4(self, ctx, new):
        """RCE4  :1408 - plain state change: FIFO, to the tail (or head)."""
        u = ctx.u
        self._unlink(u, ctx.r3)
        if ctx.head:
            self._qh(u, new)
        else:
            self._qt(u, new)
        return self.chs1(ctx, new)

    def _qt(self, u, new):
        """T:QT  :1420"""
        self.UB_FL[u] = 0
        prev = self.SB_TQ[new]
        if prev == 0:
            return self._chse25(u, new)
        self.SB_TQ[new] = u
        self.UB_BL[u] = prev
        self.UB_FL[prev] = u

    def _qh(self, u, new):
        """T:QH  :1427"""
        self.UB_BL[u] = 0
        cur = self.SB_HQ[new]
        if cur == 0:
            return self._chse25(u, new)
        self.SB_HQ[new] = u
        self.UB_BL[cur] = u
        self.UB_FL[u] = cur

    def _chse25(self, u, new):
        self.UB_BL[u] = self.UB_FL[u] = 0
        self.SB_TQ[new] = self.SB_HQ[new] = u

    def chs1(self, ctx, new):
        """CHS1  :1606"""
        self.UB_US[ctx.u] = new
        self.S_EVF += 1
        self.trace(f"user {ctx.u} -> {STATE_NAMES.get(new, new)}"
                   + (f" prio X'{self.UB_PRIO[ctx.u]:02X}'" if new <= SEXU else ""))
        return None

    def t_chs(self, u, new):
        """T:CHS  :1532 - plain state change from outside."""
        return self.rce4(Ctx(u=u, event=0, r3=self.UB_US[u], r12=1 << self.UB_US[u],
                             r15=self.UH_FLG[u]), new)

    # --- Executable state change  :1452 ----------------------------------------------

    def t_chse(self, ctx, index):
        """T:CHSE  :1453 - priority from base, boost and increment, then the state."""
        u = ctx.u
        prio = self.UB_PRIOB[u]
        if ctx.r15 & (OPNCLSUSR | SPECFILE):
            prio -= OPNBOOST
        prio -= SH_PINC[index]
        return self.chse0(ctx, prio)

    def t_chse0(self, ctx):
        """T:CHSE0  :1452 - base compute, no increment."""
        return self.t_chse(ctx, STSCOM_I)

    def chse0(self, ctx, prio):
        """CHSE0  :1459"""
        u = ctx.u
        self.UB_PRIO[u] = prio & 0xFF
        if prio < self.S_CUP and ctx.r15 & RTR:
            self.S_HIR += 1
            if self.S_HIR <= 0:
                self.S_HIR = 1
        return self.chse1(ctx, prio)

    def chse1(self, ctx, prio):
        """CHSE1  :1468 - X'F6'-X'FF' are SC1-SC10 (plain change), X'C0'-X'F5' SC0,
        below X'C0' SRT (priority back to base: 'DONT FLOAT RT')."""
        if prio - 0xF5 > 0:
            return self.rce4(ctx, SC0 + (prio - 0xF5))   # CHSE6
        if prio - 0xC0 < 0:
            self.UB_PRIO[ctx.u] = self.UB_PRIOB[ctx.u]   # CHSRT
            return self.chse2(ctx, SRT)
        return self.chse2(ctx, SC0)

    def chse2(self, ctx, new):
        """CHSE2  :1473 - unlink, then insert by priority."""
        u = ctx.u
        self._unlink(u, ctx.r3)
        p = self.UB_PRIO[u]
        if ctx.head:                                   # CHSEH: ahead of equals
            h = self.SB_HQ[new]
            if h == 0:
                self._chse25(u, new)
                return self.chs1(ctx, new)
            while not p < self.UB_PRIO[h]:
                h = self.UB_FL[h]
                if h == 0:
                    self._qt(u, new)
                    return self.chs1(ctx, new)
            self.UB_FL[u] = h                          # CHSEH2
            prev = self.UB_BL[h]
            if prev == 0:
                self.SB_HQ[new] = u
                self.UB_BL[u] = 0
            else:
                self.UB_FL[prev] = u
                self.UB_BL[u] = prev
            self.UB_BL[h] = u
            return self.chs1(ctx, new)
        t = self.SB_TQ[new]                            # behind equals
        if t == 0:
            self._chse25(u, new)
            return self.chs1(ctx, new)
        while not p >= self.UB_PRIO[t]:               # CHSE3
            t = self.UB_BL[t]
            if t == 0:
                self._qh(u, new)
                return self.chs1(ctx, new)
        self.UB_BL[u] = t                              # CHSE4
        nxt = self.UB_FL[t]
        if nxt == 0:
            self.SB_TQ[new] = u
        else:
            self.UB_BL[nxt] = u                        # CHSE5
        self.UB_FL[u] = nxt
        self.UB_FL[t] = u
        return self.chs1(ctx, new)

    # --- Special transitions  S:TRNSVEC  :1540 ---------------------------------------

    def stscom(self, ctx):
        return self.t_chse(ctx, STSCOM_I)

    def stsc(self, ctx):
        return self.t_chse(ctx, STSC_I)

    def stiocc(self, ctx):
        return self.t_chse(ctx, STIOCC_I)

    stoc = stiocc                                      # :1545

    def stirc(self, ctx):
        """STIRC / INTERACTIVE  :1544"""
        ctx.r15 |= INTERACTIVE
        self.UH_FLG[ctx.u] = ctx.r15
        return self.t_chse(ctx, STIRC_I)

    def stnop(self, ctx):
        return None

    def stiomf(self, ctx):
        """STIOMF  :1553 - zero DCB to force the block."""
        ctx.dcb = None
        return self.stiip(ctx)

    def stiip(self, ctx):
        """STIIP  :1554 - I/O in progress."""
        u = ctx.u
        if self.UB_MF[u] == 0:
            return PULLE                               # GRANT: the I/O is already done
        ctx.seo = True                                 # LI,R11 T:SEO
        new = SIOW + (ctx.event - E_IIP)
        dcb = ctx.dcb
        if dcb is None:
            return self.rce4(ctx, new)                 # NEWQ
        if dcb.fcn == 0:
            return PULLE
        if is_moc(dcb):
            return self.rce4(ctx, new)
        dcb.waiting = True                             # OR,8 Y8: waiting on this one
        return self.rce4(ctx, new)

    def stioc(self, ctx):
        """STIOC  :1574 - I/O complete."""
        u = ctx.u
        self.UB_MF[u] = (self.UB_MF[u] - 1) & 0xFF
        if not ctx.r12 & mask(SIOW, SIOMF):
            return None
        if self.UB_MF[u] == 0:
            return self._iocom3(ctx)
        if ctx.r3 == SIOMF:
            limit = self.L.SL_BIMF if ctx.r15 & BAT else self.L.SL_OIMF   # IOCOM2
            if limit < self.UB_MF[u]:
                return None
            return self._iocom3(ctx)
        return self._iocom1(ctx)

    def _iocom1(self, ctx):
        dcb = ctx.dcb
        if dcb is None or is_moc(dcb):
            return self.stiocc(ctx)
        if not dcb.waiting or dcb.fcn != 0:
            if self.UB_MF[ctx.u] != 0:                 # IOCOM4
                return None
        dcb.waiting = False                            # IOCOM5
        return self.stiocc(ctx)

    def _iocom3(self, ctx):
        self.S_SEVF += 1
        if ctx.r3 != SIOMF:
            return self._iocom1(ctx)
        return self.stiocc(ctx)

    def stbeeac(self, ctx):
        """STBEEAC  :1649 - flag and change state."""
        ctx.change = True
        return self.stbeea(ctx)

    def stbeea(self, ctx):
        """STBEEA  :1650 - pick X'1000'/X'2000'/X'4000'/X'8000' by event number."""
        ctx.flag = 0x1000 << (((ctx.event | 1) - E_CBK - 1) // 2)
        if ctx.flag == DL_ABRT:
            return self.stabrt(ctx)
        return self.setdl(ctx)

    def stabrt(self, ctx):
        """STABRT  :1615 - abort or off: find a ghost or the COC line."""
        u = ctx.u
        if ctx.r15 & BAT:
            return self.setdl(ctx)
        if u not in self.SB_GJOBUN:
            for line in range(len(self.LB_UN) - 1, -1, -1):
                if self.LB_UN[line] == u:              # COCABRT
                    self.stabrt1(ctx)
                    self.trace(f"COCOFF line {line}")
                    fn = self.hooks.get("COCOFF")
                    return fn(self, line) if fn else None
        return self.stabrt1(ctx)

    def stabrt1(self, ctx):
        ctx.r3 = self.UB_US[ctx.u]                     # (R12 is not reloaded)
        return self.setdl(ctx)

    def setdl(self, ctx):
        """SETDL  :1630"""
        u = ctx.u
        if ctx.r12 & mask(SQR, SQRO):
            r = self.U_MISC[u] >> 24
            if ctx.flag & SH_RFLG[r][1]:
                self.t_uqr(u)
                ctx.change = True
        if self.UH_DL[u] & ctx.flag:
            return None
        self.UH_DL[u] |= ctx.flag
        if ctx.change:
            return self.stirc(ctx)
        return None

    def stasp(self, ctx):
        """STASP  :1668 - special compute at the head of the queue."""
        ctx.head = True
        return self.stsc(ctx)

    def stcrd(self, ctx):
        """STCRD  :1670"""
        if ctx.r15 & EARLY:
            return self._qfora2(ctx)
        return self.rce4(ctx, STI)

    def stqa(self, ctx):
        """STQA  :1674"""
        ctx.r15 = self.UH_FLG[ctx.u]
        if ctx.r15 & EARLY:
            return self._qfora2(ctx)
        return self.rce4(ctx, SQA)

    def _qfora2(self, ctx):
        self.UH_FLG[ctx.u] = ctx.r15 & ~EARLY
        return PULLE

    def stuqa(self, ctx):
        """STUQA  :1683"""
        if ctx.r3 == SQA:
            return self.stsc(ctx)
        return self.stircu(ctx)

    def stircu(self, ctx):
        """STIRCU  :1685 - completion before the block."""
        self.UH_FLG[ctx.u] = ctx.r15 | EARLY
        return None

    def stkot(self, ctx):
        """STKOT  :1692 - kicked out: to the out-of-core twin."""
        ctx.r15 &= ~(RTR | JIC)
        self.UH_FLG[ctx.u] = ctx.r15
        return self.rce4(ctx, self.UB_US[ctx.u] + (STOBO - STOB))

    def stko(self, ctx):
        """STKO  :1697"""
        ctx.r15 &= ~(RTR | JIC)
        self.UH_FLG[ctx.u] = ctx.r15
        if ctx.r3 > SEXU:
            return None
        return self.chse1(ctx, self.UB_PRIO[ctx.u])

    # --- Resources  :1747-1844 -------------------------------------------------------

    def t_res(self, ctx):
        """T:RES  :1755 - odd differences release."""
        k = ctx.event - E_REL
        r = k >> 1
        if k & 1:
            return self.t_rel(ctx, r)
        u = ctx.u                                      # block (T:BLKV is empty)
        self.U_MISC[u] = (r << 24) | self.SB_RQ[r]
        self.UB_PRIO[u] = 0                            # back link
        self.SB_RQ[r] = u                              # (the old head's back link isn't set)
        return self.rce4(ctx, SQR)

    def t_rel(self, ctx, r):
        """T:REL  :1771"""
        routine, flags = SH_RFLG[r]
        if flags & SPECIFIC:                           # RELB
            u = ctx.u if ctx.r12 & mask(SQR, SQRO) else 0
        else:
            u = self.SB_RQ[r]
            if u == 0 and not flags & NULL:
                return None
        if routine is not None:                        # RELA: T:RELV
            return getattr(self, routine.lower())(ctx, r, u)
        return self.t_rel1(ctx, r, u)

    def t_rel1(self, ctx, r, u):
        """T:REL1  :1779 - unqueue and make special compute; FLUSH repeats."""
        if u == 0:
            return None
        self.t_uqr(u)
        # STSC with R4 = the released user. R15 still holds the reporter's flags.
        sub = Ctx(u=u, event=ctx.event, r3=self.UB_US[u], r12=1 << self.UB_US[u], r15=ctx.r15)
        self.stsc(sub)
        if SH_RFLG[r][1] & FLUSH:
            return self.t_rel(ctx, r)
        return None

    def t_uqr(self, u):
        """T:UQR  :1814 - UB:PRIO is the back link, U:MISC byte 3 the forward link."""
        m = self.U_MISC[u]
        r, fl = m >> 24, m & 0xFF
        bl = self.UB_PRIO[u]
        if bl == 0:
            self.SB_RQ[r] = fl
        self.UB_PRIO[fl] = bl
        self.U_MISC[bl] = m
        return r

    def opnunblock(self, ctx, r, u):
        """OPNUNBLOCK  :1837 - one open/close user at a time."""
        if self.OPNCLSUS:
            return None
        ctx.r15 = self.UH_FLG[u] | OPNCLSUSR
        self.UH_FLG[u] = ctx.r15
        self.OPNCLSUS = u
        return self.t_rel1(ctx, r, u)

    def uqfac(self, ctx, r, u):
        """STUQFAC  :1707 - ALLOCAT's buffers, then T:REL1."""
        for i in range(3, -1, -1):
            if not self.buffers[i].unqueue():
                self.screech(0x88, f"ALLOCAT buffer {i}")
        return self.t_rel1(ctx, r, u)

    # --- Log-on and new users  :1859-1980 ---------------------------------------------

    def t_rce(self, line, event):
        """T:RCE  :1859 - an event for a COC line's user."""
        u = self.LB_UN[line]
        if u:
            if event == E_OFF and u < len(self.UH_FLG2):
                self.UH_FLG2[u] |= HANGUP
            if u != 0xFF:
                return self.rce0(u, event)
        return self.logon(line, event)

    def logon(self, line, event):
        """LOGON  :1869 - a break on a line with no user."""
        if event != E_CBK:
            return None
        u = self.SB_HQ[SNULL]
        if u == 0 or self.S_OUIS >= self.L.S_OUAIS:
            return None
        if not any(self.L.S_OUAIS < g for g in self.M_FREE_GRAN):
            return None
        self.S_OUIS += 1
        self.LB_UN[line] = u
        self.trace(f"LOGON line {line}: user {u}")
        if self.on_logon is not None:
            self.on_logon(self, u, line)               # UB:ACP: LOGON (online.py)
        return self.add1(u, self.L.SL_OPRIO)

    def add1(self, u, prio, resource=0):
        """ADD1  :1922 - add a user (on-line, batch or ghost)."""
        self.S_CUIS += 1
        self.UB_PRIOB[u] = prio
        return self.getjit(u, resource)

    def getjit(self, u, resource=0):
        """GETJIT  :1926 - a JIT granule on the swap device with most free."""
        best = len(self.M_FREE_GRAN) - 1
        for d in range(len(self.M_FREE_GRAN) - 1, -1, -1):
            if self.M_FREE_GRAN[d] > self.M_FREE_GRAN[best]:
                best = d
        self.UB_SWAPI[u] = best
        if self.M_FREE_GRAN[best] > 0:                 # T:SGAJIT (stand-in)
            self.M_FREE_GRAN[best] -= 1
            gran = self.M_JITPAGE[best]
            self.M_JITPAGE[best] += self.MB_SPACEJIT[best]
            action, aj = "STIRC", gran
        else:
            action, aj = "T_RES", -1                   # GJG4: block for a disc page
        self.UH_AJIT[u] = aj & 0xFFFF
        self.UH_FLG[u] |= TIC | PPSWP
        self.UH_FLG2[u] = SQUAN | SWAPD
        self.UB_PCT[u] = 1 + self.L.BIG
        self.UH_DL[u] = 0
        self.do_list[u] = []
        self.jit[u] = Jit()
        if resource:                                   # RESCNCT: RAS:DOL
            self.do_list[u].append(DoEntry(7, routine=lambda s, uu: s.trace(
                f"RAS:DOL resource {resource} for user {uu}")))
        r3 = self.UB_US[u]
        ctx = Ctx(u=u, event=E_ND, r3=r3, r12=1 << r3, r15=self.UH_FLG[u])
        return self.stirc(ctx) if action == "STIRC" else self.t_res(ctx)

    def t_delus(self, u):
        """T:DELUS (STPNR.txt:1887), not translated: put the slot back in SNULL."""
        self.trace(f"T:DELUS user {u} (stand-in)")
        if u < self.MING:
            # A reserved slot isn't kept in the SNULL queue: ADDGJOB links it in again
            # when the ghost next starts (T$OV.txt:404). Unlinked, state SNULL.
            self._unlink(u, self.UB_US[u])
            self.UB_FL[u] = self.UB_BL[u] = 0
            self.UB_US[u] = SNULL
            self.S_EVF += 1
        else:
            self.rce4(Ctx(u=u, event=0, r3=self.UB_US[u], r12=0, r15=0), SNULL)
        self.M_FPPC += self.JBPPC[u]
        self.JBPPC[u] = 0
        self.S_SEVF += 1                               # the swap set changed (assumed)
        self.UH_FLG[u] = self.UH_FLG2[u] = self.UH_DL[u] = self.UB_MF[u] = 0
        self.do_list[u] = []
        self.S_CUIS -= 1
        self.breaks.discard(u)
        self.hangups.discard(u)
        if u in self.LB_UN:
            self.LB_UN[self.LB_UN.index(u)] = 0
            self.S_OUIS -= 1
        if u in self.SB_GJOBUN:
            self.SB_GJOBUN[self.SB_GJOBUN.index(u)] = 0  # the name stays in S:GJOBTBL
            self.S_GUIS -= 1
        self.programs.pop(u, None)
        for gen in reversed(self.stacks.pop(u, None) or []):
            try:
                gen.close()                            # e.g. a Python program's thread stops
            except ValueError:
                pass                                   # the one running now ends by itself
        self._send.pop(u, None)
        self.ended.append(u)
        return "SE"

    # --- T:GJOBSTRT  T$OV.txt:386 ----------------------------------------------------

    def t_gjobstrt(self, name, program=None, prio=None, account=":SYS", pages=None):
        """T:GJOBSTRT / T:GJOB - start a ghost by name. Returns (CC, user): GJ_STARTED,
        GJ_WOKEN (it was asleep: E:WU), GJ_RUNNING, or GJ_FAILED."""
        prio = self.L.SL_GPRIO if prio is None else prio
        slot = next((i for i in range(self.MAXG, 0, -1)
                     if self.S_GJOBTBL[i] == (name, account)), 0)   # CD,0 S:GJOBTBL,5
        if slot:
            u = self.SB_GJOBUN[slot]                   # GJOB01
            if u == 0:
                return self._addgjob(slot, name, account, program, prio, pages)
            if self.UB_US[u] in (SW, SQFI):
                self.trace(f"T:GJOBSTRT {name}: user {u} asleep, E:WU")
                self.t_rue(u, E_WU)
                return GJ_WOKEN, u
            return GJ_RUNNING, u
        if self.bootflg():
            self.trace(f"T:GJOBSTRT {name}: not up yet (BOOTFLG), no new names")
            return GJ_FAILED, 0                        # "NO NO-NAMES IF NOT UP YET"
        slot = next((i for i in range(self.MAXG, 0, -1) if self.S_GJOBTBL[i] is None), 0)
        if not slot:
            return GJ_FAILED, 0
        return self._addgjob(slot, name, account, program, prio, pages)

    def link_reserved(self, u):
        """ADDGJOB  T$OV.txt:404 - a reserved slot (below MING) goes on the head of SNULL."""
        h = self.SB_HQ[SNULL]
        if h == 0:
            self.SB_TQ[SNULL] = u
        self.SB_HQ[SNULL] = u
        self.UB_BL[h] = u
        self.UB_FL[u] = h

    def _addgjob(self, slot, name, account, program, prio, pages):
        if slot < self.MING:
            self.link_reserved(slot)                   # the user number is the slot
        u = self.SB_HQ[SNULL]                          # ADDGJOB1
        if u == 0:
            return GJ_FAILED, 0
        self.SB_GJOBUN[slot] = u
        self.UB_PRIOB[u] = prio
        self.S_GJOBTBL[slot] = (name, account)
        self.S_GUIS += 1
        program = (program or self.ghost_programs.get(name)
                   or (self.program_loader and self.program_loader(name, account))
                   or _no_program)
        self.programs[u] = program(self, u) if callable(program) else program
        self.trace(f"T:GJOBSTRT {name}: slot {slot}, user {u}")
        self.add1(u, prio)
        if pages is not None:
            self.UB_PCT[u] = pages
        return GJ_STARTED, u

    def rename_ghost(self, u, name):
        """STD,6 S:GJOBTBL,1 (GHOST1D.txt:368) - change a running ghost's table name."""
        slot = self.SB_GJOBUN.index(u)
        self.S_GJOBTBL[slot] = (name, self.S_GJOBTBL[slot][1])

    def start_ghost(self, u, prio, program, pages=None):
        """A ghost in user slot u, without a name lookup (for tests and the demo)."""
        slot = next(i for i in range(1, self.MAXG + 1)
                    if self.S_GJOBTBL[i] is None and not self.SB_GJOBUN[i])
        self.S_GJOBTBL[slot] = (f"#{u}", ":SYS")
        self.SB_GJOBUN[slot] = u
        self.S_GUIS += 1
        if u < self.MING:
            self.link_reserved(u)
        self.programs[u] = program
        self.add1(u, prio)
        if pages is not None:
            self.UB_PCT[u] = pages

    def start_online(self, line, program, pages=None):
        """A break on an idle COC line: T:RCE, LOGON, ADD1; the program plays the user."""
        before = self.LB_UN[line]
        self.t_rce(line, E_CBK)
        u = self.LB_UN[line]
        if u and u != before:
            self.programs[u] = program
            if pages is not None:
                self.UB_PCT[u] = pages
        return u if u != before else 0

    # --- Accounting  ACCT.txt:27 -----------------------------------------------------

    def t_acctex(self, u):
        """T:ACCTEX (ACCT.txt:27), the part SCHED relies on: a new quantum."""
        j = self.jit[u]
        used = j.DELTAT - j.IDELTAT + j.OVHTIM
        j.UTIME += used
        j.DELTAT = j.IDELTAT = -self.L.SL_QUAN
        j.CTIME = j.OVHTIM = 0

    # --- T:SE  :1021 -------------------------------------------------------------------

    def t_se(self):
        """T:SE: swap schedule, SACT, then SEO."""
        self.t_ss()
        return self.seo()                              # BAL,11 SACT: no symbionts here

    def seo(self):
        """SEO  :1036 - the first ready user in SRT, SC0..SC10, else idle."""
        while True:
            u = self._first(lambda f: f & RTR)
            if u:
                result = self.se1(u)
                if result == "SE":                     # recycle
                    self.t_ss()
                    continue
                return result
            return self.idle()

    def _first(self, want):
        """The scan  :1040 - first non-empty queue among states 1-7, else start at 8."""
        start = next((s for s in range(1, 8) if self.SB_HQ[s]), 8)
        for state in range(start, SEXU + 1):
            u = self.SB_HQ[state]
            while u:
                if want(self.UH_FLG[u]):
                    return u
                u = self.UB_FL[u]
        return 0

    def idle(self):
        """:1059 - nobody ready: the shutdown check, then the idle counters and WAIT."""
        self.S_CUP = 0xFF
        if self.S_CUIS + self.GOODNGT <= 0 and not self.symbionts_busy:
            self.screech(0x404, "idle check")
            return "SHUTDOWN"
        reason = self.S_SIP + (2 if self.SB_HQ[SIOW] or self.SB_HQ[SIOMF] else 0)
        self.S_CLOCK4 = ("C", ("IDLE", "IDLES", "IDLEW", "IDLESW")[reason])
        return None

    def se1(self, u):
        """SE1  :1129 - place the user in execution."""
        self.S_CUN = u
        flags = self.UH_FLG[u]
        if not flags & RTR:
            return "SE"                                # SWAPPER DIDN'T STEAL HIM
        prio = self.UB_PRIO[u]
        if prio < self.UB_PRIOB[u]:
            prio += self.L.S_PRIODEC
            self.UB_PRIO[u] = prio
        self.S_CUP = prio
        self.S_HIR -= 1
        self.rce4(Ctx(u=u, event=0, r3=self.UB_US[u], r12=0, r15=flags), SCU)
        # "RESET CAL INTERRUPT BIT" - XFDFF really clears RMAHOLD, and the result is
        # only stored on the swap-error and just-swapped-in paths.
        f2 = self.UH_FLG2[u] & XFDFF
        if f2 & 7:
            errors, f2 = f2 & 7, f2 & ~7
            self.UH_FLG2[u] = f2
            if errors & CTXERR:
                return self.hook("T:DELUSZAP", u)
            if errors & JITERR:
                return self.hook("T:SCRATCH%USER", u)
            self.UH_DL[u] |= DL_ERR                    # SE4D1: user area error
        if f2 & SWAPD:                                 # SE4D
            f2 &= ~SWAPD
            self.t_acctex(u)
            self.UH_FLG2[u] = f2
        j = self.jit[u]
        self.S_CLOCK4 = (u, "OVHTIM")                  # SE4F
        self.U_MISC[u] = j.DELTAT + j.OVHTIM + j.CTIME
        self.S_CLOCK4 = (u, "DELTAT")                  # T:MASTER: a slave-mode user
        if self.UH_DL[u] or self.do_list[u]:
            return self.sse1()
        if j.TIMENT and j.UTIMER <= 0:
            raise NotTranslated("STIMER entry (ALTENT)")
        return ("RUN", u)

    # --- The exit path  :848-1018 ------------------------------------------------------

    def exit_path(self, swap=True):
        """T:SSE (interrupt: T:SS first) or TRAPEXIT/T:SSEM, into SSE0 for S:CUN."""
        if swap:
            self.t_ss()
        return self.sse1()

    def sse1(self):
        """SSE1/SSE11  :890"""
        u = self.S_CUN
        j = self.jit[u]
        if j.RNST or self.UH_DL[u] or self.do_list[u]:
            j.FRS = j.RNST
            result = self.t_dolist(u)
            if result is not None:
                return result
        return self.sse5a(u)

    def t_dolist(self, u):
        """T:DOLIST  :905 - the four flags, then the DO-list entries."""
        j = self.jit[u]
        while True:
            r15 = self.UH_FLG[u]
            flags = self.UH_DL[u] & 0xF000
            self.UH_DL[u] &= 0x0FFF
            if flags & DL_ABRT:                        # SEABRT / T:OFF  :1211
                j.RNST = 0x08 if self.UH_FLG2[u] & HANGUP else 0x10
                if r15 & (TIC | BAT) == TIC | BAT:     # "PRE CCI ABORT": ignore for now
                    return None
                return self.hook("T:TELDELCCI", u)
            if flags & DL_ERR:                         # SEERR  :1229
                j.ERO, j.RNST = 3, 0x20
                return self.hook("SETRNST", u)
            if j.RNST:
                if not r15 & TIC:
                    return self.hook("T:TELDELCCI", u)
            if flags & DL_EC:                          # SE9  :1306
                if r15 & TIC or self.UH_FLG2[u] & RTHOLD:
                    continue                           # ignored: T:SSEM
                j.TELFLGS |= 2
                raise NotTranslated("control-Y to the command processor (T:ECCP)")
            if flags & DL_BRK:                         # SE7  :1291
                if r15 & TIC and not j.INTENT:
                    continue                           # TEL has no break control: ignored
                raise NotTranslated("break to TEL, Delta or M:INT (SE6, DELTAGO, ALTENT)")
            dl = self.do_list[u]
            if not dl:
                return None
            entry = dl[0]
            if entry.prio > self.UB_PRIOB[u]:
                return None                            # not now
            if entry.type == 2 and r15 & (INHIBIT | TIC | DIC):
                return None
            dl.pop(0)
            if entry.type not in (1, 7):
                raise NotTranslated(f"DO-list type {entry.type} (RT:INTENTRY, COC slave line)")
            entry.routine(self, u)                     # T:ECBSTORE, or *R7; then T:DOLISTR

    def sse5a(self, u):
        """SSE5A  :981 - the swap quantum and the quantum."""
        j = self.jit[u]
        used = j.DELTAT + j.OVHTIM + j.CTIME - j.IDELTAT
        boost = False
        if used >= self.L.SL_SQNT:
            boost = True
            if used >= self.L.SL_SQUAN:
                if self.UH_FLG2[u] & SQUAN:
                    self.S_SEVF += 1
                    self.UH_FLG2[u] &= ~SQUAN
                boost = False                          # SSE6E: AND,R4 M8
        total = used + j.IDELTAT
        if total < 0:
            return self.sse41(u, total, boost)
        self.t_acctex(u)                               # quantum end
        self.UB_PRIO[u] = self.UB_PRIOB[u]
        self.S_SEVF += 1
        self.trace(f"user {u}: quantum end")
        self.t_chse0(Ctx(u=u, event=0, r3=self.UB_US[u], r12=0, r15=self.UH_FLG[u]))
        return "SE"

    def sse41(self, u, total, boost):
        """SSE41  :794 - preempt after S:RTIR if someone more urgent is in core."""
        if total - self.U_MISC[u] < self.S_RTIR:
            return ("RUN", u)
        self.S_RTIR = self.L.SL_QMIN
        if self.S_HIR <= 0:
            return ("RUN", u)
        prio = self.UB_PRIO[u] + (self.L.SL_SQPB if boost else 0)   # SSE43
        self.trace(f"user {u}: preempted (S:HIR {self.S_HIR})")
        self.chse0(Ctx(u=u, event=0, r3=self.UB_US[u], r12=0, r15=self.UH_FLG[u]), prio)
        return "SEO"

    # --- T:SS, the swap scheduler  :2102 -----------------------------------------------

    def t_ss(self):
        """T:SS  :2109"""
        if self.S_SIP:
            return
        self.S_SIP = 1
        self.S_PCT = self.S_FPPC = self.S_OSS = self.S_PRPC = 0
        self.S_FPL, self.SB_OSUL = [], []
        u = self._first(lambda f: not f & RTR)         # pick a user to swap in
        if not u:
            self.S_ISUN = 0                            # NO1IN
            return self.usersout(0)
        return self.ssin(u)

    def ssin(self, u):
        """SSIN  :2167"""
        if u == self.S_ISUNF and self.S_SEVF == self.S_FSEVF:
            if self.ALLOOUT:
                self.S_ISUN = 0
                return self.usersout(0)
            return self.prout3()
        if self.UH_FLG[u] & BYPASS:
            if not self.giveup7(u):
                return self._next_in(u)                # PIKUS5: still won't fit
            self.UH_FLG[u] &= ~BYPASS
        self.S_ISUN = u                                # SSIN1
        need = self.UB_PCT[u]
        self.SB_PNL = []
        need += self.prcav(self.UB_OV[u])
        f = self.UH_FLG[u]
        if f & JIC:
            need -= self.JBPPC[u]
            if f & TIC:
                need += self.prcav(self.UB_ACP[u])
            else:
                need += self.procavl(u, f)
        elif f & TIC:                                  # CHKDELTEL
            self._incr(self.UB_ACP[u])
            self._incr(self.UB_OV[u])
            need += self.prcav(self.UB_ACP[u])
        else:
            self.iprocs(u)
            self._incr(self.UB_OV[u])
            need += self.procavl(u, f)
        return self.swipepgs(need)

    def _next_in(self, after):
        """PIKUS5: go on with the next user who needs to come in."""
        found = False
        start = next((s for s in range(1, 8) if self.SB_HQ[s]), 8)
        for state in range(start, SEXU + 1):
            u = self.SB_HQ[state]
            while u:
                if found and not self.UH_FLG[u] & RTR:
                    return self.ssin(u)
                if u == after:
                    found = True
                u = self.UB_FL[u]
        self.S_ISUN = 0
        return self.usersout(0)

    def procavl(self, u, f):
        """PROCAVL  :2221 - debugger or special processor, root, overlay."""
        need = 0
        p = self.UB_DB[u] if f & DIC or not self.UB_ASP[u] else self.UB_ASP[u]
        need += self.prcav(p)
        need += self.prcav(self.UB_APR[u])
        need += self.prcav(self.UB_APO[u])
        return need

    def prcav(self, p):
        """PRCAV  :2232 - a processor not in core goes on the in-swap list."""
        if not p:
            return 0
        self.PH_FRQ[p] = self.PH_FRQ.get(p, 0) + 1
        if self.PX_HPP.get(p):
            return 0
        self.C["NOPROC"] += 1
        self.SB_PNL.append(p)
        return self.PB_PSZ.get(p, 0)

    def swipepgs(self, need):
        """SWIPEPGS  :2255"""
        self.S_PCT = need
        if need == 0:
            return self.swapin()                       # GOTEXAC
        self.S_FPPC, self.M_FPPC = self.S_FPPC + self.M_FPPC, 0
        short = need - self.S_FPPC
        if short < 0:
            return self.gotnuf()
        if short == 0:
            return self.swapin()
        for p in sorted(self.PX_HPP):                  # PFA: unused in-core processors
            if self.PX_HPP[p] and self.PB_UC.get(p, 0) == 0:
                self.getprcpg(p)
        short -= self.S_PRPC
        if short > 0:
            return self.usersout(short)
        return self.gotnuf()

    def getprcpg(self, p):
        """GETPRCPG  :2772"""
        self.S_FPL.append((self.PH_FRQ.get(p, 0), p))
        self.S_PRPC += self.PB_PSZ.get(p, 0)

    def usersout(self, short):
        """USERSOUT  :2445 - choose users to swap out, in the SB:SWP order."""
        while True:
            r13 = self.S_EVF
            self.SB_FPN, self.SB_OSUL, self.S_OSS = [], [], 0
            got = 0
            result = None
            for state in SB_SWP[1:]:
                if state <= SEXU:
                    if self.S_ISUN == 0:
                        return self.prout3()
                    if state == 0:
                        return self.giveup()
                u = self.SB_TQ[state]
                while u:
                    if u == self.S_ISUN:
                        return self.giveup()
                    if self.UH_FLG[u] & (JIC | RTR) and self._swappable(u):
                        got += self._take(u, short - got)
                        if self.S_ISUN and got >= short:
                            result = "PROUT2"
                            break
                    u = self.UB_BL[u]
                if result:
                    break
            if result is None:
                return self.giveup()
            if r13 != self.S_EVF:                      # USEROR: events, try again
                self.giveup3()
                continue
            for p in reversed(self.SB_FPN):            # PROUT2
                self.getprcpg(p)
            return self.prout3()

    def _swappable(self, u):
        """USOUT5  :2479"""
        f2 = self.UH_FLG2[u]
        if f2 & (RTHOLD | CALINT) or self.UB_MF[u]:
            return False
        f = self.UH_FLG[u]
        if self.UB_US[u] <= SEXU and f & RTR:
            if f2 & (RMAHOLD | SQUAN):
                return False
        return len(self.SB_OSUL) < SMAXOUT - 1        # USOUT9
        # (A batch job in a held partition, PLH:FLG, is also passed by: no partitions here.)

    def _take(self, u, short):
        """USOUT9 - add the user and the processors that come free with them."""
        pages = self.JBPPC[u]
        self.S_OSS += pages
        self.SB_OSUL.append(u)
        got = pages
        procs = [self.UB_OV[u]]
        f = self.UH_FLG[u]
        if f & TIC:
            procs.append(self.UB_ACP[u])
        else:
            procs.append(self.UB_DB[u] if f & DIC or not self.UB_ASP[u] else self.UB_ASP[u])
            procs += [self.UB_APR[u], self.UB_APO[u]]
        for p in procs:                                # DECR then ADDPRC
            self.PB_UC[p] = self.PB_UC.get(p, 0) - 1
            if self.PB_UC[p] == 0 and got < short and self.PX_HPP.get(p) and self.PB_PSZ.get(p):
                got += self.PB_PSZ[p]
                self.SB_FPN.append(p)
        return got

    def prout3(self):
        """PROUT3  :2567 - report E:KO for the chosen users."""
        if not self.SB_OSUL:
            return self.ssexit()
        for u in reversed(self.SB_OSUL):
            self.t_rue(u, E_KO)
        return self.gotnuf()

    def gotnuf(self):
        """GOTNUF  :2319"""
        self.S_SEVF += 1
        if self.S_ISUN == 0:
            return self.swapout()
        short = self.S_PCT - self.S_OSS - self.S_FPPC
        if short > 0:
            self.S_FPL.sort(reverse=True)              # SORTL: by frequency
            while short > 0 and self.S_FPL:            # KOPROC: least called first
                _, p = self.S_FPL.pop()
                size = self.PB_PSZ.get(p, 0)
                self.trace(f"T:SS: processor {p} out ({size} pages)")
                self.PX_HPP[p] = 0
                self.S_FPPC += size
                short -= size
        if short < 0:                                  # RETXCS
            back = min(-short, self.S_FPPC)
            self.S_FPPC -= back
            self.M_FPPC += back
        return self.doswap()

    def doswap(self):
        """DOSWAP  :2388"""
        if self.SB_OSUL:
            return self.swapout()
        return self.swapin()

    def swapout(self):
        """SWAPOUT (SWAPPER.txt:260), a stand-in: the users' pages go to the swapper."""
        for u in self.SB_OSUL:
            self.trace(f"SWAPOUT user {u} ({self.JBPPC[u]} pages)")
            self.S_FPPC += self.JBPPC[u]
            self.JBPPC[u] = 0
        if self.S_ISUN:
            return self.swapin()
        self.M_FPPC += self.S_FPPC
        self.S_FPPC = 0
        return self.ssexit()

    def swapin(self):
        """SWAPIN (SWAPPER.txt:587), a stand-in: the user and their processors come in."""
        u = self.S_ISUN
        if self.S_FPPC + self.M_FPPC < self.S_PCT:
            raise AssertionError(f"SWAPIN: {self.S_PCT} pages needed, {self.S_FPPC} held")
        take = min(self.S_PCT, self.S_FPPC)
        self.M_FPPC -= self.S_PCT - take
        self.S_FPPC -= take
        for p in self.SB_PNL:
            self.PX_HPP[p] = self.PB_PSZ.get(p, 0)
        self.JBPPC[u] = self.UB_PCT[u]
        self.UH_FLG[u] |= RTR | JIC
        self.UH_FLG2[u] |= SWAPD | SQUAN               # SWAPPER.txt:1429
        if self.UB_PRIO[u] < self.S_CUP:
            self.S_HIR = max(self.S_HIR + 1, 1)
        self.trace(f"SWAPIN user {u} ({self.S_PCT} pages)")
        self.M_FPPC += self.S_FPPC
        self.S_FPPC = 0
        return self.ssexit()

    def giveup(self):
        """GIVEUP  :2580 - no swap set."""
        self.C["NSP"] += 1
        self.M_FPPC += self.S_FPPC
        self.S_FPPC = 0
        self.giveup3()
        u = self.S_ISUN                                # GIVEUP4
        self.S_ISUNF, self.S_FSEVF = u, self.S_SEVF
        f = self.UH_FLG[u]
        if not f & JIC:
            self._decr(self.UB_OV[u])
            self.dtorp(u)
        net, gross = self.t_totesz(u)                  # GIVEUP1
        if net > self.S_PCORE + 6:
            return self.screech(0x62, f"user {u} never fits")
        # As intended (R6 = GIVEUPA), not as read: see docs/scheduler.md.
        if not self.giveup8(net):
            self.UH_FLG[u] |= BYPASS                   # GIVEUPB
            self.trace(f"T:SS: user {u} doesn't fit now: BYPASS")
        return self.ssexit()

    def giveup3(self):
        """GIVEUP3  :2599 - give back the processor counts of the out-swap list."""
        for u in reversed(self.SB_OSUL):
            self.itorp(u)
            self._incr(self.UB_OV[u])
        self.SB_OSUL = []

    def giveup7(self, u):
        """GIVEUP7  :2626 - True if the user fits now."""
        net, gross = self.t_totesz(u)
        if gross + 6 > self.S_PCORE:
            self.screech(0x62, f"user {u} never fits")
            return False
        return self.giveup8(net)

    def giveup8(self, net):
        """GIVEUP8  :2646 - fits in the fluid pages? Otherwise ask the page stealer."""
        fluid = self.S_ACORE - self.S_RTCORE
        stealable = max(self.S_STL_ - self.L.SL_RSVP, 0)
        deficit = net - fluid
        if deficit <= 0:
            return True
        if deficit <= stealable:
            self.S_STLC = min(self.S_STLC, -deficit)
        return False

    def ssexit(self):
        """SSEXIT  :2669"""
        self.S_SIP = 0
        return None

    def t_totesz(self, u):
        """T:TOTESZ  :2686 - (net of locked processors, gross)."""
        f = self.UH_FLG[u]
        net = gross = self.UB_PCT[u]
        if f & TIC:
            procs = [self.UB_ACP[u]]
        elif f & DIC:
            procs = [self.UB_DB[u]]
        else:
            procs = [self.UB_APR[u], self.UB_APO[u], self.UB_ASP[u] or self.UB_DB[u]]
        for p in procs + [self.UB_OV[u]]:
            if p:
                size = self.PB_PSZ.get(p, 0)
                gross += size
                if not self.PB_LCT.get(p):
                    net += size
        return net, gross

    # Use counts  :2729-2770
    def _incr(self, p):
        self.PB_UC[p] = self.PB_UC.get(p, 0) + 1

    def _decr(self, p):
        self.PB_UC[p] = self.PB_UC.get(p, 0) - 1

    def iprocs(self, u):
        self._incr(self.UB_APR[u])
        self._incr(self.UB_APO[u])
        self._incr(self.UB_DB[u] if self.UH_FLG[u] & DIC or not self.UB_ASP[u] else self.UB_ASP[u])

    def itorp(self, u):
        if self.UH_FLG[u] & TIC:
            return self._incr(self.UB_ACP[u])
        return self.iprocs(u)

    def dtorp(self, u):
        if self.UH_FLG[u] & TIC:
            return self._decr(self.UB_ACP[u])
        self._decr(self.UB_APR[u])
        self._decr(self.UB_APO[u])
        self._decr(self.UB_DB[u] if self.UH_FLG[u] & DIC or not self.UB_ASP[u] else self.UB_ASP[u])

    # --- The driver ------------------------------------------------------------------

    def t_reg(self, event, dcb=None):
        """T:REG  :1343 - report for the current user and give up control."""
        result = self.t_re(event, dcb)
        if result == PULLE:
            return ("RUN", self.S_CUN)
        return result or "SE"

    def run(self, until=None, max_steps=10000):
        """Schedule and run the stand-in programs until nothing is left to do, or
        ``until`` clock units have passed. Returns 'idle', 'shutdown' or 'time'. A run
        stopped by ``until`` carries on where it stopped on the next call."""
        nxt, self._next = self._next, "SE"
        for _ in range(max_steps):
            if until is not None and self.now >= until:
                self._next = nxt
                return "time"
            if nxt == "SE":
                nxt = self.t_se()
            elif nxt == "SEO":
                nxt = self.seo()
            if nxt == "SHUTDOWN":
                return "shutdown"
            if nxt is None:                            # idle: WAIT for the next interrupt
                if not self.timers:
                    return "idle"
                due = self.timers[0][0]
                if until is not None:
                    due = min(due, until)
                self.clock(max(due - self.now, 0))
                self.interrupts()
                nxt = "SE"                             # T:SSE ... back into the idle loop, T:SE
                continue
            if isinstance(nxt, tuple):
                nxt = self.pulle(nxt[1])
        raise RuntimeError("scheduler run: too many steps")

    def _cal(self):
        if self.cal is None:
            from .cal import CalProcessor
            self.cal = CalProcessor(self)
        return self.cal

    def pulle(self, u):
        """T:PULLE  :2069 - back into the user: resume its program. A user whose line
        dropped is removed; a BREAK goes to the BREAK hook (online.py), as the break
        address STBEEA set up would."""
        if u in self.hangups:
            self.hangups.discard(u)
            self.breaks.discard(u)
            return self.hook("HANGUP", u)
        if u in self.breaks:
            self.breaks.discard(u)
            if "BREAK" in self.hooks:
                return self.hook("BREAK", u)
        stack = self.stacks.get(u)
        if stack is None:
            prog = self.programs.get(u)
            if prog is None:
                return self.hook("T:DELUS", u)
            stack = self.stacks[u] = [prog]
        try:
            req = stack[-1].send(self._send.pop(u, None))
        except NotTranslated as e:
            if "NOT TRANSLATED" not in self.hooks:
                raise
            self.trace(f"user {u}: not translated: {e}")
            self.not_translated[u] = e                 # the hook says what happened
            return self.hook("NOT TRANSLATED", u)
        except StopIteration as e:
            stack.pop()
            if not stack:
                return self.t_delus(u)                 # the program ended: it logs off
            return self._cal().finish(u, e.value)      # the monitor's CAL processing ended
        if isinstance(req, (Cal1, CalAt)):
            stack.append(self._cal().trap(u, req))     # trap X'48': into the monitor
            return ("RUN", u)
        if isinstance(req, Compute):
            self.clock(req.n)
            self.interrupts()                          # T:SSE for what came due
            self.t_ss()
            return self.sse1()                         # CLK4 -> SSE1
        if isinstance(req, Sleep):
            if req.n is not None:
                self.after(req.n, E_WU, u)
            return self.t_reg(E_SL)
        if isinstance(req, Io):
            self.UB_MF[u] += 1
            self.after(req.n, E_IC, u, req.dcb)
            result = self.t_re(E_IIP, req.dcb)         # T:IOREG
            if result == PULLE:
                return ("RUN", u)
            return "SEO"                               # STIIP changed the return to T:SEO
        if isinstance(req, Report):
            return self.t_reg(req.event, req.dcb)
        if isinstance(req, Release):
            if req.user:
                self.t_rue(req.user, req.event)
            else:
                self.t_re(req.event)
            return self.exit_path(swap=False)          # TRAPEXIT
        if isinstance(req, Call):
            if req.what:
                self.trace(f"user {u}: {req.what}")
            req.fn(self, u)
            if self.S_CUN != u or self.UB_US[u] != SCU:
                return "SE"                            # it logged itself off, or blocked
            return self.exit_path(swap=False)          # TRAPEXIT
        raise TypeError(f"user {u}: unknown request {req!r}")


def demo():
    """Three ghosts and an on-line user on a small machine (12 pages for 16 pages of
    users, so T:SS has to swap). When the last user ends, S:CUIS is 0 and the idle
    check executes SCREECH X'404', as after a ZAP. Returns (scheduler, outcome)."""
    s = Scheduler(smuis=8, ming=4, pages=12, screech=lambda code, why: None)

    def cruncher(n):
        for _ in range(n):
            yield Compute(40)

    def sleeper():
        for _ in range(3):
            yield Compute(5)
            yield Sleep(150)

    def io_user():
        for _ in range(3):
            yield Compute(10)
            yield Io(30)

    s.start_ghost(1, 0xF4, cruncher(8), pages=5)
    s.start_ghost(2, 0xF4, cruncher(8), pages=5)
    s.start_ghost(3, 0xF0, sleeper(), pages=2)
    s.start_online(0, io_user(), pages=4)
    outcome = s.run()
    return s, outcome
