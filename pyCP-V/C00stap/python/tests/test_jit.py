"""The JIT page in a user's memory (uts/jit.py): the template from JIT.txt, the user's
own fields, and programs that read it: M:UC at its real address, J:CCBUF."""

from tests.test_online import logged_on
from uts import jit
from uts.asm import assemble
from uts.fetch import write_load_module
from uts.files import EBCDIC


def test_the_template_and_the_users_fields():
    t = logged_on()
    u = t.s.LB_UN[0]
    t.s.cal.ccbuf[u] = "PROG ARGS"
    page = jit.build(t.s, u, tcb=0xA000, dcblink=0xA800, start=0xA064, name="PROG")
    w = lambda i: page[jit.J_JIT + i]
    assert w(jit.SYSID) >> 30 == jit.KIND_ONLINE and w(jit.SYSID) & 0xFFFF == u
    assert b"".join(w(jit.ACCN + i).to_bytes(4, "big") for i in range(2)) == "BOB     ".encode(EBCDIC)
    assert b"".join(w(jit.UNAME + i).to_bytes(4, "big") for i in range(3)).decode(EBCDIC).strip() == "ROBERT"
    assert (w(jit.TCB), w(jit.DCBLINK), w(jit.START)) == (0xA000, 0xA800, 0xA064)
    assert w(jit.M_UC) == 3 and w(jit.M_UC + 1) >> 8 == 0x1E4            # M:UC: ASN 3
    assert w(jit.M_UC + 1) & 0xFF == t.s.coc.line_of(u)                  # LINE#: the COC line
    assert jit.UC_ADDRESS == 0x8C2C and jit.XX_ADDRESS == 0x8CEA
    assert jit.CCBUF == 204 and jit.TSTACK == 78                         # CP-V's JIT (jit.py)
    assert w(jit.ABC) == 0x80700000 and w(70) & ~0xFF == 0x36314800   # JB:LPP/LC/PCW
    assert w(70) & 0xFF == ord("!".encode(EBCDIC))                       # JB:PROMPT: TEL's
    line = b"".join(w(jit.CCBUF + i).to_bytes(4, "big") for i in range(3))
    assert line[:10] == "PROG ARGS".encode(EBCDIC) + bytes([jit.EOM])
    assert w(jit.PUF) >> 24 == 10                                       # J:PUF: its length


CCLINE = """
* Write the command line (J:CCBUF) on M:UC at its real address, X'8C2C'
         ORG      X'D000'
START    CAL1,1   WRITE
         CAL1,9   1
WRITE    DATA     X'11008C2C',X'30000000',X'8CCC',18
         END      START
"""


def test_a_program_reads_its_command_line_and_writes_on_m_uc():
    t = logged_on()
    words, start = assemble(CCLINE)
    write_load_module(t.s.cal.fs, "CCLINE", ":SYS", words, start)
    t.type("CCLINE HELLO THERE\r")
    assert t.text() == "CCLINE HELLO THERE\r\nCCLINE HELLO THERE\r\n!"
