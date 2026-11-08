"""OPEN's access checks, and deleting files by closing them with release."""

import pytest

from cpvmodel import (ALL, NONE, Close, FileError, FileMode, Open, Organization, Protection,
                      System, WriteRecord)
from cpvmodel.filesystem import ACCESS_REFUSED, NO_SUCH_FILE, GranuleShortage


def program(*steps):
    yield from steps


def setUp(protection=None, organization=Organization.CONSECUTIVE):
    """An owner in account OWNER with a file DATA; returns the system and a function that
    makes users."""
    system = System()

    def makeUser(account, privilege=0, name=None):
        return system.startUser(name or account.lower(), program(), priority=0xF8,
                                account=account, privilege=privilege)

    owner = makeUser("OWNER")
    files = system.files
    try:
        handle = files.openFile(owner, "DATA", FileMode.OUT, organization=organization,
                                protection=protection, size=2)
    except GranuleShortage:                     # a random file's run comes from ALLOCAT
        system.run()
        handle = files.openFile(owner, "DATA", FileMode.OUT, organization=organization,
                                protection=protection, size=2)
    files.closeFile(handle)
    return system, makeUser


def refused(system, user, mode, password=None, account="OWNER"):
    with pytest.raises(FileError) as error:
        system.files.openFile(user, "DATA", mode, account, password=password)
    return error.value.code == ACCESS_REFUSED


def opens(system, user, mode, password=None):
    return system.files.openFile(user, "DATA", mode, "OWNER", password=password)


# --- SECCHK ---------------------------------------------------------------------------------

def testAFileWithNoListsCanBeReadByAnyoneButNotWritten():
    system, makeUser = setUp()
    other = makeUser("OTHER")
    assert not opens(system, other, FileMode.IN).ownFile
    assert refused(system, other, FileMode.OUT)


def testTheOwnerOpensForAnything():
    system, makeUser = setUp(Protection(readAccounts=(NONE,)))
    owner = system.users[0]
    assert opens(system, owner, FileMode.IN).ownFile
    assert opens(system, owner, FileMode.OUT).ownFile


def testReadAccountsDecideWhoMayRead():
    system, makeUser = setUp(Protection(readAccounts=("FRIEND",)))
    assert opens(system, makeUser("FRIEND"), FileMode.IN)
    assert refused(system, makeUser("STRANGER"), FileMode.IN)


def testReadAccountsAllAndNone():
    system, makeUser = setUp(Protection(readAccounts=(ALL,)))
    assert opens(system, makeUser("ANYONE"), FileMode.IN)
    system, makeUser = setUp(Protection(readAccounts=(NONE,)))
    assert refused(system, makeUser("ANYONE"), FileMode.IN)


def testAWriteAccountIsAsGoodAsOwning():
    system, makeUser = setUp(Protection(writeAccounts=("PARTNER",)))
    partner = makeUser("PARTNER")
    assert opens(system, partner, FileMode.IN).ownFile
    assert opens(system, partner, FileMode.OUT).ownFile


def testAPasswordMustMatch():
    system, makeUser = setUp(Protection(password="SECRET"))
    owner = system.users[0]
    assert refused(system, owner, FileMode.IN)               # even the owner
    assert refused(system, owner, FileMode.IN, password="WRONG")
    assert opens(system, owner, FileMode.IN, password="SECRET")


def testAnEmptyPasswordIsForSysOnly():
    system, makeUser = setUp(Protection(password=""))
    assert refused(system, system.users[0], FileMode.IN)
    assert opens(system, makeUser(":SYS"), FileMode.IN).ownFile


def testExecuteAccountsAloneDontGiveReadAccess():
    system, makeUser = setUp(Protection(executeAccounts=(ALL,)))
    assert refused(system, makeUser("OTHER"), FileMode.IN)


def testPrivilegeC0OpensAnything():
    system, makeUser = setUp(Protection(password="SECRET", readAccounts=(NONE,)))
    operator = makeUser("OPS", privilege=0xC0)
    assert not opens(system, operator, FileMode.IN).ownFile
    assert opens(system, operator, FileMode.OUT)


# --- OPNF's other rules -----------------------------------------------------------------------

def testCreatingAFileInAnotherAccountNeedsPrivilege():
    system, makeUser = setUp()
    with pytest.raises(FileError) as error:
        system.files.openFile(makeUser("OTHER"), "NEW", FileMode.OUT, "OWNER")
    assert error.value.code == ACCESS_REFUSED
    assert system.files.openFile(makeUser("OPS", privilege=0xC0), "NEW", FileMode.OUT, "OWNER")


def testRandomAndNonRandomFilesCantReplaceEachOther():
    system, makeUser = setUp(organization=Organization.RANDOM)
    owner = system.users[0]
    with pytest.raises(FileError) as error:
        system.files.openFile(owner, "DATA", FileMode.OUT, organization=Organization.KEYED)
    assert error.value.code == ACCESS_REFUSED


# --- Deleting -------------------------------------------------------------------------------

def testClosingWithReleaseDeletesTheFile():
    system, makeUser = setUp()
    owner = system.users[0]
    files = system.files
    before = files.disc.freeCount()
    handle = files.openFile(owner, "DATA", FileMode.IN)
    files.closeFile(handle, release=True)
    assert files.fileNames("OWNER") == []
    assert files.disc.freeCount() >= before
    with pytest.raises(FileError) as error:
        files.openFile(owner, "DATA", FileMode.IN)
    assert error.value.code == NO_SUCH_FILE


def testNothingIsDeletedWhileSomeoneElseHasItOpen():
    system, makeUser = setUp()
    owner, files = system.users[0], system.files
    reader = files.openFile(makeUser("OTHER"), "DATA", FileMode.IN, "OWNER")
    files.closeFile(files.openFile(owner, "DATA", FileMode.IN), release=True)
    assert files.fileNames("OWNER") == ["DATA"]
    assert reader.isOpen


def testAnotherAccountsFileIsntDeletedWithoutPrivilege():
    system, makeUser = setUp()
    files = system.files
    files.closeFile(files.openFile(makeUser("OTHER"), "DATA", FileMode.IN, "OWNER"),
                    release=True)
    assert files.fileNames("OWNER") == ["DATA"]
    files.closeFile(files.openFile(makeUser("OPS", privilege=0xC0), "DATA", FileMode.IN,
                                   "OWNER"), release=True)
    assert files.fileNames("OWNER") == []


def testReleasingANewFileDiscardsItAndKeepsTheOldOne():
    system, makeUser = setUp()
    owner, files = system.users[0], system.files
    handle = files.openFile(owner, "DATA", FileMode.OUT)
    files.writeRecord(handle, "replacement")
    files.closeFile(handle, release=True)
    old = files.openFile(owner, "DATA", FileMode.IN)
    assert files.readRecord(old) is None         # the old, empty file is still there


def testAProgramDeletesAFile():
    def deleter():
        out = yield Open("TEMP", FileMode.OUT)
        yield WriteRecord(out, "scratch")
        yield Close(out)
        again = yield Open("TEMP", FileMode.IN)
        yield Close(again, release=True)

    system = System()
    system.startUser("deleter", deleter(), priority=0xF8)
    system.run()
    assert system.files.fileNames("GUEST") == []
    assert any(entry.what == "deletes TEMP" for entry in system.trace)
