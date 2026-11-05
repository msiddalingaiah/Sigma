"""CP-V labeled tapes (docs/labtape.md): read a tape image's files and restore them
into the file system.

The image is simh's .tap format (each record framed by its length, little-endian, a
zero length a tape mark). The tape is what the monitor's labeled-tape I/O writes:
the sentinels OPNL reads (:LBL, :ACN, :BOF, :EOF, OPNL.txt:102-106) and LBLT's
blocking (LBLT.txt:310-480): 2048-byte blocks of keyed records, each a key area
(the DCB's key buffer, GETKEYSB IORT.txt:1217), a size word (SVSIZ :652) and the
data; a record too long for a block goes out unblocked, as the next tape record.

NOT a translation of a CP-V utility: the restore is a host-side tool, like --file,
standing in for copying the tape to disc with PCL or FRES.
"""

from dataclasses import dataclass, field

from .files import EBCDIC, Position

BLOCK = 2048
F_FIRST, F_MORE, F_UNBLK = 0x01, 0x02, 0x04    # size word flags (SVSIZ; WRTL1 Y04)


class TapeError(Exception):
    pass


@dataclass
class TapeFile:
    name: str
    records: list = field(default_factory=list)   # [(key bytes, data bytes)]
    key_area: int = 4                             # bytes before the size word


@dataclass
class Tape:
    reel: str = ""
    account: str = ""
    files: list = field(default_factory=list)


def tape_records(data):
    """The .tap container: tape records (bytes), and None for a tape mark."""
    pos = 0
    while pos + 4 <= len(data):
        n = int.from_bytes(data[pos:pos + 4], "little")
        if n == 0:
            yield None
            pos += 4
            continue
        if n == 0xFFFFFFFF:                            # end of medium
            return
        n &= 0x7FFFFFFF                                # bit 31: a record in error
        if pos + 8 + n > len(data):
            raise TapeError(f"record at {pos} runs past the end of the image")
        yield data[pos + 4:pos + 4 + n]
        pos += 8 + n + (n & 1 if int.from_bytes(
            data[pos + 4 + n:pos + 8 + n], "little") != n else 0)


def _sentinel(r):
    return r[:4].decode(EBCDIC, "replace") if r else ""


def _pieces(trecs, area):
    """LBLT's blocks: [(key, flags, data)] with a key area of ``area`` bytes. A block
    is the word PBD (previous block size) | number of entries (INITBLK :671), then
    the entries; an unblocked record's data is the next tape record (WRTL1)."""
    out, i = [], 0
    while i < len(trecs):
        b = trecs[i]
        i += 1
        entries, p = int.from_bytes(b[2:4], "big"), 4
        for _ in range(entries):
            if p + area + 4 > len(b):
                raise TapeError("entry past the block")
            kl = b[p]
            if kl == 0 or kl + 1 > area:
                raise TapeError("key length")
            key = b[p + 1:p + 1 + kl]
            q = p + area
            word = int.from_bytes(b[q:q + 4], "big")
            flags, size = word >> 24, word & 0xFFFFFF
            if flags & F_UNBLK:
                if i >= len(trecs) or len(trecs[i]) != size:
                    raise TapeError("unblocked record size")
                data, i = trecs[i], i + 1
            else:
                data = b[q + 4:q + 4 + size]
                if len(data) != size:
                    raise TapeError("record past the block")
            p = q + 4 + ((size + 3) & ~3)
            out.append((key, flags, data))
    return out


def _records(trecs):
    """A file's logical records, its pieces joined (F_FIRST starts a record, F_MORE
    says more follows). The key area isn't on the tape: the smallest that parses."""
    last = None
    for area in range(4, 260, 4):
        try:
            pieces = _pieces(trecs, area)
        except TapeError as e:
            last = e
            continue
        records, open_ = [], False
        for key, flags, data in pieces:
            if open_ and not flags & F_FIRST and records[-1][0] == key:
                records[-1] = (key, records[-1][1] + data)
            elif flags & F_FIRST:
                records.append((key, data))
            else:
                break                                  # a piece with nothing to join
            open_ = bool(flags & F_MORE)
        else:
            if not open_:
                return records, area
    raise TapeError(f"no key area fits ({last})")


def read_tape(data):
    """A Tape from a .tap image's bytes."""
    tape, name, trecs = Tape(), None, []
    for r in tape_records(data):
        if r is None:
            continue
        s = _sentinel(r)
        if s == ":LBL":
            tape.reel = r[4:8].decode(EBCDIC).strip()
        elif s == ":ACN":
            tape.account = r[4:12].decode(EBCDIC).strip()
        elif s == ":BOF":
            name, trecs = r[9:9 + r[8]].decode(EBCDIC), []
        elif s == ":EOF":
            if name is None:
                raise TapeError(":EOF without :BOF")
            records, area = _records(trecs)
            tape.files.append(TapeFile(name, records, area))
            name = None
        elif name is not None:
            trecs.append(r)
    return tape


def sequential(records):
    """Keys 0, 1, 2, ... (3 bytes): LBLT's sequential keys for a consecutive file
    (SKEY X'03000000', WRTL12 'INCREASE SEQUENTIAL KEY')."""
    return all(k == i.to_bytes(3, "big") for i, (k, _) in enumerate(records))


def restore(fs, tape, account=None, log=None):
    """Each file into the file system, in the tape's account (or ``account``): a file
    with sequential keys as a consecutive file, any other as a keyed file. An existing
    file is replaced. Returns the names restored."""
    account = account or tape.account
    fs.add_account(account)
    names = []
    for f in tape.files:
        for old in (f.name,):
            if old in fs.files(account):
                cfu = fs.open(old, account, "OUT")
                fs.close(cfu, release=True)
        if sequential(f.records):
            cfu = fs.open(f.name, account, "OUT", org=1)
            pos = Position()
            for _, data in f.records:
                cfu.file.write(pos, data)
        else:
            cfu = fs.open(f.name, account, "OUT", keym=max(len(k) for k, _ in f.records))
            for key, data in f.records:
                cfu.file.write(key, data)
        fs.close(cfu)
        names.append(f.name)
        if log is not None:
            log.append(f"restore {f.name}.{account}: {len(f.records)} records")
    return names
