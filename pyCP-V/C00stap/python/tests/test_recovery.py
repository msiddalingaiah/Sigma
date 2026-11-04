import pytest

from uts.__main__ import boot, crash, install, operator_recovery
from uts.devices import SECTOR_WORDS
from uts.machine import (BOOTTYPE, DBOOT_RD0, MTBOOT_LI1, OP_RECOVERY, RECOVERY,
                         boot_type, interpret)
from uts.config import Sysgen
from uts.keyin import OperatorConsole
from uts.monitor import NotTranslated
from uts.recovery import SUA, code_word, screech

STD = ["06/15/76", "13:45", "N"]


def running():
    m, mon, outcome = boot(replies=STD)
    assert outcome == "up"
    return m, mon


def test_x2a_holds_the_bootstrap_instructions():
    m, _ = running()
    assert m.mem[BOOTTYPE] == DBOOT_RD0 and boot_type(m.mem[BOOTTYPE]) == 3
    im, _, _ = install()
    assert im.mem[BOOTTYPE] >> 20 == MTBOOT_LI1 >> 20 and boot_type(im.mem[BOOTTYPE]) == 1
    assert interpret(im.mem[BOOTTYPE])[2] == 66          # LI,1 n: n root records


def test_boot_type_table():
    assert [boot_type(w) for w in (0xD5D60000, MTBOOT_LI1 | 5, 0xFFFFFFFF, DBOOT_RD0,
                                   RECOVERY, OP_RECOVERY)] == [0, 1, 2, 3, 4, 5]


def test_screech_word_mask():
    # LI of X'F00FF' sign-extends to X'FFFF00FF': SCREECH -1 keeps code X'FFFF'.
    assert code_word(-1) & 0xFFFF00FF == 0xFFFF0000


def test_crash_recovers_and_reboots_without_prompts():
    m, mon = running()
    m, new, outcome = crash(m, mon, code=0x2E, subcode=3)
    assert outcome == "up"
    text = m.console.text()
    assert "SOFTWARE CHECK  2E-03" in text
    assert "DATE(" not in text.split("SOFTWARE CHECK")[1]  # MONINIT skipped the dialog
    assert m.mem[BOOTTYPE] == RECOVERY and boot_type(m.mem[BOOTTYPE]) == 4
    assert new.ghosts_started == ["ALLOCAT", "GHOST1"]


def test_dump_area_holds_the_crash_time_memory():
    m, mon = running()
    m.mem[0x1234] = 0x11111111     # below X'4000'
    m.mem[0x5678] = 0x22222222     # X'4000'-X'7FFF': overwritten by RECOVER, saved first
    m.mem[0x9ABC] = 0x33333333     # above X'8000'
    rcvrad, seek4000 = mon.RCVRAD, mon.SEEK4000
    disc = m.swap_disc
    crash(m, mon, code=0x2E)
    assert seek4000 == rcvrad + 0x44
    start = rcvrad + 4                                    # after the 4-sector recovery buffer

    def dumped(address):
        sector, offset = divmod(address, SECTOR_WORDS)
        return disc.sectors[start + sector][offset]

    assert dumped(0x1234) == 0x11111111
    assert dumped(0x5678) == 0x22222222
    assert dumped(0x9ABC) == 0x33333333
    assert mon.TRCVRAD == rcvrad and mon.RCVRAD == start + 2 * (mon.CORED >> 9)


def test_operator_recovery():
    m, mon = running()
    m, new, outcome = operator_recovery(m, mon)
    assert outcome == "up"
    assert "OPERATOR RECOVERY" in m.console.text()
    assert m.mem[BOOTTYPE] == OP_RECOVERY and boot_type(m.mem[BOOTTYPE]) == 5


def test_unknown_reason():
    m, mon = running()
    m, _, outcome = crash(m, mon, code=0x123)
    assert outcome == "up" and "RECOVERY FOR UNKNOWN REASON" in m.console.text()


def test_shutdown_code_types_nothing_and_skips_the_dump():
    m, mon = running()
    m.console.transcript.clear()
    m, _, outcome = crash(m, mon, code=0x404)
    assert m.console.text() == ""
    assert m.mem[BOOTTYPE] == 0x40404
    # Under the INT assumption the reboot's REQDELT then branches to TBOOT:.
    assert "TBOOT" in outcome


def test_cold_operator_recovery_has_nothing_to_recover():
    _, _, outcome = boot(sense_switches=[3])
    assert "no monitor in memory" in outcome


def test_sua_is_not_translated():
    m, mon = running()
    with pytest.raises(NotTranslated, match="SUA"):
        screech(m, mon, Sysgen(), 0x61, kind=SUA)


def test_ghost1_starts_anlz_after_a_recovery():
    m, mon = running()
    m, new, outcome = crash(m, mon, code=0x2E, subcode=3)
    con = OperatorConsole(m, new, Sysgen())
    con.start()
    names = [n for n, _ in filter(None, new.sched.S_GJOBTBL)]
    assert m.mem[BOOTTYPE] == 0 and "ANLZ" in names        # MTB,0 X'2A' is zero
    assert new.sched.S_CUIS == 2
