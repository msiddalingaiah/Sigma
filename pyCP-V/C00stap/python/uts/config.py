"""SYSGEN parameters, the device table, and the contents of M:MON that WRITEMON copies.

The real values come from the SYSGEN'd tables and the linked M:MON. We don't have
those, so these defaults are *invented but self-consistent*: picked so that the
layout rules the code relies on hold (root below the JIT page, UMOV after the JIT,
XDELTA above the free-page chain start, overlays at most six pages, and so on).
Values taken from source are marked with their file and line.
"""

from dataclasses import dataclass, field


@dataclass
class Module:
    """One load module as WRITEMON sees it. Sizes are in pages, biases are page numbers."""
    name: str
    start: int                  # start address (words)
    proc: tuple = (0, 0)        # (pages, bias page)
    data: tuple = (0, 0)
    dcbs: tuple = (0, 0)
    tcb: int = 0                # TCB address (words)


@dataclass
class DctEntry:
    """One device: DCT16 name ('YYNDD'), DCT4 type, and DCT1 address.

    Before RECONFIG's INITL runs, ``ndd`` is the SYSGEN'd channel letter plus two
    hex digits. INITL converts it into ``address`` (processor address << 8 | DD).
    """
    yy: str
    ndd: str
    type: str
    address: int = 0

    @property
    def name(self):
        return self.yy + self.ndd


def default_dct():
    # Invented. Index 0 is unused, as DCT index 0 is in the source (VALINP starts at 1).
    return [None,
            DctEntry("TY", "A01", "OC"),
            DctEntry("LP", "A02", "LP"),
            DctEntry("CR", "A03", "CR"),
            DctEntry("9T", "A80", "MT"),
            DctEntry("DC", "B01", "DC")]


def default_modules():
    """Invented M:MON contents: shared processors, overlays (name order), RECOVER."""
    return [
        Module("ALLOCAT", start=0x10000, data=(2, 0x60), proc=(4, 0x80), tcb=0xC000),
        Module("GHOST1", start=0x10000, data=(1, 0x60), dcbs=(1, 0x61), proc=(3, 0x80), tcb=0xC000),
        Module("FIX", start=0x10000, data=(1, 0x60), dcbs=(1, 0x61), proc=(2, 0x80), tcb=0xC000),
        Module("OVLY1", start=0x8000, proc=(2, 0x40)),
        Module("OVLY2", start=0x8000, proc=(6, 0x40)),
        Module("OVLY3", start=0x8000, proc=(1, 0x40)),
        Module("UMOV", start=0x8E00, proc=(3, 0x47)),
        Module("RECOVER", start=0x8000, proc=(4, 0x40)),
    ]


@dataclass
class Sysgen:
    # --- from source ---
    JJITVP: int = 0x46      # JIT.txt:272  monitor JIT virtual page
    JOVVP: int = 0x40       # JIT.txt:270  overlay area
    JXBUFVP: int = 0x2C     # JIT.txt:269
    DAJ: int = 6            # BOOTSUBR.txt:557  JIT disc sector on a RAD
    UMOV_PAGE: int = 0x47   # UTMBPMBT: UMOV bias X'4700' doublewords = page X'47'
    MB_SWAPS: int = 0       # 0 = 7212 RAD swapper, else 7232 (BOOTSUBR.txt:536)

    # --- invented ---
    CORE: int = 0x20000     # SYSGEN'd maximum memory, words (128K)
    MONORG: int = 0x100     # end of the interrupt locations filled with MTW,0 0
    PPSTART: int = 0x2000   # start of monitor pure procedure
    GETHGP: int = 0x2000    # start of the MONCHK checksum range
    TOPROOT: int = 0x7A40   # end of the monitor root
    MONIRTN: int = 0x8200   # address of MONIRTN: the boot-only BOOTSUBR code sits between
                            # TOPROOT and here, so the root is written in three parts
    UMOV_PAGES: int = 3
    DLTBIAS: int = 0xE000   # XDELTA load address (words); WRITEMON requires
                            # XDELTA plus symbols to end below X'10000'
    DLTPAGES: int = 8       # XDELTA size in pages
    PSA_END: int = 0x1480   # PSA%END, sectors
    IOLOW: int = 0x7000     # 560 I/O buffer range (write lock 00)
    IOHIGH: int = 0x7400
    OC_ADDRESS: int = 0x001  # operator-console address
    MB_SDI: int = 5         # DCT index of the swapper
    modules: list = field(default_factory=default_modules)
    dct: list = field(default_factory=default_dct)

    # Pack swapping (S:DP etc). 0 = RAD swapper.
    S_DP: int = 0
    S_CYLSZ: int = 0
    S_UCYL: int = 0

    # Real-time: RTICBHDR >= 0 means a real-time system.
    realtime: bool = False
    RESDF: int = 0           # resident dedicated-foreground pages
    RESDFP: int = 0          # first RESDF word address
    DYNRESDF: int = 0
    MDYNRESDF: int = 0
    PPTABLSZ: int = 4

    # User limits the ON/ONB/OFF key-ins change (invented). COC = 0: no terminals.
    SMUIS: int = 40          # maximum users
    S_GUAIS: int = 8         # ghosts
    S_BUAIS: int = 4         # batch
    S_OUAIS: int = 0         # on-line
    COC: int = 0
    S_CUIS: int = 2          # users in the system once it is up: ALLOCAT and RBBAT

    # Ghost table (S:GJOBTBL) and the first non-reserved user, MING (invented). Slot 2 is
    # ALLOCAT (INITIAL.txt:124 loads S:GJOBTBL+4) and slot MING the starter ghost
    # (INITIAL.txt:126); slots below MING are KEYIN, ALLOCAT and RBBAT (KEYN.txt:816).
    MING: int = 4
    MAXG: int = 8
    GHOSTS: tuple = ("KEYIN", "ALLOCAT", "RBBAT", "GHOST1")

    version: str = "C00 "    # WRITEMON's VERSION word (4 EBCDIC characters)
    timedate: str = "10:00 NOV 02,'76"  # 16 characters, as M:TIME would give them

    @property
    def JIT(self):
        return self.JJITVP * 512

    @property
    def overlays(self):
        return [mod for mod in self.modules if mod.name not in ("ALLOCAT", "GHOST1", "FIX", "RECOVER")]

    @property
    def MAXOVLY(self):
        """TBOOT: fills overlay slots MAXOVLY-1 down to 1 (BOOTSUBR.txt:1061)."""
        return len(self.overlays) + 1

    @property
    def xdelta(self):
        return Module("XDELTA", start=self.DLTBIAS, proc=(self.DLTPAGES, self.DLTBIAS >> 9))
