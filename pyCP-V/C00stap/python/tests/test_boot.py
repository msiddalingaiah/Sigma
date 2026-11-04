from uts.__main__ import boot
from uts.bootsubr import option_bits, parse_date, parse_time
from uts.config import Sysgen
from uts.machine import MachineType, FLAG_I, FLAG_P, FLAG_D, FLAG_T, FLAG_F, FLAG_C

STD = ["06/15/76", "13:45", "N"]


def test_disc_boot_reaches_scheduler():
    m, mon, outcome = boot(replies=STD)
    assert outcome == "up"
    assert mon.ghosts_started == ["ALLOCAT", "GHOST1"]
    assert m.interrupt_mask == 0x34F0          # Sigma 9: MFI
    assert m.mem.get_byte(0x27) == FLAG_I | FLAG_P


def test_memory_probe_finds_installed_size():
    for k in (64, 96, 128):
        _, mon, _ = boot(memory_k=k, replies=STD)
        assert mon.CORED == k * 1024
        assert mon.HIGH == k * 2 - 1           # 2 pages per K words


def test_machine_type_and_interrupts():
    expected = {MachineType.SIGMA7: 0x38F0, MachineType.SIGMA9: 0x34F0, MachineType.X560: 0x3CF0}
    for model, mask in expected.items():
        m, mon, _ = boot(model=model, replies=STD)
        assert mon.CSED_MACHINE == model.value
        assert m.interrupt_mask == mask


def test_bad_date_and_time_are_reasked():
    m, mon, outcome = boot(replies=["13/01/76", "02/29/77", "02/29/76", "24:00", "23:59", "N"])
    assert outcome == "up"
    assert mon.DATE == {"MO": 2, "DA": 29, "YR": 76, "HR": 23, "MI": 59}
    assert m.console.text().count("??") == 3


def test_date_parsing():
    assert parse_date("1/2/70") == {"MO": 1, "DA": 2, "YR": 70}
    assert parse_date("01/02/69") is None      # MIND year is 70
    assert parse_date("04/31/76") is None      # BADATES
    assert parse_date("") is None              # timeout: no default
    assert parse_time("0:0") == {"HR": 0, "MI": 0}
    assert parse_time("12:60") is None


def test_option_letters():
    assert option_bits("") == FLAG_T
    assert option_bits("IP") == FLAG_I | FLAG_P
    assert option_bits("DFTCPI") == 0xFC
    assert option_bits("CX") == FLAG_C
    assert option_bits("F") == FLAG_F


def page_pool_is_consistent(mon):
    free = mon.chain(mon.M_FPPH)
    mp = mon.chain(mon.MP_UPPH)
    pp = mon.chain(mon.PP_UPPH)
    assert len(free) == mon.M_FPPC
    assert len(mp) == mon.MP_UPPC
    assert len(pp) == mon.PP_UPPC
    assert free[-1] == mon.M_FPPT
    assert not (set(free) & set(mp)) and not (set(free) & set(pp))
    return free, mp, pp


def test_page_pool_without_xdelta():
    _, mon, _ = boot(replies=STD)
    free, mp, _ = page_pool_is_consistent(mon)
    sg = Sysgen()
    assert mp == list(range(sg.JJITVP, sg.UMOV_PAGE + sg.UMOV_PAGES))   # JIT + UMOV pages
    assert mon.S_PCORE == mon.S_ACORE - 7


def test_keeping_xdelta_removes_its_pages():
    m, mon, _ = boot(replies=["06/15/76", "13:45", "Y"])
    assert m.mem.get_byte(0x27) == FLAG_I | FLAG_P | FLAG_D
    free, mp, _ = page_pool_is_consistent(mon)
    sg = Sysgen()
    delta = list(range(sg.DLTBIAS >> 9, (sg.DLTBIAS >> 9) + sg.DLTPAGES))
    assert mp[-len(delta):] == delta
    assert not set(delta) & set(free)


def test_realtime_resdf_pages():
    sg = Sysgen(realtime=True)
    _, mon, outcome = boot(replies=["5,10000", "06/15/76", "13:45", "N"], sysgen=sg)
    assert outcome == "up"
    free, _, pp = page_pool_is_consistent(mon)
    assert pp == [0x80, 0x81, 0x82, 0x83, 0x84]


def test_ssw3_stops_at_operator_recovery():
    _, _, outcome = boot(sense_switches=[3])
    assert outcome.startswith("stopped") and "SCREECH" in outcome


def test_sysvers_has_machine_bits():
    # Version 'E123': the low nibbles of characters 2 and 4 give the byte X'13'.
    _, mon, _ = boot(model=MachineType.X560, replies=STD, sysgen=Sysgen(version="E123"))
    assert mon.SYSVERS == 0x701300C1   # rotr8(13 00 C1 70): X'C170' for a 560
