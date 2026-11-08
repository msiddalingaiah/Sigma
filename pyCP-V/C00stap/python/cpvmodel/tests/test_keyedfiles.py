"""Index chains, keyed files with their pyramid, and directories on index chains."""

import random

import pytest

from cpvmodel import FileError, FileMode, FileSystemSettings, Organization, Program, System
from cpvmodel.filesystem import (FILE_ENTRY, KEY_NOT_FOUND, NO_KEY, Directory, Disc,
                                 IndexChain, KeyedFile)


from .scripts import Script, fileDcb, openFile


def keys(count, prefix="K"):
    return [f"{prefix}{n:05d}" for n in range(count)]


def newChain(spare=102):
    return IndexChain(Disc(2000), entrySize=25, spare=spare, headerInFirstBlock=True)


def keyedFile(system, user, name, records, keyLength=11):
    files = system.files
    dcb = openFile(files, user, name, FileMode.OUT, organization=Organization.KEYED)
    for key, text in records:
        files.write(user, dcb, text, key)
    files.close(user, dcb)
    return files.lookUp(user.account, name)[0]


# --- The index chain ------------------------------------------------------------------------

def testEntriesStayInKeyOrderWhateverTheInsertOrder():
    chain = newChain()
    shuffled = keys(2000)
    random.Random(7).shuffle(shuffled)
    for key in shuffled:
        chain.insert(key, key.lower())
    assert [key for key, _ in chain.items()] == keys(2000)
    assert all(chain.search(key)[0] == key.lower() for key in shuffled)


def testAFullBlockChainsANewOneAndCountsASlide():
    chain = newChain()
    for key in keys(200):
        chain.insert(key, key)
    assert len(chain.blocks) > 1
    assert chain.slides == len(chain.blocks) - 1


def testTheFirstBlockHasLessRoomBecauseTheHeaderIsThere():
    chain = newChain(spare=0)
    for key in keys(500):
        chain.insert(key, key)
    first, second = chain.blocks[0], chain.blocks[1]
    assert len(first.keys) < len(second.keys)


def testWithoutAPyramidASearchWalksTheChain():
    chain = newChain()
    for key in keys(1000):
        chain.insert(key, key)
    _, nearStart = chain.search("K00000")
    _, nearEnd = chain.search("K00999")
    assert nearStart == 1
    assert nearEnd == len(chain.blocks)


def testAPyramidMakesEverySearchShort():
    chain = newChain()
    for key in keys(3000):
        chain.insert(key, key)
    chain.buildPyramid(keyLength=11)
    assert chain.slides == 0
    accesses = {chain.search(key)[1] for key in keys(3000)}
    assert max(accesses) <= len(chain.pyramid.levels) + 2
    assert chain.search("NOT THERE")[0] is None


def testABlockThePyramidPointsAtKeepsItsFirstKey():
    chain = newChain()
    for key in keys(300, "B"):
        chain.insert(key, key)
    chain.buildPyramid(keyLength=11)
    second = chain.blocks[1]
    firstKey = second.keys[0]
    before = chain.blocks[0].keys[-1]
    newKey = before + "X"                       # sorts between the two blocks
    assert before < newKey < firstKey
    chain.insert(newKey, "new")
    assert second.keys[0] == firstKey
    assert chain.search(newKey)[0] == "new"


# --- Keyed files ----------------------------------------------------------------------------

def testRecordsAreFoundByKeyAndReadInKeyOrder():
    system = System()
    user = system.startUser("u", Script(), priority=0xF8)
    keyedFile(system, user, "PHONE", [("SMITH", "555-1234"), ("ADAMS", "555-9876"),
                                      ("JONES", "555-4444")])
    files = system.files
    handle = openFile(files, user, "PHONE")
    assert files.read(user, handle, "JONES") == "555-4444"
    ordered = openFile(files, user, "PHONE")
    assert [files.read(user, ordered) for _ in range(4)] == ["555-9876", "555-4444",
                                                             "555-1234", None]


def testAMissingKeyIsAnError():
    system = System()
    user = system.startUser("u", Script(), priority=0xF8)
    keyedFile(system, user, "F", [("A", "1")])
    handle = openFile(system.files, user, "F")
    with pytest.raises(FileError) as error:
        system.files.read(user, handle, "B")
    assert error.value.code == KEY_NOT_FOUND


def testAKeyedWriteNeedsAKey():
    system = System()
    user = system.startUser("u", Script(), priority=0xF8)
    handle = openFile(system.files, user, "F", FileMode.OUT, organization=Organization.KEYED)
    with pytest.raises(FileError) as error:
        system.files.write(user, handle, "no key")
    assert error.value.code == NO_KEY


def testWritingAKeyAgainReplacesTheRecord():
    system = System()
    user = system.startUser("u", Script(), priority=0xF8)
    file = keyedFile(system, user, "F", [("A", "first"), ("A", "second")])
    assert file.read("A")[0] == "second"


def testALongRecordSpansDataGranules():
    system = System()
    user = system.startUser("u", Script(), priority=0xF8)
    file = keyedFile(system, user, "F", [("BIG", "Y" * 5000)])
    text, accesses = file.read("BIG")
    assert text == "Y" * 5000
    assert accesses == 1 + 3                     # the index block, three data granules


def testThePyramidIsBuiltAtCloseOnlyPastTheSlideLimit():
    records = [(key, key) for key in keys(1000)]
    loose = System(fileSettings=FileSystemSettings(rebuildAfterSlides=254))
    user = loose.startUser("u", Script(), priority=0xF8)
    assert keyedFile(loose, user, "F", records).index.pyramid is None
    eager = System(fileSettings=FileSystemSettings(rebuildAfterSlides=4))
    user = eager.startUser("u", Script(), priority=0xF8)
    file = keyedFile(eager, user, "F", records)
    assert file.index.pyramid is not None
    assert file.read("K00999")[1] < loose.files.lookUp("GUEST", "F")[0].read("K00999")[1]


def testReplacingAKeyedFileReleasesAllItsGranules():
    system = System()
    user = system.startUser("u", Script(), priority=0xF8)
    before = system.files.disc.freeCount()
    records = [(key, "X" * 100) for key in keys(400)]
    keyedFile(system, user, "F", records)
    keyedFile(system, user, "F", [("ONLY", "1")])
    # the second file: its index granule and one data granule; and the account's file
    # directory (the account directory was there from the start)
    assert system.files.disc.freeCount() == before - 2 - 1


def testAProgramUsesAKeyedFile():
    class PhoneBook(Program):
        def __init__(self):
            self.book = fileDcb("PHONE", organization=Organization.KEYED)
            self.found = None

        def run(self, m):
            m.open(self.book, mode=FileMode.OUT)
            m.write(self.book, "555-1234", key="SMITH")
            m.write(self.book, "555-9876", key="ADAMS")
            m.close(self.book)
            m.open(self.book, mode=FileMode.IN)
            self.found = m.read(self.book, key="ADAMS")
            m.close(self.book)

    system = System()
    phoneBook = PhoneBook()
    system.startUser("u", phoneBook, priority=0xF8)
    assert system.run() == "shutdown"
    assert phoneBook.found == "555-9876"


# --- Directories ----------------------------------------------------------------------------

def testABigDirectoryTakesLongerToSearch():
    directory = Directory(Disc(100), FILE_ENTRY)
    for name in keys(300, "FILE"):
        directory.insert(name, name)
    assert len(directory.blocks) > 3
    assert directory.search("FILE00000")[1] == 1
    assert directory.search("FILE00299")[1] == len(directory.blocks)


def testOpeningAFileInABigAccountCostsMoreDiscAccesses():
    system = System(fileSettings=FileSystemSettings(discGranules=1000))
    files = system.files
    user = system.startUser("u", Script(), priority=0xF8)
    for name in keys(200, "F"):
        files.close(user, openFile(files, user, name, FileMode.OUT))
    first, last = fileDcb("F00000"), fileDcb("F00199")
    files.connect(user, first)
    files.connect(user, last)
    assert last.takeDiscAccesses() > first.takeDiscAccesses()
