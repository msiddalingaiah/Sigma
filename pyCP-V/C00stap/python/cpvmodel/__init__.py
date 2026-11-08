"""A small, readable, runnable model of CP-V, with modern names.

Not a translation: ``uts`` is the faithful one. This model keeps the design and leaves out the
machine. Every name maps back to CP-V's symbols and source lines in the glossary
(``docs/model/glossary.md``). See ``docs/model.md``.

Each major CP-V component is a subpackage with one class in front (``scheduler.Scheduler``;
later ``filesystem.FileSystem`` and others). ``System`` puts them together.
"""

from .program import (Break, Close, Compute, DoIo, Open, OpenClose, ReadRecord, ReadTerminal,
                      Release, Sleep, WaitFor, WriteRecord, WriteTerminal, Yield)
from .filesystem import (ALL, NONE, FileError, FileHandle, FileMode, FileSystem,
                         FileSystemSettings, Organization, Protection)
from .memory import Memory
from .scheduler import (Event, EventRouter, ExitPath, ImpossibleSwap, InconsistentEvent,
                        NotModelledYet, PriorityBoost, Resource, ResourceManager, Scheduler,
                        SchedulerSettings, Signal, StateQueues, SwapScheduler,
                        TransitionTable)
from .system import NoFreeSlot, System, TraceEntry
from .terminals import Line, TerminalController, TerminalSettings, echoSession
from .user import User, UserState
