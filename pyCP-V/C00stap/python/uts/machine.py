"""Machine model: word-addressed Sigma memory, low-memory cells, clock, sense switches.

This is deliberately not an instruction emulator. Translated routines are plain
Python; they use this model only for state whose *location* matters (low memory,
boot flags, the clock) and for hardware behavior the boot code probes (memory size,
machine type).
"""

from dataclasses import dataclass, field
from enum import Enum

MASK32 = 0xFFFFFFFF
PAGE_WORDS = 512  # one Sigma page = 512 words = 2048 bytes


class MachineType(Enum):
    """Values stored in CSED%MACHINE (BOOTSUBR.txt:119, NSIG7TRP)."""
    SIGMA7 = 0x80
    SIGMA9 = 0x40
    X560 = 0x20


# Fixed low-memory locations (docs/boot.md, "Fixed low-memory locations").
LOADDEV = 0x25   # address of the device the system was loaded from
SYSTRT = 0x26    # B SYSTRT
BOOTFLG = 0x27   # boot option flags, byte 0
BOOTTYPE = 0x2A  # boot type code; bootstraps also load here
SYSVERS_LOC = 0x2B
INITIAL_VEC = 0x5F  # DATA 0,INITIAL at X'5E'-X'5F'
ROOT_ORIGIN = 0x5A  # load point of the monitor root

# BOOTFLG byte values (docs/boot.md, "Boot flags").
FLAG_I = 0x80  # TTY (OC) I/O
FLAG_P = 0x40  # LP output
FLAG_C = 0x20  # card patches
FLAG_T = 0x10  # tape patches
FLAG_F = 0x08  # boot under files
FLAG_D = 0x04  # keep XDELTA

# What X'2A' holds. Both bootstraps load at X'2A', so their first instructions are
# there; RCVCTL stores 0 or X'00010000' before a recovery reboot (docs/recovery.md §6).
MTBOOT_LI1 = 0x22100000  # LI,1 n  (n = root records)
DBOOT_RD0 = 0x6C000000   # RD,0 0
UNDER_FILES = 0xFFFFFFFF  # -1, stored by MONINIT for the F option
RECOVERY = 0x00000000
OP_RECOVERY = 0x00010000

# GHOST1's BOOTYPE table (GHOST1D.txt:74): halfword 0 of X'2A' -> boot type index.
BOOTYPE = (None, 0x2210, 0xFFFF, 0x6C00, 0x0000, 0x0001)
BOOT_NAMES = ("INDETERMINATE", "COLD TAPE BOOT", "BOOT UNDER FILES", "RAD BOOT",
              "RECOVERY", "OPERATOR RECOVERY")


def boot_type(word):
    """GHOST1's lookup (GHOST1D.txt:298): index of halfword 0 in BOOTYPE, else 0."""
    for i in range(len(BOOTYPE) - 1, 0, -1):
        if BOOTYPE[i] == word >> 16:
            return i
    return 0


def interpret(word):
    """INT: (CC, R, Ru1) = (bits 0-3, bits 4-15, bits 16-31). Assumed from the Sigma
    architecture, not this source. For an odd R, R ends up with Ru1."""
    return word >> 28, (word >> 16) & 0xFFF, word & 0xFFFF


class NonexistentMemory(Exception):
    """Reference beyond installed memory: trap X'40' on the real machine."""

    def __init__(self, address):
        super().__init__(f"nonexistent memory at X'{address:X}'")
        self.address = address


class Memory:
    """Word-addressed memory. Bytes are numbered 0..3 from the most significant end."""

    def __init__(self, words):
        self.size = words
        self._w = [0] * words

    def _check(self, address):
        if not 0 <= address < self.size:
            raise NonexistentMemory(address)

    def __getitem__(self, address):
        self._check(address)
        return self._w[address]

    def __setitem__(self, address, value):
        self._check(address)
        self._w[address] = value & MASK32

    def get_byte(self, address, n=0):
        return (self[address] >> (24 - 8 * n)) & 0xFF

    def set_byte(self, address, value, n=0):
        shift = 24 - 8 * n
        self[address] = (self[address] & ~(0xFF << shift)) | ((value & 0xFF) << shift)

    def signed(self, address):
        v = self[address]
        return v - (1 << 32) if v & 0x80000000 else v


@dataclass
class Machine:
    model: MachineType
    memory_words: int
    sense_switches: set = field(default_factory=set)  # e.g. {3} for SSW3
    console: object = None
    printer: object = None
    swap_disc: object = None
    tape: object = None
    card_reader: object = None
    devices: dict = field(default_factory=dict)  # device address -> stub
    log: list = field(default_factory=list)

    def __post_init__(self):
        self.mem = Memory(self.memory_words)
        self.tinc = 0                 # clock 3 counter (X'54' is MTW,-1 TINC)
        self.interrupt_mask = None    # value written by WD X'1200'
        self.clock3_running = False

    def trace(self, msg):
        self.log.append(msg)
