"""RECONFIG entry points used by TBOOT:, and BOOTSUBR's CL2PA and RECNFG.

Translated from c00co/RECONFIG.txt and c00co/BOOTSUBR.txt. Only the paths a boot
without ':' commands takes are translated; any ':' command stops the boot.
"""

from .machine import BOOTFLG, FLAG_P, MachineType
from .monitor import NotTranslated

NL = "\n"
NORCNFG = "NO RECONFIGURATION PERFORMED"                       # RECONFIG.txt:2852
BAD_CRD = NL + "** ':' COMMAND NOT IN PATCH DECK PROPERLY" + NL  # BOOTSUBR :CRD

# X560CUCL (BOOTSUBR.txt:1467): channel letters indexed by 560 IOP address.
# The last character is unreadable in this copy of the source.
X560CUCL = ("A%#@:\0\0\0" "BCDEFG\0\0" "HIJKLM\0\0" "NOPQRS\0\0" "TUVWXY\0\0" "Z01234\0\0"
            "56789") + "�"


def cl2pa(letter, model):
    """CL2PA  BOOTSUBR.txt:1441 - channel letter to processor address, or None if invalid."""
    if model is MachineType.X560:
        n = X560CUCL.find(letter) if letter and letter != "\0" else -1
        return n if n >= 0 else None
    n = ord(letter) - ord("A") if len(letter) == 1 else -1
    return n if 0 <= n <= 7 else None


def ndd_address(ndd, model):
    """Channel letter + hex DD -> processor address << 8 | DD, as INITL's DCTLOOP does."""
    pa = cl2pa(ndd[0], model)
    if pa is None:
        raise NotTranslated(f"INITL: bad channel letter in DCT1 '{ndd}' (the source loops on B %)")
    return (pa << 8) | int(ndd[1:], 16)


def initl(m, mon):
    """INITL (RECNFG:0)  RECONFIG.txt:134 - convert every DCT1 address."""
    # OCNDDFLG is never set by the Python MONINIT (the stub OC always answers),
    # so the OC-address reformatting at the top of INITL doesn't apply.
    for entry in mon.DCT[1:]:
        entry.address = ndd_address(entry.ndd, m.model)
    # CSEBRANCH table setup: one set of handlers in this model, so nothing to do.
    mon.M_TAURUS = 1 if m.model is MachineType.X560 else 0
    m.trace("RECNFG:0: DCT addresses " +
            ", ".join(f"{e.name}=X'{e.address:03X}'" for e in mon.DCT[1:]))


def recnfgll(m, text):
    """RECNFGLL: list a line on the LL if the P flag is set."""
    if m.mem.get_byte(BOOTFLG) & FLAG_P:
        m.printer.print(text)


def recnfg(m, mon, card):
    """RECNFG  BOOTSUBR.txt:1593 - XDELTA hands over a ':' card."""
    recnfgll(m, card)
    if mon.SEGNO == 0:
        # RECNFG:1 (PROC:) sets FND:CRD on the first card, so even a lone :END
        # takes the RECNF path (ORGANIZ, DORECNFG, DOREMOVE) at :END.
        raise NotTranslated(f"RECONFIG ':' commands (PROC:): {card.strip()}")
    if not mon.MSG_OUT:
        mon.MSG_OUT = 1
        m.console.write(BAD_CRD)
        recnfgll(m, "*" + BAD_CRD[1:-1])


def endfalt(m, mon):
    """:ENDFALT (RECNFG:2) -> :ENDX -> GOEND  RECONFIG.txt:931."""
    mon.ENDFND = 1
    recnfgll(m, " " + NORCNFG)
    # DSPRESLL (resource display on the LL), DOPART (partitions) and the COC
    # address loop aren't translated.
    m.trace("RECNFG:2: no reconfiguration performed (DSPRESLL/DOPART not translated)")
