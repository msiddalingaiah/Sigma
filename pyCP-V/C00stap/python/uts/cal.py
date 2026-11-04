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
CLOCK4's wake-up; overlays have invented sizes; user trap control (J:USENT) isn't
modeled, so CALBAD always aborts.
"""

from dataclasses import dataclass, field, replace

from .monitor import NotTranslated
from .sched import E_AP, E_IC, E_IIP, E_IP, E_SL, E_WU, RTR, TIC, Dcb, Report

# --- Instruction and FPT layout -------------------------------------------------------

OP_CAL1, OP_EXU = 0x04, 0x25
INDIRECT = 0x80000000
J_JIT = 0x46 * 512              # JIT.txt:272 JJITVP: a PSD at or below this is the monitor
FPT_ADDR, CAL_ADDR = 0xA000, 0xA100   # where a stand-in's FPT and CAL1 go (invented)
M_OC, M_UC, M_XX = 0x8D00, 0x8D10, 0x8D20   # the monitor's DCB addresses (invented)
WAIT_UNIT = 600                 # clock units (2 ms) per M:WAIT unit: 1/50 minute (assumed)
TMS = 0x00800000                # FPT word 0 flag for M:TIME's binary result (Y008)


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
F_NWK, F_ONWK = 0x08, 0x04                     # NEWKEY, ONEWKEY flags (positions assumed)
TYCOR = [0, 0, 0, 0, 1, 1, 1, 1]                   # IOQ.txt:763: typewriter read 0, write 1
CODE = {2: 0x07, 3: 0x1D, 4: 0x04, 5: 0x1C, 6: 0x05, 7: 0x06, 8: 0x41, 9: 0x45,
        0xA: 0x57, 0xD: 0x33, 0xE: 0x5B, 0xF: 0x5C, 0x13: 0x4F}   # IORT.txt:1168


class CalAbort(Exception):
    def __init__(self, code):
        self.code = code


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
        self.account = {}                              # J:JIT's ACCN per user (:SYS if none)
        self.running = {}                              # M:XX: (name, account) of the program
        self.ended = {}                                # user -> how a CAL ended them
        self.hooks = {}
        self.io = None                                 # io.IOSystem, from attach_io
        self.fs = None                                 # files.FileSystem
        self.dcb_objs = {}                             # user -> {address: Dcb}
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
        """CAL1P (ENTRY.txt:248) and T:CTRAPM: trap X'48', into the monitor."""
        psd = self.place(u, req)
        self.s.S_CLOCK4 = (u, "OVHTIM")                # T:CTRAPM: overhead
        try:
            ctx = self.cal1p11(u, psd)
            result = yield from self.dispatch(ctx)
        except CalAbort as e:
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
        if code in (0x2D, 0x2E):
            raise NotTranslated(f"CAL1,1 code X'{code:02X}': assign/merge, IORT CAL11N7")
        if code == 0x29:                               # CHECK: IORT IOCHEK
            return (yield from self.iochek(ctx, self.dcb_at(u, dcb)))
        for c, target in reversed(C11CDS):             # CHKCAL1, from NC11S down
            if c == code:
                if dcb == M_UC:
                    raise CalAbort(0xAE)               # only read/write/device on M:UC
                return (yield from self.invoke(ctx, target))
        if code in DEVCDS:
            return (yield from self.invoke(ctx, Res("IOSDEV")))
        raise CalAbort(0xAE)

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
            for i in range(4):
                s.umem[u][block + i] = text[4 * i:4 * i + 4]
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
        a = address & 0x1FFFF
        return self.monitor_dcbs.get(a) or self.dcb_objs.get(u, {}).get(a)

    def put_text(self, u, address, text, textc=False):
        """Store text in the user's memory, four characters a word (TEXTC: count first)."""
        if textc:
            text = chr(len(text)) + text
        for i in range(0, len(text), 4):
            self.s.umem[u][address + i // 4] = text[i:i + 4].ljust(4, "\0")

    def read_text(self, u, address, btd, count):
        """Bytes from the user's memory: word ``address`` plus ``btd`` bytes."""
        out, n = [], btd + count
        for i in range((n + 3) // 4):
            w = self.s.umem[u].get(address + i, "")
            if isinstance(w, int):
                w = "".join(chr((w >> s) & 0xFF) for s in (24, 16, 8, 0))
            out.append(str(w).ljust(4, "\0"))
        return "".join(out)[btd:n]

    def _params(self, u, words):
        """JHKBIT  IORT.txt:393 - take a parameter word: indirect through memory or a register."""
        def take():
            w = next(words)
            if w & INDIRECT:
                a = w & 0x1FFFF
                return self.s.uregs[u][a] if not a & 0x1FFF0 else self.s.umem[u].get(a, 0)
            return w
        return take

    def cal11n7(self, ctx, dcb, write):
        """CAL11N7  IORT.txt:209 - the fast CAL path for READ and WRITE."""
        presence = self.fetch(ctx.u, ctx.r7)           # FPT word 1
        words = (self.s.umem[ctx.u].get(ctx.r7 + 1 + i, 0) for i in range(16))
        if not dcb.open:                               # MSRRDWTA: A DEFAULT OPN
            if dcb.asn != 1:
                raise NotTranslated("default OPEN of a closed device DCB")
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
        if not write:
            raise NotTranslated("device read (MSRRED / MSROTHR)")
        return (yield from self.msrwrt(ctx, dcb))

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

    def msr012(self, ctx, dcb, code, sub=0):
        """MSR012 / MERC  IORT.txt:896, :1557 - to the user's routine, or the run status."""
        j = self.s.jit[ctx.u]
        error = bool(code & 0xC0)
        sr3 = (code << 24) | (dcb.address & 0x1FFFF)
        routine = (j.ERO if error else j.ABO) & 0x1FFFF
        self.trace(f"{'error' if error else 'abnormal'} X'{code:02X}'"
                   + (f"-{sub:02X}" if sub else "") + f" on {dcb.name}"
                   + (f": routine X'{routine:X}'" if routine else ""))
        if not routine and error:                      # MERC
            j.ABC = code
            j.RNST = 0x01 if code & 0x80 else 0x02     # I/O ERROR
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
        if u in s.LB_UN and not oc_only:
            raise NotTranslated("M:KEYIN on a terminal (M:UC, COC)")
        take = self._params(u, (s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(4)))
        take()                                         # the message (CHKBIT1)
        buf = take() & 0x1FFFF if presence & 0x40000000 else 0
        size = take() & 0xFFFF if presence & 0x20000000 else 60   # USE DEFAULT FOR LIMIT
        if presence & 0x10000000:
            raise NotTranslated("M:KEYIN with an ECB")
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
            self.write_bytes(u, buf, 0, (chr(len(reply)) + reply).encode("latin-1"))
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
            dcb = self.monitor_dcbs[M_UC]              # TYPE, on-line: M:UC
        else:
            dcb = self.monitor_dcbs[M_OC]              # MESSAGE, or TYPE for batch/ghost
        take = self._params(u, (self.s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(2)))
        message = take() & 0x1FFFF                     # CHKBIT1: the TEXTC
        size = ord(self.read_text(u, message, 0, 1) or "\0")   # LB,D2 *D1
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
        dcb.usr = account_key(dcb.account) != account_key(who.account)   # USR X'4000'
        try:
            cfu = self.fs.open(dcb.fname, dcb.account, dcb.fun, dcb.keym,
                               org={0: 1, 0x10: 3}.get(dcb.org, 2), size=dcb.rstore,
                               who=who, password=dcb.prot.get(0x03), prot=dcb.prot)
        except FileError as e:
            return e.code
        dcb.cfu, dcb.open, dcb.kbuf = cfu, True, None
        dcb.special = self.fs.access == "special"      # SEC97: X'100'
        # An existing file keeps its organization (OPNF reads the X'09' VLP); the DCB
        # follows it. Whether OPEN overrides the DCB's ORG this way wasn't traced.
        if isinstance(cfu.file, ConsecutiveFile):
            dcb.org, dcb.cpos = 0, Position()
        elif isinstance(cfu.file, RandomFile):
            dcb.org, dcb.rgran = 0x10, 0
        else:
            dcb.org = 0x20
        return 0

    def file_open(self, ctx):
        """M:OPEN (CAL1,1 X'14', overlay OPEN entry 0)."""
        u, dcb = ctx.u, self.dcb_at(ctx.u, ctx.r6)
        if self.fs is None:
            raise NotTranslated("M:OPEN: no file system attached")
        take = self._params(u, (self.s.umem[u].get(ctx.r7 + 1 + i, 0) for i in range(2)))
        presence, j = self.fetch(u, ctx.r7), self.s.jit[u]
        if presence & P_ERR:
            j.ERO = take() & 0x1FFFF
        if presence & P_ABN:
            j.ABO = take() & 0x1FFFF
        if not dcb.open:
            code = self._open(u, dcb)
            if code:
                return self.msr012(ctx, dcb, code)     # X'03': no such file (abnormal)
        return self.pullallexit(ctx, 0, 0)
        yield

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
        n = ord(self.read_text(u, dcb.kad, 0, 1) or "\0")
        from .files import EBCDIC
        return self.read_text(u, dcb.kad, 1, n).encode(EBCDIC)   # memory holds characters

    def write_bytes(self, u, address, btd, data):
        """RECTRAN into the user's buffer: ``data`` at word ``address`` + ``btd`` bytes."""
        old = self.read_text(u, address, 0, btd + len(data))
        new = old[:btd] + data.decode("latin-1")
        for i in range(0, len(new), 4):
            self.s.umem[u][address + i // 4] = new[i:i + 4].ljust(4, "\0")

    def isequb(self, ctx, dcb):
        """ISEQUB  RDF.txt:2443 - a keyed read (KAD) or the next record (after KBUF)."""
        from .files import EBCDIC
        kf, u = dcb.cfu.file, ctx.u
        if dcb.org == 0:
            return self.seq_read(ctx, dcb)             # BAZ SEQ0: CONSECUTIVE
        if dcb.org == 0x10:
            return self.rwrand(ctx, dcb, write=False)  # BANZ RWRAND: IT'S RANDOM
        if dcb.kad:
            key = self._key(u, dcb)
            data = kf.read(key)
            if data is None:
                return self.msr012(ctx, dcb, 0x43)     # KEYER3: RETURN1--DIDNT FIND
        else:
            nxt = kf.read_next(dcb.kbuf)
            if nxt is None:
                dcb.tyc, dcb.egv = 7, True             # end of file: TYC 7
                return self.msr012(ctx, dcb, CODE[7])
            key, data = nxt
        dcb.kbuf = key                                 # the key goes into KBUF
        n = min(len(data), dcb.rws)
        self.write_bytes(u, dcb.buf, dcb.btd, data[:n])
        dcb.ars, dcb.tyc, dcb.last = len(data), 1, "read"
        self.trace(f"READ {dcb.name} key {key.decode(EBCDIC)!r}: {len(data)} bytes")
        return self.pullallexit(ctx, 0, 0)

    def iosfile(self, ctx, dcb):
        """IOSFILE / IOSEQUB  WRTF.txt:153, :236 - a keyed write; without a key, the key
        of the record just read (the implied key), else an operation error."""
        from .files import FileError, EBCDIC
        kf, u = dcb.cfu.file, ctx.u
        if dcb.fun == "IN":
            return self.msr012(ctx, dcb, 0x15)         # (writing a file opened IN)
        if dcb.org == 0:
            return self.seq_write(ctx, dcb)            # BAZ SEQ0: IT'S CONSEC
        if dcb.org == 0x10:
            return self.rwrand(ctx, dcb, write=True)   # B RWRAND: IT'S A RANDOM
        if dcb.kad:
            key = self._key(u, dcb)
        elif getattr(dcb, "last", None) == "read" and dcb.kbuf:
            key = dcb.kbuf                             # PREVIOUS OPN MUST BE READ
        else:
            return self.msr012(ctx, dcb, 0x15)         # OPERATION ERROR
        data = self.read_text(u, dcb.buf, dcb.btd, dcb.rws).encode("latin-1")
        try:
            kf.write(key, data, newkey=dcb.nwk, onewkey=dcb.onwk)
        except FileError as e:
            return self.msr012(ctx, dcb, e.code)
        dcb.kbuf, dcb.last = key, "write"
        self.trace(f"WRITE {dcb.name} key {key.decode(EBCDIC)!r}: {len(data)} bytes")
        return self.pullallexit(ctx, 0, 0)

    def delrec(self, ctx, dcb):
        from .files import EBCDIC
        if dcb.org == 0:                               # DELSET: BAZ SEQ0 CONSECUTIVE
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
        data = self.read_text(ctx.u, dcb.buf, dcb.btd, dcb.rws).encode("latin-1")
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
                data = self.read_text(u, dcb.buf, dcb.btd, dcb.rws).encode("latin-1")
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
                              "OPEN entry 0": CalProcessor.file_open,
                              "CLOSE entry 2": CalProcessor.file_close,
                              "CLOSE entry 4": CalProcessor.cal_delrec,
                              "MSRKEY": CalProcessor.msrkey})
CalProcessor.resident.update({"T:CLRERR": CalProcessor.t_clrerr,
                              "MSRTYPR": CalProcessor.msrtypr, "MSROCTY": CalProcessor.msrtypr})
for _kind in ("T:EXIT", "T:ERROR", "T:ABORT"):
    CalProcessor.resident[_kind] = CalProcessor.exit_cal(None, _kind)
