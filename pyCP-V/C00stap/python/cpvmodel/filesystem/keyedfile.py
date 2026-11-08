"""Keyed files: records found by key, through an index chain."""

from dataclasses import dataclass, field

from ..glossary import cpv, modelOnly
from .disc import SEGMENT_OVERHEAD, Segment
from .files import File, Organization
from .indexchain import IndexChain

MASTER_ENTRY_EXTRA = 13         # a master-index entry is the key slot plus 13 bytes


@cpv("FNDMI", "FNDDA", source="FIX1.txt:2240, FIX1.txt:2334",
     note="A master-index entry: the segment's data granule, displacement and size, and flags")
@dataclass(eq=False)
class RecordLocation:
    """Where a record is: its segments, in the data granules they are in."""
    segments: list = field(default_factory=list)
    granules: list = field(default_factory=list)

    cpvNames = {
        "segments": cpv("FAK", source="WRTF.txt:1745",
                        note="CP-V has an index entry per segment; the first has FAK"),
        "granules": cpv("SREC", source="UTS.txt:463"),
    }


@cpv("SETUPUB", "INST", "MUL", source="RDF.txt:1575, WRTF.txt:608, CLS.txt:1424",
     note="ORG 2. The master index starts in the file's first granule, with the FIT at its end")
class KeyedFile(File):
    """Records found by key. The **master index** is an index chain of key → where the
    record is, kept in key order; its first block shares the first granule with the header.
    The records themselves go into **data granules**, packed one after another and split
    across granules when they don't fit.

    At close, a file that was written and has chained in more than ``rebuildAfterSlides``
    new index blocks gets its **pyramid** rebuilt, so later searches go down a few levels
    instead of along the chain.

    In CP-V a record split across granules has an index entry per segment, the first marked
    FAK, and rewriting a record reuses its space when the new one fits. The model has one
    entry a record and writes a rewritten record anew.
    """

    def __init__(self, header, disc, keyLength=11, spare=102, rebuildAfterSlides=254):
        super().__init__(header, disc)
        header.organization = Organization.KEYED
        self.keyLength = keyLength
        self.rebuildAfterSlides = rebuildAfterSlides
        self.index = IndexChain(disc, keyLength + 1 + MASTER_ENTRY_EXTRA, spare,
                                headerInFirstBlock=True)
        self.dataGranules = []
        self.written = False

    cpvNames = {
        "keyLength": cpv("KEYM", source="UTS.txt:588, FIX1.txt:1859-1861",
                         note="The maximum key length, in the FIT's X'09' entry"),
        "rebuildAfterSlides": cpv("LSLIDES", "WRDL0", source="UTS.txt:609, UTS.txt:660, OPNF.txt:1841",
                                  note="254 by default"),
        "index": cpv("FDA", "TDA", source="UTS.txt:455, UTS.txt:462",
                     note="The master index (level 0) from FDA, the pyramid from TDA"),
        "dataGranules": cpv("SREC", source="UTS.txt:463",
                            note="New records go into SREC, the last data granule"),
        "written": cpv("CLSFILD", source="CLS.txt:1423, CLS.txt:2005",
                       note="Only a file that was written gets its pyramid rebuilt"),
    }

    @cpv("ENTKEYUB", "INST", source="WRTF.txt:608, WRTF.txt:1532",
         note="Returns the disc accesses: the index search and blocks, and the data granules")
    def write(self, key, text):
        location, accesses = self.store(text)
        accesses += self.index.insert(key, location)
        self.written = True
        return accesses

    @cpv("IMAGEREC", "SREC", source="UTS.txt:463, WRTF.txt:1686",
         note="Into the last data granule, split across new ones when it doesn't fit")
    def store(self, text):
        location = RecordLocation()
        remaining = text
        if not self.dataGranules:
            self.dataGranules.append(self.disc.getGranule())
        while True:
            granule = self.dataGranules[-1]
            if granule not in location.granules:
                location.granules.append(granule)
            room = granule.bytesFree() - SEGMENT_OVERHEAD
            if len(remaining) <= room:
                segment = Segment(remaining)
                granule.segments.append(segment)
                location.segments.append(segment)
                return location, len(location.granules)
            if room > 0:
                segment = Segment(remaining[:room], continues=True)
                granule.segments.append(segment)
                location.segments.append(segment)
                remaining = remaining[room:]
            self.dataGranules.append(self.disc.getGranule())

    @cpv("SETUPUB", source="RDF.txt:1575",
         note="Returns the record (None if the key isn't there) and the disc accesses")
    def read(self, key):
        location, accesses = self.index.search(key)
        if location is None:
            return None, accesses
        return self.textOf(location), accesses + len(location.granules)

    @cpv("LOCCODEUB", source="RDF.txt:1252",
         note="The next entry in the index block in the buffer, or the next block")
    def readNext(self, position):
        """The record after ``position`` in key order: (key, text, next position, disc
        accesses), with key None at the end of the file. Moving to another index block is a
        disc access; staying in the one in the buffer isn't."""
        blockIndex, entryIndex = position
        accesses = 0
        while blockIndex < len(self.index.blocks):
            block = self.index.blocks[blockIndex]
            if entryIndex < len(block.keys):
                if entryIndex == 0:
                    accesses += 1
                location = block.values[entryIndex]
                return (block.keys[entryIndex], self.textOf(location),
                        (blockIndex, entryIndex + 1), accesses + len(location.granules))
            blockIndex, entryIndex = blockIndex + 1, 0
        return None, None, position, accesses

    @modelOnly("A record's text from its segments")
    def textOf(self, location):
        return "".join(segment.text for segment in location.segments)

    @cpv("CLSFILD", "LSLIDES", "MUL", source="CLS.txt:1423, UTS.txt:660, MUL.txt:1",
         note="Returns the disc accesses: the pyramid's blocks written")
    def close(self):
        if self.written and self.index.slides > self.rebuildAfterSlides:
            self.index.buildPyramid(self.keyLength)
            return len(self.index.pyramid.addresses())
        return 0

    @cpv("REL", "RELFILUB3", source="DLT.txt:665-705",
         note="The pyramid first, then each master-index block and the data granules")
    def release(self):
        self.index.release()
        for granule in self.dataGranules:
            self.disc.releaseGranule(granule)
        self.dataGranules = []
