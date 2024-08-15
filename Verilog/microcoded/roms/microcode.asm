
# ---- BEGIN Pipeline definitions DO NOT EDIT

const seq.endian = BIG;
const seq.width = 56;

field seq.op = 0:1;
field seq.address_mux = 2:3;
field seq.condition = 4:6;
field ax = 7:10;
field dx = 11:13;
field px = 14:16;
field qx = 17:17;
field rrx = 18:21;
field sxop = 22:25;
field ende = 26:26;
field testa = 27:27;
field wd_en = 28:28;
field trap = 29:29;
field uc_debug = 30:30;
field __unused = 31:43;
field seq.address = 44:55;
field _const8 = 48:55;

const SX_ADD = 0;
const SX_SUB = 1;
const SX_D = 2;
const AX_NONE = 0;
const AX_S = 1;
const AX_RR = 2;
const DX_NONE = 0;
const DX_1 = 1;
const DX_CINB = 2;
const DX_CINH = 3;
const DX_CIN = 4;
const PX_NONE = 0;
const PX_D_INDX = 1;
const PX_Q = 2;
const QX_NONE = 0;
const QX_P = 1;
const RRX_NONE = 0;
const RRX_S = 1;
const RRX_Q = 2;
const COND_NONE = 0;
const COND_S_GT_ZERO = 1;
const COND_S_LT_ZERO = 2;
const COND_CC_AND_R_ZERO = 3;
const COND_C0_EQ_1 = 4;
const COND_CIN0_EQ_0 = 5;
const ADDR_MUX_SEQ = 0;
const ADDR_MUX_OPCODE = 1;
const ADDR_MUX_OPROM = 2;

# ---- END Pipeline definitions DO NOT EDIT

def main {
    sxop = SX_ADD;
    sxop = SX_ADD;
    sxop = SX_ADD;
    ende = 1;
    loop {
        sxop = SX_ADD; # Empty slot for indirect
        direct: ax = AX_RR, qx = QX_P, px = PX_D_INDX, romswitch ADDR_MUX_OPROM "roms/op_switch.txt" {
            OP_NAO_00: {
                continue _trap;
            }
            OP_NAO_01: {
                continue _trap;
            }
            OP_LCFI: {
                continue _trap;
            }
            OP_NAO_03: {
                continue _trap;
            }
            OP_CAL1: {
                continue _trap;
            }
            OP_CAL2: {
                continue _trap;
            }
            OP_CAL3: {
                continue _trap;
            }
            OP_CAL4: {
                continue _trap;
            }
            OP_PLW: {
                continue _trap;
            }
            OP_PSW: {
                continue _trap;
            }
            OP_PLM: {
                continue _trap;
            }
            OP_PSM: {
                continue _trap;
            }
            OP_NAO_0c: {
                continue _trap;
            }
            OP_NAO_0d: {
                continue _trap;
            }
            OP_LPSD: {
                continue _trap;
            }
            OP_XPSD: {
                continue _trap;
            }
            OP_AD: {
                continue _trap;
            }
            OP_CD: {
                continue _trap;
            }
            OP_LD: {
                continue _trap;
            }
            OP_MSP: {
                continue _trap;
            }
            OP_NAO_14: {
                continue _trap;
            }
            OP_STD: {
                continue _trap;
            }
            OP_NAO_16: {
                continue _trap;
            }
            OP_NAO_17: {
                continue _trap;
            }
            OP_SD: {
                continue _trap;
            }
            OP_CLM: {
                continue _trap;
            }
            OP_LCD: {
                continue _trap;
            }
            OP_LAD: {
                continue _trap;
            }
            OP_FSL: {
                continue _trap;
            }
            OP_FAL: {
                continue _trap;
            }
            OP_FDL: {
                continue _trap;
            }
            OP_FML: {
                continue _trap;
            }
            OP_AI: {
                sxop = SX_ADD, rrx = RRX_S;
                px = PX_Q, ax = AX_S;
                testa = 1, ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_CI: {
                # d has immediate value
                continue _trap;
            }
            OP_LI: { # 3-215
                # d has immediate value
                px = PX_Q, sxop = SX_D, ax = AX_S, rrx = RRX_S, if COND_C0_EQ_1 continue _trap;
                testa = 1, ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_MI: {
                continue _trap;
            }
            OP_SF: {
                continue _trap;
            }
            OP_S: {
                continue _trap;
            }
            OP_NAO_26: {
                continue _trap;
            }
            OP_NAO_27: {
                continue _trap;
            }
            OP_CVS: {
                continue _trap;
            }
            OP_CVA: {
                continue _trap;
            }
            OP_LM: {
                continue _trap;
            }
            OP_STM: {
                continue _trap;
            }
            OP_NAO_2c: {
                continue _trap;
            }
            OP_NAO_2d: {
                continue _trap;
            }
            OP_WAIT: {
                forever: sxop = SX_ADD, continue forever;
            }
            OP_LRP: {
                continue _trap;
            }
            OP_AW: {
                continue _trap;
            }
            OP_CW: {
                continue _trap;
            }
            OP_LW: {
                dx = DX_CIN;
                sxop = SX_D, ax = AX_S, rrx = RRX_S, px = PX_Q;
                testa = 1, ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_MTW: {
                continue _trap;
            }
            OP_NAO_34: {
                continue _trap;
            }
            OP_STW: {
                continue _trap;
            }
            OP_DW: {
                continue _trap;
            }
            OP_MW: {
                continue _trap;
            }
            OP_SW: {
                continue _trap;
            }
            OP_CLR: {
                continue _trap;
            }
            OP_LCW: {
                continue _trap;
            }
            OP_LAW: {
                continue _trap;
            }
            OP_FSS: {
                continue _trap;
            }
            OP_FAS: {
                continue _trap;
            }
            OP_FDS: {
                continue _trap;
            }
            OP_FMS: {
                continue _trap;
            }
            OP_TTBS: {
                continue _trap;
            }
            OP_TBS: {
                continue _trap;
            }
            OP_NAO_42: {
                continue _trap;
            }
            OP_NAO_43: {
                continue _trap;
            }
            OP_ANLZ: {
                continue _trap;
            }
            OP_CS: {
                continue _trap;
            }
            OP_XW: {
                continue _trap;
            }
            OP_STS: {
                continue _trap;
            }
            OP_EOR: {
                continue _trap;
            }
            OP_OR: {
                continue _trap;
            }
            OP_LS: {
                continue _trap;
            }
            OP_AND: {
                continue _trap;
            }
            OP_SIO: {
                continue _trap;
            }
            OP_TIO: {
                continue _trap;
            }
            OP_TDV: {
                continue _trap;
            }
            OP_HIO: {
                continue _trap;
            }
            OP_AH: {
                continue _trap;
            }
            OP_CH: {
                continue _trap;
            }
            OP_LH: {
                continue _trap;
            }
            OP_MTH: {
                continue _trap;
            }
            OP_NAO_54: {
                continue _trap;
            }
            OP_STH: {
                continue _trap;
            }
            OP_DH: {
                continue _trap;
            }
            OP_MH: {
                continue _trap;
            }
            OP_SH: {
                continue _trap;
            }
            OP_NAO_59: {
                continue _trap;
            }
            OP_LCH: {
                continue _trap;
            }
            OP_LAH: {
                continue _trap;
            }
            OP_NAO_5c: {
                continue _trap;
            }
            OP_NAO_5d: {
                continue _trap;
            }
            OP_NAO_5e: {
                continue _trap;
            }
            OP_NAO_5f: {
                continue _trap;
            }
            OP_CBS: {
                continue _trap;
            }
            OP_MBS: {
                continue _trap;
            }
            OP_NAO_62: {
                continue _trap;
            }
            OP_EBS: {
                continue _trap;
            }
            OP_BDR: {
                dx = DX_1;
                sxop = SX_SUB, rrx = RRX_S, if COND_S_GT_ZERO {
                    # take branch
                    ende = 1, if COND_CIN0_EQ_0 continue direct;
                    continue direct;
                }
                # next instruction
                px = PX_Q;
                ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_BIR: {
                dx = DX_1;
                sxop = SX_ADD, rrx = RRX_S, if COND_S_LT_ZERO {
                    # take branch
                    ende = 1, if COND_CIN0_EQ_0 continue direct;
                    continue direct;
                }
                # next instruction
                px = PX_Q;
                ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_AWM: {
                continue _trap;
            }
            OP_EXU: {
                continue _trap;
            }
            OP_BCR: {
                if COND_CC_AND_R_ZERO {
                    # take branch
                    ende = 1, if COND_CIN0_EQ_0 continue direct;
                    continue direct;
                }
                # next instruction
                px = PX_Q;
                ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_BCS: {
                if not COND_CC_AND_R_ZERO {
                    # take branch
                    ende = 1, if COND_CIN0_EQ_0 continue direct;
                    continue direct;
                }
                # next instruction
                px = PX_Q;
                ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_BAL: {
                rrx = RRX_Q, ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_INT: {
                continue _trap;
            }
            OP_RD: {
                continue _trap;
            }
            OP_WD: {
                px = PX_Q;
                sxop = 2, wd_en = 1, ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_AIO: {
                continue _trap;
            }
            OP_MMC: {
                continue _trap;
            }
            OP_LCF: {
                continue _trap;
            }
            OP_CB: {
                continue _trap;
            }
            OP_LB: {
                dx = DX_CINB;
                sxop = SX_D, ax = AX_S, rrx = RRX_S, px = PX_Q;
                testa = 1, ende = 1, if COND_CIN0_EQ_0 continue direct;
                continue direct;
            }
            OP_MTB: {
                continue _trap;
            }
            OP_STFC: {
                continue _trap;
            }
            OP_STB: {
                continue _trap;
            }
            OP_PACK: {
                continue _trap;
            }
            OP_UNPK: {
                continue _trap;
            }
            OP_DS: {
                continue _trap;
            }
            OP_DA: {
                continue _trap;
            }
            OP_DD: {
                continue _trap;
            }
            OP_DM: {
                continue _trap;
            }
            OP_DSA: {
                continue _trap;
            }
            OP_DC: {
                continue _trap;
            }
            OP_DL: {
                continue _trap;
            }
            OP_DST: {
                continue _trap;
            }
        }
        sxop = SX_ADD;
    }

    _trap: trap = 1, continue _trap;
}


const OP_NAO_00 = 0;
const OP_NAO_01 = 1;
const OP_LCFI = 2;
const OP_NAO_03 = 3;
const OP_CAL1 = 4;
const OP_CAL2 = 5;
const OP_CAL3 = 6;
const OP_CAL4 = 7;
const OP_PLW = 8;
const OP_PSW = 9;
const OP_PLM = 10;
const OP_PSM = 11;
const OP_NAO_0c = 12;
const OP_NAO_0d = 13;
const OP_LPSD = 14;
const OP_XPSD = 15;
const OP_AD = 16;
const OP_CD = 17;
const OP_LD = 18;
const OP_MSP = 19;
const OP_NAO_14 = 20;
const OP_STD = 21;
const OP_NAO_16 = 22;
const OP_NAO_17 = 23;
const OP_SD = 24;
const OP_CLM = 25;
const OP_LCD = 26;
const OP_LAD = 27;
const OP_FSL = 28;
const OP_FAL = 29;
const OP_FDL = 30;
const OP_FML = 31;
const OP_AI = 32;
const OP_CI = 33;
const OP_LI = 34;
const OP_MI = 35;
const OP_SF = 36;
const OP_S = 37;
const OP_NAO_26 = 38;
const OP_NAO_27 = 39;
const OP_CVS = 40;
const OP_CVA = 41;
const OP_LM = 42;
const OP_STM = 43;
const OP_NAO_2c = 44;
const OP_NAO_2d = 45;
const OP_WAIT = 46;
const OP_LRP = 47;
const OP_AW = 48;
const OP_CW = 49;
const OP_LW = 50;
const OP_MTW = 51;
const OP_NAO_34 = 52;
const OP_STW = 53;
const OP_DW = 54;
const OP_MW = 55;
const OP_SW = 56;
const OP_CLR = 57;
const OP_LCW = 58;
const OP_LAW = 59;
const OP_FSS = 60;
const OP_FAS = 61;
const OP_FDS = 62;
const OP_FMS = 63;
const OP_TTBS = 64;
const OP_TBS = 65;
const OP_NAO_42 = 66;
const OP_NAO_43 = 67;
const OP_ANLZ = 68;
const OP_CS = 69;
const OP_XW = 70;
const OP_STS = 71;
const OP_EOR = 72;
const OP_OR = 73;
const OP_LS = 74;
const OP_AND = 75;
const OP_SIO = 76;
const OP_TIO = 77;
const OP_TDV = 78;
const OP_HIO = 79;
const OP_AH = 80;
const OP_CH = 81;
const OP_LH = 82;
const OP_MTH = 83;
const OP_NAO_54 = 84;
const OP_STH = 85;
const OP_DH = 86;
const OP_MH = 87;
const OP_SH = 88;
const OP_NAO_59 = 89;
const OP_LCH = 90;
const OP_LAH = 91;
const OP_NAO_5c = 92;
const OP_NAO_5d = 93;
const OP_NAO_5e = 94;
const OP_NAO_5f = 95;
const OP_CBS = 96;
const OP_MBS = 97;
const OP_NAO_62 = 98;
const OP_EBS = 99;
const OP_BDR = 100;
const OP_BIR = 101;
const OP_AWM = 102;
const OP_EXU = 103;
const OP_BCR = 104;
const OP_BCS = 105;
const OP_BAL = 106;
const OP_INT = 107;
const OP_RD = 108;
const OP_WD = 109;
const OP_AIO = 110;
const OP_MMC = 111;
const OP_LCF = 112;
const OP_CB = 113;
const OP_LB = 114;
const OP_MTB = 115;
const OP_STFC = 116;
const OP_STB = 117;
const OP_PACK = 118;
const OP_UNPK = 119;
const OP_DS = 120;
const OP_DA = 121;
const OP_DD = 122;
const OP_DM = 123;
const OP_DSA = 124;
const OP_DC = 125;
const OP_DL = 126;
const OP_DST = 127;
