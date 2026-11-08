"""A spike: users as threads, programs as classes, CALs on a Monitor, I/O through queues.

Not part of the model yet. It tries the design on a small scale, reusing the model's
scheduler, exit path and run loop:

- **A thread per user, with strict handoff.** Exactly one thread runs at a time: the run loop
  (CP-V's interrupt level and scheduler), or one user's thread (their program, and the monitor
  code running their CALs). A user's thread runs until it computes, blocks in a CAL, or ends,
  then hands control back to the loop and waits to be resumed. That is ``T:REG`` and ``LPSD``.
- **A program is a class** with ``run(self, m)``. ``m`` is the ``Monitor``: its methods are the
  CALs, so ``M:READ`` with its FPT becomes ``m.read(dcb, ...)``. Computing isn't a CAL; it is
  the program's own ``self.compute(ticks)``.
- **I/O goes through queues.** ``m.read`` puts an ``IoRequest`` on the device's queue (CP-V's
  IOQ) and the user waits in ``IO_WAIT``; the device serves one request at a time, and its
  completion (at interrupt level, in the loop) reports ``IO_COMPLETE``.
"""

import threading
from dataclasses import dataclass, field

from .program import Break
from .scheduler import Event
from .system import System


class UserEnded(BaseException):
    """Thrown into a user's thread to unwind their program when the user is removed."""


class UserContext:
    """A user's thread: where their program and their CALs run, and wait while suspended.
    In CP-V this is the user's environment, saved in the JIT while they don't run."""

    def __init__(self, system, user, program):
        self.system = system
        self.user = user
        self.program = program
        self.turn = threading.Semaphore(0)
        self.request = None
        self.pendingException = None
        self.finished = False
        self.outcome = None
        program.context = self
        self.thread = threading.Thread(target=self.main, name=f"user {user.name}", daemon=True)
        self.thread.start()

    # --- In the user's thread ---------------------------------------------------------------

    def main(self):
        self.turn.acquire()
        try:
            self.raisePending()
            self.program.run(Monitor(self.system, self.user, self))
        except UserEnded:
            pass
        except BaseException as error:              # handed to the loop to deal with
            self.outcome = error
        self.finished = True
        self.system.loopTurn.release()

    def handBack(self, request):
        """Give the processor back to the loop, and wait to be resumed."""
        self.request = request
        self.system.loopTurn.release()
        self.turn.acquire()
        self.raisePending()

    def raisePending(self):
        if self.pendingException is not None:
            error, self.pendingException = self.pendingException, None
            raise error

    # --- In the loop's thread ---------------------------------------------------------------

    def resume(self):
        """Run the user's thread until it hands control back."""
        self.request = None
        self.turn.release()
        self.system.loopTurn.acquire()

    def throw(self, error):
        """Raise ``error`` in the program when it next runs. The exit path calls this to
        deliver a break."""
        self.pendingException = error


class Program:
    """A user's program. Subclasses write ``run(self, m)``, making CALs on ``m``."""

    context = None

    def run(self, m):
        raise NotImplementedError

    def compute(self, ticks):
        """The program's own work: run for ``ticks``. Not a CAL."""
        self.context.handBack(("compute", ticks))


@dataclass(eq=False)
class DCB:
    """A program's data control block. In the spike it is assigned to a disc file of
    records, read one record per disc transfer."""
    name: str
    records: list = field(default_factory=list)
    position: int = 0


class Monitor:
    """The CALs a program can make, bound to its user."""

    def __init__(self, system, user, context):
        self.system = system
        self.user = user
        self.context = context

    def wait(self, ticks):
        """M:WAIT: sleep for ``ticks``."""
        self.system.reportAt(self.system.clock + ticks, self.user, Event.WAKE_UP)
        self.system.scheduler.report(self.user, Event.SLEEP)
        self.endCal()

    def read(self, dcb):
        """M:READ: the next record from ``dcb``, or None at the end. The read is queued
        for the disc, and the user waits for it."""
        if dcb.position >= len(dcb.records):
            self.endCal()
            return None
        self.user.ioInFlight += 1
        self.system.io.submit("disc", IoRequest(self.user, self.system.discTime))
        self.system.scheduler.report(self.user, Event.IO_STARTED)
        record = dcb.records[dcb.position]
        dcb.position += 1
        self.endCal()
        return record

    def endCal(self):
        """The CAL is done, or blocked: back to the loop, which runs the exit path
        (TRAPEXIT) if the user is still running, and dispatches someone if not."""
        self.context.handBack(("cal", None))


@dataclass(eq=False)
class IoRequest:
    """One entry on a device's queue (CP-V's IOQ)."""
    user: object
    ticks: int


@dataclass(eq=False)
class Device:
    name: str
    queue: list = field(default_factory=list)
    current: IoRequest = None


class IoSystem:
    """The devices and their request queues. A device serves one request at a time; its
    completion comes at interrupt level and starts the next request."""

    def __init__(self, system, deviceNames=("disc",)):
        self.system = system
        self.devices = {name: Device(name) for name in deviceNames}

    def submit(self, deviceName, request):
        device = self.devices[deviceName]
        device.queue.append(request)
        if device.current is None:
            self.start(device)

    def start(self, device):
        device.current = device.queue.pop(0)
        self.system.futureEvents.schedule(self.system.clock + device.current.ticks,
                                          lambda: self.complete(device))

    def complete(self, device):
        request, device.current = device.current, None
        self.system.scheduler.report(request.user, Event.IO_COMPLETE)
        if device.queue:
            self.start(device)


class ThreadedSystem(System):
    """The model's System, running users as threads."""

    def __init__(self, *args, discTime=10, **kwargs):
        super().__init__(*args, **kwargs)
        self.loopTurn = threading.Semaphore(0)
        self.io = IoSystem(self)
        self.discTime = discTime
        self.contexts = {}

    def startProgram(self, name, program, priority, **kwargs):
        user = self.startUser(name, None, priority, **kwargs)
        context = UserContext(self, user, program)
        self.contexts[user] = context
        user.program = context                  # the exit path throws breaks into it
        return user

    def execute(self, user):
        if user.computeLeft > 0:
            self.compute(user)
            return
        context = self.contexts[user]
        context.resume()
        if context.finished:
            self.finish(user, context)
            return
        kind, value = context.request
        if kind == "compute":
            user.computeLeft = value
            self.log(user, f"computes {value}")
            self.compute(user)
        elif user is self.scheduler.currentUser:
            self.scheduler.exitToUser(user)

    def finish(self, user, context):
        error = context.outcome
        if error is None:
            self.endUser(user)
        elif isinstance(error, Break):
            self.endUser(user, "break with no break routine: back to the command processor")
        else:
            self.endUser(user, f"failed: {error!r}")
            raise error

    def endUser(self, user, reason=None):
        context = self.contexts.pop(user, None)
        if context is not None and not context.finished:
            context.pendingException = UserEnded()
            context.resume()
        super().endUser(user, reason)

    def shutdown(self):
        """Unwind every user's thread that is still waiting."""
        for user in list(self.contexts):
            self.endUser(user, "shut down")
