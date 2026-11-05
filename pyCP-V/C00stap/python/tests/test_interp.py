"""Interpreted programs as ghosts (uts/interp.py): assembled Sigma code under the
scheduler, its CALs through the Python monitor."""

from tests.test_pyprog import keyins, system
from uts.asm import assemble
from uts.interp import read_image, store_image

HELLO = """
* Type a line three times, then M:EXIT
         ORG      X'D000'
START    LI,5     3
LOOP     CAL1,2   TYPE
         BDR,5    LOOP
         CAL1,9   1
TYPE     DATA     X'02000000',X'80000000',MSG
MSG      TEXTC    'HELLO FROM SIGMA CODE'
         END      START
"""

ECHO = """
* Ask the operator (M:KEYIN), then type the reply back with a prefix
         ORG      X'D000'
START    CAL1,2   ASK
         LB,3     BUF               the reply's length, n
         AI,3     4
         STB,3    OUT               OUT's count: 'YOU ' + n
         AI,3     -4
         SLS,3    24                R3: n in bits 0-7 ...
         OR,3     DEST              ... and the destination byte address
         LI,2     BA(BUF)+1         R2: the source, after BUF's count
         MBS,2    0
         CAL1,2   TYPE
         CAL1,9   1
ASK      DATA     X'04000000',X'E0000000',QUESTION,BUF,60
TYPE     DATA     X'02000000',X'80000000',OUT
DEST     DATA     BA(OUT)+5
QUESTION TEXTC    'WHO ARE YOU?'
OUT      TEXTC    'YOU '
         RES      16
BUF      RES      16
         END      START
"""

TRAPS = """
         ORG      X'D000'
START    CAL1,2   TYPE
         WD,0     X'45'             privileged: trap X'40', CC3
         CAL1,9   1
TYPE     DATA     X'02000000',X'80000000',MSG
MSG      TEXTC    'BEFORE THE TRAP'
         END      START
"""

SPIN = """
* Never calls the monitor
         ORG      X'D000'
START    AI,1     1
         B        START
         END      START
"""
SPIN = SPIN.replace("         B        START", "         BCR,0    START")


def with_images(**sources):
    m, con, s = system()
    for name, src in sources.items():
        dcbs = {}
        words, start = assemble(src, dcbs)
        store_image(s.cal.fs, name, ":SYS", words, start, dcbs)
    m.console.transcript.clear()
    return m, con, s


def lines(text):
    return [t.split(": ", 1)[1] for t in text.splitlines() if ": " in t]


def test_an_image_round_trips_through_its_file():
    m, con, s = with_images(HELLO=HELLO)
    words, start = assemble(HELLO)
    assert read_image(s.cal.fs, "HELLO", ":SYS") == (words, start, {})


def test_an_assembled_program_types_and_exits():
    m, con, s = with_images(HELLO=HELLO)
    text = keyins(m, con, "GJOB HELLO")
    assert lines(text) == ["HELLO FROM SIGMA CODE"] * 3
    assert any("LOAD HELLO" in l and "interpreted" in l for l in s.log)
    assert any("T:EXIT" in l for l in s.log)


def test_a_program_asks_the_operator_and_echoes():
    m, con, s = with_images(ECHO=ECHO)
    text = keyins(m, con, "GJOB ECHO", "MADHU")
    assert "WHO ARE YOU?" in text and lines(text)[-1] == "YOU MADHU"


def test_a_trap_ends_the_program_with_a_message():
    m, con, s = with_images(TRAPS=TRAPS)
    text = keyins(m, con, "GJOB TRAPS")
    out = lines(text)
    assert out[0] == "BEFORE THE TRAP"
    assert out[1].startswith("TRAPS TRAP X'40' CC 2 AT X'0D001'")
    assert "PRIVILEGED" in out[1]


def test_a_program_that_never_calls_the_monitor_doesnt_hold_the_system(monkeypatch):
    monkeypatch.setattr("uts.interp.SLICE", 20)        # fewer instructions a clock unit
    m, con, s = with_images(SPIN=SPIN, HELLO=HELLO)
    keyins(m, con, "GJOB SPIN")
    text = keyins(m, con, "GJOB HELLO")
    assert lines(text) == ["HELLO FROM SIGMA CODE"] * 3   # it was preempted
    spin = next(u for u in range(len(s.uregs)) if s.uregs[u][1] > 1000)
    assert s.uregs[spin][1] > 1000                     # and it kept running


def test_file_imports_an_assembly_program(tmp_path, capsys):
    from uts.__main__ import main
    src = tmp_path / "hello.s"
    src.write_text(HELLO)
    main(["--replies", "06/15/76", "13:45", "N", "--file", f"{src}=HELLO",
          "--keyins", "GJOB HELLO"])
    assert capsys.readouterr().out.count("HELLO FROM SIGMA CODE") == 3


# --- file I/O with the program's own DCB (docs/dcb.md) -------------------------------------

FILES = """
* Its own DCB: create LOG, write three records, reopen IN, read and type them to EOF
         ORG      X'D000'
START    CAL1,1   OPEN
         LI,5     3
         LI,6     7                 index of the record's digit
WLOOP    CAL1,1   WRITE
         MTB,1    REC,6             ENTRY 1 -> 2 -> 3
         BDR,5    WLOOP
         CAL1,1   CLOSE
         LW,4     FUNIN             FUN = IN, in place
         STW,4    F:LOG+1
         CAL1,1   OPEN
RLOOP    CAL1,1   READ              EOF goes to the abnormal address
         CAL1,2   TYPE              each record is a TEXTC
         BCR,0    RLOOP
EOF      LW,3     F:LOG+2             TYC, bits 8-14
         CAL1,2   TYPEEOF
         CAL1,1   CLOSE
         CAL1,9   1
ERR      CAL1,2   TYPEERR
         CAL1,9   3
OPEN     DATA     X'14000000'+F:LOG,X'C0000000',ERR,EOF
CLOSE    DATA     X'15000000'+F:LOG,0
WRITE    DATA     X'11000000'+F:LOG,X'F0000000',ERR,EOF,REC,8
READ     DATA     X'10000000'+F:LOG,X'F0000000',ERR,EOF,INBUF,32
TYPE     DATA     X'02000000',X'80000000',INBUF
TYPEEOF  DATA     X'02000000',X'80000000',MEOF
TYPEERR  DATA     X'02000000',X'80000000',MERR
FUNIN    DATA     X'00020000'
REC      TEXTC    'ENTRY 1'
INBUF    RES      8
MEOF     TEXTC    'END OF FILE'
MERR     TEXTC    'ERROR'
F:LOG    DATA     X'1F000001'       22 words + VLPs; ASN 1, a file
         DATA     X'00040000'       FUN = OUT
         DATA     X'03000000'       3 retries
         DATA     0,0
         DATA     0                 ORG 0: consecutive
         DATA     VLPS              FLP
         RES      15
VLPS     DATA     X'01010108'       code 1 (name), last, 1 word used, 8 reserved
         TEXTC    'LOG'
         RES      7
         END      START
"""

MISSING = """
         ORG      X'D000'
START    CAL1,1   OPEN
         CAL1,9   1
ERR      LW,4     10                SR3: the code in byte 0
         SLS,4    -24
         STW,4    CODE
         CAL1,2   TYPEERR
         CAL1,9   1
OPEN     DATA     X'14000000'+F:LOG,X'C0000000',ERR,ERR
TYPEERR  DATA     X'02000000',X'80000000',MERR
CODE     DATA     0
MERR     TEXTC    'NO SUCH FILE'
F:LOG    DATA     X'1F000001'
         DATA     X'00020000'       FUN = IN
         DATA     0,0,0,0
         DATA     VLPS
         RES      15
VLPS     DATA     X'01010108'
         TEXTC    'NOPE'
         RES      6
         END      START
"""


def test_a_program_does_file_io_with_its_own_dcb():
    m, con, s = with_images(FILES=FILES)
    text = keyins(m, con, "GJOB FILES")
    assert lines(text) == ["ENTRY 1", "ENTRY 2", "ENTRY 3", "END OF FILE"]
    f = s.cal.fs.open("LOG", ":SYS")
    assert f.file.records() == [b"\x07" + f"ENTRY {i}".encode("cp037") for i in (1, 2, 3)]


def test_the_dcb_fields_change_in_memory():
    m, con, s = with_images(FILES=FILES)
    keyins(m, con, "GJOB FILES")
    u = next(u for u, d in s.cal.mem_dcbs.items() if d)
    dcb = next(iter(s.cal.mem_dcbs[u].values()))
    assert dcb.fname == "LOG" and dcb.fun == "IN" and not dcb.open   # closed at the end
    assert dcb.tyc == 7                                # the end of file, left in TYC
    assert dcb.ars == 8                                # the last record's size


def test_a_missing_file_goes_to_the_error_address():
    m, con, s = with_images(MISSING=MISSING)
    text = keyins(m, con, "GJOB MISSING")
    assert lines(text) == ["NO SUCH FILE"]
    from uts.asm import Assembler
    asm = Assembler(MISSING)
    asm.assemble()
    u = next(iter(s.cal.mem_dcbs))
    assert s.umem[u][asm.sym["CODE"]] == 3             # X'03', from R10's byte 0


def test_the_guests_example_keeps_its_book_between_runs(tmp_path, capsys):
    from pathlib import Path
    from uts.__main__ import main
    example = Path(__file__).parent.parent / "examples" / "guests.s"
    disc = tmp_path / "book.json.gz"
    main(["--disc", str(disc), "--replies", "06/15/76", "13:45", "N",
          "--file", f"{example}=GUESTS", "--keyins", "GJOB GUESTS", "ADA"])
    capsys.readouterr()
    main(["--disc", str(disc), "--replies", "06/16/76", "09:00", "N",
          "--keyins", "GJOB GUESTS", "GRACE"])
    out = lines(capsys.readouterr().out)
    i = out.index("THE VISITORS SO FAR:")
    assert out[i + 1:i + 3] == ["ADA", "GRACE"]


def test_importing_again_replaces_the_old_image():
    from uts.files import Disc, FileSystem
    fs = FileSystem(Disc(400))
    fs.add_account(":SYS")
    store_image(fs, "P", ":SYS", {0xD000 + i: i for i in range(1200)}, 0xD000)
    store_image(fs, "P", ":SYS", {0xD000 + i: 7 for i in range(10)}, 0xD000)
    words, start, _ = read_image(fs, "P", ":SYS")
    assert words == {0xD000 + i: 7 for i in range(10)}
