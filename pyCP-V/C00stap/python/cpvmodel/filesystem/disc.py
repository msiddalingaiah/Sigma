"""The disc: granules, and where free ones come from."""

from dataclasses import dataclass, field

from ..glossary import cpv, modelOnly
from .allocation import GranuleAllocator
from .errors import DISC_FULL, FileError

GRANULE_BYTES = 2048            # BUFSIZ: 512 words


@modelOnly("CP-V gives an error when no granule is left; which code wasn't traced")
class DiscFull(FileError):
    """No free granule is left."""

    def __init__(self):
        super().__init__(DISC_FULL, "no granule left on the disc")


@modelOnly("A piece of a record in a granule; CP-V's segment has a control word in front")
@dataclass
class Segment:
    """Part of a record. ``continues`` says the record goes on in the next segment."""
    text: str
    continues: bool = False


@cpv("BUFSIZ", "BLINK", "FLINK", source="UTS.txt:479-486",
     note="512 words. A chained block starts with its back link, forward link and control word")
@dataclass(eq=False)
class Granule:
    """The unit of disc allocation: 2048 bytes. The model keeps a granule's contents as
    segments of records and counts their bytes; the links and control words aren't kept."""
    address: int
    capacity: int = GRANULE_BYTES
    segments: list = field(default_factory=list)

    cpvNames = {
        "address": cpv("LSECTA", source="DLT.txt:930",
                       note="A 24-bit disc address: device and relative sector"),
        "capacity": cpv("BUFSIZ", source="UTS.txt:479"),
        "segments": modelOnly("The records, or pieces of them, in this granule"),
    }

    @modelOnly("Bytes in use: each segment's text and its 4-byte control word")
    def bytesUsed(self):
        return sum(len(segment.text) + SEGMENT_OVERHEAD for segment in self.segments)

    @modelOnly("Bytes still free")
    def bytesFree(self):
        return self.capacity - self.bytesUsed()


SEGMENT_OVERHEAD = 4            # a segment control word


@cpv("GETDGRAN", "RELRBG", source="WRTF.txt:1176, DLT.txt:915",
     note="The file code gets and releases granules through GRAN")
class Disc:
    """The granules of the file area: those in use, and the allocator that hands out the
    free ones. ``system`` is needed to start the ALLOCAT ghost; a disc without one (in
    tests) never starts it."""

    def __init__(self, granuleCount=512, system=None):
        self.granuleCount = granuleCount
        self.allocator = GranuleAllocator(system, granuleCount)
        self.granules = {}

    cpvNames = {
        "granuleCount": modelOnly("The size of the file area"),
        "allocator": cpv("GBG", "RBG", source="GRAN.txt:10-11"),
        "granules": modelOnly("The granules in use, by address"),
    }

    @cpv("GETDGRAN", "GBG", source="WRTF.txt:1176-1180, GRAN.txt:95-117")
    def getGranule(self):
        address = self.allocator.get()
        if address is None:
            raise DiscFull()
        granule = Granule(address)
        self.granules[granule.address] = granule
        return granule

    @cpv("RELRBG", "RBG", source="DLT.txt:915-990, GRAN.txt:95-117")
    def releaseGranule(self, granule):
        del self.granules[granule.address]
        self.allocator.release(granule.address)

    @cpv("RELRBG", source="DLT.txt:915-990")
    def releaseGranuleAt(self, address):
        self.releaseGranule(self.granules[address])

    @modelOnly("How many granules are free")
    def freeCount(self):
        return self.allocator.freeCount()
