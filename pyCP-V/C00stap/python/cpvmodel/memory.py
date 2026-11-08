"""Core memory, counted in pages."""

from .glossary import cpv, modelOnly


@cpv("M:FPPH", "S:PCORE", source="SCHED.txt:2255-2271, TABLES.txt:725",
     note="CP-V chains the free physical pages through MX:PPUT, with head, tail and count in "
          "M:FPPH, M:FPPT and M:FPPC")
class Memory:
    """The pages users can occupy. The model only counts them: which page holds what, the
    monitor's own pages and shared processors aren't modelled."""

    def __init__(self, totalPages):
        self.totalPages = totalPages
        self.freePages = totalPages

    cpvNames = {
        "totalPages": cpv("S:PCORE", source="TABLES.txt:725",
                          note="The pages that users and processors can have"),
        "freePages": cpv("M:FPPC", source="SCHED.txt:2373", note="The free page count"),
    }

    @modelOnly("Pages go to a user being swapped in; CP-V moves them to the swapper's chain")
    def take(self, pages):
        if pages > self.freePages:
            raise ValueError(f"taking {pages} pages, only {self.freePages} free")
        self.freePages -= pages

    @modelOnly("Pages come back from a user swapped out or ended")
    def give(self, pages):
        self.freePages += pages
        assert self.freePages <= self.totalPages
