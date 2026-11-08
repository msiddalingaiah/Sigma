"""Directories: names in order, each pointing at something."""

import bisect

from ..glossary import cpv, modelOnly


@cpv("ACNCFU", "FDA", source="UTS.txt:455-464",
     note="Both directories are chains of index blocks with entries in key order, written "
          "twice (the dual copy)")
class Directory:
    """Keys in order, each with a value. The account directory maps an account to its file
    directory; a file directory maps a file name to the file.

    In CP-V both are index-format chains on the disc, searched like a keyed file's master
    index, and kept in two copies. This first version keeps them as a sorted list in memory
    (iteration 2 gives them the index blocks). Keys sort in EBCDIC on the real system; here
    they sort as Python strings.
    """

    def __init__(self):
        self.keys = []
        self.values = {}

    cpvNames = {
        "keys": cpv("SCR", "MIDIS", source="UTS.txt:487, UTS.txt:602",
                    note="The entries' keys, in order"),
        "values": modelOnly("What each key points at: a file directory, or a file"),
    }

    @cpv("FNDKEY", source="FIX1.txt:2194", note="A search like a keyed file's level 0")
    def find(self, key):
        return self.values.get(key)

    @cpv("INST", source="WRTF.txt:608", note="Inserted in key order")
    def insert(self, key, value):
        if key not in self.values:
            bisect.insort(self.keys, key)
        self.values[key] = value

    @cpv("DELF", "DEL1", source="DLT.txt:314-378",
         note="DEL1 slides the following entries up over the deleted one")
    def remove(self, key):
        self.keys.remove(key)
        del self.values[key]

    @modelOnly("The keys in order")
    def names(self):
        return list(self.keys)
