"""TBOOT: - tape boot / system install. Translated from c00co/BOOTSUBR.txt:462-1338.

Reads the system tape that writemon.writemon builds and installs it on the swap
disc: JIT, segments, RECOVER, XDELTA and the root in three parts, then DBOOT in
sector 0. Comments of the form ``# BOOTSUBR.txt:NNN`` point at the source.

Simplifications: disc addresses are relative sector numbers (DSCCVT/SEEKCVT are
identities); only a RAD swapper is handled; one swapper (LSWAP = 0).
"""

from .devices import Disc, DeviceError, SECTOR_WORDS
from .machine import BOOTFLG, BOOTTYPE, FLAG_I, FLAG_P, MachineType, PAGE_WORDS
from .monitor import Halted, NotTranslated
from .writemon import FIXED_LINES, MSZ, words_text
from .xdelta import BootPatcher
from . import reconfig

NL = "\n"
DFALTM = NL + "C/LL/DC ASSIGN OK (YES/NO)"
QM = " ??" + NL
SSWM = (NL + "SET SENSE SWITCHES AND TYPE N/L" + NL + "SSW1 => CHECKWRITE DISC WRITES"
        + NL + "SSW2 => NO AUTOMATIC LOGON/LOGOFF" + NL + "SSW3 => OPERATOR RECOVERY ON DISC BOOT"
        + NL + "SSW4 => SYSTEM SECURITY CHECKING")
BADCM = NL + "SWAPPER NOT  72{}" + NL
WRTPRTM = NL + "SWAPPER WRITE PROTECTED  {}" + NL

ROOTSA_OFFSET = 0x35 - 0x2A   # ROOTSA at X'35' (TABLES.txt:655) in DBOOT, loaded at X'2A'


def messg(m, text):
    m.console.write(text)
    return m.console.read().strip().upper()


def oc(m):
    return m.mem.get_byte(BOOTFLG) & FLAG_I


def tboot(m, mon, sysgen):
    """TBOOT:  BOOTSUBR.txt:462"""
    if m.tape is None:
        raise Halted("TBOOT: no system tape mounted")
    mon.DCT = [e if e is None else type(e)(e.yy, e.ndd, e.type) for e in sysgen.dct]
    reconfig.initl(m, mon)                                   # RECNFG:0
    assign_devices(m, mon, sysgen)
    jit_setup(m, mon, sysgen)
    names = creation_data(m, mon)
    load_xdelta(m, mon)
    if oc(m):
        messg(m, SSWM)                                       # the chain reads 1 byte (N/L)
    patcher = BootPatcher(m, mon, names)
    segpatch(mon, patcher)                                   # SEGNO 0: the root
    swapinit(m, mon, sysgen, patcher)


def segpatch(mon, patcher, base=None, size=None):
    """SEGPATCH  BOOTSUBR.txt:675"""
    mon.SEGNO += 1
    patcher.segpatch(mon.SEGNO, base, size)


# --- device assignment -------------------------------------------------------

def assign_devices(m, mon, sysgen):
    """C/LL/DC ASSIGN OK, VALINP/DCINP and the swapper check (BOOTSUBR.txt:466-549)."""
    ask = False
    if oc(m):
        reply = messg(m, DFALTM)
        while reply not in ("", "YES", "NO"):                # whole BUF word compared
            reply = messg(m, QM)
        ask = reply == "NO"
    mon.CNDD = valinp(m, mon, "CR", ask)
    mon.LLNDD = valinp(m, mon, "LP", ask)
    # GETDC1: each swapper (one here). After an error, DCINP is forced.
    index = sysgen.MB_SDI
    addr = valinp1(m, mon, index, ask)
    while True:
        mon.M_SWAPD = addr
        error = check_rad(m, mon, sysgen, addr)
        if error is None:
            break
        m.console.write(error)                               # BADCMN
        addr = dcinp(m, mon, index)
    m.swap_disc = m.devices[mon.M_SWAPD]
    m.trace(f"TBOOT: CR X'{mon.CNDD:03X}' LP X'{mon.LLNDD:03X}' swapper X'{mon.M_SWAPD:03X}'")


def valinp(m, mon, dtype, ask):
    """VALINP  BOOTSUBR.txt:768 - find the DCT index by type code."""
    for i, entry in enumerate(mon.DCT):
        if entry is not None and entry.type == dtype:
            return valinp1(m, mon, i, ask)
    raise Halted(f"VALINP: no {dtype} in the DCT (B %: can't boot)")


def valinp1(m, mon, index, ask):
    if not ask:
        return mon.DCT[index].address
    return dcinp(m, mon, index)


def dcinp(m, mon, index):
    """DCINP  BOOTSUBR.txt:778 - 'YYNDD => ', reply SA or a new NDD."""
    entry = mon.DCT[index]
    reply = messg(m, NL + entry.name + " => ")
    while True:
        if reply.startswith("SA"):
            return entry.address
        addr = parse_ndd(reply, m.model)
        if addr is not None:
            break
        reply = messg(m, QM)                                 # EOM
    entry.ndd = (reply[:3] + "\0\0\0")[:3].rstrip("\0")       # STS,8 13 under X'00FFFFFF'
    entry.address = addr                                     # DCT1, DCT1A, DCT1P
    return addr


def parse_ndd(reply, model):
    """CL2PA plus FLD: letter, then hex digits up to a blank or the end."""
    if not reply:
        return None
    pa = reconfig.cl2pa(reply[0], model)
    if pa is None:
        return None
    r9 = pa + 1
    for ch in reply[1:]:
        if ch <= " ":
            break
        if ch not in "0123456789ABCDEF":
            return None
        r9 = (r9 << 4) | int(ch, 16)
        if r9 >> 28:
            return None                                      # too many characters
    r9 -= 0x100
    return r9 if r9 >= 0 else None


def check_rad(m, mon, sysgen, addr):
    """GETDC2  BOOTSUBR.txt:527 - controller model and write protect from sense data."""
    dev = m.devices.get(addr)
    want, digits = (0x80, "12") if sysgen.MB_SWAPS == 0 else (0x56, "32")
    if sysgen.S_DP:
        raise NotTranslated("TBOOT: disk-pack swapper check (CT1)")
    if not isinstance(dev, Disc) or dev.model != want:       # BADISC
        return BADCM.format(digits)
    if dev.write_protected:                                  # WRTPRT
        return WRTPRTM.format(mon.DCT[sysgen.MB_SDI].name)
    return None


def jit_setup(m, mon, sysgen):
    """DCDPOK  BOOTSUBR.txt:549 - JIT disc address, JX:CMAP, JIT CLIST, S:MAPCW/S:ACCW."""
    mon.DISCLOC = 2 if sysgen.S_DP else sysgen.DAJ
    # The JX:CMAP entries, the JIT swap command list and the swapper's map
    # control words aren't modeled.
    m.trace(f"TBOOT: JIT disc address {mon.DISCLOC}")


# --- tape reads --------------------------------------------------------------

def creation_data(m, mon):
    """Creation-data record, SYSVERS, MAXSEG, listing (BOOTSUBR.txt:601-654)."""
    rec = m.tape.read_record()
    nlines = rec[0] & 0xFFFFFF
    v = rec[rec[0] >> 24]
    byte = (((v >> 16) & 0xF) << 4) | (v & 0xF)              # SLD -4, SLS -12, SLD 4
    r5 = 0x4170                                              # symbiont, CP-V, Sigma 7
    if m.model is MachineType.SIGMA9:
        r5 += 0x4000
    elif m.model is MachineType.X560:
        r5 += 0x8000
    word = (byte << 24) | r5                                 # STB,4 5
    mon.SYSVERS = ((word >> 8) | (word << 24)) & 0xFFFFFFFF  # SCS,5 -8
    mon.MAXSEG = nlines - 11                                 # LI,2 -11 + count -> LI,3 MAXSEG
    lines = [words_text(rec[1 + MSZ * i:1 + MSZ * (i + 1)]) for i in range(nlines)]
    if m.mem.get_byte(BOOTFLG) & FLAG_P:
        for line in lines:
            m.printer.print(line[1:].rstrip())
    if oc(m):
        m.console.write("".join(NL + line[1:] for line in lines))
    names = [line.strip() for line in lines[FIXED_LINES:FIXED_LINES + mon.MAXSEG]]
    m.trace(f"TBOOT: SYSVERS=X'{mon.SYSVERS:08X}' MAXSEG={mon.MAXSEG}")
    return names


def load_xdelta(m, mon):
    """DELTA HEAD and code  BOOTSUBR.txt:655"""
    head = m.tape.read_record()
    mon.DLTBIAS = head[1] & 0x1FFFF
    pages = head[4] >> 24
    for k in range(pages):
        _store(m, mon.DLTBIAS + k * PAGE_WORDS, m.tape.read_record())
    mon.DLTSZ = pages * 2048
    m.trace(f"TBOOT: XDELTA at X'{mon.DLTBIAS:X}', {pages} pages")


def rtape(m, nrec):
    """RTAPE  BOOTSUBR.txt:1177 - read ``nrec`` 2048-byte records."""
    words = []
    for _ in range(nrec):
        words += m.tape.read_record()
    return words


def gethead(m, mon):
    """GETHEAD  BOOTSUBR.txt:1168 - read a head; its symbol-table size goes in XDELTA word 4."""
    head = m.tape.read_record()
    m.mem[mon.DLTBIAS + 4] = head[7] >> 2
    return head


def _store(m, address, words):
    for i, w in enumerate(words):
        m.mem[address + i] = w


def _fetch(m, address, nwords):
    return [m.mem[address + i] for i in range(nwords)]


# --- disc writes -------------------------------------------------------------

def wdisc(m, mon, words, nbytes, read=False):
    """WDISC  BOOTSUBR.txt:1210 - write (or read) at DISCLOC, rounded to whole granules,
    then check-write. Returns the words (read) and advances DISCLOC."""
    granules = (nbytes + 2047) // 2048                       # GRANBND
    nwords = nbytes // 4
    disc = m.swap_disc
    if read:
        words = disc.read_words(mon.DISCLOC, nwords)
    else:
        try:
            disc.write_words(mon.DISCLOC, list(words[:nwords]))
        except DeviceError:
            # NOCHKWRT: SPECFLG is set, so WRTPRT stops the machine (B %).
            mon.SPECFLG = 1
            m.console.write(WRTPRTM.format(mon.DCT[mon_sdi(mon)].name))
            raise Halted("SWAPPER WRITE PROTECTED during the copy to disc")
        if disc.read_words(mon.DISCLOC, nwords) != list(words[:nwords]):   # check-write (code 5)
            raise Halted("!! CHECK-WRITE ERROR")
    mon.DISCLOC += granules * 2
    return words


def mon_sdi(mon):
    for i, entry in enumerate(mon.DCT):
        if entry is not None and entry.address == mon.M_SWAPD:
            return i
    return 0


def rwdsk(m, mon, patcher, nrec, headword, words=None):
    """RWDSK  BOOTSUBR.txt:1201 - read a piece, let XDELTA patch it, write it."""
    if words is None:
        words = rtape(m, nrec)
    size = (headword >> 16) << 1                             # LH,6 3 / SLS,6 1
    base = (headword & 0xFFFF) << 1                          # INT,3 3 / SLS,3 1
    segpatch(mon, patcher, base, size)
    wdisc(m, mon, words, len(words) * 4)
    return len(words) * 4


# --- SWAPINIT / RECOV / WRTROOT ----------------------------------------------

def swapinit(m, mon, sysgen, patcher):
    """SWAPINIT  BOOTSUBR.txt:1036 - first return from XDELTA."""
    if not mon.ENDFND:
        reconfig.endfalt(m, mon)                             # RECNFG:2
    wdisc(m, mon, _fetch(m, sysgen.JIT, PAGE_WORDS), 512 * 4)
    maxovly = sysgen.MAXOVLY
    mon.init_tables(maxovly + 5)
    slot = maxovly + 4                                       # ALLOCAT
    while True:
        head = gethead(m, mon)                               # RHEAD
        if slot == maxovly + 1:
            slot -= 2                                        # skip to the overlays
        parshead(m, mon, sysgen, patcher, head, slot)
        slot -= 1                                            # BDR,4 RHEAD
        if slot == 0:
            break
    recov(m, mon, sysgen, patcher)


def parshead(m, mon, sysgen, patcher, head, slot):
    """PARSHEAD  BOOTSUBR.txt:1064"""
    mon.P_SA[slot] = head[1] & 0x1FFFF
    mon.P_TCB[slot] = (head[2] >> 16) << 1
    mon.PB_DSZ[slot] = head[3] >> 24
    mon.PB_DCBSZ[slot] = head[6] >> 24
    mon.PB_PVA[slot] = (head[4] >> 8) & 0xFF
    mon.PB_PSZ[slot] = head[4] >> 24
    mon.PB_HVA[slot] = (mon.PB_PVA[slot] + mon.PB_PSZ[slot]) & 0xFF
    mon.PH_DDA[slot] = mon.DISCLOC
    if mon.PB_DSZ[slot]:
        words = rtape(m, mon.PB_DSZ[slot])
        if m.mem.signed(BOOTTYPE) + mon.SEGNO <= 0:          # under files, ALLOCAT's data
            saved = mon.DISCLOC
            words = wdisc(m, mon, None, len(words) * 4, read=True)
            mon.DISCLOC = saved
        rwdsk(m, mon, patcher, 0, head[3], words)            # PWDATA: RWDSK+1
    if mon.PB_DCBSZ[slot]:
        rwdsk(m, mon, patcher, mon.PB_DCBSZ[slot], head[6])
    mon.PH_PDA[slot] = mon.DISCLOC
    if mon.PB_PVA[slot] == sysgen.JJITVP + 1:                # UMOV
        mon.UMOVSA = mon.DISCLOC
        mon.UMOVSZ = mon.PB_PSZ[slot] << 11
        mon.UMOV_ += slot
    rwdsk(m, mon, patcher, mon.PB_PSZ[slot], head[4])
    m.trace(f"SWAPINIT: slot {slot} DDA {mon.PH_DDA[slot]} PDA {mon.PH_PDA[slot]} "
            f"PVA X'{mon.PB_PVA[slot]:02X}' HVA X'{mon.PB_HVA[slot]:02X}'")


def recov(m, mon, sysgen, patcher):
    """RECOV  BOOTSUBR.txt:1127 - RECOVER, XDELTA, MONCHK, PPTABLE."""
    head = gethead(m, mon)
    mon.RCVSTART = head[1]
    mon.PH_PDA[0] = mon.DISCLOC                              # end of the last overlay, for DRSP
    mon.RCVDISC = mon.DISCLOC
    mon.RCVSIZE = rwdsk(m, mon, patcher, head[4] >> 24, head[4])
    mon.DLTDSC = mon.DISCLOC
    wdisc(m, mon, _fetch(m, mon.DLTBIAS & 0x1FFFF, mon.DLTSZ // 4), mon.DLTSZ)
    total = 0
    for a in range(sysgen.GETHGP, sysgen.TOPROOT + 1):
        total += m.mem[a]
    mon.MONCHK = total & 0xFFFFFFFF
    if sysgen.realtime:                                      # PPTABLE exists
        mon.PPTABDSK = mon.DISCLOC
        wdisc(m, mon, [0] * sysgen.PPTABLSZ, sysgen.PPTABLSZ * 4)
        mon.PPTABDSK2 = mon.DISCLOC                          # SEEKCVT of R3 as WDISC leaves it
    m.trace(f"RECOV: RECOVER at {mon.RCVDISC}, XDELTA at {mon.DLTDSC}, MONCHK=X'{mon.MONCHK:08X}'")
    wrtroot(m, mon, sysgen)


def wrtroot(m, mon, sysgen):
    """WRTROOT  BOOTSUBR.txt:1265 - the root in up to three parts, then DBOOT."""
    mon.DABOOT = [mon.DISCLOC, 0, 0]
    r4 = ((sysgen.MONIRTN + 0x1FF - 0x4000) >> 9) - 32
    r7 = 32 if r4 > 0 else 32 + r4
    m.clock3_running = False                                 # WD X'1100': so the check-write works
    wdisc(m, mon, _fetch(m, 0, 0x4000), 32 * 2048)
    m.clock3_running = True
    mon.DABOOT[1] = mon.MPPSEEK = mon.DISCLOC
    start = 0x4000
    if r4 > 0:
        wdisc(m, mon, _fetch(m, 0x4000, 0x4000), 32 * 2048)
        mon.DABOOT[2] = mon.DISCLOC
        start, r7 = 0x8000, r4
    wdisc(m, mon, _fetch(m, start, r7 * PAGE_WORDS), r7 * 2048)  # WRTM2
    mon.RCVRAD = mon.DISCLOC
    mon.DISCLOC = mon.DABOOT[0]
    mon.SEEK4000 = mon.RCVRAD + 0x44                         # AI,R8 X'44' (see open questions)
    # BOOTIC: byte count BA(MONIRTN) & X'FFFF', command chain cleared.
    ba = sysgen.MONIRTN * 4
    count = (ba & 0xFFFF) or 0x10000
    if ba > 0x8000 * 4:
        mon.BOOTIC = [(0x4000, 0x10000), (0x8000, count)]
    else:
        mon.BOOTIC = [(0x4000, count)]
    # Part 1 again, from X'5A', now that BOOTIC and the disc addresses are set.
    sector = mon.DISCLOC
    wdisc(m, mon, _fetch(m, 0x5A, 0x4000), 32 * 2048)
    m.swap_disc.attached[sector] = mon.root_snapshot()
    # DBOOT to sector 0.
    dboot_image = [0] * PAGE_WORDS
    dboot_image[ROOTSA_OFFSET:ROOTSA_OFFSET + 3] = mon.DABOOT
    mon.DISCLOC = 0
    wdisc(m, mon, dboot_image, 2048)
    m.trace(f"WRTROOT: ROOTSA={mon.DABOOT} BOOTIC={mon.BOOTIC} RCVRAD={mon.RCVRAD}")


def read_root(m, mon, disc):
    """DBOOT's DCDW and BOOTIC: read the root back from the swap disc (BOOTSUBR.txt:1758)."""
    rootsa = disc.read_words(0, SECTOR_WORDS)[ROOTSA_OFFSET:ROOTSA_OFFSET + 3]
    if rootsa[0] == 0 or rootsa[0] not in disc.attached:
        raise Halted("DBOOT: no system on the swap disc (sector 0 has no ROOTSA)")
    _store(m, 0x5A, disc.read_words(rootsa[0], 0x4000))     # 1st 16K to X'5A'
    mon.restore(disc.attached[rootsa[0]])                   # BOOTIC is in TABLES, in part 1
    for (address, nbytes), sector in zip(mon.BOOTIC, rootsa[1:]):
        _store(m, address, disc.read_words(sector, nbytes // 4))
