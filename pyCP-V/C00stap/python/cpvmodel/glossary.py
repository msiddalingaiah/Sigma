"""The glossary: every name in the model, and the CP-V symbols and source lines it stands for.

A model name is tied to CP-V by a ``CpvRef``:

- Classes and methods are decorated: ``@cpv("T:SE", "SE1", source="SCHED.txt:1021-1209")``.
- Attributes, and the members of an enum, are listed in the class's ``cpvNames`` dict.
- A name with no CP-V counterpart is marked ``modelOnly("why")``.

The tests check that every public class and method has a ref, that each symbol really appears
in the cited source lines, and that ``docs/model/glossary.md`` is what ``renderGlossary()``
produces. Regenerate it with ``python -m cpvmodel docs``.
"""

import enum
import importlib
import inspect
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPO_ROOT / "c00co"

MODEL_MODULES = [
    "cpvmodel.user",
    "cpvmodel.program",
    "cpvmodel.futureevents",
    "cpvmodel.memory",
    "cpvmodel.system",
    "cpvmodel.scheduler.scheduler",
    "cpvmodel.scheduler.statequeues",
    "cpvmodel.scheduler.events",
    "cpvmodel.scheduler.eventrouter",
    "cpvmodel.scheduler.exitpath",
    "cpvmodel.scheduler.settings",
    "cpvmodel.scheduler.swapscheduler",
    "cpvmodel.scheduler.resources",
    "cpvmodel.terminals.terminals",
    "cpvmodel.filesystem.errors",
    "cpvmodel.filesystem.allocation",
    "cpvmodel.filesystem.disc",
    "cpvmodel.filesystem.indexchain",
    "cpvmodel.filesystem.directory",
    "cpvmodel.filesystem.files",
    "cpvmodel.filesystem.keyedfile",
    "cpvmodel.filesystem.filesystem",
]


@dataclass(frozen=True)
class CpvRef:
    """What a model name stands for in CP-V. ``source`` is one or more ranges such as
    ``"SCHED.txt:1021-1209, SSDAT.txt:51"``, relative to ``c00co/``."""
    symbols: tuple = ()
    source: str = ""
    note: str = ""

    def __call__(self, target):
        """Used as a decorator: attach this ref to a class or function."""
        target.cpvRef = self
        return target

    def ranges(self):
        """The cited ranges as (file name, first line, last line)."""
        result = []
        for part in filter(None, (p.strip() for p in self.source.split(","))):
            fileName, lines = part.split(":")
            first, _, last = lines.partition("-")
            result.append((fileName, int(first), int(last or first)))
        return result

    @property
    def isModelOnly(self):
        return not self.symbols


def cpv(*symbols, source, note=""):
    return CpvRef(tuple(symbols), source, note)


def modelOnly(note):
    return CpvRef((), "", note)


@dataclass(frozen=True)
class Entry:
    name: str           # "System.dispatch"
    kind: str           # class, method, attribute, member
    ref: CpvRef


def _modelClasses():
    for moduleName in MODEL_MODULES:
        module = importlib.import_module(moduleName)
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == moduleName and not cls.__name__.startswith("_"):
                yield cls


def _publicMethods(cls):
    if issubclass(cls, enum.Enum):
        return
    for name, value in cls.__dict__.items():
        if name.startswith("_"):
            continue
        if isinstance(value, (staticmethod, classmethod)):
            value = value.__func__
        elif isinstance(value, property):
            value = value.fget
        if inspect.isfunction(value):
            yield name, value


def entries():
    """Every glossary entry, plus None refs for public names that lack one."""
    for cls in _modelClasses():
        yield Entry(cls.__name__, "class", cls.__dict__.get("cpvRef"))
        for name, ref in getattr(cls, "cpvNames", {}).items():
            kind = "member" if issubclass(cls, enum.Enum) else "attribute"
            yield Entry(f"{cls.__name__}.{name}", kind, ref)
        for name, function in _publicMethods(cls):
            yield Entry(f"{cls.__name__}.{name}", "method", getattr(function, "cpvRef", None))


def missingRefs():
    return [entry.name for entry in entries() if entry.ref is None]


def sourceProblems():
    """Symbols that don't appear in the lines their entry cites."""
    problems = []
    for entry in entries():
        if entry.ref is None or entry.ref.isModelOnly:
            continue
        text = ""
        for fileName, first, last in entry.ref.ranges():
            path = SOURCE_ROOT / fileName
            if not path.exists():
                problems.append(f"{entry.name}: no file {fileName}")
                continue
            lines = path.read_text(encoding="latin-1").splitlines()
            if last > len(lines):
                problems.append(f"{entry.name}: {fileName} has only {len(lines)} lines")
            text += "\n".join(lines[first - 1:last]) + "\n"
        for symbol in entry.ref.symbols:
            if symbol not in text:
                problems.append(f"{entry.name}: {symbol} not in {entry.ref.source}")
        if not entry.ref.ranges():
            problems.append(f"{entry.name}: symbols but no source")
    return problems


def _sourceLinks(ref):
    links = []
    for fileName, first, last in ref.ranges():
        anchor = f"#L{first}" + (f"-L{last}" if last != first else "")
        label = f"{fileName}:{first}" + (f"–{last}" if last != first else "")
        links.append(f"[{label}](../../c00co/{fileName}{anchor})")
    return ", ".join(links)


def renderGlossary():
    rows = ["# Glossary: model names → CP-V", "",
            "Generated by `python -m cpvmodel docs` from the `cpv(...)` refs in",
            "`python/cpvmodel/`. Don't edit by hand. *model only* means the name has no CP-V",
            "counterpart. Source paths are in `c00co/`.", ""]
    currentClass = None
    for entry in entries():
        className = entry.name.split(".")[0]
        if className != currentClass:
            currentClass = className
            rows += ["", f"## {className}", "",
                     "| Model name | Kind | CP-V | Source | Notes |", "|---|---|---|---|---|"]
        ref = entry.ref or modelOnly("(missing)")
        symbols = ", ".join(f"`{s}`" for s in ref.symbols) or "*model only*"
        rows.append(f"| `{entry.name}` | {entry.kind} | {symbols} | {_sourceLinks(ref)} "
                    f"| {ref.note} |")
    return "\n".join(rows) + "\n"

