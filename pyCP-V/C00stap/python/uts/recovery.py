"""Crash recovery: INITRCVR's RECOVER0/RCV1 and the RECOVER overlay's RCVCTL.

Translated from c00co/INITRCVR.txt, RCVCTL.txt and CYCUSR.txt (RCVDMP, INCRDA).
See docs/recovery.md. Comments of the form ``# FILE:NNN`` point at the source.

Translated: decoding the SCREECH word, saving X'4000'-X'7FFF' at SEEK4000,
reading RECOVER, the reason message, the dump area at RCVRAD, the X'2A' flag,
and the simulated disc boot through BOOTENT.

Not translated: SUA and DUMP (they need a running user), multiprocessor slaves,
and RCVCTL's system-specific saves (users, symbionts, error log, TP, COC). Those
are traced as skipped. The recovery buffer is written, but only with the words
RCVDMP itself saves.
"""

from .devices import DeviceError, SECTOR_WORDS
from .machine import BOOTTYPE, LOADDEV, RECOVERY, interpret
from .monitor import Halted, NotTranslated

NL = "\n"
M0 = NL + "OPERATOR RECOVERY" + NL                      # RCVCTL.txt:1131
MNTH = NL + "RECOVERY FOR UNKNOWN REASON" + NL
MSFTW = NL + "SOFTWARE CHECK  {:02X}-{:02X}" + NL
OPERFAIL = NL + "RECOVERY ERROR -"
BRKMS = NL + "RE-BOOT SYSTEM - SAVE DUMP TAPE FOR ANLZ" + NL
# To the terminals, as COCOUT's table makes them ASCII: TC, the timing character, a
# rubout (DEL); BELL; CR, LF. RELOGM's XO first isn't sent: its code didn't survive in
# the listing (a control character; X-OFF, probably).
TC, BELL, CRLF = "\x7f", "\x07", "\r\n"
RELOGM = CRLF + TC * 8 + BELL + TC + BELL + "RECOVERY SAYS-STAND BY-" + CRLF   # RCVCTL.txt:1181
FAILMS = CRLF + TC * 8 + "STAND BY - FOR EXTENDED RECOVERY" + CRLF               # :1141

SCREECH, SUA, DUMP = 0, 1, 2                            # NAME values of the UTS.txt:20 proc
SHUTDOWN_CODE = 0x404                                   # "ZAP CODE, FROM SSS"


def code_word(code, subcode=0, kind=SCREECH):
    """The GEN,16,8,8 word after XPSD,0 RCVPSD."""
    return ((code & 0xFFFF) << 16) | ((kind & 0xFF) << 8) | (subcode & 0xFF)


def screech(m, mon, sysgen, code, subcode=0, reboot=None, kind=SCREECH):
    """XPSD,0 RCVPSD -> RECOVER0  INITRCVR.txt:134. ``reboot`` is BOOTENT for the new root."""
    word = code_word(code, subcode, kind)
    # RCV60: AND with X'FFFF00FF' (LI of X'F00FF' sign-extends). A zero result
    # would take the code from R15; the Python always passes it in the word.
    mon.RCVCODE = word & 0xFFFF00FF
    kind = (word & 0x300) >> 8
    mon.RCVCODE |= kind << 8                             # STS,D1 RCVCODE: type for ANLZ
    m.trace(f"RECOVER0: RCVCODE=X'{mon.RCVCODE:08X}'")
    if kind == SUA:
        raise NotTranslated("SUA: single-user abort (needs a running user)")
    if kind == DUMP:
        raise NotTranslated("DUMP: dump to the SUA file (needs the dump file)")
    rcv1(m, mon, sysgen, reboot)


def rcv1(m, mon, sysgen, reboot):
    """RCV1  INITRCVR.txt:321 - crash: halt devices, save X'4000'-X'7FFF', read RECOVER."""
    # RT:RCVR is RTBOOT's stub (it returns). The ADAM code is branched around.
    m.trace("RCV1: halted all devices, acknowledged interrupts")
    disc = m.swap_disc
    try:
        # KRD2 with R6 = 0: DUMPCOM writes X'4000'-X'7FFF' at SEEK4000 on the swapper.
        disc.write_words(mon.SEEK4000, [m.mem[a] for a in range(0x4000, 0x8000)])
    except DeviceError as e:
        raise Halted(f"RCV1: can't save X'4000'-X'7FFF' ({e}); the SIO loop never ends")
    # REDDWD: seek RCVDISC, read RCVSIZE bytes to X'4000'.
    for i, w in enumerate(disc.read_words(mon.RCVDISC, mon.RCVSIZE // 4)):
        m.mem[0x4000 + i] = w
    m.trace(f"RCV1: saved X'4000'-X'7FFF' at {mon.SEEK4000}, RECOVER read from {mon.RCVDISC}")
    rcvctl(m, mon, sysgen, reboot)                       # B *RCVSTART+1,R6 with R6 = 0


def shutdown(m):
    """INT,5 X'2A' / BDR,5: no typing (and no dump) when the low halfword is above 1."""
    return interpret(m.mem[BOOTTYPE])[2] - 1 > 0


def tyout(m, text):
    """TYOUT  RCVCTL.txt:341"""
    if not shutdown(m):
        m.console.write(text)


def cocout(m, mon, text):
    """COCOUT  RCVCTL.txt:363 - the message to every line of every COC, a character at a
    time through RECOVER's own ASCII table; not when shutting down (INT,R3 X'2A' /
    BDR). Here: to the lines COC has (mon.sched.coc), as they are. Not CP-V's way
    around COC: RECOVER writes to the hardware directly, so the lines' buffers and
    columns aren't touched."""
    if shutdown(m):
        return
    coc = getattr(getattr(mon, "sched", None), "coc", None)
    if coc is None:
        return                                           # LI,1 COC / BEZ: NO COC
    data = text.encode("latin-1")
    for line in coc.lines:
        if line.send is not None:
            line.send(data)
    m.trace(f"COCOUT: {text.strip(CRLF + TC + BELL)!r} to the terminals")


def rcvctl(m, mon, sysgen, reboot):
    """RCVCTL  RCVCTL.txt:93"""
    try:
        _rcvctl(m, mon, sysgen, reboot)
    except DeviceError as e:
        norcvr(m, str(e), mon)


def _rcvctl(m, mon, sysgen, reboot):
    # Clear pending interrupts; X'40' traps now go to NORCVR, X'46' (watchdog) is ignored.
    m.mem[BOOTTYPE] = RECOVERY                           # INDICATE RECOVERY TO GHOST1
    mon.TRCVRAD = mon.RCVRAD
    # R:DCT1 is RECOVER's own copy of the I/O tables (RCVDEF); its channel letters
    # are converted here as INITL does. The Python uses Monitor.DCT directly.
    code = mon.RCVCODE >> 16
    code = code - 0x10000 if code & 0x8000 else code     # LH: signed
    if code == 0x89:
        mon.recovery_buffer.append(0x0B000000)           # HGPRECON request (SV1)
    if code == SHUTDOWN_CODE:
        m.mem[BOOTTYPE] = code + 0x40000                 # AI,0 X'40000' / STW,0 X'2A'
    if code < -1:
        message = MNTH
    elif code == -1:
        m.mem[BOOTTYPE] = m.mem[BOOTTYPE] + 0x10000       # MTH,1 X'2A': operator recovery
        message = M0
    elif code <= 0xFF:
        message = MSFTW.format(code & 0xFF, mon.RCVCODE & 0xFF)
    else:
        message = MNTH
    tyout(m, message)
    for _ in range(2):                                   # INCRDA twice: room for the buffer
        incrda(mon)
    cocout(m, mon, RELOGM)                               # TELL USERS TO STAND BY
    # RBOUT / TPCHECK: no remote work stations or TP in this model.
    d = mon.DATE
    if d:
        tyout(m, f"{NL}{d['MO']:02d}/{d['DA']:02d}/{d['YR']:02d} {d['HR']:02d}:{d['MI']:02d}{NL}")
    if not shutdown(m):                                  # INT,11 X'2A' / BDR,11: no dump on shutdown
        rcvdmp(m, mon)
    m.trace("RCVCTL: TSTHGP, IOQFLUSH, RCVRT, TP, SAVSYM, CYCUSRS, error log, SYSLIM, "
            "SYMFILS, COC, HGP: not translated")
    mvebuf(m, mon)
    reboot_disc(m, mon, reboot)


def incrda(mon):
    """INCRDA  CYCUSR.txt:1335 - one granule further into the dump area."""
    mon.RCVRDSZ -= 1
    mon.RCVRAD += 2


def rcvdmp(m, mon):
    """RCVDMP  CYCUSR.txt:1308 - core dump to the swap disc at RCVRAD (COMMRAD layout)."""
    pages = mon.CORED >> 9
    if mon.RCVRDSZ < pages:
        raise NotTranslated("TAPDMP: not enough room on the swap disc, dump to tape")
    mon.recovery_buffer.append(mon.RCVRAD)               # SV1 RCVRAD
    disc, start = m.swap_disc, mon.RCVRAD
    # COMMRAD (CYCUSR.txt:1596): write X'0'-X'3FFF', read-with-skip over X'4000'-X'7FFF'
    # (already saved there by INITRCVR), then write from X'8000' on.
    disc.write_words(start, [m.mem[a] for a in range(0, 0x4000)])
    disc.write_words(start + 0x8000 // SECTOR_WORDS, [m.mem[a] for a in range(0x8000, mon.CORED)])
    mon.RCVRAD += pages * 2                              # 2 sectors per page
    mon.RCVRDSZ -= pages
    mon.recovery_buffer += [mon.RCVRAD, 0x03000002]      # BADRAD: SV1 RCVRAD, RCVCODE (RAD dump)
    m.trace(f"RCVDMP: {pages} pages dumped at {start}, X'4000' at {start + 0x4000 // SECTOR_WORDS}")


def mvebuf(m, mon):
    """MVEBUF: the recovery buffer goes to the two granules at the original RCVRAD
    (FIX1 reads it back from there, FIX1.txt:5258)."""
    words = mon.recovery_buffer[:4 * SECTOR_WORDS]
    m.swap_disc.write_words(mon.TRCVRAD, words + [0] * (4 * SECTOR_WORDS - len(words)))


def reboot_disc(m, mon, reboot):
    """Simulate a disc boot  RCVCTL.txt:299"""
    d4 = m.mem[BOOTTYPE]                                 # SAVE FLAG OVER BOOT
    # Halt all devices; read the 88-byte bootstrap from sector 0 into X'2A'.
    for i, w in enumerate(m.swap_disc.read_words(0, 22)):
        m.mem[0x2A + i] = w
    m.mem[BOOTTYPE] = d4                                 # RESTORE FLAG
    m.mem[LOADDEV] = mon.M_SWAPD
    m.trace(f"RCVCTL: X'2A'=X'{d4:08X}', B BOOTENT")
    if reboot is None:
        raise Halted("RCVCTL: B BOOTENT")
    return reboot()


def norcvr(m, why, mon=None):
    """NORCVR  RCVCTL.txt:1163"""
    if mon is not None:
        cocout(m, mon, FAILMS)                           # TELL USERS ABOUT PROBLEMS
    m.console.write(OPERFAIL + " " + why + NL)
    m.console.write(BRKMS)
    raise Halted("NORCVR: recovery failed, operator must reboot")
