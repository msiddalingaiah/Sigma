import pytest

from uts import cal as C
from uts import sched as S
from uts.cal import Fpt, instruction, OP_CAL1, OP_EXU
from uts.monitor import NotTranslated
from uts.sched import Cal1, Compute


def system(**kw):
    kw.setdefault("smuis", 8)
    kw.setdefault("ming", 5)
    kw.setdefault("pages", 40)
    kw.setdefault("screech", lambda code, why: None)
    s = S.Scheduler(**kw)
    s.cal = C.CalProcessor(s, date={"MO": 6, "DA": 15, "YR": 76, "HR": 13, "MI": 45})
    return s


def run(body, flags=0, **kw):
    """Run ``body(sched, u, out)`` as ghost user 1; returns (sched, out)."""
    s, out = system(**kw), []
    s.start_ghost(1, 0xF0, body(s, 1, out), pages=2)
    s.UH_FLG[1] |= flags
    s.run()
    return s, out


# --- decoding ------------------------------------------------------------------------

def decoded(setup):
    s = system()
    setup(s.umem[1], s.uregs[1])
    return s.cal.cal1p11(1, C.CAL_ADDR)


def test_decode_a_plain_cal():
    def setup(mem, regs):
        mem[C.CAL_ADDR] = instruction(OP_CAL1, 8, 0xA000)
        mem[0xA000] = (0x0F << 24) | 5
    ctx = decoded(setup)
    assert (ctx.n, ctx.sr1, ctx.r6 & 0xFFFFFF, ctx.r7) == (8, 0x0F, 5, 0xA001)
    assert not ctx.from_monitor


def test_decode_follows_indirect_index_and_exu():
    def setup(mem, regs):
        regs[3] = 0x10
        mem[C.CAL_ADDR] = instruction(OP_EXU, 0, 0xA200)            # EXU *... -> the CAL
        mem[0xA200] = instruction(OP_CAL1, 2, 0xA300, x=3, indirect=True)
        mem[0xA300] = 0xA400                                         # indirect word
        mem[0xA410] = (4 << 24)                                      # FPT at X'A400' + R3
    ctx = decoded(setup)
    assert (ctx.n, ctx.sr1, ctx.r7) == (2, 4, 0xA411)


def test_decode_an_fpt_in_a_register_and_an_indirect_dcb():
    def setup(mem, regs):
        mem[C.CAL_ADDR] = instruction(OP_CAL1, 1, 5)                 # FPT "in" R5
        regs[5] = C.INDIRECT | (0x94 << 24) | 0xA500                 # code X'14' + X'80'
        mem[0xA500] = C.M_XX
    ctx = decoded(setup)
    assert ctx.sr1 == 0x14 and ctx.r6 == C.M_XX


# --- dispatch errors ---------------------------------------------------------------------

@pytest.mark.parametrize("n, code", [(0, 0), (10, 0), (8, 0x7F), (8, 0), (2, 8), (3, 6),
                                     (4, 7), (5, 0x30)])
def test_bad_cals_abort_with_ae(n, code):
    def body(s, u, out):
        yield Cal1(n, Fpt(code))
        out.append("not reached")
    s, out = run(body)
    assert not out and s.cal.ended[1] == ("ABORT", 0xAE) and s.jit[1].ABC == 0xAE


def test_cal1_1_with_a_dcb_that_is_not_the_users_is_af():
    def body(s, u, out):
        yield Cal1(1, Fpt(0x14, word0=0x9999))
    s, _ = run(body)
    assert s.cal.ended[1] == ("ABORT", 0xAF)


def test_set_prompt_needs_no_dcb_but_only_on_line_users_get_it():
    def body(s, u, out):
        out.append((yield Cal1(1, Fpt(0x2C, word0=ord("?")))))
    _, out = run(body)
    assert out == [8]                                  # a ghost: CC1SET


def test_open_goes_to_the_open_overlay():
    def body(s, u, out):
        s.cal.dcbs[u] = {"M:SI": 0x9000}
        yield Cal1(1, Fpt(0x14, word0=0x9000))
    with pytest.raises(NotTranslated, match="no file system"):
        run(body)                                      # after OPEN's overlay came in


def test_terminal_dcb_takes_only_read_write_and_device_calls():
    def body(s, u, out):
        yield Cal1(1, Fpt(0x15, word0=C.M_UC))        # CLOSE M:UC
    s, _ = run(body)
    assert s.cal.ended[1] == ("ABORT", 0xAE)

    def body2(s, u, out):
        yield Cal1(1, Fpt(0x10, word0=C.M_UC))        # READ M:UC: legal for a ghost
    with pytest.raises(NotTranslated, match="device read"):
        run(body2)


# --- overlays ----------------------------------------------------------------------------

def test_an_overlay_not_in_core_is_swapped_in_through_e_ap():
    def body(s, u, out):
        out.append((yield Cal1(8, Fpt(0x10))))        # M:TIME, in MISOV
        out.append((yield Cal1(8, Fpt(0x10))))
    s, out = run(body)
    misov = C.OVLY_BASE + C.MISOVSEG
    log = "\n".join(s.log)
    assert out == [0, 0] and log.count("not in core, E:AP") == 1
    assert "SWAPIN user 1 (4 pages)" in log and s.PX_HPP[misov] == 4


def test_a_cal_from_the_monitor_remembers_the_overlay(monkeypatch):
    monkeypatch.setattr(C, "CAL_ADDR", 0x5000)       # below J:JIT: the monitor's own CAL

    def body(s, u, out):
        yield Cal1(8, Fpt(0x10))
        out.append(s.UB_OV[u])
    _, out = run(body)
    assert out == [0]                                  # T:REMEMBER put back "no overlay"


# --- the translated services ---------------------------------------------------------------

def test_m_wait_sleeps_for_its_limit():
    def body(s, u, out):
        out.append((s.now, (yield Cal1(8, Fpt(0x0F, word0=2))), s.now))
    s, out = run(body)
    (before, cc, after), = out
    assert cc == 0 and after - before == 3 * C.WAIT_UNIT     # (2 + 1) units
    assert any("user 1 -> SW" in l for l in s.log)


def test_m_time_block_and_tms():
    def body(s, u, out):
        yield Cal1(8, Fpt(0x10, word0=C.TMS | 0xB000))
        out.append(("".join(s.umem[u][0xB000 + i] for i in range(4)), list(s.uregs[u][8:11])))
    _, out = run(body)
    (text, (sr1, sr2, sr3)), = out
    assert text == "13:45 JUN 15,'76"
    assert sr1 == (76 << 16) | (15 + 151 + 1)          # day of year, leap year after Feb
    assert sr2 >> 16 == (13 << 8) | 45


def test_clear_error_is_for_tel_only():
    def body(s, u, out):
        s.jit[u].RNST, s.jit[u].ABC = 0x20, 0xB4
        out.append((yield Cal1(4, Fpt(6))))
        out.append((s.jit[u].RNST, s.jit[u].ABC))
    _, out = run(body)                                 # ADD1 sets TIC
    assert out == [0, (0, 0)]


def test_reliability_cals_need_privilege_or_tel():
    def body(s, u, out):
        s.UH_FLG[u] &= ~S.TIC
        out.append((yield Cal1(6, Fpt(0))))
    _, out = run(body)
    assert out == [8]                                  # ERCC1


def test_cal_count_leaves_out_cal1_3_and_up():
    def body(s, u, out):
        yield Cal1(8, Fpt(0x10))
        yield Cal1(1, Fpt(0x2C))
        out.append(s.cal.calcnt[u])
    _, out = run(body)
    assert out == [1]


# --- CAL1,9 ----------------------------------------------------------------------------------

def test_m_exit_ends_the_ghost():
    def body(s, u, out):
        yield Cal1(9, address=1)
        out.append("not reached")
    s, out = run(body)
    assert not out and s.cal.ended[1] == ("T:EXIT",) and 1 in s.ended


def test_m_err_and_m_xxx_set_the_run_status():
    for t, rnst in ((2, 0x80), (3, 0x40)):
        def body(s, u, out):
            yield Cal1(9, address=t)
        s, _ = run(body)
        assert s.jit[1].RNST == rnst and s.jit[1].ABC == 0xA8


def test_step_condition_codes_with_the_presence_bit():
    def body(s, u, out):
        yield Cal1(9, address=0x10000 | (5 << 8) | 1)  # M:EXIT with step CC 5
    s, _ = run(body)
    assert s.jit[1].STEPCC == 5 and s.cal.ended[1] == ("T:EXIT",)


@pytest.mark.parametrize("t", [0, 7, 8, 10, 12])
def test_bad_exit_types(t):
    def body(s, u, out):
        yield Cal1(9, address=t)
    s, _ = run(body)
    assert s.cal.ended[1] == ("ABORT", 0xAE)


# --- on the booted system ------------------------------------------------------------------

def test_ghost1_exits_to_fill_with_m_exit():
    from tests.test_keyin import started
    m, mon, con, s = started()
    log = "\n".join(s.log)
    assert "CAL1,9 user 4" in log and "T:EXIT user 4: step to FILL" in log
    assert 4 in s.ended and s.S_CUIS == 2
