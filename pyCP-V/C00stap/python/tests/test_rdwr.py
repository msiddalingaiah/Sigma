import pytest

from tests.test_keyin import started
from uts import sched as S
from uts.cal import (CODE, Fpt, M_OC, P_BTD, P_BUF, P_ERR, P_SIZE)
from uts.io import TYC_ERROR
from uts.monitor import NotTranslated
from uts.sched import Cal1, Sleep

MSG, REC, ROUTINE = 0xB000, 0xB100, 0xC000


def ghost(body):
    """A booted, started system with ``body(sched, u, out)`` as a ghost; run until idle."""
    m, mon, con, s = started()
    m.console.transcript.clear()
    out = []

    def program(sched, u):
        yield from body(sched, u, out)
        while True:
            yield Sleep()

    cc, u = s.t_gjobstrt("WRITER", program=program)
    con.run_sched()
    return m, con, s, u, out


def m_type(text, code=2):
    def body(s, u, out):
        s.cal.put_text(u, MSG, text, textc=True)
        out.append((yield Cal1(2, Fpt(code, presence=0x80000000, params=[MSG]))))
    return body


def m_write(text, presence=P_BUF | P_SIZE, params=None, error=None):
    def body(s, u, out):
        s.cal.put_text(u, REC, text)
        p = params if params is not None else [REC, len(text)]
        if error is not None:
            presence_, p = presence | P_ERR, [error] + p
        else:
            presence_ = presence
        out.append((yield Cal1(1, Fpt(0x11, word0=M_OC, presence=presence_, params=p))))
    return body


def test_m_type_from_a_ghost_reaches_the_operator_console():
    m, con, s, u, out = ghost(m_type("HELLO OPERATOR"))
    assert out == [0]
    assert m.console.text() == f"\n{u:X}: HELLO OPERATOR"
    assert s.UB_MF[u] == 0                             # FRONTEND +1, E:IC -1
    dcb = s.cal.monitor_dcbs[M_OC]
    assert dcb.fcn == 0 and dcb.tyc == 1 and dcb.ars == len(m.console.text())


def test_m_message_goes_to_the_console_too():
    m, *_ = ghost(m_type("MSG", code=0))
    assert m.console.text().endswith(": MSG")


def test_m_write_with_a_byte_displacement():
    m, *_ = ghost(m_write("..ABCDEF", presence=P_BUF | P_SIZE | P_BTD, params=[REC, 6, 2]))
    assert m.console.text().endswith(": ABCDEF")


def test_m_print_without_an_m_ll_does_nothing():
    m, con, s, u, out = ghost(m_type("NOT PRINTED", code=1))
    assert out == [0] and m.console.text() == ""


def test_the_ding_counts_against_the_quantum():
    def body(s, u, out):
        before = s.jit[u].CTIME
        yield from m_type("X")(s, u, out)
        out.append(s.jit[u].CTIME - before)
    m, con, s, u, out = ghost(body)
    assert out == [0, s.L.SL_IOTA]                     # FRONTEND: SL:IOTA into J:CTIME


# --- waiting and errors ------------------------------------------------------------------

def hang_console(con):
    con.io.devices[con.oc].unit.faults["hang"] = 1


def complete(con, tyc):
    dev = con.io.devices[con.oc]
    con.io.reqcom(dev, dev.current, tyc)               # the interrupt's REQCOM


def test_a_write_with_an_error_address_waits_and_the_error_goes_to_the_routine():
    m, mon, con, s = started()
    hang_console(con)
    out = []

    def program(sched, u):
        yield from m_write("BAD", error=ROUTINE)(sched, u, out)
        while True:
            yield Sleep()

    cc, u = s.t_gjobstrt("WRITER", program=program)
    con.run_sched()
    assert s.UB_US[u] == S.SIOW and not out            # IOSPIN: T:IOREG, E:IIP
    complete(con, TYC_ERROR)                           # a write error: TYC 9
    con.run_sched()
    code = CODE[9]
    assert out == [("ROUTINE", ROUTINE, (code << 24) | M_OC)]
    assert s.uregs[u][10] == (code << 24) | M_OC       # SR3 in R10
    assert s.jit[u].ERO == 0 and s.UB_MF[u] == 0


def test_an_error_without_a_routine_sets_the_run_status():
    m, mon, con, s = started()
    hang_console(con)
    out = []

    # With no error or abnormal address the write doesn't wait: M:CHECK waits instead.
    def checker(sched, u):
        sched.cal.put_text(u, REC, "BAD")
        yield Cal1(1, Fpt(0x11, word0=M_OC, presence=P_BUF | P_SIZE, params=[REC, 3]))
        out.append((yield Cal1(1, Fpt(0x29, word0=M_OC))))
        while True:
            yield Sleep()

    cc, u = s.t_gjobstrt("CHECKER", program=checker)
    con.run_sched()
    assert s.UB_US[u] == S.SIOW                         # M:CHECK waits
    complete(con, TYC_ERROR)
    con.run_sched()
    assert out == [0]                                  # MERC: no routine, CAL ends
    assert s.jit[u].ABC == 0x45 and s.jit[u].RNST == 0x02


def test_an_earlier_error_is_seen_by_the_next_write():
    m, mon, con, s = started()
    dcb = con.sched.cal.monitor_dcbs[M_OC]
    dcb.tyc, dcb.egv = 9, False                         # left by an unchecked write
    out = []
    cc, u = s.t_gjobstrt("WRITER", program=lambda sched, uu: m_type("NEXT")(sched, uu, out))
    con.run_sched()
    assert s.jit[u].ABC == 0x45 and s.jit[u].RNST == 0  # IOQUEUE4: a ghost isn't aborted


def test_end_of_file_is_abnormal_and_ignored_without_an_address():
    from uts.cal import CalProcessor
    s = S.Scheduler(smuis=8, ming=5, screech=lambda c, w: None)
    cal = CalProcessor(s)
    dcb = cal.monitor_dcbs[M_OC]
    ctx = cal_ctx(cal)
    result = cal.msr012(ctx, dcb, CODE[7])              # end of file: X'06'
    assert result == ("IOSPRTN", 0, (6 << 24) | M_OC) and s.jit[1].RNST == 0


def cal_ctx(cal):
    from uts.cal import Ctx
    return Ctx(u=1, n=1, sr1=0x11, r6=M_OC, r7=0, psd=0, from_monitor=False)


# --- the I/O limit (FRONTEND) --------------------------------------------------------------

def test_a_batch_user_at_its_limit_waits_in_siomf():
    m, mon, con, s = started()
    out = []

    def batch(sched, u):
        sched.UB_MF[u] = sched.L.SL_BXMF                # four requests outstanding
        yield from m_type("LATE")(sched, u, out)
        while True:
            yield Sleep()

    u = s.SB_HQ[S.SNULL]
    s.programs[u] = batch(s, u)
    s.add1(u, 0xF0)                                     # a batch user: no ghost slot
    con.run_sched()
    assert s.UB_US[u] == S.SIOMF and not out            # E:IP
    for _ in range(s.L.SL_BXMF):
        s.t_rue(u, S.E_IC)                              # earlier requests complete
    con.run_sched()
    assert out == [0] and m.console.text().endswith(": LATE")


# --- not translated --------------------------------------------------------------------------

def test_a_read_is_not_translated():
    def body(s, u, out):
        yield Cal1(1, Fpt(0x10, word0=M_OC, presence=P_BUF | P_SIZE, params=[REC, 4]))
    with pytest.raises(NotTranslated, match="device read"):
        ghost(body)


def test_a_file_write_is_not_translated():
    def body(s, u, out):
        s.cal.add_dcb(u, "M:EO", 0x9000, asn=1)
        yield Cal1(1, Fpt(0x11, word0=0x9000, presence=P_BUF | P_SIZE, params=[REC, 4]))
    m, con, s, u, out = ghost(body)                    # a file DCB: default OPEN first
    assert s.jit[u].ABC == 0x47 and s.jit[u].RNST == 0x02   # 47 for write, OPEN's 03 the sub
    assert any("error X'47'-03 on M:EO" in l for l in s.log)
