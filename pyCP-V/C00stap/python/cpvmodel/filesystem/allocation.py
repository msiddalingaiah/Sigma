"""Granule allocation: the bit map of free granules, the stack users take them from, and the
ALLOCAT ghost that keeps the stack between its levels."""

from dataclasses import dataclass

from ..glossary import cpv, modelOnly
from ..program import Compute, Release
from ..scheduler import Resource

ALLOCAT_PRIORITY = 0xC0         # illustrative: a ghost's priority comes from its start


@cpv("E:QFAC", "REG4CAT", source="GRAN.txt:202, GRAN.txt:301-308",
     note="The stack is empty: the user is queued for ALLOCAT")
class GranuleShortage(Exception):
    """Not enough granules on the stack: the user waits for ALLOCAT to fill it."""


@cpv("HGP", "GETBIT", "CMNRG", source="GRANSUB.txt:87-105, GRANSUB.txt:258, GRANSUB.txt:362",
     note="A header and two bit maps (PER and PFA) per device, chained by device type")
class AllocationMap:
    """One bit per granule of the file area; set means free. A search for a free granule
    goes on from where the last one stopped. Releasing a granule that is already free is a
    **dual allocation**: it is logged, and the release goes on.

    In CP-V there is a map per disc device, with separate areas for symbionts (PER) and
    files (PFA), and allocation by cylinder for some devices. The model has one map.
    """

    def __init__(self, granuleCount):
        self.free = [True] * granuleCount
        self.position = 0
        self.dualAllocations = []

    cpvNames = {
        "free": cpv("HGP", source="GRANSUB.txt:87-105", note="1 = free"),
        "position": cpv("GBIT5", source="GRANSUB.txt:296",
                        note="Word 3 of the HGP: where the last search stopped"),
        "dualAllocations": cpv("LOGDUAL", source="GRANSUB.txt:465"),
    }

    @cpv("CMNGG", "GETBIT", "GBIT5", source="GRANSUB.txt:87-95, GRANSUB.txt:258-296")
    def take(self):
        """A free granule's address, or None when the map is empty."""
        count = len(self.free)
        for step in range(count):
            index = (self.position + step) % count
            if self.free[index]:
                self.free[index] = False
                self.position = index
                return index + 1
        return None

    @cpv("CMNRG", "LOGDUAL", source="GRANSUB.txt:362, GRANSUB.txt:465")
    def give(self, address):
        if self.free[address - 1]:
            self.dualAllocations.append(address)
        self.free[address - 1] = True

    @modelOnly("How many granules are free in the map")
    def freeCount(self):
        return sum(self.free)


@cpv("HGPSTK", "TOP", "BOTTOM", source="HGPSTK.txt:1-36",
     note="Four circular stacks (RAD, pack, symbiont, cylinder) of free disc addresses")
@dataclass
class GranuleStack:
    """Free granule addresses that users take from and give back to, quickly. ALLOCAT keeps
    the count between ``lowLevel`` and ``highLevel``; a get or release that leaves it at a
    threshold wakes ALLOCAT.

    **Users see ALLOCAT's fill only later.** Granules it adds wait in ``pendingFill`` until the
    commit (``STUQFAC``), when ALLOCAT has finished. So a user who found the stack empty
    still finds it empty while ALLOCAT works, and waits for the commit.
    """
    capacity: int = 128
    lowLevel: int = 40
    highLevel: int = 80
    lowThreshold: int = 16
    highThreshold: int = 100

    def __post_init__(self):
        self.addresses = []
        self.pendingFill = []
        self.pendingReleases = []

    cpvNames = {
        "capacity": cpv("CATBUF", source="HGPSTK.txt:11", note="128 slots"),
        "lowLevel": cpv("LOLEVEL", source="HGPSTK.txt:25", note="40"),
        "highLevel": cpv("HILEVEL", source="HGPSTK.txt:26", note="80"),
        "lowThreshold": cpv("LOTHRSH", source="HGPSTK.txt:27", note="16"),
        "highThreshold": cpv("HITHRSH", source="HGPSTK.txt:28", note="100"),
        "addresses": cpv("TOP", "BOTTOM", "WORDCNT", source="HGPSTK.txt:13-35",
                         note="A get pops below TOP; WORDCNT is the count"),
        "pendingFill": cpv("TEMPBOT", "ADJSTCNT", source="HGPSTK.txt:34-36",
                           note="ALLOCAT fills below BOTTOM down to TEMPBOT, counted in ADJSTCNT"),
        "pendingReleases": cpv("NORELROM", "QUEMSG", source="GRAN.txt:169, GRAN.txt:319",
                               note="A release with no room goes to ALLOCAT as a message"),
    }

    @modelOnly("The count users can take from now")
    def count(self):
        return len(self.addresses)


@cpv("GBG", "RBG", source="GRAN.txt:95-117",
     note="The resident allocator the file code calls (GETDGRAN, GETIGRAN, RELRBG)")
class GranuleAllocator:
    """Granules for the file system, at three levels: the **stack** for speed, the **map** of
    every free granule, and the **ALLOCAT ghost**, which moves granules between them.

    - **Get** pops the stack. A user who finds too few waits on the ``ALLOCATOR`` resource
      (``E:QFAC``) while ALLOCAT fills it; the monitor's own needs go to the map directly.
    - **Release** pushes on the stack, or, with the stack full, leaves the granule for ALLOCAT.
    - **After either**, a count at a threshold starts ALLOCAT.
    - **ALLOCAT** fills a low stack up to ``highLevel`` from the map, or empties a high one down
      to ``lowLevel`` into the map, and releases the queued granules. When it is done it reports
      ``E:UQFAC``; the scheduler's release routine for ``ALLOCATOR`` commits the fill
      (``STUQFAC``) and the users waiting go on.

    In CP-V ALLOCAT is started at boot and sleeps between runs, and ``E:UQFAC`` comes from the
    swapper when it takes ALLOCAT out of core. The model starts ALLOCAT when it is needed,
    and it reports ``E:UQFAC`` itself as it ends. There is one stack (CP-V has one per device
    type) and no messages for runs of granules (``GNBG``) yet.
    """

    def __init__(self, system, granuleCount):
        self.system = system
        self.map = AllocationMap(granuleCount)
        self.stack = GranuleStack()
        self.allocatRunning = False
        self.allocatRuns = 0

    cpvNames = {
        "system": modelOnly("The system: ALLOCAT is started as a user"),
        "map": cpv("HGP", source="GRANSUB.txt:87-105"),
        "stack": cpv("HGPSTK", source="HGPSTK.txt:1-36"),
        "allocatRunning": cpv("BUFLAGS", source="HGPSTK.txt:14",
                              note="X'0001': ALLOCAT is working on the stack"),
        "allocatRuns": cpv("GRAJST", source="GRAN.txt:243", note="# TIMES ADJUSTED"),
    }

    @cpv("GETGRAN", "REG4CAT", source="GRAN.txt:193-202",
         note="Checked before a user's file operation starts, so it never stops half done")
    def ensure(self, count):
        """Make sure a user can take ``count`` granules from the stack, or raise
        ``GranuleShortage`` (the user must wait) after starting ALLOCAT. When the map is
        empty too, there is nothing to wait for: the operation goes on and fails if it runs
        out."""
        if self.stack.count() >= count:
            return
        if self.map.freeCount() + len(self.stack.pendingFill) == 0:
            return
        self.startAllocat()
        raise GranuleShortage(f"{count} granules needed, {self.stack.count()} on the stack")

    @cpv("GBG", "GETGRAN", "RELX", source="GRAN.txt:101-102, GRAN.txt:160, GRAN.txt:193",
         note="A user with the stack empty waits (ensure); the monitor takes from the map")
    def get(self):
        """A free granule's address, or None when there are none at all."""
        if self.stack.addresses:
            address = self.stack.addresses.pop()
            self.checkThresholds()
            return address
        return self.map.take()

    @cpv("RBG", "ROOM", "NORELROM", source="GRAN.txt:95, GRAN.txt:169-186")
    def release(self, address):
        if self.stack.count() < self.stack.capacity:
            self.stack.addresses.append(address)
        else:
            self.stack.pendingReleases.append(address)
        self.checkThresholds()

    @cpv("CHKTHRSH", "THRESH", source="GRAN.txt:230-243, GRAN.txt:337",
         note="At or above HITHRSH, or at or below LOTHRSH while the map isn't empty")
    def checkThresholds(self):
        count = self.stack.count()
        if (count >= self.stack.highThreshold or self.stack.pendingReleases
                or (count <= self.stack.lowThreshold and self.map.freeCount() > 0)):
            self.startAllocat()

    @cpv("T:GJOBSTRT", "THRESH", source="GRAN.txt:337-340",
         note="CP-V wakes the ALLOCAT ghost; the model starts it as a new user")
    def startAllocat(self):
        if self.allocatRunning or self.system is None or not self.system.freeSlots:
            return
        self.allocatRunning = True
        self.system.startUser("ALLOCAT", allocatProgram(self), priority=ALLOCAT_PRIORITY,
                              pages=2, account=":SYS")

    @cpv("ADJBUFS", "FILL", "EMPTY1", source="ALLYCAT.txt:330-410",
         note="Returns the granules moved, for the ghost's computing time")
    def adjust(self):
        """ALLOCAT's work: the queued releases into the map, then fill or empty the stack."""
        stack, moved = self.stack, 0
        for address in stack.pendingReleases:
            self.map.give(address)
            moved += 1
        stack.pendingReleases = []
        if stack.count() <= stack.lowLevel:
            while stack.count() + len(stack.pendingFill) < stack.highLevel:
                address = self.map.take()
                if address is None:
                    break
                stack.pendingFill.append(address)
                moved += 1
        elif stack.count() > stack.highLevel:
            while stack.count() > stack.lowLevel:
                self.map.give(stack.addresses.pop(0))      # from the bottom
                moved += 1
        self.allocatRuns += 1
        return moved

    @cpv("STUQFAC", "TEMPBOT", "ADJSTCNT", source="SCHED.txt:1707-1745",
         note="Called by the scheduler when ALLOCAT reports E:UQFAC")
    def commit(self):
        """The fill becomes visible: the pending granules go under the stack."""
        self.stack.addresses[:0] = self.stack.pendingFill
        self.stack.pendingFill = []
        self.allocatRunning = False

    @modelOnly("Free granules anywhere: the stack, the fill not yet committed, and the map")
    def freeCount(self):
        return (self.stack.count() + len(self.stack.pendingFill)
                + len(self.stack.pendingReleases) + self.map.freeCount())


@cpv("ALLOCAT", "NOMORE", source="ALLYCAT.txt:253, ALLYCAT.txt:675",
     note="Each run: messages, then the stacks (ADJBUFS), then sleep")
def allocatProgram(allocator):
    """The ALLOCAT ghost: adjust the stack, taking a tick a granule moved, then report
    ``E:UQFAC`` so the fill is committed and the users waiting for it are released."""
    moved = allocator.adjust()
    yield Compute(max(1, moved))
    yield Release(Resource.ALLOCATOR)
