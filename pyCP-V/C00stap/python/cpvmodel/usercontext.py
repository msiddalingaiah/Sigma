"""A user's context: the thread their program and their CALs run in."""

import threading

from .glossary import cpv, modelOnly

_current = threading.local()


@modelOnly("Thrown into a user's thread to unwind their program when the user is removed")
class UserEnded(BaseException):
    pass


@cpv("J:JIT", "T:REG", source="JIT.txt:304, SCHED.txt:1343",
     note="CP-V saves a suspended user's environment in their JIT")
class UserContext:
    """Where a user's program, and the monitor code running their CALs, run: a thread.

    **Only one thread runs at a time.** The run loop (CP-V's interrupt level and scheduler)
    resumes a user's thread, and waits until the thread hands control back: when the program
    computes, when a CAL waits or ends, or when the program ends. Then the thread waits
    until it is resumed. Python's threads are only places to wait; the model's scheduler
    decides who runs, so a run is the same every time.

    In CP-V the user's registers and PSD are saved in their JIT while they don't run, and
    ``T:REG`` is how monitor code running a CAL waits for an event.
    """

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

    cpvNames = {
        "system": modelOnly("The system the user runs in"),
        "user": modelOnly("The user"),
        "program": modelOnly("The user's program"),
        "turn": modelOnly("The thread waits on this until it is resumed"),
        "request": modelOnly("Why the thread handed back: ('compute', ticks) or ('cal', None)"),
        "pendingException": modelOnly("An exception to raise when the thread is resumed: a "
                                      "break, or UserEnded"),
        "finished": modelOnly("The program has ended"),
        "outcome": modelOnly("The exception the program ended with, if any"),
        "thread": modelOnly("The Python thread"),
    }

    @staticmethod
    @modelOnly("Whether the code running is a user's (a program or its CAL), not the loop's")
    def inUser():
        return getattr(_current, "context", None) is not None

    # --- In the user's thread ---------------------------------------------------------------

    @modelOnly("The thread's body: run the program, then hand back for the last time")
    def main(self):
        _current.context = self
        self.turn.acquire()
        try:
            self.raisePending()
            self.program.run(self.system.monitorFor(self))
        except UserEnded:
            pass
        except BaseException as error:              # the loop deals with it
            self.outcome = error
        self.finished = True
        self.system.loopTurn.release()

    @modelOnly("Give the processor back to the loop, and wait to be resumed")
    def handBack(self, request):
        self.request = request
        self.system.loopTurn.release()
        self.turn.acquire()
        self.raisePending()

    @modelOnly("The program computes for ``ticks``: the loop runs the time")
    def computeFor(self, ticks):
        self.handBack(("compute", ticks))

    @cpv("T:REG", source="SCHED.txt:1343",
         note="Report an event and give up control: the user's CAL waits here")
    def suspend(self):
        """Back to the loop: the CAL has ended, or it waits (the user's state says which)."""
        self.handBack(("cal", None))

    @modelOnly("Raises the pending exception, if any")
    def raisePending(self):
        if self.pendingException is not None:
            error, self.pendingException = self.pendingException, None
            raise error

    # --- In the loop's thread ---------------------------------------------------------------

    @cpv("T:PULLE", "LPSD", source="SCHED.txt:2069-2084",
         note="Back to the user: their environment is loaded")
    def resume(self):
        """Run the user's thread until it hands control back."""
        self.request = None
        self.turn.release()
        self.system.loopTurn.acquire()

    @modelOnly("Raise ``error`` in the program when it is next resumed")
    def throw(self, error):
        self.pendingException = error
