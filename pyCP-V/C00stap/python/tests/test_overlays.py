"""Overlays: FETCH of an overlaid load module (the root, M:SGLD from M:XX), and M:SEGLD
(ALTCP.txt MSEGLD, SEGLD.txt) reading a segment by its tree entry. Also the services EDIT
needed at its start: M:DISASSOC, M:TS, and a terminal record's NL."""

from tests.test_online import logged_on
from uts import jit
from uts.cal import OP_CAL1, instruction
from uts.fetch import LM_KEYM
from uts.files import EBCDIC

ROOT, OV1 = "ROOT", "OV1"
TREE_AT, CODE_AT, DCB_TABLE, SGLD, OV1_DATA = 0xAC00, 0xAC20, 0xA800, 0xA810, 0xA200


def text(s, n):
    data = s.encode(EBCDIC).ljust(4 * n, b"\x40")
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, 4 * n, 4)]


def name3(s):
    """A TEXTC name in three words, blank-padded."""
    data = (bytes([len(s)]) + s.encode(EBCDIC)).ljust(12, b"\x40")
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, 12, 4)]


def as_bytes(ws):
    return b"".join((w & 0xFFFFFFFF).to_bytes(4, "big") for w in ws)


def entry(name, flags, links, data, proc, dcbs=0):
    """A tree entry: the name, word 3 flags/parent, word 4 child/sibling, the sections."""
    return name3(name) + [flags, links, data, 0, proc, 0, dcbs, 0]


def overlaid_module(fs, name="PROG"):
    """Data X'A000'-X'A3FF' (the TCB at X'A000', OV1's data at X'A200'), DCBs at X'A800'
    (M:SGLD), procedure at X'AC00': the tree, then the root's code."""
    tree = [23] + entry(ROOT, 0, 11 << 16, 0x10 << 16 | 0x5000, 0x20 << 16 | 0x5600,
                        0x10 << 16 | 0x5400) \
        + entry(OV1, 0, 0, 0x2 << 16 | 0x5100, 0x5620)
    write = [0x11000000 | 0x8C2C, 0x30000000, OV1_DATA, 5]
    code = [instruction(OP_CAL1, 8, CODE_AT + 4),          # M:SEGLD OV1
            instruction(OP_CAL1, 1, CODE_AT + 6),          # write its data on M:UC
            instruction(OP_CAL1, 9, 1),
            0,
            0x01000000, TREE_AT + 12,                      # FPT: X'01', the OV1 entry
            *write]
    proc = tree + [0] * (CODE_AT - TREE_AT - len(tree)) + code
    data = [0] * 10 + [DCB_TABLE] + [0] * 21               # the TCB: word 10, the DCB table
    sgld_name = name3("M:SGLD")[:2]                        # TEXTC 'M:SGLD' in two words
    table = [DCB_TABLE + 1 + 3] + sgld_name + [SGLD] + [0]
    dcb = [0x33000003, 0, 0, 0, 0, 0, SGLD + 22] + [0] * 15 \
        + [0x01000003, 0, 0, 0, 0x02000002, 0, 0, 0x03010002, 0, 0]
    dcbs = table + [0] * (SGLD - DCB_TABLE - len(table)) + dcb
    head = [0x8000FF30, 0x80000000 | CODE_AT, 0x5000 << 16 | 0x5000, 0x200 << 16 | 0x5000,
            0x100 << 16 | 0x5600, 0, 0x10 << 16 | 0x5400, 0, 0, 0, 0, 0]
    root, ov = ROOT.encode(EBCDIC), OV1.encode(EBCDIC)
    records = {"HEAD".encode(EBCDIC): as_bytes(head), "TREE".encode(EBCDIC): as_bytes(tree),
               root + bytes([3]): as_bytes(data), root + bytes([5]): as_bytes(proc),
               root + bytes([7]): as_bytes(dcbs), ov + bytes([3]): as_bytes(text("HELLO", 2))}
    fs.add_account(":SYS")
    cfu = fs.open(name, ":SYS", "OUT", keym=LM_KEYM)
    for key in sorted(records):
        cfu.file.write(key, records[key])
    fs.close(cfu)


def test_m_segld_reads_an_overlay():
    t = logged_on()
    overlaid_module(t.s.cal.fs)
    t.type("PROG\r")
    assert t.text() == "PROG\r\nHELLO\r\n!"
    u = t.s.LB_UN[0]
    mem, cal = t.s.umem[u], t.s.cal
    assert cal.jword(u, jit.TREE) == TREE_AT                         # J:PLL's page
    assert mem[TREE_AT + 12 + 3] >> 31 == 1                          # OV1: in memory now
    assert 0x51 in cal.cmap[u]                                       # MEMSET got its page
    assert any("SEGLD user" in line and "OV1 type 3" in line for line in t.s.log)
    sgld = [mem.get(SGLD + 22 + i, 0) for i in range(4)]            # M:XX's name VLP
    assert sgld[0] == 0x01000303 and sgld[1] >> 24 == 4              # TEXTC 'PROG'


ASSOC = """
         ORG      X'D000'
START    CAL1,4   DIS               M:DISASSOC :PDD: no such processor here, CC1
         STCF     R
         CAL1,8   TS                M:TS, extended: R8-R11
         STW,8    R+1
         STW,9    R+2
         STW,10   R+3
         STW,11   R+4
         CAL1,9   1
DIS      DATA     X'05000000'
         TEXT     ':PDD    '
TS       DATA     X'06600000'
R        RES      5
         END      START
"""


def test_m_disassoc_and_m_ts():
    from uts.asm import assemble
    from uts.fetch import write_load_module
    t = logged_on()
    words, start = assemble(ASSOC)
    write_load_module(t.s.cal.fs, "ASSOC", ":SYS", words, start)
    t.type("ASSOC\r")
    t.text()
    u = t.s.LB_UN[0]
    r = [t.s.umem[u].get(max(words) - 4 + i, 0) & 0xFFFFFFFF for i in range(5)]
    assert r[0] >> 28 == 8                                           # CC1: not a processor
    assert r[1] == 0x00882000                                        # COCTERM, MODE, MODE2, MODE3
    assert r[2] & 0xFF == u                                          # LB:UN
    assert r[4] & 0xFFFF == (72 << 8) | 54                           # JB:PCW, JB:LPP


READ = """
         ORG      X'D000'
START    CAL1,1   READ              M:READ on M:UC
         CAL1,9   1
READ     DATA     X'10008C2C',X'30000000',BUF,20
BUF      RES      5
         END      START
"""


def test_a_terminal_record_ends_with_its_nl_and_m_uc_shows_the_ars():
    from uts.asm import assemble
    from uts.fetch import write_load_module
    t = logged_on()
    words, start = assemble(READ)
    write_load_module(t.s.cal.fs, "READ", ":SYS", words, start)
    t.type("READ\r")
    t.type("ABC\r")
    t.text()
    u = t.s.LB_UN[0]
    buf = max(words) - 4
    assert t.s.cal.read_bytes(u, buf, 0, 4) == "ABC".encode(EBCDIC) + b"\x15"   # MUCRLFNL
    assert (t.s.umem[u][0x8C2C + 4] >> 17) & 0x7FFF == 4             # the ARS, in M:UC itself
