"""The Monitor: the CALs a program can make."""

from .dcb import TERMINAL, DCB
from .glossary import cpv, modelOnly
from .scheduler import Event


@cpv("CAL1", "TRAPEXIT", source="UCAL.txt:187, SCHED.txt:877-889",
     note="A program asks for monitor services with CAL instructions; each comes back "
          "through TRAPEXIT")
class Monitor:
    """The CALs, as methods: ``M:READ`` with its FPT is ``m.read(dcb, ...)``. Each CAL is
    served by the component that owns it, in the user's thread, and may wait there: for the
    disc, the terminal, the open/close lock, or granules. When it is done, the user goes back
    through the exit path (``TRAPEXIT``), which may act on a signal or preempt them.

    The I/O CALs name a DCB, and go where it is assigned: the terminal, another device, or a
    file.

    In CP-V the CALs are decoded by the CAL processor and the I/O routines (UCAL, IORT),
    which pass them to the module that serves them. The model has the CALs its programs need:
    ``M:WAIT``, ``M:OPEN``, ``M:READ``, ``M:WRITE`` and ``M:CLOSE``.
    """

    def __init__(self, system, user, context):
        self.system = system
        self.user = user
        self.context = context

    cpvNames = {
        "system": modelOnly("The system; monitor code reaches the components through it"),
        "user": cpv("S:CUN", source="TCATCH.txt:173", note="The user making the CALs"),
        "context": modelOnly("The user's thread"),
    }

    @property
    @cpv("M:UC", source="UCAL.txt:1172", note="An on-line user's terminal DCB")
    def uc(self):
        return self.system.terminals.terminalDcb(self.user)

    @cpv("M:WAIT", "E:SL", "E:WU", source="BPM.txt:428, SCHED.txt:607-615",
         note="Sleep: E:SL now, and CLOCK4 reports E:WU after the time")
    def wait(self, ticks):
        self.system.reportAt(self.system.clock + ticks, self.user, Event.WAKE_UP)
        self.system.scheduler.report(self.user, Event.SLEEP)
        self.endCal()

    @cpv("M:OPEN", "OPNFIL", source="BPM.txt:956, OPNF.txt:115",
         note="The arguments override the DCB's own settings, as an FPT's parameters do")
    def open(self, dcb, mode=None, fileName=None, account=None, organization=None,
             size=None, password=None, protection=None):
        overrides = dict(mode=mode, fileName=fileName, account=account,
                         organization=organization, size=size, password=password,
                         protection=protection)
        for name, value in overrides.items():
            if value is not None:
                setattr(dcb, name, value)
        self.system.files.open(self.user, dcb)
        self.endCal()

    @cpv("M:READ", "MSRRDWT1", source="BPM.txt:591, IORT.txt:305",
         note="Returns the record, or None at the end; a file DCB may give a key, and a "
              "random file's read a size")
    def read(self, dcb, key=None, size=None):
        if dcb.device == TERMINAL:
            text = self.system.terminals.read(self.user)
        elif dcb.device is not None:
            text = self.system.io.read(self.user, dcb)
        else:
            text = self.system.files.read(self.user, dcb, key, size)
        self.endCal()
        return text

    @cpv("M:WRITE", "MSRRDWT1", source="BPM.txt:598, IORT.txt:305")
    def write(self, dcb, text, key=None):
        if dcb.device == TERMINAL:
            self.system.terminals.write(self.user, text)
        elif dcb.device is not None:
            self.system.io.write(self.user, dcb, text)
        else:
            self.system.files.write(self.user, dcb, text, key)
        self.endCal()

    @cpv("M:CLOSE", "CLSFIL", source="BPM.txt:680, CLS.txt:1443",
         note="release=True is the REL option, which deletes the file")
    def close(self, dcb, release=False):
        self.system.files.close(self.user, dcb, release)
        self.endCal()

    @cpv("TRAPEXIT", source="SCHED.txt:877-889",
         note="The CAL is done: back to the user through the exit path")
    def endCal(self):
        self.context.suspend()
