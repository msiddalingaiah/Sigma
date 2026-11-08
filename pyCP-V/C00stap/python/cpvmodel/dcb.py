"""The DCB: a program's data control block, through which all its I/O goes."""

import enum
from dataclasses import dataclass, field

from .glossary import cpv, modelOnly

TERMINAL = "UC"                 # the device a terminal DCB (M:UC) is assigned to


class FileMode(enum.Enum):
    """What a DCB is opened for."""
    IN = 1
    OUT = 2


cpv("FUNCTION", "BAFUNM", source="UTS.txt:448-460",
    note="CP-V also has INOUT, OUTIN and UPDATE")(FileMode)

FileMode.cpvNames = {
    "IN": cpv("CLSFIL", source="CLS.txt:1443-1530", note="Read an existing file"),
    "OUT": cpv("CLSFIL4", source="CLS.txt:1994-1998",
               note="Write a new file; it goes into the directory at close"),
}


@cpv("DCB", "M:UC", source="UTS.txt:448-530, UCAL.txt:1172",
     note="A program's DCBs are in its own memory; M:OPEN fills one in, and every I/O CAL "
          "names one")
@dataclass(eq=False)
class DCB:
    """A data control block: one of the program's I/O connections. A program declares its
    DCBs, and every I/O CAL names one: ``m.read(self.data)``.

    - **Assigned to a file** (``fileName``): ``m.open`` connects it to the file, and reads and
      writes go to the file system.
    - **Assigned to a device** (``device``): reads and writes are transfers on that device's
      queue. ``TERMINAL`` is the user's terminal: every on-line user has ``M:UC``, which is
      ``m.uc``.

    The fields up to ``protection`` are what the program sets, as CP-V's DCB is assembled with
    defaults; ``m.open``'s arguments override them, as an FPT's parameters do. The rest is the
    DCB's state while it is open.
    """
    name: str
    fileName: str = None
    account: str = None
    device: str = None
    mode: FileMode = FileMode.IN
    organization: object = None
    size: int = None
    password: str = None
    protection: object = None
    records: list = field(default_factory=list)
    file: object = None
    isOpen: bool = False
    position: object = (0, 0)
    ownFile: bool = True
    discAccesses: int = 0

    cpvNames = {
        "name": cpv("M:UC", source="UCAL.txt:1172", note="M:xx and F:xx are DCB names"),
        "fileName": cpv("CHKFLACN", source="OBSE.txt:190", note="VLP X'01', the file name"),
        "account": cpv("CHKFLACN", source="OBSE.txt:190",
                       note="VLP X'02'; the user's own account if none"),
        "device": modelOnly("What the DCB is assigned to when it isn't a file; CP-V's "
                            "assignment comes from the program, TEL's !ASSIGN, or defaults"),
        "mode": cpv("FUNCTION", source="UTS.txt:448-460"),
        "organization": cpv("ORG", source="OPNF.txt:1015-1038"),
        "size": cpv("RSTORE", source="GRAND.txt:63", note="A random file's granules"),
        "password": cpv("SECCHK05", source="OBSE.txt:328-334", note="VLP X'03'"),
        "protection": cpv("FIL9", source="CLS.txt:2288-2335",
                          note="The account lists for a new file (VLPs X'05', X'06', X'14')"),
        "records": modelOnly("A device DCB's data: what reads take and writes add"),
        "file": cpv("CFU", source="UTS.txt:446-452", note="DCB word 1 points at the CFU"),
        "isOpen": modelOnly("Whether the DCB is open"),
        "position": cpv("SEQPOS", source="RDF.txt:3136-3138",
                        note="Where the next sequential read starts"),
        "ownFile": cpv("USR", "CHKFLACN", source="OBSE.txt:190, OBSE.txt:293-304",
                       note="The USR bit X'4000' clear: the user's own file, or as good as"),
        "discAccesses": modelOnly("Disc accesses the open file's work has made, not yet "
                                  "waited for"),
    }

    @modelOnly("The disc accesses since last asked, to be waited for")
    def takeDiscAccesses(self):
        count, self.discAccesses = self.discAccesses, 0
        return count
