import pytest

from uts.__main__ import boot, operator
from uts.config import Sysgen
from uts.keyin import Fields, OperatorConsole
from uts.sched import GJ_STARTED, SNULL, SW, Sleep

STD = ["06/15/76", "13:45", "N"]


def running():
    m, mon, outcome = boot(replies=STD)
    assert outcome == "up"
    return m, mon


def session(keyins, lp_faults=None, sysgen=None, prints=()):
    m, mon = running()
    m.console.transcript.clear()
    con = operator(m, mon, sysgen, keyins, lp_faults, prints)
    return m, mon, con, dict(con.state.log)


def test_time_and_date():
    _, mon, _, log = session(["T 14:30", "DATE 6/16/76"])
    assert mon.DATE == {"MO": 6, "DA": 16, "YR": 76, "HR": 14, "MI": 30}
    assert log["T 14:30"] == "TIME 14:30"


def test_only_four_characters_of_the_name_count():
    _, mon, _, _ = session(["TIMEX 9:05"])
    assert (mon.DATE["HR"], mon.DATE["MI"]) == (9, 5)


def test_bad_date_is_eh_and_keeps_the_fields_already_stored():
    m, mon, _, log = session(["D 07/32/76"])
    assert log["D 07/32/76"] == "EH?"
    assert mon.DATE["MO"] == 7 and mon.DATE["DA"] == 15   # month stored before the error
    assert "  EH? " in m.console.text()


def test_fields_after_the_last_value_are_ignored():
    _, mon, _, log = session(["T 1:2:3X"])
    assert (mon.DATE["HR"], mon.DATE["MI"]) == (1, 2)


def test_no_badates_check_in_the_keyin():
    _, mon, _, _ = session(["D 02/31/77"])                # MONINIT would reject this
    assert (mon.DATE["MO"], mon.DATE["DA"]) == (2, 31)


@pytest.mark.parametrize("bad", ["T 24:00", "T 123:00", "T A1:00", "T", "D 13/01/76"])
def test_bad_values(bad):
    _, _, _, log = session([bad])
    assert log[bad] == "EH?"


def test_eh_gives_a_fresh_prompt_in_the_same_interrupt():
    m, mon, con, _ = session(["HELLO", "T 10:10"])
    assert m.console.text().count("\n!") == 2
    assert mon.DATE["HR"] == 10


def test_users_allowed():
    _, _, con, log = session(["ONB 10", "ON 5"])
    assert con.state.S_BUAIS == 10
    assert log["ON 5"] == "EH?"                           # no COC: not an on-line system
    _, _, con, log = session(["ONB 33"])                  # 33 + 0 + 8 ghosts > SMUIS 40
    assert log["ONB 33"] == "EH?" and con.state.S_BUAIS == Sysgen().S_BUAIS


def test_on_with_terminals():
    sg = Sysgen(COC=1)
    _, _, con, log = session(["ON 12", "OFF"], sysgen=sg)
    assert log["ON 12"] == "ON 12"
    assert con.state.S_OUAIS == con.state.S_BUAIS == 0   # OFF: gentle down


def test_flags():
    _, _, con, _ = session(["PREF RAD", "OBOF", "OBOF"])
    assert con.state.RAD1ST == 1 and con.state.SSTAT == 2
    _, _, con, _ = session(["PREF", "OBON"])
    assert con.state.RAD1ST == 0 and con.state.SSTAT == 0


def test_syst_and_unknown_are_errors_and_empty_is_nothing():
    _, _, _, log = session(["SYST", "FOO", ""])
    assert log["SYST"] == log["FOO"] == "EH?"
    assert log[""] == "empty"


def test_untranslated_keyins_are_logged_and_the_session_goes_on():
    _, mon, _, log = session(["ABORT 3", "SEND HELLO", "T 11:11"])
    assert log["ABORT 3"].startswith("not translated")
    assert log["SEND HELLO"] == "EH?"                     # no COC
    assert mon.DATE["HR"] == 11


def test_device_keyin_answers_a_real_device_error():
    m, _, con, log = session(["LPA02,R"], lp_faults={"notop": 1}, prints=["LINE"])
    assert "LPA02 NOT OPERATIONAL" in m.console.text()
    assert log["LPA02,R"] == "device LPA02: retry"
    assert m.printer.lines == ["LINE"] and not con.waiting()


def test_device_keyin_needs_a_pending_request_and_valid_letter():
    _, _, con, log = session(["CRA03,C", "LPA02,X", "LPA02,R"], lp_faults={"notop": 1},
                             prints=["LINE"])
    assert log["CRA03,C"] == "EH?"                        # nothing pending on CRA03
    assert log["LPA02,X"] == "EH?"
    assert log["LPA02,R"] == "device LPA02: retry"


def test_continue_not_allowed_becomes_retry():
    # NOT OPERATIONAL sets key-in pending with "no continue" (X'2800'), so C retries.
    m, _, con, log = session(["LPA02,C"], lp_faults={"notop": 1}, prints=["LINE"])
    assert log["LPA02,C"] == "device LPA02: retry"
    assert m.printer.lines == ["LINE"]


def test_field_parser():
    f = Fields("  ABC,DEF  GHIJKLMNOPQRS:X\n")
    assert f.gkifld() == ("ABC".ljust(12), ",")
    assert f.gkifld() == ("DEF".ljust(12), " ")
    assert f.gkifld()[0] is None                          # 13 characters
    f = Fields("\n")
    assert f.gkifld() == (None, "\n")


def test_off_alone_does_not_shut_down():
    _, _, con, _ = session(["OFF", "T 10:00"])
    assert con.shutdown is None and con.state.GOODNGT == 0


def test_zap_shuts_down_through_the_idle_check():
    m, mon, con, log = session(["T 14:30", "ZAP", "T 15:00"])
    assert log["ZAP"] == "ZAP" and "T 15:00" not in log      # the session ends at the shutdown
    assert con.state.GOODNGT == -2 and con.state.S_OUAIS == con.state.S_BUAIS == 0
    _, new, outcome = con.shutdown
    assert mon.RCVCODE >> 16 == 0x404
    assert m.mem[0x2A] == 0x40404
    text = m.console.text()
    assert "SOFTWARE CHECK" not in text and text.rstrip().endswith("!ZAP")  # shutdown types nothing
    assert "TBOOT" in outcome                                # the INT reading: see recovery.md


def test_zap_waits_for_busy_symbionts():
    m, mon = running()
    con = OperatorConsole(m, mon, Sysgen(), screech=lambda c, s: ("shut", c))
    con.state.symbionts_busy = True
    m.console.replies.extend(["ZAP"])
    con.interrupt()
    con.idle()
    assert con.shutdown is None
    con.state.symbionts_busy = False
    con.idle()
    assert con.shutdown == ("shut", 0x404)


def test_zap_aborts_the_users_above_the_system_ghosts():
    m, mon = running()
    con = OperatorConsole(m, mon, Sysgen(), screech=lambda c, s: ("shut", c))
    con.start()
    s = mon.sched

    def forever(sched, u):
        while True:
            yield Sleep()

    cc, u = s.t_gjobstrt("SLEEPY", program=forever)    # BOOTFLG is 0 now: a new name
    assert cc == GJ_STARTED and u >= s.MING
    con.run_sched()
    assert s.UB_US[u] == SW and con.shutdown is None
    m.console.replies.extend(["ZAP"])
    con.interrupt()
    assert any(f"ZAP: abort user {u}" in l for l in s.log)
    assert u in s.ended and any(f"T:TELDELCCI user {u}" in l for l in s.log)
    assert con.shutdown == ("shut", 0x404)
    assert s.S_CUIS == 2                               # ALLOCAT and RBBAT


# --- the scheduler behind the key-ins ------------------------------------------------

def started():
    m, mon = running()
    con = OperatorConsole(m, mon, Sysgen())
    con.start()
    return m, mon, con, mon.sched


def test_initial_starts_allocat_and_the_starter_ghost():
    m, mon = running()
    s = mon.sched
    assert mon.ghosts_started == ["ALLOCAT", "GHOST1"]
    assert s.SB_GJOBUN[2] == 2 and s.SB_GJOBUN[s.MING] == s.MING    # reserved slot 2, head of SNULL
    assert s.S_CUIS == 2 and m.mem[0x27] != 0                         # nothing has run yet


def test_ghost1_finishes_the_start_up():
    m, mon, con, s = started()
    assert m.mem[0x27] == 0                            # BOOTFLG: running
    assert s.S_GJOBTBL[s.MING] == ("FILL", ":SYS")     # GHOST1 became FILL, which ended
    assert s.SB_GJOBUN[3] == 3 and s.UB_US[3] == SW    # RBBAT, asleep
    assert s.UB_US[2] == SW                            # ALLOCAT, asleep
    assert s.S_CUIS == 2 == con.state.S_CUIS
    names = [n for n, _ in filter(None, s.S_GJOBTBL)]
    assert "ERR:FIL" in names and "MOOSE" in names and "ANLZ" not in names   # X'2A' byte 0 set


def test_keyin_runs_as_a_ghost_and_logs_off():
    m, mon, con, s = started()
    m.console.replies.extend(["T 14:30"])
    con.interrupt()
    assert mon.DATE["HR"] == 14
    assert any("T:GJOBSTRT KEYIN: slot 1, user 1" in l for l in s.log)
    assert 1 in s.ended and s.SB_GJOBUN[1] == 0 and s.UB_US[1] == SNULL


def test_eh_from_the_ghost_still_gives_a_fresh_prompt():
    m, mon, con, s = started()
    m.console.replies.extend(["HELLO", "T 10:10"])
    con.interrupt()
    assert m.console.text().count("\n!") == 2 and mon.DATE["HR"] == 10


def test_keyin_that_cannot_start_says_later():
    m, mon = running()
    con = OperatorConsole(m, mon, Sysgen())
    mon.sched.S_GJOBTBL[1] = None                      # no KEYIN entry, and BOOTFLG still set
    m.console.replies.extend(["T 14:30"])
    con.interrupt()
    assert dict(con.state.log)["T 14:30"] == "LATER"
    assert "LATER" in m.console.text() and mon.DATE.get("HR") != 14
