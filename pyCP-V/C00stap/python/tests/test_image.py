"""Disc images (--disc): the swap and public discs saved and loaded between runs."""

import gzip

from uts import image, pyprog
from uts.__main__ import boot, crash, install, main
from uts.files import Disc as FilesDisc

PARTS = '''
def main(cpv):
    f = cpv.open("PARTS", fun="OUT")
    for i in range(3):
        f.write(f"P{i}", f"PART {i}")
    f.close()
'''

LIST = '''
def main(cpv):
    for key, data in cpv.open("PARTS"):
        cpv.type(key + "=" + data.decode())
'''


def installed():
    public = FilesDisc(2048)
    m, mon, outcome = install(public_disc=public)
    assert outcome == "up"
    return m, mon


def test_save_and_load_give_back_both_discs(tmp_path):
    m, mon = installed()
    pyprog.store_source(mon.sched.cal.fs, "HELLO", ":SYS", PARTS)
    path = tmp_path / "sys.json.gz"
    image.save(path, m.swap_disc, m.public_disc)
    swap, public = image.load(path)
    assert swap.sectors == m.swap_disc.sectors and swap.model == m.swap_disc.model
    assert swap.attached == m.swap_disc.attached        # DCT entries, BOOTIC's tuples
    assert public.g == m.public_disc.g and public.free == m.public_disc.free
    assert public.ad_fda == m.public_disc.ad_fda != 0


def test_the_image_is_gzipped_and_a_plain_one_loads_too(tmp_path):
    m, mon = installed()
    path = tmp_path / "sys.json.gz"
    image.save(path, m.swap_disc, m.public_disc)
    assert path.read_bytes()[:2] == b"\x1f\x8b"
    plain = tmp_path / "sys.json"
    plain.write_bytes(gzip.decompress(path.read_bytes()))
    swap, public = image.load(plain)
    assert swap.sectors == m.swap_disc.sectors and public.g == m.public_disc.g


def test_a_disc_boot_from_a_loaded_image_finds_the_files(tmp_path):
    m, mon = installed()
    pyprog.store_source(mon.sched.cal.fs, "HELLO", ":SYS", PARTS)
    path = tmp_path / "sys.json.gz"
    image.save(path, m.swap_disc, m.public_disc)
    swap, public = image.load(path)
    m2, mon2, outcome = boot(replies=["06/16/76", "08:00", "N"], disc=swap, public_disc=public)
    assert outcome == "up"
    assert pyprog.read_source(mon2.sched.cal.fs, "HELLO", ":SYS") == PARTS
    assert mon2.sched.cal.fs.ad.FDA == public.ad_fda    # mounted, not a new directory


def test_files_outlive_a_recovery():
    m, mon = installed()
    pyprog.store_source(mon.sched.cal.fs, "HELLO", ":SYS", PARTS)
    m, mon2, outcome = crash(m, mon, code=0x10, replies=["06/16/76", "08:00", "N"])
    assert outcome == "up"
    assert pyprog.read_source(mon2.sched.cal.fs, "HELLO", ":SYS") == PARTS


def test_a_file_written_in_one_run_is_read_in_the_next(tmp_path, capsys):
    path, src = tmp_path / "sys.json.gz", tmp_path
    (src / "parts.py").write_text(PARTS)
    (src / "list.py").write_text(LIST)
    main(["--disc", str(path), "--replies", "06/15/76", "13:45", "N",
          "--file", f"{src / 'parts.py'}=WRITER", f"{src / 'list.py'}=LIST",
          "--keyins", "GJOB WRITER"])
    first = capsys.readouterr().out
    assert "disc image saved" in first and path.exists()
    main(["--disc", str(path), "--replies", "06/16/76", "08:00", "N", "--keyins", "GJOB LIST"])
    second = capsys.readouterr().out
    assert "RAD BOOT" in second                         # booted from the image, no install
    assert all(f"P{i}=PART {i}" in second for i in range(3))
