"""Disc images: the swap disc and the public disc kept in a host file between runs.

On a real system both discs simply stay on their drives, so a disc boot finds the
monitor WRTROOT wrote and every file finds its granules again. Here they are Python
objects, so ``--disc PATH`` saves them when a run ends and loads them when the next
one starts (docs/python-programs.md, "Disc images").

The image is gzipped JSON (``gunzip`` gives the readable file; a plain JSON image
loads too):
- ``rad``: the swap disc's sectors (8 hex digits a word) and, per root sector, the
  root variables the Python keeps on Monitor (devices.Disc.attached);
- ``public``: the public disc's granules (hex bytes), its allocation table (the HGP
  bit map and where the last get stopped) and stack (HGPSTK), and the account
  directory's FDA (ACNCFU's, which the real start-up finds; not read). A version 1
  image had a free list instead; it loads as a bit map with an empty stack.

Open files (CFUs) aren't saved: like the monitor's memory, they go when a run ends.
"""

import gzip
import json
from dataclasses import asdict

from .config import DctEntry
from .devices import Disc as SwapDisc
from .files import Disc as PublicDisc

VERSION = 2
STACK_FIELDS = ("TOP", "BOTTOM", "TEMPBOT", "WORDCNT", "ADJSTCNT", "BUFLAGS")


def _words(ws):
    return "".join(f"{w & 0xFFFFFFFF:08x}" for w in ws)


def _unwords(s):
    return [int(s[i:i + 8], 16) for i in range(0, len(s), 8)]


def _encode(v):
    """Root variables: ints, lists, BOOTIC's tuples and the DCT's entries."""
    if isinstance(v, DctEntry):
        return {"DctEntry": asdict(v)}
    if isinstance(v, tuple):
        return {"tuple": [_encode(x) for x in v]}
    if isinstance(v, list):
        return [_encode(x) for x in v]
    if isinstance(v, dict):
        return {"dict": {k: _encode(x) for k, x in v.items()}}
    return v


def _decode(v):
    if isinstance(v, list):
        return [_decode(x) for x in v]
    if isinstance(v, dict):
        if "DctEntry" in v:
            return DctEntry(**v["DctEntry"])
        if "tuple" in v:
            return tuple(_decode(x) for x in v["tuple"])
        return {k: _decode(x) for k, x in v["dict"].items()}
    return v


def save(path, swap, public):
    image = {
        "version": VERSION,
        "rad": {
            "model": swap.model,
            "sectors": {str(s): _words(ws) for s, ws in sorted(swap.sectors.items())},
            "root": {str(s): {k: _encode(x) for k, x in snap.items()}
                     for s, snap in swap.attached.items()},
        },
        "public": {
            "ad_fda": public.ad_fda,
            "hgp": {"first": public.hgp.first, "granules": public.hgp.n,
                    "map": bytes(public.hgp.map).hex(), "last": public.hgp.last},
            "stack": dict({f: getattr(public.stack, f) for f in STACK_FIELDS},
                          slots=public.stack.slots),
            "granules": {str(da): bytes(b).hex() for da, b in sorted(public.g.items())},
        },
    }
    with gzip.open(path, "wt", encoding="ascii") as f:
        json.dump(image, f, indent=1)


def load(path):
    """Returns (swap disc, public disc)."""
    with open(path, "rb") as f:
        gzipped = f.read(2) == b"\x1f\x8b"             # the gzip magic number
    with (gzip.open if gzipped else open)(path, "rt", encoding="ascii") as f:
        image = json.load(f)
    if image.get("version") not in (1, VERSION):
        raise ValueError(f"{path}: disc image version {image.get('version')}, expected {VERSION}")
    rad = image["rad"]
    swap = SwapDisc(model=rad["model"])
    swap.sectors = {int(s): _unwords(ws) for s, ws in rad["sectors"].items()}
    swap.attached = {int(s): {k: _decode(x) for k, x in snap.items()}
                     for s, snap in rad["root"].items()}
    pub = image["public"]
    granules = {int(da): bytearray.fromhex(h) for da, h in pub["granules"].items()}
    if image["version"] == 1:                          # a free list: its granules free,
        every = sorted(set(pub["free"]) | set(granules))   # the rest in use
        public = PublicDisc(every[-1] - every[0] + 1 if every else 0, every[0] if every else 0x100)
        public.hgp.map = bytearray(len(public.hgp.map))
        for da in pub["free"]:
            public.hgp._set(da - public.hgp.first, True)
    else:
        h = pub["hgp"]
        public = PublicDisc(h["granules"], h["first"])
        public.hgp.map = bytearray.fromhex(h["map"])
        public.hgp.last = h["last"]
        st = pub["stack"]
        for f in STACK_FIELDS:
            setattr(public.stack, f, st[f])
        public.stack.slots = list(st["slots"])
    public.g = granules
    public.ad_fda = pub["ad_fda"]
    return swap, public
