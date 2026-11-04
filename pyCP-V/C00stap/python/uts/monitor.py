"""Monitor variables the boot path reads and writes.

Naming: source symbols keep their spelling with ':' and '%' turned into '_',
so M:FPPH -> M_FPPH, CSED%MACHINE -> CSED_MACHINE, S:ACORE -> S_ACORE. A trailing
'#' becomes '_' too (UMOV# -> UMOV_, PB:C# -> PB_C_).
"""

import copy
from dataclasses import dataclass, field


class SystemUp(Exception):
    """Raised when INITIAL branches to the scheduler T:SE: boot finished."""


class NotTranslated(Exception):
    """Reached code that hasn't been translated yet."""


class Halted(Exception):
    """The boot code stopped the machine (B %) or can't go on."""


def _slots():
    return field(default_factory=list)


# Root variables that TBOOT: sets and WRTROOT writes to disc with the root, so a
# later disc boot gets them back (see Disc.attached).
ROOT_FIELDS = (
    "DCT", "CNDD", "LLNDD", "M_SWAPD", "M_TAURUS",
    "DLTBIAS", "DLTSZ", "DLTDSC", "UMOVSA", "UMOVSZ", "UMOV_",
    "P_SA", "P_TCB", "PB_DSZ", "PB_DCBSZ", "PB_PSZ", "PB_PVA", "PB_HVA", "PB_C_", "PB_DC_",
    "PH_DDA", "PH_PDA",
    "RCVSTART", "RCVDISC", "RCVSIZE", "RCVRAD", "MPPSEEK", "SEEK4000", "MONCHK",
    "DABOOT", "BOOTIC", "PPTABDSK", "PPTABDSK2", "SYSVERS",
)


@dataclass
class Monitor:
    # MONINIT
    MONIRTN: object = None
    CSED_MACHINE: int = 0
    OCNDD: int = 0
    OCNDDFLG: int = 0
    CORED: int = 0
    HIGH: int = 0
    LOW: int = 0
    DATE: dict = field(default_factory=dict)  # {'MO','DA','YR','HR','MI'}
    PPTABLE: list = field(default_factory=list)

    # Page pool (FIXPPUT / PUTRT)
    MX_PPUT: list = field(default_factory=list)  # forward link per physical page; 0 = end
    M_FPPH: int = 0
    M_FPPT: int = 0
    M_FPPC: int = 0
    MP_UPPH: int = 0
    MP_UPPT: int = 0
    MP_UPPC: int = 0
    PP_UPPH: int = 0
    PP_UPPT: int = 0
    PP_UPPC: int = 0
    SPOOL: int = 0
    SL_CORE: int = 0
    S_ACORE: int = 0
    S_PCORE: int = 0
    LEE20_2: int = 0

    # GMONEX
    xdelta_loaded: bool = False
    umov_loaded: bool = False

    # Devices (DCT tables, RECONFIG, TBOOT:)
    DCT: list = field(default_factory=list)
    CNDD: int = 0
    LLNDD: int = 0
    M_SWAPD: int = 0
    M_TAURUS: int = 0

    # TBOOT: / SWAPINIT / RECOV / WRTROOT
    SEGNO: int = -1
    MAXSEG: int = 0
    ENDFND: int = 0          # :ENDFND
    MSG_OUT: int = 0         # MSG:OUT
    SPECFLG: int = 0
    DISCLOC: int = 0
    DLTBIAS: int = 0
    DLTSZ: int = 0           # bytes
    DLTDSC: int = 0
    UMOVSA: int = 0
    UMOVSZ: int = 0          # bytes
    UMOV_: int = 0           # UMOV#: overlay-table slot of UMOV
    P_SA: list = _slots()
    P_TCB: list = _slots()
    PB_DSZ: list = _slots()
    PB_DCBSZ: list = _slots()
    PB_PSZ: list = _slots()
    PB_PVA: list = _slots()
    PB_HVA: list = _slots()
    PB_C_: list = _slots()
    PB_DC_: list = _slots()
    PH_DDA: list = _slots()
    PH_PDA: list = _slots()
    RCVSTART: int = 0
    RCVDISC: int = 0
    RCVSIZE: int = 0
    RCVRAD: int = 0
    MPPSEEK: int = 0
    SEEK4000: int = 0
    MONCHK: int = 0
    DABOOT: list = field(default_factory=lambda: [0, 0, 0])  # ROOTSA
    BOOTIC: list = field(default_factory=list)  # [(word address, bytes)] after part 1
    PPTABDSK: int = 0
    PPTABDSK2: int = 0
    patch_cards: list = field(default_factory=list)  # (segno, card) XDELTA accepted

    # Recovery (INITRCVR / RCVCTL)
    RCVCODE: int = 0
    RCVRDSZ: int = 0         # dump-area size, granules (set by SYSMAK)
    TRCVRAD: int = 0
    recovery_buffer: list = field(default_factory=list)  # words saved with SV1

    # INITIAL
    SYSVERS: int = 0
    LKIMG: list = field(default_factory=list)  # 2-bit write-lock code per page
    BOOTSBAND: int = 0
    CSED_PATH: int = 1
    ghosts_started: list = field(default_factory=list)
    sched: object = None     # sched.Scheduler, from INITIAL (ghosts.boot_scheduler)

    def init_tables(self, nslots):
        for name in ("P_SA", "P_TCB", "PB_DSZ", "PB_DCBSZ", "PB_PSZ", "PB_PVA", "PB_HVA",
                     "PB_C_", "PB_DC_", "PH_DDA", "PH_PDA"):
            setattr(self, name, [0] * nslots)

    def root_snapshot(self):
        return {name: copy.deepcopy(getattr(self, name)) for name in ROOT_FIELDS}

    def restore(self, snapshot):
        for name, value in snapshot.items():
            setattr(self, name, copy.deepcopy(value))

    def chain(self, head):
        """Walk an MX:PPUT chain from ``head``; returns the page numbers."""
        pages, p, seen = [], head, set()
        while p and p not in seen:
            seen.add(p)
            pages.append(p)
            p = self.MX_PPUT[p]
        return pages
