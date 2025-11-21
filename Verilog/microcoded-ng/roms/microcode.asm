
# ---- BEGIN Pipeline definitions DO NOT EDIT

const seq.endian = BIG
const seq.width = 56

field seq.op = 0:1
field seq.address_mux = 2:3
field seq.condition = 4:7
field ax = 8:10
field bx = 11:12
field cx = 13:15
field dx = 16:18
field ex = 19:21
field ox = 22:22
field px = 23:25
field qx = 26:27
field rrx = 28:28
field sx = 29:32
field ende = 33:33
field testa = 34:34
field wd_en = 35:35
field trap = 36:36
field uc_debug = 37:37
field write_size = 38:39
field __unused = 40:43
field seq.address = 44:55
field _const12 = 44:55

const AXNONE = 0
const AXCONST = 1
const AXE = 2
const AXR = 3
const AXRR = 4
const AXS = 5
const BXNONE = 0
const BXCONST = 1
const BXS = 2
const CXNONE = 0
const CXCONST = 1
const CXMB = 2
const CXRR = 3
const CXS = 4
const DXNONE = 0
const DXCONST = 1
const DXC = 2
const DXCC = 3
const DXNC = 4
const DXPSW1 = 5
const DXPSW2 = 6
const EXNONE = 0
const EXCONST = 1
const EXB = 1
const EXCC = 2
const EXS = 3
const OXNONE = 0
const OXC = 1
const PXNONE = 0
const PXCONST = 1
const PXQ = 2
const PXS = 3
const PCTP1 = 4
const QXNONE = 0
const QXCONST = 1
const QXP = 2
const RRXNONE = 0
const RRXS = 1
const SXPLUS = 0
const SXXOR = 1
const SXOR = 2
const SXAND = 3
const SXMA = 4
const SXMD = 5
const SXUAB = 6
const SXUAH = 7
const SXUDB = 8
const SXUDH = 9
const SXA = 10
const SXB = 11
const SXD = 12
const SXP = 13
const ADDR_MUX_SEQ = 0
const ADDR_MUX_OPCODE = 1
const ADDR_MUX_OPROM = 2
const COND_NONE = 0
const WR_NONE = 0
const WR_BYTE = 1
const WR_HALF = 2
const WR_WORD = 3

# ---- END Pipeline definitions DO NOT EDIT

def main:
    _const12 = 5, ax = AXCONST, uc_debug=1
    _const12 = 7, dx = DXCONST, uc_debug=1
    sx = SXPLUS, ax = AXS, uc_debug=1
    # sx = SXPLUS
    # sx = SXPLUS
    # trap = 1
