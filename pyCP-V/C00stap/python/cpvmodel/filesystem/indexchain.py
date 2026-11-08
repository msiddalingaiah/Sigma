"""Index chains: entries in key order, in a chain of index blocks, with an optional pyramid
of upper levels. Directories and keyed files are both index chains."""

import bisect
from dataclasses import dataclass, field

from ..glossary import cpv, modelOnly
from .disc import GRANULE_BYTES
from .files import HEADER_BYTES

ENTRIES_START = 12              # MIDIS: the first entry follows the block's three words
TOP_LEVEL_MOST_BLOCKS = 3       # the top level is at most three blocks


@cpv("BLINK", "FLINK", "NAVX", source="UTS.txt:483-486",
     note="An index block is a granule: links, a control word with the next available byte "
          "(NAV) and the level, then the entries")
@dataclass(eq=False)
class IndexBlock:
    """One granule of an index chain. Its entries are (key, value) pairs in key order."""
    address: int
    level: int = 0
    holdsHeader: bool = False
    addedSinceBuild: bool = False
    keys: list = field(default_factory=list)
    values: list = field(default_factory=list)

    cpvNames = {
        "address": cpv("FLINK", source="UTS.txt:484", note="The links are disc addresses"),
        "level": cpv("NAVX", source="UTS.txt:486", note="X'1C00' of the control word"),
        "holdsHeader": cpv("NWFITST", source="WRTF.txt:44-46",
                           note="X'8000', FIT PRESENT: the file's first block"),
        "addedSinceBuild": cpv("MULCHK", source="WRTF.txt:893",
                               note="X'100': chained in since the pyramid was built"),
        "keys": cpv("SCR", source="UTS.txt:602", note="Keys in order, each in a slot"),
        "values": modelOnly("What each key points at"),
    }

    @modelOnly("Bytes in use, as CP-V's NAV: the first entry's offset plus the entries")
    def nextAvailable(self, entrySize):
        return ENTRIES_START + len(self.keys) * entrySize


@cpv("INST", "SETUPUB", "LOCCODEUB", source="WRTF.txt:608, RDF.txt:1575, RDF.txt:1252",
     note="The master-index format, also used by both directories")
class IndexChain:
    """Entries in key order, in a chain of fixed-size blocks (level 0), each a granule.

    - **Search** walks the chain from the first block (following ``FLINK``), one disc access
      a block, until the block whose keys reach the key. A long chain makes searches slow;
      that is what the **pyramid** is for. Its upper levels hold the first key of each block
      below, so a search goes down a few levels instead of along the chain.
    - **Insert** slides the entries after the new one down. A block keeps ``spare`` bytes
      free. When there's no room, the block's **last entry moves** to the front of the next
      block, or to a new block chained in after this one, which counts a **slide**.
    - **The pyramid restriction:** while a pyramid exists, a block it points at must keep its
      first key, so an insert in front of it goes to the end of the block before.

    In CP-V this is a byte layout (``UTS.txt:482``) used by the master index of keyed files
    (WRTF, RDF, MUL) and by both directories. The model counts bytes but keeps the entries
    as Python pairs.
    """

    def __init__(self, disc, entrySize, spare=0, headerInFirstBlock=False):
        self.disc = disc
        self.entrySize = entrySize
        self.spare = spare
        self.blocks = [self.newBlock(holdsHeader=headerInFirstBlock)]
        self.pyramid = None
        self.slides = 0

    cpvNames = {
        "disc": modelOnly("Where the blocks' granules come from"),
        "entrySize": cpv("IMT", "SCR", source="UTS.txt:594, UTS.txt:602",
                         note="The key slot plus 13 bytes in a master index"),
        "spare": cpv("WRDL0", "DFRDL0", source="UTS.txt:609, OPNF.txt:1841",
                     note="Bytes left free in each block on insert; 102 by default"),
        "blocks": cpv("FDA", "FLINK", source="UTS.txt:455, UTS.txt:484",
                      note="Level 0, in chain order from FDA"),
        "pyramid": cpv("TDA", source="UTS.txt:462", note="TOP DISC ADDRESS (OF MULTI-LEVEL)"),
        "slides": cpv("BASLIDES", source="UTS.txt:454, WRTF.txt:1508",
                      note="New blocks since the pyramid was built"),
    }

    @cpv("GETIGRAN", source="WRTF.txt:1149")
    def newBlock(self, level=0, holdsHeader=False):
        granule = self.disc.getGranule()
        return IndexBlock(granule.address, level, holdsHeader)

    @cpv("COMPLEN", source="WRTF.txt:956",
         note="X'7FF', or X'6BF' in the block with the FIT, less the spare bytes")
    def limit(self, block):
        """The highest byte an insert may reach in ``block``."""
        size = GRANULE_BYTES - HEADER_BYTES if block.holdsHeader else GRANULE_BYTES
        return size - 1 - self.spare

    @modelOnly("Whether one more entry fits in the block")
    def hasRoom(self, block):
        return block.nextAvailable(self.entrySize) + self.entrySize <= self.limit(block)

    @cpv("MULCHK", source="WRTF.txt:893",
         note="With a pyramid, a block not added since the build is pointed at")
    def isPointedAt(self, block):
        return self.pyramid is not None and not block.addedSinceBuild

    # --- Search ---------------------------------------------------------------------------

    @cpv("SETUPUB", "LOCCODEUB", source="RDF.txt:1575, RDF.txt:1252",
         note="Down the pyramid if there is one, then along level 0")
    def locate(self, key):
        """Where ``key`` is, or would go: (block index, position, disc accesses)."""
        if self.pyramid is not None:
            start, accesses = self.pyramid.descend(key)
            index = self.blocks.index(start)
        else:
            index, accesses = 0, 0
        accesses += 1
        while (index + 1 < len(self.blocks) and self.blocks[index].keys
               and key > self.blocks[index].keys[-1]):
            index += 1
            accesses += 1
        block = self.blocks[index]
        return index, bisect.bisect_left(block.keys, key), accesses

    @modelOnly("The value for ``key`` (or None) and the disc accesses the search took")
    def search(self, key):
        index, position, accesses = self.locate(key)
        block = self.blocks[index]
        if position < len(block.keys) and block.keys[position] == key:
            return block.values[position], accesses
        return None, accesses

    # --- Insert and remove ----------------------------------------------------------------

    @cpv("INST", "INSTN", source="WRTF.txt:608-810",
         note="Returns the disc accesses: the search, and each block written")
    def insert(self, key, value):
        """Put ``key`` in, or give an existing key a new value."""
        index, position, accesses = self.locate(key)
        block = self.blocks[index]
        if position < len(block.keys) and block.keys[position] == key:
            block.values[position] = value
            return accesses + 1
        if position == 0 and index > 0 and self.isPointedAt(block):
            return accesses + self.insertAfterPrevious(index, key, value)
        return accesses + self.insertAt(index, position, key, value)

    @cpv("INST2D", "INST3", "INST3A3", "INSTN", source="WRTF.txt:660-810",
         note="Room enough; or the last entry to the next block; or a new block")
    def insertAt(self, index, position, key, value):
        block = self.blocks[index]
        if self.hasRoom(block):
            block.keys.insert(position, key)
            block.values.insert(position, value)
            return 1
        following = self.blocks[index + 1] if index + 1 < len(self.blocks) else None
        if following is None or self.isPointedAt(following) or not self.hasRoom(following):
            following = self.chainNewBlock(index)
        if position == len(block.keys):         # at the end of a full block (INST2D)
            following.keys.insert(0, key)
            following.values.insert(0, value)
        else:
            self.moveLastEntry(block, following)
            block.keys.insert(position, key)
            block.values.insert(position, value)
        return 2

    @cpv("INST4", "MULCHK", source="WRTF.txt:857, WRTF.txt:893",
         note="A block the pyramid points at keeps its first key")
    def insertAfterPrevious(self, index, key, value):
        previous = self.blocks[index - 1]
        if not self.hasRoom(previous):
            previous = self.chainNewBlock(index - 1)
        previous.keys.append(key)
        previous.values.append(value)
        return 1

    @modelOnly("Moves a block's last entry to the front of the next block")
    def moveLastEntry(self, block, following):
        following.keys.insert(0, block.keys.pop())
        following.values.insert(0, block.values.pop())

    @cpv("INSTN", "BASLIDES", source="WRTF.txt:804, UTS.txt:454, WRTF.txt:1508-1514",
         note="Past LSLIDES the count is pinned at X'FF' so the pyramid is rebuilt at close")
    def chainNewBlock(self, index):
        block = self.newBlock()
        block.addedSinceBuild = True
        self.blocks.insert(index + 1, block)
        self.slides += 1
        return block

    @cpv("DEL1", source="DLT.txt:343-378",
         note="Slides the entries after it up; a block left empty stays in the chain")
    def remove(self, key):
        index, position, accesses = self.locate(key)
        block = self.blocks[index]
        if position < len(block.keys) and block.keys[position] == key:
            del block.keys[position]
            del block.values[position]
            return True, accesses + 1
        return False, accesses

    @modelOnly("Every (key, value) in key order")
    def items(self):
        for block in self.blocks:
            yield from zip(block.keys, block.values)

    @modelOnly("Every granule address the chain and its pyramid use")
    def addresses(self):
        result = [block.address for block in self.blocks]
        if self.pyramid is not None:
            result += self.pyramid.addresses()
        return result

    # --- The pyramid ----------------------------------------------------------------------

    @cpv("MUL", "CLSFILD", source="CLS.txt:1423, MUL.txt:1",
         note="At close, when the slides have passed the limit")
    def buildPyramid(self, keyLength):
        if self.pyramid is not None:
            self.pyramid.release()
        self.pyramid = Pyramid.build(self, keyLength)
        for block in self.blocks:
            block.addedSinceBuild = False
        self.slides = 0

    @modelOnly("Gives back every granule")
    def release(self):
        if self.pyramid is not None:
            self.pyramid.release()
            self.pyramid = None
        for block in self.blocks:
            self.disc.releaseGranuleAt(block.address)
        self.blocks = []


@cpv("TDA", "MUL", source="UTS.txt:462, CLS.txt:1424",
     note="The upper levels of a keyed file's index (the multi-level index)")
class Pyramid:
    """Levels above level 0. Each entry is the first key of a block on the level below and
    that block; each level is built from the one below until a level has at most three
    blocks, the top. A search goes down from the top, one block a level.

    In CP-V the entries hold disc addresses, a search does a binary search in each block,
    and a continuation key (a record's later segment) at the front of a block needs care.
    """

    def __init__(self, chain, levels):
        self.chain = chain
        self.levels = levels

    cpvNames = {
        "chain": modelOnly("The index chain the pyramid is over"),
        "levels": cpv("TDA", source="UTS.txt:462",
                      note="Level 1 up; TDA points at the top"),
    }

    @staticmethod
    @cpv("MOVEAKEY", "MUL", source="MUL.txt:1, MUL.txt:231",
         note="Level 1 from the first keys of level 0, then more levels while more than 3")
    def build(chain, keyLength):
        upperEntry = keyLength + 1 + 4          # SCR + a disc address
        perBlock = (GRANULE_BYTES - 1 - ENTRIES_START) // upperEntry
        lower = list(chain.blocks)
        levels = []
        while True:
            level = []
            for start in range(0, len(lower), perBlock):
                block = chain.newBlock(level=len(levels) + 1)
                block.values = lower[start:start + perBlock]
                block.keys = [below.keys[0] if below.keys else "" for below in block.values]
                level.append(block)
            levels.append(level)
            if len(level) <= TOP_LEVEL_MOST_BLOCKS:
                return Pyramid(chain, levels)
            lower = level

    @cpv("MLCHK", "MLSET03A", source="RDF.txt:1575-1803",
         note="Walk the top level, then a binary search in each block on the way down")
    def descend(self, key):
        """The level-0 block to start a search at, and the disc accesses to get there."""
        top = self.levels[-1]
        accesses = 0
        for position, block in enumerate(top):
            accesses += 1
            if position + 1 == len(top) or key < top[position + 1].keys[0]:
                break
        while True:
            below = block.values[max(0, bisect.bisect_right(block.keys, key) - 1)]
            if block.level == 1:
                return below, accesses
            block = below
            accesses += 1

    @modelOnly("Every granule address of the upper levels")
    def addresses(self):
        return [block.address for level in self.levels for block in level]

    @modelOnly("Gives back the upper levels' granules")
    def release(self):
        for address in self.addresses():
            self.chain.disc.releaseGranuleAt(address)
