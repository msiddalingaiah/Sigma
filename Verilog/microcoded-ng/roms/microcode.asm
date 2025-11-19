
# ---- BEGIN Pipeline definitions DO NOT EDIT

const seq.endian = BIG
const seq.width = 56

field seq.op = 0:1
field seq.address_mux = 2:3
field seq.condition = 4:7
field ax = 8:11
field dx = 12:14
field px = 15:17
field qx = 18:18
field rrx = 19:22
field sxop = 23:26
field ende = 27:27
field testa = 28:28
field wd_en = 29:29
field trap = 30:30
field divide = 31:33
field multiply = 34:35
field uc_debug = 36:36
field write_size = 37:38
field __unused = 39:43
field seq.address = 44:55
field _const8 = 48:55

const SX_ADD = 0
const SX_SUB = 1
const SX_A = 2
const SX_D = 3
const AX_NONE = 0
const AX_S = 1
const AX_RR = 2
const AX_0 = 3
const DX_NONE = 0
const DX_0 = 1
const DX_1 = 2
const DX_CINB = 3
const DX_CINH = 4
const DX_CIN = 5
const PX_NONE = 0
const PX_D_INDX = 1
const PX_Q = 2
const QX_NONE = 0
const QX_P = 1
const RRX_NONE = 0
const RRX_S = 1
const RRX_Q = 2
const COND_NONE = 0
const COND_S_GT_ZERO = 1
const COND_S_LT_ZERO = 2
const COND_CC_AND_R_ZERO = 3
const COND_C0_EQ_1 = 4
const COND_CIN0_EQ_1 = 5
const COND_E_NEQ_0 = 6
const ADDR_MUX_SEQ = 0
const ADDR_MUX_OPCODE = 1
const ADDR_MUX_OPROM = 2
const DIV_NONE = 0
const DIV_PREP = 1
const DIV_LOOP = 2
const DIV_POST = 3
const DIV_SAVE = 4
const MUL_NONE = 0
const MUL_PREP = 1
const MUL_LOOP = 2
const MUL_SAVE = 3
const WR_NONE = 0
const WR_BYTE = 1
const WR_HALF = 2
const WR_WORD = 3

# ---- END Pipeline definitions DO NOT EDIT

