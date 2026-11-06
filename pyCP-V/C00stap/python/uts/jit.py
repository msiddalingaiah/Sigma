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
TELFLGS, INTENT, TIMENT = 33, 35, 36    # J:TELFLGS, J:INTENT, J:TIMENT
USENT = 38                              # J:USENT: USRENT and TRPFLAGS, one word (:438-:439)
TCB, TREE, DCBLINK = 39, 40, 43         # J:TCB, J:TREE, J:DCBLINK
EXTENT = 72                             # J:EXTENT: exit control (:487; STPNR.txt:335)
M_UC = 44                               # M:UC: a DCB of 22 words (JH:PC, its last, :467)
PRIV_BYTE = 268                         # JB:PRIV
PUF = 69                                # J:PUF: byte 0, the command line's length (TEL.txt:6239)
PROMPT_BYTE = 283                       # JB:PROMPT
# CP-V's JIT, as the tape's processors address it, has 4 words more than JIT.txt's (a UTS
# JIT) between TMPDCPK (word 73) and TSTACK: TEL, SHOW, EDIT and LOGON address J:CCBUF at
# word 204, TSTACK at 78, J:START at 233, M:XX's name VLP at 257, J:BUP at 274; everything
# up to J:EXTENT where JIT.txt has it. What the 4 words hold isn't known: 0 here.
CPV_EXTRA = 4
TSTACK = 74 + CPV_EXTRA                 # the temporary stack, 123 words (JTSTACKSZ 121 + 2)
CCBUF, CCBUF_WORDS = 200 + CPV_EXTRA, 13   # J:CCBUF: the command line
LMN, START = 226 + CPV_EXTRA, 229 + CPV_EXTRA   # J:LMN (3 words), J:START
M_XX = 230 + CPV_EXTRA                  # M:XX, the program's own load module's DCB
MXFPL, MXKB = M_XX + 22, M_XX + 32      # its VLPs (name, account, password), key buffer
# Memory management (JIT.txt:539-:617): page numbers, lower and upper limits of each area
BUP, EUP = M_XX + 40, M_XX + 41         # J:BUP, J:EUP: the user's pages
PLL, PUL, DLL, DUL = BUP + 2, BUP + 3, BUP + 4, BUP + 5       # pure procedure; data
DDLL, DDUL, CLL, CUL = BUP + 6, BUP + 7, BUP + 8, BUP + 9     # dynamic data; context
DCBLL, DCBUL = BUP + 10, BUP + 11                             # DCBs
PCP_BYTE = 4 * (BUP + 12)               # JB:PCP, PCD, PCDD, PCC, PCDCB: page counts by area
TDP_BYTE, BCP_BYTE = 4 * (BUP + 15), 4 * (BUP + 15) + 1   # JB:TDP, JB:BCP
JBUPVP, JEUPVP = 0x50, 0xDF             # JIT.txt:282, :284
SIZE = BUP + 16                         # the template's words
UC_ADDRESS = J_JIT + M_UC               # X'8C2C'
XX_ADDRESS = J_JIT + M_XX               # X'8CEA'

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
            M_XX + 6: J_JIT + MXFPL,    # MXFPL
            M_XX + 10: J_JIT + MXKB,    # MXKB
            MXFPL: 0x01000003,          # MXFPL: the name VLP
            MXFPL + 4: 0x02000002,      # the account VLP
            MXFPL + 7: 0x03010002,      # the password VLP, the last
            BUP: JBUPVP, EUP: JEUPVP,   # an area's upper limit below its lower: no pages
            PLL: JBUPVP, PUL: JBUPVP - 1, DLL: JBUPVP, DUL: JBUPVP - 1,
            DDLL: JBUPVP, DDUL: JEUPVP, CLL: 0x46, CUL: JBUPVP - 1,
            DCBLL: JBUPVP, DCBUL: JBUPVP - 1,
            BUP + 14: 0x00004000,       # JB:CBLL  DATA,1 JOVVP
            BUP + 15: (JBUPVP << 24) | (JEUPVP << 16)}   # JB:TDP, JB:BCP
KIND_BATCH, KIND_GHOST, KIND_ONLINE = 0, 1, 2   # J:JIT byte 0 >> 6 (OPND.txt:268-:270)
EOM = 0x15                              # the end of a command line (EBCDIC NL)


def text_words(data, n, fill=b"\x40"):
    data = data[:4 * n].ljust(4 * n, fill)
    return [int.from_bytes(data[i:i + 4], "big") for i in range(0, 4 * n, 4)]


def build(sched, u, tcb=0, dcblink=0, tree=0, start=0, name="", limits=None, account=""):
    """The JIT page for user ``u``: {word address: value}. ``limits``: FETCH's memory
    limits by JIT word (fetch.linklims), with JB:TDP from the dynamic data's lower limit.
    M:XX's name and account VLPs hold the load module's NAME.ACCOUNT, as the step's
    open of M:XX leaves them (the source of M:SGLD's, STPNR.txt:1497-:1499)."""
    cal = sched.cal
    kind = KIND_ONLINE if u in sched.LB_UN else KIND_GHOST if u in sched.SB_GJOBUN else KIND_BATCH
    words = [TEMPLATE.get(i, 0) for i in range(SIZE)]
    for i, v in (limits or {}).items():
        words[i] = v
    if limits and DDLL in limits:
        words[TDP_BYTE // 4] = (words[TDP_BYTE // 4] & 0x00FFFFFF) | ((limits[DDLL] & 0xFF) << 24)
    words[SYSID] = (kind << 30) | (u & 0xFFFF)
    words[ACCN:ACCN + 2] = text_words(cal.account.get(u, ":SYS").encode(EBCDIC), 2)
    words[UNAME:UNAME + 3] = text_words(cal.uname.get(u, "").encode(EBCDIC), 3)
    words[TCB], words[DCBLINK], words[TREE], words[START] = tcb, dcblink, tree, start
    words[INTENT] = cal.intent.get(u, 0)
    line = sched.coc.line_of(u) if getattr(sched, "coc", None) is not None else None
    if line is not None:                               # LINE#: M:UC+COCLN's low byte
        words[M_UC + 1] = (words[M_UC + 1] & ~0xFF) | (line & 0xFF)   # (UCAL.txt:418, :439)
    words[LMN:LMN + 3] = text_words(bytes([len(name)]) + name.encode(EBCDIC), 3)
    if name:                                           # MXFPL: the name VLP, 3 words used
        words[MXFPL] = (words[MXFPL] & 0xFFFF00FF) | (3 << 8)
        words[MXFPL + 1:MXFPL + 4] = words[LMN:LMN + 3]
    if account:                                        # the account VLP, 2 words used
        words[MXFPL + 4] = (words[MXFPL + 4] & 0xFFFF00FF) | (2 << 8)
        words[MXFPL + 5:MXFPL + 7] = text_words(account.encode(EBCDIC), 2)
    line = cal.ccbuf.get(u, "").encode(EBCDIC, errors="replace")[:4 * CCBUF_WORDS - 1]
    line += bytes([EOM])                               # TEL's line ends with its NL
    words[CCBUF:CCBUF + CCBUF_WORDS] = text_words(line, CCBUF_WORDS)
    words[PUF] = (len(line) << 24) | (words[PUF] & 0x00FFFFFF)
    w = PRIV_BYTE // 4
    words[w] = (words[w] & 0x00FFFFFF) | ((cal.priv.get(u, 0) & 0xFF) << 24)
    w = PROMPT_BYTE // 4
    words[w] = (words[w] & 0xFFFFFF00) | (cal.prompt.get(u, 0) & 0xFF)
    return {J_JIT + i: v & 0xFFFFFFFF for i, v in enumerate(words)}
