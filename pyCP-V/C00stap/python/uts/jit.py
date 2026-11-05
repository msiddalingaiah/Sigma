"""The JIT page in a user's memory (docs/jit.md). In CP-V each user's job information
table sits at virtual page X'46' (JJITVP, JIT.txt:272), word X'8C00', and programs read
it there: the kind of user, the account and name, the privilege, the command line,
M:UC and M:XX themselves. The translation's monitor keeps its JIT as Python fields
(sched.Jit); this builds the page a program sees, from JIT.txt's template and the
user's own values, when the program starts. It isn't kept in step with the monitor's
fields afterwards (a departure), except J:INTENT, which M:INT writes.

The template was assembled from JIT.txt, J:JIT (:304) to the memory-management words
(JBUP, :542): the labels' word offsets and the initial words below.
"""

from .files import EBCDIC

J_JIT = 0x46 * 512                      # X'8C00'
# Word offsets from J:JIT (a byte field: its byte offset)
SYSID = 0                               # J:UN: the kind of user (bits 0-1), the user number
ACCN, UNAME = 1, 3                      # J:ACCN (2 words), J:UNAME (3 words)
ABC, RNST, ASSIGN = 17, 18, 20          # J:ABC, J:RNST, J:ASSIGN
ERO, ABO = 21, 22                       # the error and abnormal addresses
TELFLGS, INTENT = 33, 35                # J:TELFLGS, J:INTENT
TCB, TREE, DCBLINK = 39, 40, 43         # J:TCB, J:TREE, J:DCBLINK
M_UC = 44                               # M:UC: a DCB of 22 words (JH:PC, its last, :467)
PRIV_BYTE = 268                         # JB:PRIV
PUF = 69                                # J:PUF: byte 0, the command line's length (TEL.txt:6239)
PROMPT_BYTE = 283                       # JB:PROMPT
TSTACK = 74                             # the temporary stack, 123 words
CCBUF, CCBUF_WORDS = 200, 13            # J:CCBUF: the command line
LMN, START = 226, 229                   # J:LMN (3 words), J:START
M_XX = 230                              # M:XX, the program's own load module's DCB
SIZE = 270                              # the template's words
UC_ADDRESS = J_JIT + M_UC               # X'8C2C'
XX_ADDRESS = J_JIT + M_XX               # X'8CE6'

TEMPLATE = {ABC: 0x80700000,            # J:ABC  DATA X'80700000'
            26: 0x0FFE0000,             # J:JIP  GEN,15,17 X'7FF',0
            34: 0x02000000,             # J:CASSIN  DATA X'2000000'
            M_UC: 3,                    # M:UC  DATA 3,X'1E4C3': ASN 3, the name UC
            M_UC + 1: 0x0001E4C3,
            PUF: 0x0000000F,            # J:PUF  DATA X'F'
            70: 0x36314800,             # JB:LPP 54, JB:LC 49, JB:PCW 72, JB:PROMPT 0
            TSTACK: J_JIT + TSTACK + 20,   # TSTACK  DATA TSTACK+20
            TSTACK + 1: 0x00660013,     # GEN,16,16 JTSTACKSZ-19,19
            TSTACK + 2: 0x00C0000F,
            TSTACK + 3: 0x10000000,     # GOOD WRITE KEY
            TSTACK + 18: 0x7AE2E8E2,    # TEXT ':SYS    '
            TSTACK + 19: 0x40404040,
            TSTACK + 20: 0x04900001,    # CAL1,9 1  REG. 15
            **{i: 0x00000BAD for i in range(TSTACK + 21, TSTACK + 123)},   # DO ... X'BAD'
            M_XX: 1,                    # M:XX  DATA 1,0,0,0,0,0,MXFPL / 0,0,0,MXKB
            M_XX + 6: J_JIT + 252,      # MXFPL
            M_XX + 10: J_JIT + 262,     # MXKB
            252: 0x01000003,            # MXFPL: the name VLP
            256: 0x02000002,            # the account VLP
            259: 0x03010002}            # the password VLP, the last
KIND_BATCH, KIND_GHOST, KIND_ONLINE = 0, 1, 2   # J:JIT byte 0 >> 6 (OPND.txt:268-:270)
EOM = 0x15                              # the end of a command line (EBCDIC NL)


def text_words(data, n, fill=b"\x40"):
    data = data[:4 * n].ljust(4 * n, fill)
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, 4 * n, 4)]


def build(sched, u, tcb=0, dcblink=0, tree=0, start=0, name=""):
    """The JIT page for user ``u``: {word address: value}."""
    cal = sched.cal
    kind = KIND_ONLINE if u in sched.LB_UN else KIND_GHOST if u in sched.SB_GJOBUN else KIND_BATCH
    words = [TEMPLATE.get(i, 0) for i in range(SIZE)]
    words[SYSID] = (kind << 30) | (u & 0xFFFF)
    words[ACCN:ACCN + 2] = text_words(cal.account.get(u, ":SYS").encode(EBCDIC), 2)
    words[UNAME:UNAME + 3] = text_words(cal.uname.get(u, "").encode(EBCDIC), 3)
    words[TCB], words[DCBLINK], words[TREE], words[START] = tcb, dcblink, tree, start
    words[INTENT] = cal.intent.get(u, 0)
    words[LMN:LMN + 3] = text_words(bytes([len(name)]) + name.encode(EBCDIC), 3)
    line = cal.ccbuf.get(u, "").encode(EBCDIC, errors="replace")[:4 * CCBUF_WORDS - 1]
    line += bytes([EOM])                               # TEL's line ends with its NL
    words[CCBUF:CCBUF + CCBUF_WORDS] = text_words(line, CCBUF_WORDS)
    words[PUF] = (len(line) << 24) | (words[PUF] & 0x00FFFFFF)
    w = PRIV_BYTE // 4
    words[w] = (words[w] & 0x00FFFFFF) | ((cal.priv.get(u, 0) & 0xFF) << 24)
    w = PROMPT_BYTE // 4
    words[w] = (words[w] & 0xFFFFFF00) | (cal.prompt.get(u, 0) & 0xFF)
    return {J_JIT + i: v & 0xFFFFFFFF for i, v in enumerate(words)}
