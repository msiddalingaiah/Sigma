"""A small, readable, runnable model of CP-V, with modern names.

Not a translation: ``uts`` is the faithful one. This model keeps the design and leaves out the
machine. Every name maps back to CP-V's symbols and source lines in the glossary
(``docs/model/glossary.md``). See ``docs/model.md``.

A user's program is a ``Program`` whose ``run(self, m)`` makes CALs on the ``Monitor``; it runs
in the user's thread. Each major CP-V component is a subpackage with one class in front
(``scheduler.Scheduler``, ``terminals.TerminalController``, ``filesystem.FileSystem``), and
``System`` puts them together.
"""

from .dcb import DCB, TERMINAL, FileMode
from .filesystem import (ALL, NONE, FileError, FileSystem, FileSystemSettings, Organization,
                         Protection)
from .iosystem import Device, IoRequest, IoSystem
from .memory import Memory
from .monitor import Monitor
from .program import Break, Program
from .scheduler import (Event, EventRouter, ExitPath, ImpossibleSwap, InconsistentEvent,
                        NotModelledYet, PriorityBoost, Resource, ResourceManager, Scheduler,
                        SchedulerSettings, Signal, StateQueues, SwapScheduler,
                        TransitionTable)
from .system import NoFreeSlot, System, TraceEntry
from .terminals import EchoSession, Line, TerminalController, TerminalSettings
from .user import User, UserState
from .usercontext import UserContext
