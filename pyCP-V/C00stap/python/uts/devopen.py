"""OPEN of a device DCB (docs/devopen.md): OPN's device option (MSROPN5, OPN.txt:689-
:732) and OPND's OPENDEV (OPND.txt:57-:418): the DCB's word 1, an operational label or
a device name, resolved through the assignment table for the kind of user.

The tables are SYSGEN's (P2OPL, the :OPLB command). The defaults are translated
(P2OPL.txt:50-:90); a site's :OPLB cards would change them.

What an assignment can name, and what the translation does with it:
- ME, the user's terminal: COC (an on-line user only);
- TY, the operator's console: M:OC's IOQ path;
- NO, or no assignment: the null device;
- C1, L1, P1 and other logical devices (symbiont streams through COOP): not translated;
- a device type (CR, CP, LP, PR, PP): allocating a device isn't modeled, so the
  allocation fails as for a user who may not have one (KRD10, X'02000049').
"""

from .files import EBCDIC
from .monitor import NotTranslated

# SH:OPNM: the operational labels, then pseudo-op entries for device types (P2OPL.txt:52-:61)
LABELS = ["", "C", "OC", "LO", "LL", "DO", "PO", "BO", "LI", "SI", "BI", "SL", "SO",
          "CI", "CO", "AL", "EI", "EO", "UC", "CR", "CP", "LP", "PR", "PP", "ME"]
# OB:BTX, OB:OTX, OB:GTX defaults, by label index (P2OPL.txt:63-:90); None: no entry (0)
BATCH = [None, "C1", "TY", "L1", "L1", "L1", "P1", "P1", "C1", "C1", "C1", "L1", "P1",
         "C1", "P1", "P1", "C1", "P1", "TY", "CR", "CP", "LP", "PR", "PP", None]
ONLINE = [None, "ME", "ME", "ME", "ME", "ME", None, None, None, "ME", None, "ME", None,
          None, None, None, "ME", None, "ME", "CR", "CP", "LP", "PR", "PP", "ME"]
GHOST = [None, "TY", "TY", "L1", "L1", "L1", "P1", "P1", "TY", "TY", "TY", "L1", "P1",
         "TY", "P1", "P1", "TY", "P1", "TY", "CR", "CP", "LP", "PR", "PP", "TY"]
DEVICE_TYPES = ("CR", "CP", "LP", "PR", "PP")

# OPEN's error codes for a device (byte 3 the code, byte 0 the subcode)
OPNERAB = (0x14, 0x0A)                  # an op label or name out of range (OPNERAB, OPND.txt:406)
NODEVICE = (0x49, 0x02)                 # no device of the type can be had (KRD10, :336)


class OpenError(Exception):
    def __init__(self, code, sub):
        super().__init__(f"X'{code:02X}'-{sub:02X}")
        self.code, self.sub = code, sub


def kind_of_user(sched, u):
    """J:JIT's type, as OPND's XTX takes it: 0 batch, 1 ghost, 2 on-line (:268-:270)."""
    if u in sched.LB_UN:
        return 2
    if u in sched.SB_GJOBUN:
        return 1
    return 0


def text_name(halfword):
    """Two EBCDIC characters, trailing blanks dropped."""
    return halfword.to_bytes(2, "big").decode(EBCDIC).rstrip()


def assignment(kind, index):
    table = (BATCH, GHOST, ONLINE)[kind]
    return table[index] if 0 < index < len(table) else None


def resolve(sched, u, word1, option=None):
    """The device a DCB opens on: 'ME', 'TY' or 'NO'. ``word1`` is the DCB's word 1
    (DSI); ``option`` the FPT's device option, which comes first (MSROPN5 sets the
    DSI before OPENDEV reads it)."""
    kind = kind_of_user(sched, u)
    if option is not None:
        if not option & 0x8000:                        # MSROPN5: not text, a device address
            raise NotTranslated("OPEN with a diagnostic device option")
        name = text_name(option & 0xFFFF)
        if name not in LABELS:
            raise OpenError(*OPNERAB)                  # ILLEGAL OPLB (OPN.txt:707)
        target = assignment(kind, LABELS.index(name))
    elif not word1 & 0x10000 and not word1 & 0x8000:  # OPD1: an op label index
        index = word1 & 0xFF
        if index >= len(LABELS) - 6:
            raise OpenError(*OPNERAB)                  # OP LABEL OUT OF RANGE (:94)
        target = assignment(kind, index)
    elif word1 & 0x10000 and word1 & 0x8000 and word1 & 0x4000:   # OPD29/OPD30: a name
        name = text_name(word1 & 0xFFFF)
        if name not in LABELS:
            raise OpenError(*OPNERAB)                  # TEXT NAME NOT FOUND (:254-:261)
        target = assignment(kind, LABELS.index(name))
    else:
        raise NotTranslated(f"OPEN of a DCB with type and DCT index (word 1 X'{word1:08X}')")
    if target in (None, "NO"):
        return "NO"                                    # the null device (NONTAPE)
    if target == "ME" and kind == 2:
        return "ME"
    if target == "TY":
        return "TY"
    if target in DEVICE_TYPES:
        raise OpenError(*NODEVICE)                     # no allocatable device of the type
    raise NotTranslated(f"OPEN on logical device {target} (a symbiont stream, COOP)")
