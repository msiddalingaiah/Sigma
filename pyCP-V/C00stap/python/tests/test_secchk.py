"""OPEN's checks (docs/files.md section 10): SECCHK's password and account lists, creating
in another account, and deleting another account's file."""

import pytest

from tests.test_pyprog import keyins, system
from uts.files import (V_READ, Disc, FileError, FileSystem, Opener, protection, secchk,
                       fit_protection, NWFITST)

ALPHA, BETA = Opener("ALPHA"), Opener("BETA")


def fs_with(prot=None, owner=":SYS", org=2):
    fs = FileSystem(Disc(300))
    for a in (":SYS", "ALPHA", "BETA"):
        fs.add_account(a)
    fs.close(fs.open("F", owner, "OUT", org=org, prot=prot or {}))
    return fs


def opens(fs, who, mode="IN", password=None, account=":SYS"):
    try:
        fs.close(fs.open("F", account, mode, who=who,
                         password=protection(password=password).get(3) if password else None))
        return fs.access
    except FileError as e:
        assert e.code == 0x14
        return None


# --- SECCHK -------------------------------------------------------------------------------

def test_privilege_c0_opens_anything():
    fs = fs_with(protection(password="SECRET", read=["NONE"], write=["NONE"]))
    assert opens(fs, Opener("ALPHA", priv=0xC0), "UPDATE") == "own"


def test_an_empty_password_admits_only_sys():
    fs = fs_with(protection(password=""))
    assert opens(fs, Opener(":SYS")) == "own"
    assert opens(fs, ALPHA) is None


def test_a_password_must_match_even_for_the_owner():
    fs = fs_with(protection(password="SECRET"))
    assert opens(fs, Opener(":SYS"), "UPDATE") is None
    assert opens(fs, Opener(":SYS"), "UPDATE", password="WRONG") is None
    assert opens(fs, Opener(":SYS"), "UPDATE", password="SECRET") == "own"


def test_the_owner_may_do_anything_and_others_only_read_by_default():
    fs = fs_with()
    assert opens(fs, Opener(":SYS"), "UPDATE") == "own"
    assert opens(fs, ALPHA, "IN") == "read"             # SEC0: no lists, open to all
    assert opens(fs, ALPHA, "UPDATE") is None           # SECCHK4: only IN


def test_write_accounts_open_for_anything():
    fs = fs_with(protection(write=["ALPHA"]))
    assert opens(fs, ALPHA, "UPDATE") == "own"
    assert opens(fs, BETA, "UPDATE") is None
    assert opens(fs, BETA, "IN") == "read"              # no read list, no execute list


@pytest.mark.parametrize("read, alpha, beta", [
    (["ALPHA"], "read", None),
    (["ALL"], "read", "read"),
    (["NONE"], None, None),
    (["BETA", "ALPHA"], "read", "read"),
])
def test_read_accounts(read, alpha, beta):
    fs = fs_with(protection(read=read))
    assert opens(fs, ALPHA) == alpha and opens(fs, BETA) == beta


def test_execute_accounts_need_the_vehicle():
    fs = fs_with(protection(read=["NONE"], execute=["ALPHA"], vehicle="EDIT"))
    assert opens(fs, Opener("ALPHA", program=("EDIT", ":SYS"))) == "special"
    assert opens(fs, Opener("ALPHA", program=("EDIT", "ALPHA"))) is None   # not from :SYS
    assert opens(fs, Opener("ALPHA", program=("OTHER", ":SYS"))) is None
    assert opens(fs, Opener("BETA", program=("EDIT", ":SYS"))) is None    # not in the list
    fs = fs_with(protection(read=["NONE"], execute=["ALPHA"]))
    assert opens(fs, Opener("ALPHA", program=("EDIT", ":SYS"))) is None   # no vehicle, no fetch


def test_the_protection_survives_a_reopen_for_every_organization():
    for org in (1, 2, 3):
        fs = fs_with(protection(read=["ALPHA"]), org=org)
        assert opens(fs, ALPHA) == "read" and opens(fs, BETA) is None


def test_a_long_list_is_cut_to_fit_the_fit():
    prot = protection(read=[f"A{i}" for i in range(40)])
    vlps = fit_protection(prot, NWFITST)
    (code, words), = vlps
    assert code == V_READ and NWFITST + 9 + 1 + len(words) - NWFITST < 40
    fs = fs_with(prot)
    assert opens(fs, Opener("A0")) == "read" and opens(fs, Opener("A39")) is None
    assert fs.open("F", ":SYS").file.check() == []


def test_secchk_as_a_function():
    prot = protection(write=["NONE"], read=["ALPHA"])
    assert secchk(prot, False, "IN", ALPHA) == "read"
    assert secchk(prot, False, "UPDATE", ALPHA) is None
    assert secchk(prot, True, "UPDATE", BETA) == "own"


# --- creating and deleting ------------------------------------------------------------------

def test_creating_in_another_account_needs_privilege_c0():
    fs = fs_with()
    with pytest.raises(FileError) as e:
        fs.open("NEW", "BETA", "OUT", who=ALPHA)
    assert e.value.code == 0x14                         # OP71
    fs.close(fs.open("NEW", "BETA", "OUT", who=Opener("ALPHA", priv=0xC0)))
    assert "NEW" in fs.files("BETA")


THIEF = '''
def main(cpv):
    try:
        cpv.open("LOCKED", account=":SYS")
    except cpv.CpvError as e:
        cpv.type(f"NO PASSWORD {e.code:02X}")
    f = cpv.open("LOCKED", account=":SYS", password="SESAME")
    cpv.type("READ " + f.read("K").decode())
    f.close(release=True)                       # opened IN, another's file: not deleted
    try:
        cpv.open("MINE", account=":SYS", fun="OUT")
    except cpv.CpvError as e:
        cpv.type(f"CREATE {e.code:02X}")
    g = cpv.open("OWN", fun="OUT")              # its own account: ALPHA
    g.write("K", "MINE")
    g.close()
    cpv.type("OWN FILE OK")
'''

OWNER = '''
def main(cpv):
    f = cpv.open("LOCKED", fun="OUT", password="SESAME", read=["ALPHA"])
    f.write("K", "TREASURE")
    f.close()
'''


def test_programs_in_two_accounts():
    m, con, s = system(OWNER=OWNER, **{"THIEF.ALPHA": THIEF})
    keyins(m, con, "GJOB OWNER")
    text = keyins(m, con, "GJOB THIEF.ALPHA")
    lines = [t.split(": ", 1)[1] for t in text.splitlines() if ": " in t]
    assert lines == ["NO PASSWORD 14", "READ TREASURE", "CREATE 14", "OWN FILE OK"]
    assert "LOCKED" in s.cal.fs.files(":SYS")          # CLSFIL2M: the release was dropped
    assert "OWN" in s.cal.fs.files("ALPHA")
