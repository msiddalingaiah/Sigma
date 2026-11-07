"""Assignments: TEL's processor command, the assign/merge record, and the step's merge
(docs/assign.md).

TEL.txt's PARSER turns ``NAME [source] [ON|OVER [object]] [,listing]`` into assign/merge
sets for M:SI, M:GO and M:LO: each an OPEN parameter list (PLIST or OPENME, TEL.txt:4024,
:4093) under the DCB's name. When the program is fetched, STPNR.txt's ASP17-ASM8 give its
M:GO the default object file and merge each set into the DCB of that name through
MSROPN (cal.step_merge); the program's own M:OPEN opens it.

The record is a Python list per user (cal.amr), not the record on disc that T:AMRDWT
reads and writes: a departure.
"""

import re

from .files import EBCDIC, FileError
from .jit import text_words

SI, GO, LO = "M:SI", "M:GO", "M:LO"
# J:OPT / JSTDOPT bits (TEL.txt LOFINS; AP's CCI.txt:192-:195)
OPT_LO, OPT_SI, OPT_GO = 0x1, 0x10, 0x80
# J:TELFLGS bits used while parsing (TEL.txt:253-:262)
F_ON, F_OVER = 0x20, 0x40
IN, OUT = 1, 2                                         # PLIST's MODE word
FID = re.compile(r"([A-Z0-9:$*_-]{1,31})(?:\.([A-Z0-9:]{0,8}))?(?:\.([A-Z0-9:]{1,8}))?$")
DEVICES = ("NO", "CP")                                 # ROMDEV: a device for M:GO
LIST_DEVICES = ("ME", "LP", "NO")                      # DOLO: one for M:LO


class Syntax(Exception):
    """A syntax error (CHKULM, TEL.txt:950): for an unrecognized load module, ignored."""


class OnError(Exception):
    """ONERR  TEL.txt:819-:836: ON names a file that exists. The message, then SYN2: the
    options as before the command, the record as it was, and the program isn't run."""


def _textc(name):
    data = name.encode(EBCDIC)
    return bytes([len(data)]) + data


def file_plist(name, account, mode, password=""):
    """PLIST  TEL.txt:4093-:4106, filled in by FILENT (:6031-:6063): OPEN in the "A" form,
    ASN 1, VLPs; FUN and FOPT present; the mode, SAVE; the name, account and password."""
    words = [0x14000000, 0x0000E001, 0x01400000, mode, 2]
    words += [0x01000303] + text_words(_textc(name), 3, fill=b"\x40")
    words += [0x02000202] + text_words(account.encode(EBCDIC), 2)
    if password:                                       # AI,R6 X'200': TURN ON PARAMETER WORD
        words += [0x03010202] + text_words(password.encode(EBCDIC), 2)
    else:
        words += [0x03010002, 0x40404040, 0x40404040]
    return words


def device_plist(label):
    """OPENME  TEL.txt:4024-:4027: OPEN in the "A" form with no VLPs, the device option
    present: the operational label, right-justified (UC for ME)."""
    label = "UC" if label == "ME" else label
    return [0x14000000, 0x0000A000, 0x00040000, int.from_bytes(label.encode(EBCDIC), "big")]


def default_name(u):
    """NAME%  TEL.txt:6075-:6081; ASM2  STPNR.txt:2630-:2636: the user number's halfword,
    then G: the default object file's name."""
    return ((u & 0xFFFF).to_bytes(2, "big") + b"\xC7").decode(EBCDIC)


def _release(record, dcb):
    """ASSIGN  TEL.txt:4783: the DCB's earlier sets go."""
    record[:] = [(n, w) for n, w in record if n != dcb]


def _fields(rest):
    """SCAN  TEL.txt:5224: the fields, each with the character that ended it (blank,
    comma, or '' at the end of the message)."""
    out = []
    for m in re.finditer(r"\s*([^\s,]+)\s*(,|$|\s)", rest):
        end = m.group(2)
        out.append((m.group(1), "," if end == "," else ""))
    return out


def parse(cal, u, rest, account):
    """PARSER  TEL.txt:609-:900 for an unrecognized load module: the sets into the user's
    record, the options into JSTDOPT. Returns (message, source given): a message means
    the command is dropped (ONERR). A syntax error only stops the parse: what was done
    stays and the program runs (CHKULM)."""
    record = cal.amr.setdefault(u, [])
    opt = cal.stdopt.get(u, 0)
    saved = (list(record), opt)                        # JRESOPT; the record on disc
    flags, phase, si_given = 0, None, False

    def fid(text):
        m = FID.match(text)
        if m is None or text.startswith("%"):
            raise Syntax(text)
        name, acct, password = m.groups()
        return name, acct or account, password or ""

    def on_check(name, acct):
        """FLOP  TEL.txt:5161: with ON, the file must be new."""
        if not flags & F_ON:
            return
        try:
            exists = name in cal.fs.files(acct)
        except FileError:
            exists = False
        if exists:
            raise OnError(f"ON FILE {name} ILLEGAL")

    try:
        for text, end in _fields(rest):
            if phase is None:                          # TOPPARSE  :611
                if text == "%":
                    raise Syntax(text)
                if text in ("ON", "OVER"):             # DOON, DOOVER  :696-:704
                    flags |= F_ON if text == "ON" else F_OVER
                    phase = "LO" if end == "," else "GO"   # EXTDGO  :811: GO implied
                    if phase == "LO":
                        opt |= OPT_GO
                    continue
                if si_given:
                    raise Syntax(text)                 # TESTSI1: MULT SI NOT ALLOWED
                _release(record, SI)
                if text == "ME":                       # DOME  :665
                    record.append((SI, device_plist("ME")))
                else:
                    name, acct, password = fid(text)
                    record.append((SI, file_plist(name, acct, IN, password)))   # MGSI
                si_given = True
                continue
            if phase == "GO":                          # OPRSE  :705
                phase = "LO"
                opt |= OPT_GO
                if text == "%":                        # %ROM
                    _release(record, GO)
                    record.append((GO, file_plist(default_name(u), account, OUT)))
                elif text == "ME":
                    raise Syntax(text)                 # ERRME, ignored: :725-:727
                elif text in DEVICES:                  # ROMDEV  :760-:790
                    if flags & F_OVER:
                        raise Syntax(text)
                    _release(record, GO)
                    record.append((GO, device_plist(text)))
                elif text == "LP":
                    raise Syntax(text)
                else:
                    name, acct, password = fid(text)
                    on_check(name, acct)
                    _release(record, GO)               # ROMGO
                    record.append((GO, file_plist(name, acct, OUT, password)))
                continue
            if phase == "LO":                          # DOLO  :838
                opt |= OPT_LO
                _release(record, LO)
                if text in LIST_DEVICES:               # LOME
                    record.append((LO, device_plist(text)))
                else:
                    name, acct, password = fid(text)
                    on_check(name, acct)
                    record.append((LO, file_plist(name, acct, OUT, password)))
                phase = "END"                          # X'20000': NO FOLLOWING TEXT
                continue
            raise Syntax(text)                         # trailing garbage
    except Syntax as e:
        cal.trace(f"TEL user {u}: syntax at {e} (an unrecognized load module: ignored)")
    except OnError as e:
        record[:], cal.stdopt[u] = saved               # SYN1
        return str(e), False
    cal.stdopt[u] = opt
    return None, si_given


def step(cal, u, si_given, account):
    """GROUP2C  TEL.txt:483-:510: the M:SI sets released unless this command gave one;
    the default object file if the record has no M:GO set (%ROM); J:OPT for the step."""
    record = cal.amr.setdefault(u, [])
    if not si_given:
        _release(record, SI)                           # GRPEXT
    if not any(n == GO for n, _ in record):            # GRPEXT1
        record.append((GO, file_plist(default_name(u), account, OUT)))
    cal.jopt[u] = cal.stdopt.get(u, 0) | OPT_SI        # AN SI OPTION IS ALWAYS PROVIDED


def merge(sched, u, dcbs):
    """ASP17-ASM8  STPNR.txt:2595-:2737, when a program is fetched: M:GO's defaults (a
    file, OUT, the default name; ASM2), then each set whose DCB is in the program's
    table merged into it (cal.step_merge). ``dcbs``: {name: address}."""
    cal = sched.cal
    from .cal import FUNCTIONS
    if GO in dcbs:                                     # ASM2: SET DEFAULTS INTO M:GO
        dcb = cal.dcb_at(u, dcbs[GO])
        dcb.asn, dcb.fun = 1, FUNCTIONS[OUT]
        if dcb.flp:
            dcb.set_vlp(0x01, text_words(_textc(default_name(u)), 1))
    for name, plist in cal.amr.get(u, []):
        if name not in dcbs:
            continue                                   # ASM5: NOT IN TABLE
        cal.step_merge(u, dcbs[name], plist)
        cal.trace(f"ASM8 user {u}: {name} merged")
