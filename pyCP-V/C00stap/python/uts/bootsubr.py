"""BOOTSUBR: MONINIT (every boot), GMONEX/FIXPPUT/PUTRT, and the disc bootstrap DBOOT.

Translated from c00co/BOOTSUBR.txt. Comments of the form ``# BOOTSUBR.txt:NNN LABEL``
point at the code each section comes from. TBOOT: (the tape install
path) is in tboot.py, and the tape bootstrap MTBOOT is here as ``mtboot``.
"""

from .machine import (
    BOOTFLG, BOOTTYPE, SYSTRT, MachineType, NonexistentMemory, PAGE_WORDS,
    FLAG_I, FLAG_P, FLAG_T, FLAG_F, FLAG_D,
    MTBOOT_LI1, DBOOT_RD0, UNDER_FILES, interpret,
)
from .monitor import Halted, NotTranslated
from . import tboot

NL = "\n"

# Message texts, as assembled (X'15' shown as NL).
ENTER_ANY_OF = (NL + "ENTER ANY OF:" + NL + "I=TTY I/O" + NL + "P=LP OUTPUT" + NL
                + "F=TAPE FILES" + NL + "T=TAPE PATCHES" + NL + "C=CARD PATCHES" + NL
                + "D=XDELTA" + NL)                                  # 1STMESM
GDATEM = NL + "DATE(MM/DD/YY)="
GTIMEM = NL + "TIME(HH:MM)="
RDLTM = NL + "DO YOU WANT DELTA (Y/N)"
QM = " ??" + NL
RESDFM = NL + "RESET RESDF {:03d},{:05X} ? "

CODES = "DFTCPI"  # BOOTSUBR.txt CODES TEXTC; letter n sets bit 2**(n+1)

MIND = {"MI": 0, "HR": 0, "YR": 70, "DA": 1, "MO": 1}   # MIND '  0000700101'
MAXD = {"MI": 59, "HR": 23, "YR": 99, "DA": 31, "MO": 12}  # MAXD '  5923993112'
BADATES = {(2, 29), (2, 30), (2, 31), (4, 31), (6, 31), (9, 31), (11, 31)}


def messg(m, text):
    """MESSG: type ``text`` on the OC, read a reply (about 10 s timeout -> '')."""
    m.console.write(text)
    return m.console.read().strip().upper()


def option_bits(reply):
    """Turn the ENTER ANY OF reply into a BOOTFLG byte (CODLOOP)."""
    if not reply:
        return FLAG_T                       # default for no response
    bits = 0
    for ch in reply[:12]:                   # LI,2 -12  max input
        n = CODES.find(ch)
        if n >= 0:
            bits |= 1 << (n + 2)            # OR,5 BT31TO0+2,3 (n is 1-based there)
    return bits


def parse_date(reply):
    """DATETIME/GETDIG for MM/DD/YY. Returns a dict or None if invalid."""
    parts = reply.split("/")
    if len(parts) != 3 or not all(p.isdigit() and 1 <= len(p) <= 2 for p in parts):
        return None
    mo, da, yr = (int(p) for p in parts)
    d = {"MO": mo, "DA": da, "YR": yr}
    for k, v in d.items():
        if not MIND[k] <= v <= MAXD[k]:
            return None
    if (mo, da) in BADATES and (mo, da) != (2, 29):
        return None
    if (mo, da) == (2, 29) and yr % 4:      # leap-year check on BCD year digits
        return None
    return d


def parse_time(reply):
    parts = reply.split(":")
    if len(parts) != 2 or not all(p.isdigit() and 1 <= len(p) <= 2 for p in parts):
        return None
    hr, mi = (int(p) for p in parts)
    if not (MIND["HR"] <= hr <= MAXD["HR"] and MIND["MI"] <= mi <= MAXD["MI"]):
        return None
    return {"HR": hr, "MI": mi}


def ask_until_valid(m, prompt, parse):
    """Prompt, then on a bad reply type ' ??' and read again (EOM falls into MESSG)."""
    result = parse(messg(m, prompt))
    while result is None:
        result = parse(messg(m, QM))
    return result


def moninit(m, mon, sysgen):
    """MONINIT  BOOTSUBR.txt:107"""
    mem = m.mem

    # Machine type: AD,11 traps through X'4D' unless on a Sigma 7; the trap handler
    # NSIG7TRP tries to set FR to tell a 560 from a Sigma 9.
    mon.CSED_MACHINE = m.model.value
    m.trace(f"MONINIT: machine {m.model.name}")

    # OC address: HIO the SYSGEN'd address; if it doesn't answer, WAIT for the
    # operator to key a new one into R0. The stub console always answers.
    mon.OCNDD = sysgen.OC_ADDRESS

    # OCADDROK: default flags for disc boots.
    mem.set_byte(BOOTFLG, FLAG_I | FLAG_P)

    probe_memory(m, mon, sysgen)

    # INT,11 X'2A' / BCR,15 REQDELT: CC zero only after RCVCTL (recovery).
    cc, _, r11 = interpret(mem[BOOTTYPE])
    recovery = cc == 0
    if not recovery:
        mem[SYSTRT] = 0x68000000 | SYSTRT   # MPBR: B SYSTRT (placeholder encoding)
        r11 -= 4                             # AI,11 -4 / BLZ RT: low halfword < 4 is a disc boot
        if r11 >= 0:
            tape_options(m)
        if sysgen.realtime:
            resdf_dialog(m, mon, sysgen)
        mon.DATE.update(ask_until_valid(m, GDATEM, parse_date))
        mon.DATE.update(ask_until_valid(m, GTIMEM, parse_time))
        m.trace(f"MONINIT: date/time {mon.DATE}")

    reqdelt(m, mon, sysgen, r11, recovery)


def probe_memory(m, mon, sysgen):
    """Find installed memory: step down from CORE+X'FFF' by X'1000' words until a
    reference doesn't trap through X'40' (CORC)."""
    addr = sysgen.CORE + 0xFFF
    while True:
        addr -= 0x1000                      # CORC  AI,2 -X'1000'
        try:
            m.mem[addr]                     # MTW,0 0,2
            break
        except NonexistentMemory:
            continue
    mon.CORED = addr + 1
    mon.HIGH = mon.M_FPPT = addr >> 9
    m.trace(f"MONINIT: CORED=X'{mon.CORED:X}' HIGH=X'{mon.HIGH:X}'")


def tape_options(m):
    """ENTER ANY OF: (tape boot only)."""
    bits = option_bits(messg(m, ENTER_ANY_OF))
    m.mem.set_byte(BOOTFLG, bits)
    # Comment says 'IS THIS BOOT-UNDER-FILES ... YES, SET FLAG' and stores -1 in X'2A'.
    # The CI/BANZ test reads the other way round (docs/boot.md open questions); we
    # follow the comment.
    if bits & FLAG_F:
        m.mem[BOOTTYPE] = UNDER_FILES
    m.trace(f"MONINIT: BOOTFLG=X'{bits:02X}'")


def resdf_dialog(m, mon, sysgen):
    """RT/RTMSG: RESET RESDF YYY,XXXXX ?  (real-time systems)."""
    npages = min(sysgen.RESDF, 999)
    first = sysgen.RESDFP
    while True:
        if not m.mem.get_byte(BOOTFLG) & FLAG_I:
            break                            # no OC, no message
        reply = messg(m, RESDFM.format(npages, first))
        fields = reply.split(",") if reply else []
        try:
            new_n = int(fields[0]) if fields and fields[0] else npages
            new_first = int(fields[1], 16) if len(fields) > 1 and fields[1] else first
        except ValueError:
            continue
        last_page = (new_first >> 9) + new_n - 1
        if new_n > 999 or (new_first and new_first < 0x10000) or last_page > mon.HIGH:
            continue
        npages, first = new_n, new_first
        break
    sysgen.RESDF, sysgen.RESDFP = npages, first
    mon.PPTABLE = [0] * sysgen.PPTABLSZ
    mon.PPTABLE[0] = ((first >> 9) << 16) | npages


def reqdelt(m, mon, sysgen, r11, recovery):
    """REQDELT  BOOTSUBR.txt:364"""
    m.tinc = 0                               # ZAP CLOCK SO TIME IS CORRECT
    if r11 - 1 > 0:                          # BDR,11 TBOOT: (branches if the result is > 0)
        tboot.tboot(m, mon, sysgen)          # WRTROOT ends with B GMONEX
    elif not recovery:
        if messg(m, RDLTM).startswith("Y"):
            m.mem.set_byte(BOOTFLG, FLAG_I | FLAG_P | FLAG_D)   # X'C4'
    gmonex(m, mon, sysgen)


def gmonex(m, mon, sysgen):
    """GMONEX  BOOTSUBR.txt:375 - read XDELTA and the root extension UMOV from the swap disc (DLTCLST)."""
    words = m.swap_disc.read_words(mon.DLTDSC, mon.DLTSZ // 4)
    _load(m, mon.DLTBIAS, words)
    mon.xdelta_loaded = True
    words = m.swap_disc.read_words(mon.UMOVSA, mon.UMOVSZ // 4)
    _load(m, 0x23800 // 4, words)                      # BAUMOV: byte X'23800'
    mon.umov_loaded = True
    m.trace("GMONEX: read XDELTA and UMOV from swap disc")
    fixpput(m, mon, sysgen)


def _load(m, address, words):
    for i, w in enumerate(words):
        if address + i < m.mem.size:
            m.mem[address + i] = w


def fixpput(m, mon, sysgen):
    """FIXPPUT  BOOTSUBR.txt:385 - build the physical page pool."""
    # Assumption: MX:PPUT starts out linking each page to the next. The source only
    # zeroes the tail, so the sequential links must come from the assembled table.
    mon.MX_PPUT = [p + 1 for p in range(mon.HIGH + 1)]

    # A free symbiont buffer: if TOPROOT rounded up to 256 words lands mid-page,
    # that half page becomes SPOOL and the free pool starts at the next page.
    r1 = sysgen.TOPROOT + 255
    if r1 & 256:
        r1 &= 0xFFFF00
        mon.SPOOL = r1
        r1 += 256
    mon.M_FPPH = mon.LOW = r1 >> 9

    mon.MX_PPUT[mon.HIGH] = 0
    count = mon.HIGH - mon.LOW + 1
    mon.SL_CORE = count

    # Take the monitor JIT and UMOV pages out into the MP:UPP chain.
    hva = mon.PB_HVA[mon.UMOV_]                     # INT,5 UMOV# / LB,5 PB:HVA,5
    mon.MX_PPUT[sysgen.JJITVP - 1] = hva
    mon.MP_UPPC = hva - sysgen.JJITVP
    count -= mon.MP_UPPC
    mon.MP_UPPT = hva - 1
    mon.MX_PPUT[mon.MP_UPPT] = 0
    mon.MP_UPPH = sysgen.JJITVP

    if m.mem.get_byte(BOOTFLG) & FLAG_D:        # keep XDELTA: remove its pages too
        first = mon.DLTBIAS >> 9
        mon.MX_PPUT[mon.MP_UPPT] = first          # hook to old tail
        before = first - 1
        n = (mon.DLTSZ + 0x7FF) >> 11
        mon.MP_UPPC += n
        last = mon.MX_PPUT[before] + n - 1
        mon.MP_UPPT = last
        after = mon.MX_PPUT[last]
        if after == 0:
            mon.M_FPPT = before                   # XDELTA was at the end of the chain
        mon.MX_PPUT[before] = after
        mon.MX_PPUT[last] = 0
        count -= n
        mon.LEE20_2 -= 1
    mon.LEE20_2 += 1

    # Maximum user swap size.
    max_user = 0xB8
    if sysgen.S_DP:
        max_user = sysgen.S_CYLSZ
        if sysgen.S_DP - sysgen.S_UCYL:
            # Code, not the comment: ((CYLSZ-2)/4)*4+2 + CYLSZ.
            max_user = ((sysgen.S_CYLSZ - 2) >> 2 << 2) + 2 + sysgen.S_CYLSZ
    if max_user < mon.SL_CORE:
        mon.SL_CORE = max_user
    mon.M_FPPC = mon.S_ACORE = count
    mon.S_PCORE = count - 7                       # AJIT + 6 pages for an overlay
    m.trace(f"FIXPPUT: free pages {count}, LOW=X'{mon.LOW:X}', SL:CORE=X'{mon.SL_CORE:X}'")
    putrt(m, mon, sysgen)


def putrt(m, mon, sysgen):
    """PUTRT  BOOTSUBR.txt:1340 - move RESDF pages from the free chain to PP:UPP."""
    if not sysgen.realtime:
        return
    if interpret(m.mem[BOOTTYPE])[0] == 0:
        raise NotTranslated("PUTRT: reading PPTABLE back from disc on recovery")
    for i, entry in enumerate(mon.PPTABLE):
        if not entry:
            continue
        first, n = entry >> 16, entry & 0xFFFF
        wanted = set(range(first, first + n))
        prev, p = 0, mon.M_FPPH
        while p and n:
            nxt = mon.MX_PPUT[p]
            if p in wanted:
                if p == mon.M_FPPH:
                    mon.M_FPPH = nxt
                else:
                    mon.MX_PPUT[prev] = nxt
                    if nxt == 0:
                        mon.M_FPPT = prev
                mon.M_FPPC -= 1
                mon.MX_PPUT[p] = 0
                if mon.PP_UPPT:
                    mon.MX_PPUT[mon.PP_UPPT] = p
                else:
                    mon.PP_UPPH = p
                mon.PP_UPPT = p
                mon.PP_UPPC += 1
                n -= 1
            else:
                prev = p
            p = nxt
        if n:
            mon.PPTABLE[i] = 0                    # PUTRT8: zap bad entry
    mon.S_ACORE -= sysgen.RESDF + sysgen.DYNRESDF
    mon.S_PCORE -= sysgen.RESDF + sysgen.MDYNRESDF
    m.trace(f"PUTRT: {mon.PP_UPPC} RESDF pages reserved")


def dboot(m, mon, initial, screech=None):
    """DBOOT  BOOTSUBR.txt:1751 - disc bootstrap in sector 0, loaded at X'2A'.

    ``screech`` stands for the monitor still in memory: SCREECH -1 is an XPSD
    through its RCVPSD. Without one (a cold machine) there is nothing to recover.
    """
    m.mem[BOOTTYPE] = DBOOT_RD0             # the bootstrap itself occupies X'2A'
    # RD,0 0 reads the sense switches; SSW3 means operator recovery.
    if 3 in m.sense_switches:
        if screech is None:
            raise Halted("SCREECH -1: no monitor in memory to recover (RCVPSD not set)")
        return screech(-1, 0)
    return bootent(m, mon, initial)


def bootent(m, mon, initial):
    """BOOTENT  BOOTSUBR.txt:1758 - read the root from ROOTSA (16K words to X'5A',
    then BOOTIC for the rest) and B *X'5F'. RCVCTL also enters here."""
    tboot.read_root(m, mon, m.swap_disc)
    m.trace(f"DBOOT: root read from {mon.DABOOT}, B *X'5F' -> INITIAL")
    return initial(m)


def mtboot(m, initial):
    """MTBOOT  UTMBPMBT.txt:802 - tape bootstrap, loaded at X'2A'.

    Reads n root records from the tape at X'25': the first to X'5A', the rest a
    page at a time from X'200'. Then branches to the monitor (STRTADRT). X'2A'
    still holds MTBOOT's own first instruction, LI,1 n.
    """
    boot = m.tape.read_record()
    nrec = boot[0]
    tboot._store(m, 0x5A, m.tape.read_record())
    for k in range(1, nrec):
        tboot._store(m, k * PAGE_WORDS, m.tape.read_record())
    m.mem[BOOTTYPE] = MTBOOT_LI1 | nrec
    m.trace(f"MTBOOT: read {nrec} root records, B INITIAL")
    return initial(m)
