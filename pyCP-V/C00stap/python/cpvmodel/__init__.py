"""A small, readable, runnable model of CP-V, with modern names.

Not a translation: ``uts`` is the faithful one. This model keeps the design and leaves out the
machine. Every name maps back to CP-V's symbols and source lines in the glossary
(``docs/model/glossary.md``). See ``docs/model.md``.
"""

from .eventrouter import EventRouter, NotModelledYet
from .events import Event, InconsistentEvent, PriorityBoost, TransitionTable
from .program import Compute, DoIo, Sleep, Yield
from .statequeues import StateQueues
from .system import NoFreeSlot, System, TraceEntry
from .user import User, UserState
