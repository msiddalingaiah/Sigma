"""Files: what every file has, and consecutive files."""

import enum
from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from .disc import SEGMENT_OVERHEAD, Segment

HEADER_BYTES = 320              # FITSIZE: 80 words


class Organization(enum.Enum):
    """How a file's records are kept."""
    CONSECUTIVE = 1
    KEYED = 2
    RANDOM = 3


cpv("ORG", "FITCHK", source="FIX1.txt:1758-1789, FIX1.txt:1848-1850",
    note="Byte 0 of the FIT's X'09' entry: 0 or 1 consecutive, 2 keyed, 3 random")(Organization)

Organization.cpvNames = {
    "CONSECUTIVE": cpv("SEQ0", source="WRTF.txt:273", note="Records one after another"),
    "KEYED": cpv("SETUPUB", source="RDF.txt:1575", note="Records found by key (iteration 2)"),
    "RANDOM": cpv("RWRAND", source="WRTF.txt:1928", note="Granules by number (iteration 4)"),
}


@cpv("FITSIZE", "NWFITST", source="WRTF.txt:44-46",
     note="The FIT: name, VLPs (organization, key size, disc addresses, protection)")
@dataclass(eq=False)
class FileHeader:
    """What the file system knows about a file, kept in the file's first granule. The
    closest modern idea is an inode."""
    name: str
    account: str
    organization: Organization = Organization.CONSECUTIVE

    cpvNames = {
        "name": cpv("FITCHK", source="FIX1.txt:1758-1789",
                    note="TEXTC, compared with the directory's entry"),
        "account": cpv("J:ACCN", source="JIT.txt:308-310", note="The owner's account"),
        "organization": cpv("FITCHK", source="FIX1.txt:1758-1789"),
    }


@cpv("FITSIZE", "NOU", source="WRTF.txt:44-46, UTS.txt:450",
     note="CP-V keeps a file on the disc, with its header (the FIT) in its first granule, and "
          "the state of an open file in core, in a CFU that exists only while it is open")
class File:
    """A file: its header, its granules, and whether it is open and in its directory.

    In CP-V the open state is a separate in-core table, the CFU ("current file usage"), one
    per open file and shared by every program that has the file open. The model's files are
    already in memory, so that state is kept on the file itself.
    """

    def __init__(self, header, disc):
        self.header = header
        self.disc = disc
        self.openCount = 0
        self.inDirectory = False

    cpvNames = {
        "header": cpv("FITSIZE", source="WRTF.txt:44-46"),
        "disc": modelOnly("Where the granules come from"),
        "openCount": cpv("NOU", "CFU", source="UTS.txt:446-452",
                         note="The CFU's number of users"),
        "inDirectory": cpv("CLSFIL4", source="CLS.txt:1994-1998",
                           note="False for a file opened OUT: it is entered at close"),
    }


@cpv("SEQ0", "SEQPOS", source="WRTF.txt:273-276, RDF.txt:3136-3138",
     note="CP-V writes control words between the segments, with back pointers, flags for "
          "blocked and unblocked segments, and the FIT as a dummy first segment")
class ConsecutiveFile(File):
    """Records one after another in a chain of granules. A record that doesn't fit in the
    rest of a granule is split into segments, continued in the next. The header takes the
    start of the first granule.

    The model writes only at the end of the file. CP-V also cuts the file at the position
    when a program writes in the middle (delete forward), reads backward, and positions by
    record; those aren't modelled yet.
    """

    def __init__(self, header, disc):
        super().__init__(header, disc)
        self.granules = []
        self.recordCount = 0

    cpvNames = {
        "granules": cpv("FDA", "LDA", "FLINK", source="UTS.txt:448-486",
                        note="CP-V chains them on the disc, from FDA (first) to LDA (last)"),
        "recordCount": cpv("TDA", source="UTS.txt:462",
                           note="A consecutive file's CFU keeps the record count in TDA"),
    }

    @cpv("SEQ0", "GETDGRAN", source="WRTF.txt:273-505",
         note="Returns the number of granules written")
    def append(self, text):
        """Add a record at the end. Returns how many granules were written."""
        if not self.granules:
            self.newGranule()
        remaining = text
        touched = 1
        while True:
            granule = self.granules[-1]
            room = granule.bytesFree() - SEGMENT_OVERHEAD
            if len(remaining) <= room:
                granule.segments.append(Segment(remaining))
                break
            if room > 0:
                granule.segments.append(Segment(remaining[:room], continues=True))
                remaining = remaining[room:]
            self.newGranule()
            touched += 1
        self.recordCount += 1
        return touched

    @cpv("GETDGRAN", source="WRTF.txt:1176-1180")
    def newGranule(self):
        granule = self.disc.getGranule()
        if not self.granules:
            granule.capacity -= HEADER_BYTES
        self.granules.append(granule)
        return granule

    @cpv("SEQ0", "SEQFRD", source="RDF.txt:3136-3268, RDF.txt:2896",
         note="Returns the record (None at the end of the file), the next position, and the "
              "granules read")
    def read(self, position):
        """Read the record at ``position``, a (granule, segment) pair."""
        granuleIndex, segmentIndex = position
        parts, touched = [], 0
        while granuleIndex < len(self.granules):
            granule = self.granules[granuleIndex]
            if segmentIndex >= len(granule.segments):
                granuleIndex, segmentIndex = granuleIndex + 1, 0
                continue
            if not parts:
                touched += 1
            segment = granule.segments[segmentIndex]
            parts.append(segment.text)
            segmentIndex += 1
            if not segment.continues:
                return "".join(parts), (granuleIndex, segmentIndex), touched
            touched += 1
        return None, (granuleIndex, segmentIndex), touched

    @cpv("SEQ3", "REL", source="DLT.txt:488, DLT.txt:665-674",
         note="The whole-file delete: every granule goes back")
    def release(self):
        for granule in self.granules:
            self.disc.releaseGranule(granule)
        self.granules = []
        self.recordCount = 0
