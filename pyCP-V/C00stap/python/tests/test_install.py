import pytest

from uts.__main__ import boot, install
from uts.config import Module, Sysgen
from uts.devices import Disc
from uts.writemon import WriteMonError, pieces, place_cards, writemon

OPTS_IP = ["IP", "06/15/76", "13:45"]          # ENTER ANY OF, DATE, TIME


def names():
    return [name for name, _, _ in pieces(Sysgen())]


def test_install_comes_up_and_lays_out_the_disc():
    m, mon, outcome = install()
    assert outcome == "up"
    sg = Sysgen()
    top = sg.MAXOVLY + 4
    assert mon.PH_DDA[top] == 8                 # JIT at sector 6, ALLOCAT data at 8
    assert mon.PB_PVA[top] == 0x80 and mon.PB_HVA[top] == 0x84
    assert mon.UMOV_ == 1                       # UMOV is the last overlay in name order
    assert mon.PB_PVA[1] == sg.JJITVP + 1 and mon.UMOVSZ == 3 * 2048
    assert mon.UMOVSA == mon.PH_PDA[1]
    assert mon.RCVDISC < mon.DLTDSC < mon.DABOOT[0] < mon.DABOOT[1] < mon.DABOOT[2]
    assert mon.BOOTIC == [(0x4000, 0x10000), (0x8000, (sg.MONIRTN - 0x8000) * 4)]
    assert mon.MAXSEG == len(names()) == 13


def test_disc_boot_reads_back_what_the_install_wrote():
    sg = Sysgen()
    root = [0] * 0x8400
    root[sg.GETHGP] = 5
    root[sg.TOPROOT] = 7
    root[0x8100] = 0xDEADBEEF                   # in part 3
    im, imon, _ = install(sysgen=sg, root=root)
    assert imon.MONCHK == 12                    # sum of GETHGP..TOPROOT
    m, mon, outcome = boot(replies=["06/15/76", "13:45", "N"], disc=im.swap_disc, sysgen=sg)
    assert outcome == "up"
    assert m.mem[0x8100] == 0xDEADBEEF and m.mem[sg.TOPROOT] == 7
    assert mon.DABOOT == imon.DABOOT and mon.UMOVSA == imon.UMOVSA
    assert mon.SYSVERS == imon.SYSVERS


def test_options_I_and_P_show_the_creation_record_and_sense_switch_reminder():
    m, mon, outcome = install(replies=OPTS_IP + ["YES", ""])
    assert outcome == "up"
    text = m.console.text()
    assert "C/LL/DC ASSIGN OK (YES/NO)" in text
    assert "VERSION NO. IS:    C00" in text and "GHOST11" in text
    assert "SSW3 => OPERATOR RECOVERY ON DISC BOOT" in text
    assert any("C P - V" in line for line in m.printer.lines)
    assert any("NO RECONFIGURATION PERFORMED" in line for line in m.printer.lines)


def test_assign_reply_must_be_exactly_yes_or_no():
    m, _, outcome = install(replies=OPTS_IP + ["Y", "YES", ""])
    assert outcome == "up"
    assert m.console.text().count("??") == 1


def test_reassigning_the_swapper():
    other = Disc()
    m, mon, outcome = install(replies=OPTS_IP + ["NO", "SA", "SA", "B02", ""],
                              extra_devices={0x102: other})
    assert outcome == "up"
    assert "DCB01 => " in m.console.text()
    assert mon.M_SWAPD == 0x102 and m.swap_disc is other
    assert mon.DCT[Sysgen().MB_SDI].name == "DCB02"
    assert other.sectors and other.attached


def test_bad_device_reply_is_reasked():
    m, mon, outcome = install(replies=OPTS_IP + ["NO", "Z03", "A03", "SA", "SA", ""])
    assert outcome == "up"
    assert m.console.text().count("??") == 1


def test_write_protected_swapper_asks_for_another():
    m, mon, outcome = install(replies=OPTS_IP + ["YES", "B02", ""],
                              disc=Disc(write_protected=True), extra_devices={0x102: Disc()})
    assert outcome == "up"
    assert "SWAPPER WRITE PROTECTED  DCB01" in m.console.text()
    assert mon.M_SWAPD == 0x102


def test_wrong_controller_model():
    m, mon, outcome = install(replies=OPTS_IP + ["YES", "B02", ""],
                              disc=Disc(model=0x56), extra_devices={0x102: Disc()})
    assert "SWAPPER NOT  7212" in m.console.text()
    assert outcome == "up"


def test_card_placement_follows_segment_order():
    ns = names()
    deck = ["/ROOT PATCH", "GHOST10/1/2", "GHOST11/1/2", "<COMMENT", "UMOV/1/2"]
    at = place_cards(deck, ns)
    g10, g11, umov = (ns.index(n) + 1 for n in ("GHOST10", "GHOST11", "UMOV"))
    assert at[0] == ["/ROOT PATCH", "GHOST10/1/2"]     # look-ahead card goes with the root
    assert at[g10] == ["GHOST11/1/2"]
    assert at[g11] == ["<COMMENT", "UMOV/1/2"]
    assert at[umov] == ["*"]
    assert at[len(ns)] == ["!"]
    with pytest.raises(WriteMonError):
        place_cards(["UMOV/1/2", "GHOST10/1/2"], ns)


def test_patch_cards_reach_the_right_segment():
    _, mon, outcome = install(deck=["<JUST A COMMENT", "GHOST11/1A/2"])
    assert outcome.startswith("stopped") and "segment 5" in outcome   # GHOST10=3, GHOST12=4
    assert mon.SEGNO == 5


def test_without_T_flag_tape_cards_are_skipped():
    _, mon, outcome = install(replies=["I", "06/15/76", "13:45", "YES", ""],
                              deck=["GHOST11/1A/2"])
    assert outcome == "up" and mon.patch_cards == []


def test_reconfig_command_stops_the_boot():
    _, _, outcome = install(deck=[":END"])
    assert "RECONFIG" in outcome


def test_boot_under_files_keeps_allocats_data():
    im, imon, _ = install()
    disc = im.swap_disc
    sector = imon.PH_DDA[Sysgen().MAXOVLY + 4]
    disc.sectors[sector] = [0x1234] * 256       # "file system" state in ALLOCAT's data
    _, mon, outcome = install(replies=["F", "06/15/76", "13:45"], disc=disc)
    assert outcome == "up"
    assert disc.sectors[sector][0] == 0x1234
    disc2 = install()[0].swap_disc               # a normal install overwrites it
    assert disc2.sectors[sector][0] == 0


def test_writemon_rejects_big_overlay():
    sg = Sysgen()
    sg.modules.insert(3, Module("BIGOV", start=0x8000, proc=(7, 0x40)))
    with pytest.raises(WriteMonError, match="OVERLAY EXCEEDS 6 PAGES"):
        writemon(sg)


def test_more_overlays_change_maxovly_and_slots():
    sg = Sysgen()
    sg.modules.insert(3, Module("OVLY0", start=0x8000, proc=(1, 0x40)))
    _, mon, outcome = install(sysgen=sg)
    assert outcome == "up" and sg.MAXOVLY == 6
    assert mon.UMOV_ == 1 and mon.PB_PVA[5] == 0x40
