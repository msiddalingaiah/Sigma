"""On-line users: stand-ins for the LOGON and TEL processors (docs/online.md).

NOT a translation of LOGON.txt or TEL.txt: small programs that play their parts, as
the user's command processor (UB:ACP), with the same CALs any program uses: M:TYPE
and M:READ on M:UC (COC, coc.py), M:PC for the prompt, M:TIME, and CAL1,9 to end.

The step code's part is translated as hooks on the step's end (T:EXIT, T:ERROR,
T:ABORT and CALBAD's T:ABORTM):
- STEP041 (STPNR.txt:1783-1796): the step ends with LOGON the command processor and
  the user logged on: SWITCH TO TEL;
- the step ends with TEL in control: TEL has the terminal again;
- STEP10 (STPNR.txt:1828-1830): the processor is still LOGON (OFF, or no log-on): the
  user is removed, T:DELUS.
"""

import os
import re

from . import assign, fetch, hostfiles, interp, labtape, pyprog
from .cal import M_UC, P_ABN, P_BTD, P_BUF, P_ERR, P_SIZE, Fpt, keyed, random
from .files import EBCDIC, FileError
from .monitor import NotTranslated
from .sched import TIC, Cal1

BUF, SIZE = 0xB400, 80                 # the command processors' input buffer
COPYDCB, FBUF, FSIZE = 0x9F00, 0xA800, 2048   # COPY's file DCB and record buffer
FID = r"([A-Z0-9:]{1,31})(?:\.([A-Z0-9:]{1,8}))?"      # NAME[.ACCOUNT]
EXIT = 1                               # CAL1,9 exit type: M:EXIT
TRIES = 3
STEP_HOOKS = ("T:EXIT", "T:ERROR", "T:ABORT", "T:ABORTM")


def _type(cal, u, text, nl=True):
    """M:TYPE: on-line, it goes to M:UC."""
    yield from pyprog._type(cal, u, text, nl)


def _read(cal, u, size=SIZE):
    """M:READ on M:UC: the next line typed (COCIO). Returns the text."""
    yield Cal1(1, Fpt(0x10, word0=M_UC, presence=P_BUF | P_SIZE | P_BTD,
                      params=[BUF, size, 0]))             # BTD 0, whatever M:UC holds
    return cal.read_text(u, BUF, 0, cal.dcb_at(u, M_UC).ars)


def _prompt(c):
    """M:PC: the prompt character, JB:PROMPT (0: none)."""
    yield Cal1(1, Fpt(0x2C, word0=c.encode(EBCDIC)[0] if c else 0))


def _time(cal, u):
    """M:TIME: 'HH:MM MON DD,'YY'."""
    yield Cal1(8, Fpt(0x10, word0=pyprog.Cpv.MSG))
    return cal.read_text(u, pyprog.Cpv.MSG, 0, 16)


def _routine(result):
    """A CAL that ended at its error or abnormal routine: ('ROUTINE', address, SR3)."""
    return isinstance(result, tuple) and result and result[0] == "ROUTINE"


def _code(result):
    return result[2] >> 24                             # SR3: the code in byte 0


def _printable(data):
    """A record as text: EBCDIC, as all text is; anything unprintable is '.'."""
    return "".join(c if 0x20 <= ord(c) < 0x7F else "." for c in data.decode(EBCDIC))


def bin2bcd(n):
    """BIN2BCD  UTILITY.txt:82 - the low 8 decimal digits, right-justified, blank-filled."""
    return f"{n % 100_000_000:8d}"


def edit_number(recnum, key):
    """WRITE3's prefix for a 3-byte key (RDWRT.txt:345-:370): SEQNUM, the record number
    (6 columns: BTD 2 skips two of BIN2BCD's 8), then LINENO, ' - ' and the key as
    XXXX.XXX (the last 7 of BIN2BCD's digits; the units and fraction digits
    zero-filled), then a blank. Key 1000, record 1: '     1 -    1.000 '."""
    d = bin2bcd(int.from_bytes(key, "big"))[1:]       # SLD,R2 8: seven digits
    lineno = " - " + d[:3] + (d[3].strip() or "0") + "." + d[4:].replace(" ", "0") + " "
    return bin2bcd(recnum)[2:] + lineno


def unprint(key):
    """UNPRINT  UTILITY.txt - a key as it prints: itself, or X'hex' if any of it isn't
    printable (CCTAB: here, an EBCDIC character outside ASCII's graphics)."""
    chars = key.decode(EBCDIC)
    if all(0x20 <= ord(c) < 0x7F for c in chars):
        return chars
    return "X'" + key.hex().upper() + "'"


def hexdump(recnum, key, data):
    """HEXDUMP  HEXDUMP.txt - one record dumped for a terminal, as lines: a blank line,
    the key (or record number) and the size, a blank line, then 4 words a line with
    the word offset (:177-:188); the character column is for the printer only (PRNT1).
    A line equal to the one before is left out, and the next line printed gets '*' in
    column 5 (DUMP4). A null record, or one of zeros, gets a message instead."""
    size = len(data)
    if key is not None:                                # :100-:126
        k = unprint(key)
        line = list(("KEY= " + k).ljust(84))
        w = (len(k) + 12) // 4                         # R5: the size's word
        span = w * 4 + 14
        if size == 0:                                  # NULLREC
            return [" ", "".join(line[:len(k) + 5]), "THIS KEYED RECORD IS NULL"]
    else:                                              # PRTREC#: '  REC #' at BTD 2
        line = list("  REC # " + bin2bcd(recnum)[4:] + " " * 76)
        w, span = 4, 28
    line[(w - 1) * 4:(w + 3) * 4] = "  - " + bin2bcd(size) + " BYTES  "   # RECSIZE
    head = "".join(line[:span] if key is not None else line[2:2 + span])
    out = [" ", head]
    if size == 0:
        return out
    out.append(" ")
    words = [int.from_bytes(data[i:i + 4].ljust(4, b"\0"), "big") for i in range(0, size, 4)]
    if not any(words):
        return out + ["THIS RECORD CONTAINS ALL ZEROES"]           # ZERORTRN
    star, i = False, 0
    while i < len(words):
        if 0 < i and i + 4 < len(words) and words[i:i + 4] == words[i - 4:i]:
            star, i = True, i + 4                      # DUMP4: the same as the line before
            continue
        text = list(f"{i:08X}"[3:] + "   ")          # HEX2BCD, SLD 24: five digits
        if star:
            text[5] = "*"
        for j, word in enumerate(words[i:i + 4]):
            text += [" "] * (9 + 11 * j - len(text)) + list(f"{word:08X}")
        if i + 4 >= len(words) and size % 4:           # a partial last word
            text = text[:len(text) - (8 - 2 * (size % 4))]
        out.append("".join(text).rstrip())
        star, i = False, i + 4
    return out


def _exit():
    yield Cal1(9, address=EXIT, regs={6: 0})


class Online:
    """The command processors for a scheduler's on-line users."""

    def __init__(self, sched):
        self.s = sched
        self.acp = {}                  # UB:ACP per user: "LOGON" or "TEL"
        self.logged = {}               # the user has logged on
        self.accounts = {}             # the account the user logged on with
        self.tapes = {}                # reel -> labtape.Tape, mounted for TAPE (not CP-V)
        self.share = None              # the host folder for IMPORT and EXPORT (not CP-V)
        cal = sched.cal
        self.prev = {name: cal.hooks.get(name) for name in STEP_HOOKS}
        for name in STEP_HOOKS:
            cal.hooks[name] = self._step(name)
        sched.on_logon = self._new_user
        cal.hooks["LDTRC"] = self._ldtrc
        sched.hooks["T:TELDELCCI"] = self._teldelcci
        sched.hooks["BREAK"] = self._break
        sched.hooks["NOT TRANSLATED"] = self._not_translated

    def online(self, u):
        return u in self.acp and u in self.s.LB_UN

    def _new_user(self, s, u, line):
        """LOGON (SCHED.txt:1869) has tied the user to the line: LOGON is UB:ACP."""
        self.acp[u], self.logged[u] = "LOGON", False
        self.accounts.pop(u, None)
        s.cal.prompt.pop(u, None)
        s.cal.account[u], s.cal.priv[u] = ":SYS", 0
        s.cal.running.pop(u, None)
        s.programs[u] = self.logon(u)

    def _start(self, u, program):
        """The user's stack replaced by a command processor (what the step code's
        load of the processor amounts to here)."""
        s = self.s
        s.cal.account[u] = self.accounts.get(u, ":SYS")   # (a program ran in its own)
        for gen in reversed(s.stacks.pop(u, None) or []):
            try:
                gen.close()                            # e.g. a Python program's thread stops
            except ValueError:
                pass
        s.stacks[u] = [program]
        s.programs[u] = program
        s._send.pop(u, None)                           # nothing pending for the old program
        s.UH_FLG[u] |= TIC                             # ISTEL: the command processor in control
        return ("RUN", u)

    def _step(self, name):
        def hook(cal, u, *args):
            """The step's end for an on-line user: STEP041, TEL again, or STEP10."""
            if not self.online(u):
                prev = self.prev[name]
                return prev(cal, u, *args) if prev is not None else cal.s.t_delus(u)
            cal.running.pop(u, None)
            if self.acp[u] == "LOGON" and not self.logged[u]:
                cal.trace(f"STEP10 user {u}: still LOGON, T:DELUS")
                return cal.s.t_delus(u)
            if self.acp[u] == "LOGON":
                cal.trace(f"STEP041 user {u}: SWITCH TO TEL")
                self.acp[u] = "TEL"
            return self._start(u, self.tel(u))
        return hook

    def _teldelcci(self, s, u):
        """T:TELDELCCI  STPNR.txt:553 - the step's end with the run status set (an I/O
        error with no error routine, an X key-in): for an on-line user, the same step end
        as an abort, so TEL has the terminal again. Others: the scheduler's default."""
        if not self.online(u):
            return s.t_delus(u)
        s.cal.trace(f"T:TELDELCCI user {u}: the step ends, TEL again")
        s.cal._close_all(u)                            # CLOSEDCBS
        return self._step("T:ABORTM")(s.cal, u)

    def _ldtrc(self, cal, u, name, account, password):
        """T:ASP after M:LDTRC (LNKTRC.txt L10LNK, :738-:796): the named processor in the
        program's place. A shared processor is found in P:NAME: here the stand-ins, LOGON
        and TEL. LOGON for a user logged on is the log-off, as TEL's OFF (STEP10,
        STPNR.txt:1828-:1830: T:DELUS). TEL is TEL again. Any other name is a program run
        in place, through FETCH, from its account (else the user's, else :SYS)."""
        if not self.online(u):
            raise NotTranslated(f"M:LDTRC {name}.{account}: T:ASP for a batch or ghost user")
        cal.running.pop(u, None)
        if name == "LOGON":
            cal.trace(f"T:ASP user {u}: LOGON, the log-off (STEP10, T:DELUS)")
            self.acp[u], self.logged[u] = "LOGON", False
            return cal.s.t_delus(u)
        if name == "TEL":
            return self._start(u, self.tel(u))
        found = self.find(u, name, account) or self.find(u, name) or account
        cal.trace(f"T:ASP user {u}: {name}.{found}")
        result = self._start(u, pyprog.program(self.s, u, name, found))
        self.s.UH_FLG[u] &= ~TIC                       # a program, not TEL, in control
        return result

    def _not_translated(self, s, u):
        """An on-line user's program reached code that isn't translated: say so on the
        terminal (straight to COC: the CAL in progress can't go on) and give the
        terminal back to TEL. Not CP-V: there, everything is translated."""
        e = s.not_translated.pop(u, None)
        line = s.coc.line_of(u) if s.coc is not None else None
        if line is not None:
            col = s.coc.lines[line].col
            s.coc.write(line, f"NOT TRANSLATED: {e}"[:140], before=1 if col else 0, after=True)
        if not self.online(u):
            return s.t_delus(u)
        s.cal.running.pop(u, None)
        return self._start(u, self.tel(u) if self.logged[u] else self.logon(u))

    def _break(self, s, u):
        """A BREAK or Ctrl-Y: with TEL in control, TEL gets the terminal back (the
        program ends; CP-V's TEL could CONTINUE it). During LOGON, LOGON starts over."""
        if not self.online(u):
            return ("RUN", u)
        s.trace(f"BREAK user {u}: to {self.acp[u]}")
        s.cal.running.pop(u, None)
        return self._start(u, self.tel(u) if self.logged[u] else self.logon(u))

    # --- LOGON  LOGON.txt:318-407 ------------------------------------------------------

    def logon(self, u):
        cal = self.s.cal
        yield from _prompt("")
        yield from _type(cal, u, "XEROX CP-V AT YOUR SERVICE")       # :331-:353
        yield from _type(cal, u, "ON AT " + (yield from _time(cal, u)))
        for _ in range(TRIES):
            yield from _type(cal, u, "LOGON PLEASE: ", nl=False)
            reply = (yield from _read(cal, u)).strip().upper()
            parts = [p.strip() for p in reply.split(",")]
            if len(parts) < 2 or not parts[1] or len(parts[1]) > 12:
                yield from _type(cal, u, "ID?")
                continue
            account = parts[0]
            if not re.fullmatch(r"[A-Z0-9:]{1,8}", account):
                yield from _type(cal, u, "ACCOUNT?")
                continue
            # :USERS isn't modeled: any account, privilege 0, the password ignored
            cal.account[u], cal.priv[u] = account, 0
            cal.uname[u] = parts[1]
            self.accounts[u] = account
            if cal.fs is not None:
                cal.fs.add_account(account)
            self.logged[u] = True
            cal.trace(f"LOGON user {u}: {account},{parts[1]}")
            yield from _exit()                         # the step ends: STEP041
            return
        yield from _type(cal, u, "SORRY, UNABLE TO LOG YOU ON")
        yield from _exit()                             # still LOGON: STEP10

    # --- TEL ---------------------------------------------------------------------------

    def tel(self, u):
        cal = self.s.cal
        yield from _prompt("!")
        while True:
            typed = (yield from _read(cal, u)).strip()
            command = typed.upper()
            verb, _, rest = command.partition(" ")
            rest = rest.strip()
            if not verb:
                continue
            if verb == "OFF" and not rest:
                self.acp[u], self.logged[u] = "LOGON", False
                yield from _exit()                     # to LOGON, which ends: STEP10
                return
            if verb in ("L", "LIST"):                  # PCL LIST (L); LIST: a stand-in alias
                yield from self.list(u, rest)
                continue
            if verb in ("COPY", "C") and rest:         # PCL  TEL.txt:3889, :4567
                yield from self.copy(u, rest)
                continue
            if verb == "TAPE":                         # not CP-V: the mounted tapes (--mount)
                yield from self.tape(u, rest)
                continue
            if verb in ("IMPORT", "EXPORT"):           # not CP-V: the shared folder (--share)
                args = typed.strip()[len(verb):].strip()   # host names keep their case
                yield from (self.import_ if verb == "IMPORT" else self.export)(u, args)
                continue
            target = rest.split()[0] if verb in ("RUN", "START") and rest else verb
            fid = re.fullmatch(FID, target)     # a name and more: the more is the
            if fid is None:                     # program's, in J:CCBUF (CHKULM, TEL.txt:950)
                yield from _type(cal, u, "EH?")        # EHMSG  TEL.txt:3879
                continue
            name, account = fid.groups()
            account = self.find(u, name, account)
            if account is None:
                yield from _type(cal, u, "EH?" if verb not in ("RUN", "START")
                                 else f"{name} NOT FOUND")
                continue
            logon = self.accounts.get(u, ":SYS")
            given = False
            if verb not in ("RUN", "START") and rest:  # PARSER  TEL.txt:609: the rest
                message, given = assign.parse(cal, u, rest, logon)
                if message:
                    yield from _type(cal, u, message)  # ONERR: the command is dropped
                    continue
            assign.step(cal, u, given, logon)          # GROUP2C  :483-:510
            yield from _prompt("")                     # the program's own reads
            cal.trace(f"TEL user {u}: run {name}.{account}")
            cal.ccbuf[u] = typed                       # TELCCBUF: the line, into J:CCBUF
            self.s.UH_FLG[u] &= ~TIC                   # STEP04C: DRTEL1, TEL no longer in control
            yield from pyprog.program(self.s, u, name, account)
            return                                     # (it ends with a CAL1,9: the step)

    # --- TAPE: not CP-V ----------------------------------------------------------------

    def mount(self, tape):
        """A labeled tape (labtape.Tape) the TAPE command can list and copy from. The
        operator mounts it (--mount); a terminal user never names a host file."""
        self.tapes[tape.reel] = tape

    def tape(self, u, args):
        """TAPE: the mounted reels. TAPE reel: its files. TAPE reel name...: each file
        copied into the user's own account (labtape.restore; an existing one replaced),
        where TEL finds a program before :SYS. NOT CP-V (there, PCL or FRES copy a tape):
        a stand-in, in place of tape drives and the labeled-tape OPEN."""
        cal = self.s.cal
        words = args.split()
        if not words:
            if not self.tapes:
                yield from _type(cal, u, "NO TAPES MOUNTED")
            for reel, t in self.tapes.items():
                yield from _type(cal, u, f"{reel:<8}{t.account:<10}{len(t.files)} FILES")
            return
        tape = self.tapes.get(words[0])
        if tape is None:
            yield from _type(cal, u, f"NO TAPE {words[0]} MOUNTED")
            return
        if len(words) == 1:
            for f in tape.files:
                yield from _type(cal, u, f"{f.name:<12}{len(f.records):>6} RECORDS")
            return
        account = cal.account.get(u, ":SYS")
        for name in words[1:]:
            f = next((f for f in tape.files if f.name == name), None)
            if f is None:
                yield from _type(cal, u, f"NO FILE {name} ON {tape.reel}")
                continue
            try:
                labtape.restore(cal.fs, labtape.Tape(tape.reel, account, [f]), account=account)
            except (FileError, ValueError) as e:
                yield from _type(cal, u, f"{name}: NOT COPIED ({e})"[:100])
                continue
            cal.trace(f"TAPE user {u}: {name} from {tape.reel} to {account}")
            yield from _type(cal, u, f"{name} COPIED TO {account}: {len(f.records)} RECORDS")

    # --- IMPORT and EXPORT: not CP-V (hostfiles.py) --------------------------------------

    def _own_fid(self, u, text):
        """A fid NAME[.ACCOUNT] in the user's own account: (name, account) or a message."""
        m = re.fullmatch(FID, text.upper())
        own = self.s.cal.account.get(u, ":SYS")
        if m is None:
            return None, f"{text}: NOT A FILE NAME"
        name, account = m.groups()
        if account and account != own:
            return None, "ONLY YOUR OWN ACCOUNT"
        return (name, own), None

    def import_(self, u, args):
        """IMPORT: the shared folder's files. IMPORT host [TO fid]: the host file into
        the user's account as an EDIT-style keyed file (by default named after the host
        file, its extension dropped), an old one replaced."""
        cal = self.s.cal
        words = args.split()
        try:
            if not words:
                files = hostfiles.listing(self.share)
                if not files:
                    yield from _type(cal, u, "NO HOST FILES")
                for name, size, when in files:
                    yield from _type(cal, u, f"{name:<24}{size:>8}  {when}")
                return
            if len(words) not in (1, 3) or (len(words) == 3 and words[1].upper() != "TO"):
                yield from _type(cal, u, "IMPORT host [TO fid]")
                return
            host = words[0]
            hostfiles.resolve(self.share, host)        # the host name first
            target = words[2] if len(words) == 3 else os.path.splitext(host)[0]
            fid, message = self._own_fid(u, target)
            if message:
                yield from _type(cal, u, message)
                return
            n, long = hostfiles.import_file(cal.fs, self.share, host, *fid)
        except (hostfiles.HostError, OSError, FileError) as e:
            yield from _type(cal, u, str(e)[:100] if isinstance(e, hostfiles.HostError)
                             else f"{words[0]}: NOT IMPORTED ({e})"[:100])
            return
        cal.trace(f"IMPORT user {u}: {host} to {fid[0]}.{fid[1]}, {n} records")
        yield from _type(cal, u, f"{fid[0]}: {n} RECORDS"
                         + (f", {long} LONGER THAN {hostfiles.CARD}" if long else ""))

    def export(self, u, args):
        """EXPORT fid [TO host]: a file of the user's account into the shared folder, a
        line a record (by default named FID.txt), an old one replaced."""
        cal = self.s.cal
        words = args.split()
        if len(words) not in (1, 3) or (len(words) == 3 and words[1].upper() != "TO"):
            yield from _type(cal, u, "EXPORT fid [TO host]")
            return
        fid, message = self._own_fid(u, words[0])
        if message:
            yield from _type(cal, u, message)
            return
        host = words[2] if len(words) == 3 else fid[0] + ".txt"
        try:
            n = hostfiles.export_file(cal.fs, self.share, *fid, host)
        except (hostfiles.HostError, OSError) as e:
            yield from _type(cal, u, str(e)[:100] if isinstance(e, hostfiles.HostError)
                             else f"{host}: NOT EXPORTED ({e})"[:100])
            return
        cal.trace(f"EXPORT user {u}: {fid[0]}.{fid[1]} to {host}, {n} records")
        yield from _type(cal, u, f"{host}: {n} RECORDS")

    def find(self, u, name, account=None):
        """The program's account: the one given, else the user's own, else :SYS."""
        fs = self.s.cal.fs
        accounts = (account,) if account else (self.s.cal.account.get(u, ":SYS"), ":SYS")
        for account in dict.fromkeys(accounts):
            if fetch.is_load_module(fs, name, account):
                return account
            try:
                pyprog.read_source(fs, name, account)
                return account
            except (FileError, UnicodeDecodeError, AttributeError):
                continue
        return None

    def copy(self, u, args):
        """PCL's COPY, the part for a terminal: COPY fid [TO ME[(opts)] | OVER ME[(opts)]],
        the options K and X. With no output on-line, the output is ME (COPYTO.txt:
        140-143). The file is read through M:OPEN, M:READ to the end and M:CLOSE; each
        line goes to M:UC with M:WRITE. With K, a record with a 3-byte key gets its
        record number and EDIT line number in front (RDWRT.txt WRITE3, :338-:370).
        With X, each record is dumped in hex, its key or record number first
        (HEXDUMP.txt; RDWRT.txt READ20 :1077, which takes X before K)."""
        cal = self.s.cal
        m = re.fullmatch(r"([A-Z0-9:]{1,31})(?:\.([A-Z0-9:]{1,8}))?"
                         r"(?:\s+(TO|OVER)\s+([^\s(]+)(?:\(([A-Z,]+)\))?)?", args)
        options = set((m.group(5) or "").split(",")) - {""} if m else set()
        if m is None or options - {"K", "X"}:
            yield from _type(cal, u, "COPY: SYNTAX ERROR")
            return
        name, account, _, dest, _ = m.groups()
        if dest is not None and dest != "ME":
            yield from _type(cal, u, f"COPY: ONLY TO ME, NOT {dest}")
            return
        cal.add_dcb(u, "F:COPY", COPYDCB, asn=1, fname=name, account=account or "",
                    fun="IN", keym=11, org=0x20)
        err = pyprog.Cpv.ERRR, pyprog.Cpv.ABNR
        result = yield Cal1(1, Fpt(0x14, word0=COPYDCB, presence=P_ERR | P_ABN, params=list(err)))
        if _routine(result):
            yield from _type(cal, u, f"COPY: CAN'T OPEN {args.split()[0]}: CODE"
                                     f" {_code(result):02X}")
            return
        if random(cal.dcb_at(u, COPYDCB)):
            yield from _type(cal, u, "COPY: A RANDOM FILE")
        else:
            recnum = 0
            while True:
                result = yield Cal1(1, Fpt(0x10, word0=COPYDCB,
                                           presence=P_ERR | P_ABN | P_BUF | P_SIZE,
                                           params=[*err, FBUF, FSIZE]))
                if _routine(result):
                    if _code(result) != 0x06:          # not the end of the file
                        yield from _type(cal, u, f"COPY: READ ERROR, CODE {_code(result):02X}")
                    break
                recnum += 1                            # READ27: MTW,1 RECNUM
                dcb = cal.dcb_at(u, COPYDCB)
                data = cal.read_bytes(u, FBUF, 0, min(dcb.ars, FSIZE))
                key = dcb.kbuf if keyed(dcb) else None
                if "X" in options:
                    lines = hexdump(recnum, key, data)
                else:
                    text = _printable(data)
                    if "K" in options and key is not None and len(key) == 3:
                        text = edit_number(recnum, key) + text
                    lines = [text]
                for text in lines:
                    text += "\x85"                     # its NL: M:UC adds none (COCWR80)
                    cal.put_text(u, FBUF, text)
                    yield Cal1(1, Fpt(0x11, word0=M_UC, presence=P_BUF | P_SIZE | P_BTD,
                                      params=[FBUF, len(text), 0]))
        yield Cal1(1, Fpt(0x15, word0=COPYDCB))         # M:CLOSE

    def list(self, u, args=""):
        """PCL's LIST: L [fid][(A)]. The fid is NAME, NAME.ACCOUNT or .ACCOUNT (COPYTRAN's
        file id forms N, N.A and A, COPYTRAN.txt:37); none is the user's own account.
        With (A), the attributes: the heading LISTHEAD (PCLLIST.txt:1113), then per file
        its organization, K, C or R (:521-:525), and its record count (PRECORD, :558).
        The granules and the date aren't shown, and the columns follow the heading."""
        cal = self.s.cal
        m = re.fullmatch(r"([A-Z0-9:]{1,31})?(?:\.([A-Z0-9:]{1,8}))?(\(A\))?", args.replace(" ", ""))
        if m is None:
            yield from _type(cal, u, "L: SYNTAX ERROR")
            return
        name, account, attributes = m.groups()
        account = account or cal.account.get(u, ":SYS")
        try:
            names = cal.fs.files(account)
        except FileError:
            names = []
        if name is not None:
            names = [n for n in names if n == name]
        if not names:
            yield from _type(cal, u, "NO FILES IN DIRECTORY")   # PCLLIST.txt:677
            return
        if attributes:
            yield from _type(cal, u, "ORG    GRAN     REC     DATE    NAME")
        for n in names:
            if not attributes:
                yield from _type(cal, u, n)
                continue
            org, recs = self._attributes(n, account)
            yield from _type(cal, u, f"{org:<7}{'':<9}{recs:<8}{'':<8}{n}")

    def _attributes(self, name, account):
        """A file's organization letter and record count (host-side, as LIST's own read)."""
        from .files import ConsecutiveFile, RandomFile
        fs = self.s.cal.fs
        cfu = fs.open(name, account, "IN")
        try:
            f = cfu.file
            if isinstance(f, RandomFile):
                return "R", ""
            if isinstance(f, ConsecutiveFile):
                return "C", str(len(f.records()))
            return "K", str(len(f.keys()))
        finally:
            fs.close(cfu)
