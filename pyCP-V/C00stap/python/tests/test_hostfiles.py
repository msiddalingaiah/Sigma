"""IMPORT and EXPORT with the shared host folder (not CP-V; docs/online.md)."""

from tests.test_online import logged_on
from uts import hostfiles, pyprog


def shared(tmp_path):
    t = logged_on()
    t.online.share = str(tmp_path)
    return t


def test_tabs_go_to_the_assembler_columns():
    assert hostfiles.expand_tabs("START\tLI,1\t5\t* FIVE") == \
        "START    LI,1     5       * FIVE"
    assert hostfiles.expand_tabs("\tEND") == "         END"


def test_import_with_no_arguments_lists_the_folder(tmp_path):
    t = shared(tmp_path)
    (tmp_path / "hello.asm").write_text("X\n")
    (tmp_path / "sub").mkdir()                          # folders aren't listed
    t.type("IMPORT\r")
    lines = t.text().splitlines()
    assert lines[1].startswith("hello.asm") and len(lines) == 3   # the echo, a file, '!'


def test_import_makes_an_edit_keyed_file(tmp_path):
    t = shared(tmp_path)
    (tmp_path / "hello.asm").write_bytes(b"START\tLI,1\t5\r\n\tEND\tSTART\r\n")
    t.type("IMPORT hello.asm\r")
    assert "HELLO: 2 RECORDS" in t.text()
    assert pyprog.read_source(t.s.cal.fs, "HELLO", "BOB") == \
        "START    LI,1     5\n         END      START\n"
    t.type("IMPORT hello.asm TO OTHER\r")
    assert "OTHER: 2 RECORDS" in t.text()


def test_export_writes_the_records_as_lines(tmp_path):
    t = shared(tmp_path)
    pyprog.store_source(t.s.cal.fs, "SRC", "BOB", "LINE ONE   \nLINE TWO")
    t.type("EXPORT SRC TO src.asm\r")
    assert "src.asm: 2 RECORDS" in t.text()
    assert (tmp_path / "src.asm").read_bytes() == b"LINE ONE\r\nLINE TWO\r\n"
    t.type("EXPORT SRC\r")
    assert (tmp_path / "SRC.txt").exists()


def test_names_outside_the_folder_are_refused(tmp_path):
    t = shared(tmp_path)
    for name in ("..\\x.txt", "../x.txt", "C:\\x.txt", "sub/x.txt", ".hidden"):
        t.type(f"EXPORT SRC TO {name}\r")
        assert "NOT A HOST FILE NAME" in t.text()
    assert not (tmp_path.parent / "x.txt").exists()
    t.type("IMPORT ..\\secret\r")
    assert "NOT A HOST FILE NAME" in t.text()


def test_only_the_users_own_account(tmp_path):
    t = shared(tmp_path)
    t.type("EXPORT AP.:SYS\r")
    assert "ONLY YOUR OWN ACCOUNT" in t.text()


def test_without_a_shared_folder():
    t = logged_on()
    t.type("IMPORT\r")
    assert "NO HOST FOLDER SHARED" in t.text()
