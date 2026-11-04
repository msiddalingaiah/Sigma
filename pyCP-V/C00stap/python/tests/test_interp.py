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
        words, start = assemble(src)
        store_image(s.cal.fs, name, ":SYS", words, start)
    m.console.transcript.clear()
    return m, con, s


def lines(text):
    return [t.split(": ", 1)[1] for t in text.splitlines() if ": " in t]


def test_an_image_round_trips_through_its_file():
    m, con, s = with_images(HELLO=HELLO)
    words, start = assemble(HELLO)
    assert read_image(s.cal.fs, "HELLO", ":SYS") == (words, start)


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
