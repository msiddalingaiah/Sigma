"""Random files: a run of granules, read and written by granule number."""

from ..glossary import cpv, modelOnly
from .disc import GRANULE_BYTES
from .errors import BEYOND_END, SHORT_TRANSFER, FileError
from .files import File, Organization


@cpv("RWRAND", "GRANDPUB", source="WRTF.txt:1928, GRAND.txt:102",
     note="ORG 3. The run's first address and size are in the FIT's X'0C' VLP")
class RandomFile(File):
    """A run of contiguous granules, fixed when the file is created, read and written by
    granule number. The header has a granule of its own.

    A transfer starts at a granule and goes on through the following ones; the position
    then moves past the granules moved, so the next transfer continues there. Starting past
    the end is error X'42' with nothing moved. A write that runs off the end moves what fits
    and ends with X'44'; a read that runs off the end returns what is there.

    In CP-V the transfers go straight between the disc and the program's buffer, at most
    32 sectors at a time. The model keeps each granule's text.
    """

    def __init__(self, header, disc, size):
        super().__init__(header, disc)
        header.organization = Organization.RANDOM
        self.size = size
        self.headerGranule = disc.getGranule()
        self.run = []
        self.contents = [""] * size

    cpvNames = {
        "size": cpv("RSTORE", "TDA", source="GRAND.txt:63, CLS.txt:1729-1732",
                    note="The number of granules; the CFU keeps it in TDA"),
        "headerGranule": cpv("SREC", source="UTS.txt:463", note="The FIT's own granule"),
        "run": cpv("CMNGNG", "GNBG", source="GRANSUB.txt:105, GRAN.txt:253",
                   note="Contiguous granules from ALLOCAT, found from the end of the map"),
        "contents": modelOnly("Each granule's text"),
    }

    @modelOnly("Takes the run ALLOCAT found")
    def allocate(self, granules):
        self.run = granules

    @cpv("RWRAND", "RWRDUN", "E5744", source="WRTF.txt:1928-2087",
         note="Returns the granules moved, for the position and the disc accesses")
    def write(self, granuleNumber, text):
        self.checkStart(granuleNumber)
        chunks = [text[i:i + GRANULE_BYTES] for i in range(0, len(text), GRANULE_BYTES)] or [""]
        room = self.size - granuleNumber
        for offset, chunk in enumerate(chunks[:room]):
            self.contents[granuleNumber + offset] = chunk
        moved = min(len(chunks), room)
        if len(chunks) > room:
            raise FileError(SHORT_TRANSFER, f"{self.header.name}: the write ran off the end")
        return moved

    @cpv("RWRAND", "RWRDUN", source="WRTF.txt:1928-2067",
         note="At most what is left in the file is moved")
    def read(self, granuleNumber, size):
        """Up to ``size`` bytes from ``granuleNumber`` on, and the granules moved."""
        self.checkStart(granuleNumber)
        granules = max(1, -(-size // GRANULE_BYTES))
        last = min(self.size, granuleNumber + granules)
        text = "".join(self.contents[granuleNumber:last])[:size]
        return text, last - granuleNumber

    @cpv("ERR01", source="WRTF.txt:2081", note="A granule number past the end: X'42'")
    def checkStart(self, granuleNumber):
        if not 0 <= granuleNumber < self.size:
            raise FileError(BEYOND_END, f"{self.header.name}: granule {granuleNumber} is past "
                                        f"the end ({self.size})")

    @cpv("RELRAND", "RNBG", source="CLS.txt:1729-1732, GRAN.txt:281",
         note="The run goes back as a message to ALLOCAT. Whether the FIT's granule is "
              "released too wasn't found; the model releases it")
    def release(self):
        self.disc.releaseRun(self.run)
        self.run = []
        self.disc.releaseGranule(self.headerGranule)
