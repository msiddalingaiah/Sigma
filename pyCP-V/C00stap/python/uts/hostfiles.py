"""IMPORT and EXPORT: text files between a host folder and the file system
(docs/online.md). NOT CP-V: a convenience for editing source on the host.

The operator names one folder (--share DIR). A terminal user names only files in it:
a bare name, no drive, path or '..', resolved inside the folder and refused if it
would land outside. Without --share the commands answer that nothing is shared.

Text is ASCII (UTF-8) on the host, EBCDIC in the file system. IMPORT makes an
EDIT-style keyed file (keys 1.000, 2.000, ...: pyprog.line_key), so EDIT and AP both
read it; tabs go to the assembler's columns (10, 19, then every 8). EXPORT writes a
keyed or consecutive file's records in order, a line each, trailing blanks dropped.
"""

import datetime
import os
import re

from .files import EBCDIC, ConsecutiveFile, FileError, RandomFile
from .pyprog import line_key

HOST_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
TABS = (9, 18)                          # 0-based: the opcode (column 10), the operand (19)
CARD = 80


class HostError(Exception):
    """A message for the terminal."""


def resolve(share, name):
    """The host path of ``name`` in the shared folder, or HostError."""
    if share is None:
        raise HostError("NO HOST FOLDER SHARED")
    if not HOST_NAME.match(name) or ".." in name:
        raise HostError(f"{name}: NOT A HOST FILE NAME")
    root = os.path.realpath(share)
    path = os.path.realpath(os.path.join(root, name))
    if os.path.dirname(path) != root:
        raise HostError(f"{name}: NOT IN THE SHARED FOLDER")
    return path


def listing(share):
    """The shared folder's files: (name, size, modified)."""
    if share is None:
        raise HostError("NO HOST FOLDER SHARED")
    out = []
    for entry in sorted(os.scandir(share), key=lambda e: e.name.upper()):
        if entry.is_file() and HOST_NAME.match(entry.name):
            st = entry.stat()
            when = datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            out.append((entry.name, st.st_size, when))
    return out


def expand_tabs(line):
    """A tab to the next assembler column: 10, then 19, then every 8."""
    out = ""
    for c in line:
        if c != "\t":
            out += c
            continue
        n = len(out)
        stop = next((t for t in TABS if t > n), None)
        if stop is None:
            stop = TABS[-1] + ((n - TABS[-1]) // 8 + 1) * 8
        out += " " * (stop - n)
    return out


def read_host(path):
    """The host file's lines: UTF-8 (a BOM dropped), else Latin-1; tabs expanded."""
    with open(path, "rb") as f:
        data = f.read()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return [expand_tabs(line) for line in text.splitlines()]


def import_file(fs, share, host_name, name, account):
    """IMPORT: the host file into NAME.ACCOUNT as an EDIT-style keyed file, an old file
    of that name replaced. Returns (records, lines longer than a card)."""
    lines = read_host(resolve(share, host_name))
    records = []
    for i, line in enumerate(lines, 1):
        try:
            records.append(line.encode(EBCDIC))
        except UnicodeEncodeError:
            raise HostError(f"LINE {i}: A CHARACTER WITH NO EBCDIC CODE")
    fs.add_account(account)
    try:                                               # an old file goes first
        fs.close(fs.open(name, account, "IN"), release=True)
    except FileError:
        pass
    cfu = fs.open(name, account, "OUT", keym=3)
    try:
        for i, record in enumerate(records, 1):
            cfu.file.write(line_key(i), record)
    finally:
        fs.close(cfu)
    return len(records), sum(1 for r in records if len(r) > CARD)


def export_file(fs, share, name, account, host_name):
    """EXPORT: NAME.ACCOUNT's records into the host file, a line each. Returns the
    number of records."""
    path = resolve(share, host_name)
    try:
        cfu = fs.open(name, account, "IN")
    except FileError:
        raise HostError(f"{name}: NO SUCH FILE")
    try:
        f = cfu.file
        if isinstance(f, RandomFile):
            raise HostError(f"{name}: A RANDOM FILE")
        if isinstance(f, ConsecutiveFile):
            records = f.records()
        else:                                          # keyed: in key order
            records, after = [], None
            while (nxt := f.read_next(after)) is not None:
                after = nxt[0]
                records.append(nxt[1])
    finally:
        fs.close(cfu)
    with open(path, "w", encoding="utf-8", newline="\r\n") as out:
        for record in records:
            out.write(bytes(record).decode(EBCDIC).rstrip(" ") + "\n")
    return len(records)
