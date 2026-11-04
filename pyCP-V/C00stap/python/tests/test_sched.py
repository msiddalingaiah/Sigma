import pytest

from uts import sched as S
from uts.sched import (Compute, Dcb, DoEntry, Io, Release, Report, Scheduler, Screech, Sleep)


def cruncher(n, size=40):
    for _ in range(n):
        yield Compute(size)


def sched(**kw):
    kw.setdefault("smuis", 8)
    kw.setdefault("ming", 5)
    kw.setdefault("screech", lambda code, why: None)
    return Scheduler(**kw)


def current(s, u, prio=0xF0, flags=S.RTR | S.JIC):
    """Make user u (state 0, a ghost slot) the current user."""
    s.UB_PRIOB[u] = s.UB_PRIO[u] = prio
    s.UH_FLG[u] = flags
    s.t_chs(u, S.SCU)
    s.S_CUN = u


# --- tables --------------------------------------------------------------------------

def test_state_and_event_numbers():
    assert (S.SRT, S.SC0, S.SC10, S.SCU, S.SIOW, S.SIOMF, S.SQFI, S.SNULL) == (1, 2, 12, 13, 16, 17, 24, 30)
    assert (S.E_IIP, S.E_QMF, S.E_CBK, S.E_CEC, S.E_ERR, S.E_OFF) == (0, 1, 8, 10, 12, 14)
    assert S.E_ABRT == S.E_OFF and S.E_AP == S.E_NC
    assert (S.E_WU, S.E_KO, S.E_IC, S.E_QFI, S.E_REL, S.E_ND, S.E_NQR) == (16, 24, 28, 29, 30, 38, 43)
    assert S.S_SET[S.E_CBK] & S.CONT and not S.S_SET[S.E_CBK + 1] & S.CONT


def test_bad_state_event_combination_is_screech_02():
    s = sched(screech=None)
    current(s, 1)
    s.t_re(S.E_SL)                                     # SCU -> SW
    with pytest.raises(Screech) as e:
        s.t_rue(1, S.E_SL)                             # sleep again from SW
    assert e.value.code == 0x02


# --- state changes and priority --------------------------------------------------------

def test_executable_queues_are_ordered_by_priority_behind_equals():
    s = sched()
    s.start_ghost(1, 0xF0, cruncher(1))                # STIRC: F0 - 6 = EA
    s.start_ghost(2, 0xE0, cruncher(1))                # DA
    s.start_ghost(3, 0xF0, cruncher(1))                # EA, behind user 1
    assert s.queue(S.SC0) == [2, 1, 3]
    assert [s.UB_PRIO[u] for u in (2, 1, 3)] == [0xDA, 0xEA, 0xEA]
    assert s.UH_FLG[1] & S.INTERACTIVE


def test_queue_to_head_in_sc0_still_goes_behind_equals():
    s = sched()
    s.start_ghost(1, 0xF0, cruncher(1))
    s.start_ghost(2, 0xE0, cruncher(1))
    s.start_ghost(3, 0xF0, cruncher(1))
    current(s, 4, prio=0xED)
    s.t_re(S.E_AP)                                     # STASP: ED - 3 = EA, scan from the head
    assert s.queue(S.SC0) == [2, 1, 3, 4]              # CHSEH1: BL, before the first greater


def test_queue_to_head_in_sc1_to_sc10_is_a_true_head():
    s = sched()
    s.start_ghost(1, 0xFC, cruncher(1))                # FC - 6 = F6: SC1
    s.start_ghost(2, 0xFC, cruncher(1))
    current(s, 4, prio=0xF9)
    s.t_re(S.E_AP)                                     # F9 - 3 = F6, plain change to the head
    assert s.queue(S.SC1) == [4, 1, 2]


def test_priorities_map_to_states_and_real_time_does_not_float():
    s = sched()
    s.start_ghost(1, 0xFF, cruncher(1))                # F9 -> SC4
    s.start_ghost(2, 0x80, cruncher(1))                # real time: back to base
    assert s.UB_US[1] == S.SC0 + (0xF9 - 0xF5)
    assert s.UB_US[2] == S.SRT and s.UB_PRIO[2] == 0x80


def test_a_boost_decays_one_notch_per_dispatch():
    s = sched()
    s.UB_PRIOB[1], s.UH_FLG[1] = 0xF0, S.RTR | S.JIC
    s.programs[1] = cruncher(1)
    s.t_chs(1, S.SW)
    s.t_rue(1, S.E_WU)                                 # STSC: F0 - 3
    assert s.UB_PRIO[1] == 0xED
    assert s.se1(1) == ("RUN", 1)
    assert s.UB_PRIO[1] == 0xEE and s.S_CUP == 0xEE and s.UB_US[1] == S.SCU


# --- the exit path ------------------------------------------------------------------------

def test_equal_users_round_robin_at_quantum_end():
    s = sched(pages=64)
    s.L.SL_QUAN = 100
    s.start_ghost(1, 0xF4, cruncher(6, 50), pages=4)
    s.start_ghost(2, 0xF4, cruncher(6, 50), pages=4)
    s.run(until=420)
    runs = [line.split()[2] for line in s.log if line.endswith("-> SCU")]
    assert runs[:5] == ["1", "2", "1", "2", "1"]
    assert sum("quantum end" in line for line in s.log) >= 3


def test_a_woken_sleeper_preempts_after_qmin():
    s = sched(pages=64)
    s.start_ghost(1, 0xF4, cruncher(10, 40), pages=4)

    def sleeper():
        yield Sleep(60)
        yield Compute(5)

    s.start_ghost(2, 0xF0, sleeper(), pages=2)
    s.run(until=200)
    assert any("interrupt: E_WU for user 2" in l for l in s.log)
    i = next(i for i, l in enumerate(s.log) if "preempted" in l)
    assert "user 1: preempted" in s.log[i]
    assert s.log[i + 2].endswith("user 2 -> SCU")


def test_swap_quantum_is_cleared_after_sl_squan():
    s = sched(pages=64)
    s.start_ghost(1, 0xF4, cruncher(10, 50), pages=4)
    s.run(until=120)
    assert s.UH_FLG2[1] & S.SQUAN
    s.run(until=260)
    assert not s.UH_FLG2[1] & S.SQUAN


def test_xfdff_clears_rmahold_not_calint():
    s = sched()
    s.UB_PRIOB[1], s.UH_FLG[1] = 0xF0, S.RTR | S.JIC
    s.t_chs(1, S.SC0)
    s.UH_FLG2[1] = S.RMAHOLD | S.CALINT | S.SWAPD
    s.se1(1)
    assert s.UH_FLG2[1] == S.CALINT


def test_user_area_swap_error_errors_the_job():
    s = sched()
    seen = []
    s.hooks["SETRNST"] = lambda sch, u: seen.append((u, sch.jit[u].RNST)) or ("RUN", u)
    s.UB_PRIOB[1], s.UH_FLG[1] = 0xF0, S.RTR | S.JIC
    s.t_chs(1, S.SC0)
    s.UH_FLG2[1] = S.USRERR
    s.se1(1)
    assert seen == [(1, 0x20)]


def test_do_list_type_7_runs_its_routine():
    s = sched()
    ran = []
    current(s, 1)
    s.t_acctex(1)                                      # a quantum to run in
    s.do_list[1].append(DoEntry(7, routine=lambda sch, u: ran.append(u)))
    assert s.sse1() == ("RUN", 1)
    assert ran == [1] and not s.do_list[1]


# --- I/O -------------------------------------------------------------------------------

def test_io_wait_and_completion():
    s = sched(pages=64)

    def io_user():
        yield Compute(10)
        yield Io(30)
        yield Compute(10)

    s.start_ghost(1, 0xF8, io_user(), pages=2)
    s.run()
    text = "\n".join(s.log)
    assert "user 1 -> SIOW" in text and "user 1 -> SC1 prio X'F6'" in text   # F8 - 2
    assert s.C["IDLEW"] == 30                          # idle while the I/O runs


def test_siomf_unblocks_at_the_online_limit():
    s = sched()
    current(s, 1)
    s.UB_MF[1] = 6
    s.t_re(S.E_QMF)
    assert s.UB_US[1] == S.SIOMF
    s.t_rue(1, S.E_IC)
    assert s.UB_US[1] == S.SIOMF and s.UB_MF[1] == 5
    s.t_rue(1, S.E_IC)                                 # 4 = SL:OIMF
    assert s.UB_US[1] <= S.SEXU


def test_siow_waits_for_the_flagged_dcb():
    s = sched()
    mine, other = Dcb("MINE"), Dcb("OTHER")
    current(s, 1)
    s.UB_MF[1] = 2
    s.t_re(S.E_IIP, mine)
    assert s.UB_US[1] == S.SIOW and mine.waiting
    s.t_rue(1, S.E_IC, other)                          # another DCB's I/O: keep waiting
    assert s.UB_US[1] == S.SIOW
    mine.fcn = 0
    s.t_rue(1, S.E_IC, mine)
    assert s.UB_US[1] <= S.SEXU and not mine.waiting


def test_no_io_left_means_the_user_continues():
    s = sched()
    current(s, 1)
    assert s.t_re(S.E_IIP) == S.PULLE                  # GRANT


# --- resources ---------------------------------------------------------------------------

def block(s, users, event):
    for u in users:
        current(s, u)
        s.t_re(event)
        assert s.UB_US[u] == S.SQR


def test_flush_releases_everyone():
    s = sched()
    block(s, [1, 2, 3], S.E_NSYMF)
    assert s.SB_RQ[S.RESOURCE_NAMES["R_SYMF"]] == 3    # pushed on the head
    current(s, 4)
    s.t_re(S.E_SYMF)
    assert all(s.UB_US[u] <= S.SEXU for u in (1, 2, 3))
    assert s.SB_RQ[S.RESOURCE_NAMES["R_SYMF"]] == 0


def test_open_close_release_takes_the_last_blocked_user():
    s = sched()
    block(s, [1, 2], S.E_OCR)
    current(s, 3)
    s.t_re(S.E_NOCR)
    assert s.OPNCLSUS == 2 and s.UH_FLG[2] & S.OPNCLSUSR
    assert s.UB_US[2] <= S.SEXU and s.UB_US[1] == S.SQR
    s.t_re(S.E_NOCR)                                   # already an open/close user
    assert s.UB_US[1] == S.SQR


def test_specific_release_and_the_missing_back_link():
    s = sched()
    r = S.RESOURCE_NAMES["R_NQW"]
    block(s, [1, 2], S.E_NQW)
    assert s.SB_RQ[r] == 2 and s.UB_PRIO[1] == 0       # the old head's back link is still 0
    current(s, 3)
    s.t_rue(1, S.E_NQR)                                # SPECIFIC: release user 1
    assert s.UB_US[1] <= S.SEXU
    # T:UQR took user 1 for the head and dropped user 2 from the sub-queue.
    assert s.SB_RQ[r] == 0 and s.UB_US[2] == S.SQR


def test_abort_unqueues_only_where_the_resource_allows():
    s = sched()
    block(s, [1], S.E_NSYMF)
    block(s, [2], S.E_NQW)
    s.t_rue(1, S.E_ABRT)
    s.t_rue(2, S.E_ABRT)
    assert s.UB_US[1] == S.SQR and s.UH_DL[1] & S.DL_ABRT
    assert s.UB_US[2] <= S.SEXU and s.UH_DL[2] & S.DL_ABRT


# --- breaks and aborts --------------------------------------------------------------------

def test_abort_of_a_sleeping_ghost_ends_it():
    s = sched(pages=64)

    def forever():
        while True:
            yield Sleep(100)

    s.start_ghost(1, 0xF0, forever(), pages=2)
    s.run(until=50)
    assert s.UB_US[1] == S.SW
    s.t_rue(1, S.E_ABRT)
    assert s.UH_DL[1] & S.DL_ABRT and s.UB_US[1] <= S.SEXU
    s.run(until=60)
    assert 1 in s.ended and any("T:TELDELCCI user 1" in l for l in s.log)


def test_break_with_tel_in_control_and_no_break_entry_is_ignored():
    s = sched(pages=64)
    done = []

    def sleeper():
        yield Sleep()
        done.append(1)

    s.start_ghost(1, 0xF0, sleeper(), pages=2)
    s.run()
    s.t_rue(1, S.E_CBK)                                # TIC is set by ADD1
    s.run()
    assert done == [1] and 1 in s.ended


def test_terminal_input_complete_before_the_read():
    s = sched()
    current(s, 1)
    s.t_re(S.E_CIC)                                    # STIRCU
    assert s.UH_FLG[1] & S.EARLY
    assert s.t_re(S.E_CRD) == S.PULLE                  # STCRD: continue, flag off
    assert not s.UH_FLG[1] & S.EARLY and s.UB_US[1] == S.SCU


# --- log-on --------------------------------------------------------------------------------

def test_logon_takes_the_head_of_the_null_queue():
    s = sched()
    s.L.S_OUAIS = 1
    u = s.start_online(0, cruncher(1))
    assert u == 5 and s.LB_UN[0] == 5 and s.S_OUIS == 1 and s.S_CUIS == 1
    assert s.UB_PRIOB[5] == s.L.SL_OPRIO and s.UH_FLG[5] & S.TIC
    assert s.UH_FLG2[5] == S.SQUAN | S.SWAPD and s.UB_PCT[5] == 2
    assert s.start_online(1, cruncher(1)) == 0          # S:OUIS = S:OUAIS
    assert s.SB_HQ[S.SNULL] == 6


def test_no_jit_granule_blocks_on_e_nd():
    s = sched(swap_granules=(0,))
    s.start_ghost(1, 0xF0, cruncher(1))
    assert s.UB_US[1] == S.SQR and s.UH_AJIT[1] == 0xFFFF
    assert s.SB_RQ[(S.E_ND - S.E_REL) // 2] == 1


# --- T:SS --------------------------------------------------------------------------------

def test_swap_quantum_protects_in_core_users():
    s = sched(pages=10)
    s.start_ghost(1, 0xF4, cruncher(1), pages=5)
    s.start_ghost(2, 0xF4, cruncher(1), pages=5)
    s.t_ss()
    s.t_ss()
    assert s.UH_FLG[1] & s.UH_FLG[2] & S.RTR and s.M_FPPC == 0
    s.start_ghost(3, 0xF0, cruncher(1), pages=4)
    s.t_ss()
    assert not s.UH_FLG[3] & S.RTR and s.C["NSP"] == 1 and s.S_ISUNF == 3
    s.UH_FLG2[2] &= ~S.SQUAN                           # user 2 has had its swap quantum
    s.S_SEVF += 1
    s.t_ss()
    assert s.UH_FLG[3] & S.RTR and not s.UH_FLG[2] & (S.RTR | S.JIC)
    assert s.JBPPC[2] == 0 and s.M_FPPC == 1


def test_sleeping_users_go_first():
    s = sched(pages=10)
    s.start_ghost(1, 0xF4, cruncher(1), pages=5)
    s.start_ghost(2, 0xF4, cruncher(1), pages=5)
    s.t_ss()
    s.t_ss()
    s.t_chs(2, S.SW)
    s.start_ghost(3, 0xF8, cruncher(1), pages=4)       # less urgent than user 1
    s.t_ss()
    assert s.UH_FLG[3] & S.RTR and not s.UH_FLG[2] & S.RTR and s.UH_FLG[1] & S.RTR


def test_impossible_swap_is_screech_62():
    s = sched(pages=10, screech=None)
    s.start_ghost(1, 0xF0, cruncher(1), pages=20)
    with pytest.raises(Screech) as e:
        s.t_ss()
    assert e.value.code == 0x62


def test_a_user_who_does_not_fit_now_gets_bypass():
    s = sched(pages=10)
    s.S_RTCORE = 8                                     # only 2 fluid pages
    s.start_ghost(1, 0xF0, cruncher(1), pages=5)
    s.M_FPPC = 2
    s.t_ss()
    assert s.UH_FLG[1] & S.BYPASS and not s.UH_FLG[1] & S.RTR


def test_demo_swaps_everyone_through_and_shuts_down():
    s, outcome = S.demo()
    assert outcome == "shutdown"
    assert sorted(s.ended) == [1, 2, 3, 4] and s.M_FPPC == 12
    assert any(l.endswith("SWAPOUT user 1 (5 pages)") for l in s.log)
    assert s.log[-1].endswith("SCREECH X'404' idle check")


# --- the idle check ------------------------------------------------------------------------

def test_zap_shutdown_from_the_idle_check():
    calls = []
    s = sched(pages=64, screech=lambda code, why: calls.append(code))

    def forever():
        while True:
            yield Sleep()

    s.start_ghost(1, 0xF0, forever(), pages=2)
    s.start_ghost(2, 0xF0, forever(), pages=2)
    assert s.run() == "idle" and not calls
    s.GOODNGT = -2                                     # KIFDOWN
    assert s.run() == "shutdown" and calls == [0x404]
