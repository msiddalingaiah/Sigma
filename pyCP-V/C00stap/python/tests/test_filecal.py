"""Keyed files through the CALs on the booted system: M:OPEN, M:WRITE, M:READ,
M:DELREC and M:CLOSE from stand-in ghosts."""

from tests.test_keyin import started
from uts.cal import (CODE, F_NWK, F_ONWK, Fpt, P_ABN, P_BUF, P_ERR, P_KEY, P_SIZE)
from uts.files import EBCDIC, FileSystem
from uts.sched import Cal1, Sleep

DCB, BUF, KEY, ERRR, ABNR = 0x9000, 0xB000, 0xB400, 0xC000, 0xC100


def run_ghost(name, body, system=None):
    m, mon, con, s = system or started()
    out = []

    def program(sched, u):
        yield from body(sched, u, out)
        while True:
            yield Sleep()

    cc, u = s.t_gjobstrt(name, program=program)
    con.run_sched()
    return (m, mon, con, s), u, out


def dcb(s, u, fun, name="PARTS"):
    return s.cal.add_dcb(u, "M:EI", DCB, asn=1, fname=name, account=":SYS", fun=fun, keym=11)


def m_open(err=0, abn=0):
    return Cal1(1, Fpt(0x14, word0=DCB, presence=P_ERR | P_ABN, params=[err, abn]))


def m_close():
    return Cal1(1, Fpt(0x15, word0=DCB))


def m_write(s, u, key, data, flags=F_ONWK, abn=0):
    s.cal.put_text(u, BUF, data)
    s.cal.put_text(u, KEY, key, textc=True)
    return Cal1(1, Fpt(0x11, word0=DCB, presence=P_ERR | P_ABN | P_BUF | P_SIZE | P_KEY | flags,
                       params=[0, abn, BUF, len(data), KEY]))


def m_read(s, u, key=None, err=0, abn=0, size=40):
    params, presence = [err, abn, BUF, size], P_ERR | P_ABN | P_BUF | P_SIZE
    if key is not None:
        s.cal.put_text(u, KEY, key, textc=True)
        params.append(KEY)
        presence |= P_KEY
    return Cal1(1, Fpt(0x10, word0=DCB, presence=presence, params=params))


def m_delrec(s, u, key):
    s.cal.put_text(u, KEY, key, textc=True)
    return Cal1(1, Fpt(0x0D, word0=DCB, presence=P_ERR | P_ABN | P_KEY, params=[0, 0, KEY]))


def buffer(s, u, n):
    return s.cal.read_text(u, BUF, 0, n)


def write_parts(sched, u, out, n=60):
    dcb(sched, u, "OUT")
    out.append(("open", (yield m_open())))
    for i in range(n):
        yield m_write(sched, u, f"P{i:04d}", f"PART NUMBER {i}")
    out.append(("files before close", sched.cal.fs.files(":SYS")))
    yield m_close()


def test_a_ghost_writes_a_keyed_file_and_another_reads_it():
    system, u, out = run_ghost("WRITER", write_parts)
    m, mon, con, s = system
    assert out == [("open", 0), ("files before close", [])]
    assert s.cal.fs.files(":SYS") == ["PARTS"]          # entered in the directory at close
    log = "\n".join(s.log)
    assert "T:OVERLAY OPEN" in log and "T:OVERLAY CLOSE" in log   # through the scheduler

    def reader(sched, uu, out2):
        d = dcb(sched, uu, "IN")
        yield m_open()
        yield m_read(sched, uu, "P0042")
        out2.append((buffer(sched, uu, 14), d.ars, d.kbuf.decode("cp037")))
        yield m_read(sched, uu)                           # the next record, by KBUF
        out2.append(buffer(sched, uu, 14))
        yield m_close()

    _, u2, out2 = run_ghost("READER", reader, system)
    assert out2 == [("PART NUMBER 42", 14, "P0042"), "PART NUMBER 43"]


def test_reading_past_the_end_goes_to_the_abnormal_routine():
    system, _, _ = run_ghost("WRITER", lambda s, u, o: write_parts(s, u, o, n=3))

    def reader(sched, uu, out):
        dcb(sched, uu, "IN")
        yield m_open()
        for _ in range(4):
            out.append((yield m_read(sched, uu, abn=ABNR)))

    _, u, out = run_ghost("READER", reader, system)
    s = system[3]
    assert out[:3] == [0, 0, 0]
    assert out[3] == ("ROUTINE", ABNR, (CODE[7] << 24) | DCB)   # end of file: X'06'


def test_a_missing_key_is_error_43():
    system, _, _ = run_ghost("WRITER", lambda s, u, o: write_parts(s, u, o, n=3))

    def reader(sched, uu, out):
        dcb(sched, uu, "IN")
        yield m_open()
        out.append((yield m_read(sched, uu, "NOPE", err=ERRR)))

    _, u, out = run_ghost("READER", reader, system)
    assert out == [("ROUTINE", ERRR, (0x43 << 24) | DCB)]


def test_newkey_on_an_existing_key_is_abnormal_16():
    def body(sched, u, out):
        dcb(sched, u, "OUT", name="KEYS")
        yield m_open()
        yield m_write(sched, u, "A", "FIRST")
        out.append((yield m_write(sched, u, "A", "AGAIN", flags=F_NWK, abn=ABNR)))
        yield m_close()

    system, u, out = run_ghost("WRITER", body)
    assert out == [("ROUTINE", ABNR, (0x16 << 24) | DCB)]


def test_delrec_and_update():
    system, _, _ = run_ghost("WRITER", lambda s, u, o: write_parts(s, u, o, n=5))

    def updater(sched, uu, out):
        dcb(sched, uu, "UPDATE")
        yield m_open()
        yield m_delrec(sched, uu, "P0002")
        yield m_read(sched, uu, "P0001")
        yield m_write(sched, uu, "P0001", "CHANGED PART 1")   # rewrite
        out.append((yield m_read(sched, uu, "P0002", err=ERRR)))
        yield m_close()

    _, u, out = run_ghost("UPDATER", updater, system)
    fs = system[3].cal.fs
    c = fs.open("PARTS", ":SYS", "IN")
    assert c.file.read("P0001") == "CHANGED PART 1".encode(EBCDIC) and c.file.read("P0002") is None
    assert c.file.keys() == ["P0000", "P0001", "P0003", "P0004"]
    assert out == [("ROUTINE", ERRR, (0x43 << 24) | DCB)]
    assert c.file.check() == []


def test_writing_a_file_opened_in_is_an_operation_error():
    system, _, _ = run_ghost("WRITER", lambda s, u, o: write_parts(s, u, o, n=1))

    def body(sched, uu, out):
        dcb(sched, uu, "IN")
        yield m_open()
        out.append((yield m_write(sched, uu, "P0000", "NO", abn=ABNR)))

    _, u, out = run_ghost("READER", body, system)
    assert out == [("ROUTINE", ABNR, (0x15 << 24) | DCB)]


def test_a_read_on_a_closed_dcb_opens_it_by_default():
    system, _, _ = run_ghost("WRITER", lambda s, u, o: write_parts(s, u, o, n=3))

    def body(sched, uu, out):
        d = dcb(sched, uu, "IN")
        yield m_read(sched, uu, "P0001")                 # no M:OPEN first
        out.append((d.open, buffer(sched, uu, 13)))

    _, u, out = run_ghost("READER", body, system)
    assert out == [(True, "PART NUMBER 1")]


def test_opening_a_missing_file_for_input_is_abnormal_03():
    def body(sched, uu, out):
        d = dcb(sched, uu, "IN", name="NOTHERE")
        out.append(((yield m_open(abn=ABNR)), d.open))

    _, u, out = run_ghost("READER", body)
    assert out == [(("ROUTINE", ABNR, (0x03 << 24) | DCB), False)]


def test_the_disc_holds_everything_needed_to_mount_it_again():
    system, _, _ = run_ghost("WRITER", write_parts)
    fs = system[3].cal.fs
    again = FileSystem.mount(fs.disc, fs.ad.FDA)
    assert again.files(":SYS") == ["PARTS"]
    f = again.open("PARTS", ":SYS", "IN").file
    assert f.read("P0059") == "PART NUMBER 59".encode(EBCDIC) and len(f.keys()) == 60 and f.check() == []
