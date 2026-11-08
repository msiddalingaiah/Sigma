"""Test helpers: programs made from a list of steps, and stand-ins for monitor code.

``Script(compute(5), io(30), sleep(100))`` is a program that does those steps in order. The
results of steps that return something (terminal reads, file reads) are kept in
``script.results``. Some helpers stand in for monitor code that no user program can run
(blocking on a resource, holding the open/close lock); they let the scheduler's mechanisms be
tested on their own.
"""

from cpvmodel import DCB, Program


class Script(Program):
    def __init__(self, *steps):
        self.steps = steps
        self.results = []

    def run(self, m):
        for step in self.steps:
            result = step(self, m)
            if result is not None:
                self.results.append(result)


def compute(ticks):
    return lambda program, m: program.compute(ticks)


def sleep(ticks):
    return lambda program, m: m.wait(ticks)


def io(ticks):
    """A transfer of ``ticks`` on a device of the user's own, so users don't share it."""
    def step(program, m):
        name = f"{m.user.name}:io{ticks}"
        if name not in m.system.io.devices:
            m.system.io.addDevice(name, ticks)
        m.read(DCB(name, device=name))
    return step


def readTerminal():
    return lambda program, m: m.read(m.uc)


def writeTerminal(text):
    return lambda program, m: m.write(m.uc, text)


def monitorEvent(event, detail=None):
    """Monitor code reporting ``event`` for the user, then the exit path."""
    def step(program, m):
        m.system.scheduler.report(m.user, event, detail)
        m.endCal()
    return step


def openClose(ticks):
    """Monitor code that is the open/close user for ``ticks``, as CLS's open/close is."""
    def step(program, m):
        scheduler = m.system.scheduler
        scheduler.acquireOpenClose(m.user)
        m.system.log(m.user, "open/close starts")
        program.compute(ticks)
        m.system.log(m.user, "open/close done")
        scheduler.releaseOpenClose(m.user)
        m.endCal()
    return step


def happened(system, name, what):
    return [entry.time for entry in system.trace if entry.user == name and entry.what == what]


def dispatchTimes(system, name):
    return [entry.time for entry in system.trace
            if entry.user == name and entry.what.startswith("dispatched")]


# --- Files ---------------------------------------------------------------------------------

def fileDcb(name, mode=None, **settings):
    """A DCB for the file ``name``."""
    from cpvmodel import FileMode
    return DCB(f"F:{name}", fileName=name, mode=mode or FileMode.IN, **settings)


def openFile(files, user, name, mode=None, **settings):
    """Opens a DCB for ``name`` straight through the file system (as monitor code would,
    so nothing waits), and returns it."""
    dcb = fileDcb(name, mode, **settings)
    files.open(user, dcb)
    return dcb


class Writer(Program):
    """Writes ``records`` to the file ``name`` (keyed if records are (key, text) pairs)."""

    def __init__(self, name, records, **settings):
        from cpvmodel import FileMode
        self.out = fileDcb(name, FileMode.OUT, **settings)
        self.records = records

    def run(self, m):
        m.open(self.out)
        for record in self.records:
            if isinstance(record, tuple):
                key, text = record
                m.write(self.out, text, key=key)
            else:
                m.write(self.out, record)
        m.close(self.out)


class Reader(Program):
    """Reads the file ``name`` to the end, after ``delay`` ticks asleep."""

    def __init__(self, name, delay=0, **settings):
        self.data = fileDcb(name, **settings)
        self.delay = delay
        self.got = []

    def run(self, m):
        if self.delay:
            m.wait(self.delay)
        m.open(self.data)
        while (text := m.read(self.data)) is not None:
            self.got.append(text)
        m.close(self.data)
