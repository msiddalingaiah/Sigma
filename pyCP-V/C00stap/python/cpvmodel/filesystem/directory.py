"""Directories: index chains of names, each pointing at something."""

from ..glossary import cpv, modelOnly
from .disc import GRANULE_BYTES
from .indexchain import IndexChain

ACCOUNT_ENTRY = 18              # the account (TEXTC, 9) and the file directory's addresses
FILE_ENTRY = 41                 # the file name (TEXTC, 32) and the FIT's address
DUAL_LINKS = 11                 # COMPLEN6: room for the dual copy's links


@cpv("ACNCFU", "FDA", source="UTS.txt:455-464",
     note="Both directories are chains of index blocks with entries in key order, written "
          "twice (the dual copy)")
class Directory(IndexChain):
    """Names in order, each with a value. The account directory maps an account to its file
    directory; a file directory maps a file name to the file. Make one with
    ``Directory(disc, ACCOUNT_ENTRY)`` or ``Directory(disc, FILE_ENTRY)``.

    A directory is an index chain, as a keyed file's master index is, searched along its
    blocks from the first. It has no pyramid, so an account with many files takes longer
    to search. In CP-V every directory block is also written twice (the dual copy), which the
    model leaves out. Keys sort in EBCDIC on the real system; here as Python strings.
    """

    cpvNames = {}

    @cpv("COMPLEN", "COMPLEN6", source="WRTF.txt:956-968",
         note="Two spare entries at the end (four in the first block) and the dual links")
    def limit(self, block):
        spareEntries = 4 if block is self.blocks[0] else 2
        return GRANULE_BYTES - 1 - spareEntries * self.entrySize - DUAL_LINKS

    @cpv("FNDKEY", source="FIX1.txt:2194", note="A search like a keyed file's level 0")
    def find(self, key):
        return self.search(key)[0]

    @modelOnly("The names in order")
    def names(self):
        return [key for key, _ in self.items()]
