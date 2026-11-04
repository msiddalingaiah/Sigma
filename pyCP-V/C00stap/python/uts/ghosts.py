"""The scheduler on a booted monitor, and stand-ins for the system ghosts.

INITIAL starts ALLOCAT and the starter ghost with T:GJOBSTRT just before it branches
to T:SE (INITIAL.txt:124-127). Here that builds a sched.Scheduler for the monitor
and starts both. They run when the system is operated (keyin.OperatorConsole):
GHOST1's stand-in follows the end of the real start-up sequence (GHOST1D.txt:320-376).

Most ghosts aren't translated. A stand-in only does what the scheduler can see: it
computes, sleeps, starts other ghosts and logs off. What the real ghosts do (GHOST1's
RECOVER2/PASS0/SYSMAK, RBBAT's symbionts) is in their own modules and not read yet.
ALLOCAT's granule service is translated (files.Disc.allocat, docs/files.md section 8).
"""

from .machine import BOOTFLG, BOOTTYPE
from .cal import CalProcessor
from .files import Disc, FileSystem
from . import pyprog
from .sched import E_UQFAC, Cal1, Call, Compute, Scheduler, Sleep


def allocat(sched, u):
    """ALLOCAT  ALLYCAT.txt: ALLOINIT ends asleep (WAIT). Each time a threshold starts
    it (T:GJOBSTRT: E:WU), ADJBUFS on the public disc's stack, then WAIT again. The
    swapper isn't translated, so the E:UQFAC it reports when ALLOCAT goes out (and
    STUQFAC's commit of the stack) comes here, as ALLOCAT goes to sleep."""
    yield Sleep()                                      # ALLOINIT ... WAIT

    def adjust(sched, u):
        fs = sched.cal.fs if sched.cal else None
        if fs is not None:
            fs.disc.allocat()                          # ADJBUFS
        sched.rce0(u, E_UQFAC)                         # SWAPPER.txt:619 (stand-in)

    while True:
        yield Call(adjust, "ALLOCAT: ADJBUFS; E:UQFAC")
        yield Sleep()                                  # WAIT


def rbbat(sched, u):
    """RBBAT stand-in: waits for symbiont work."""
    while True:
        yield Sleep()


def ends(sched, u):
    """A ghost that does its job and logs itself off (ANLZ, ERR:FIL, MOOSE, FILL)."""
    yield Compute(2)


def ghost1(m):
    def program(sched, u):
        """GHOST1 stand-in: the end of the start-up (GHOST1D.txt:320)."""
        yield Compute(20)                         # RECOVER2 or PASS0, SYSMAK, ... (not read)

        def up(sched, u):
            m.mem[BOOTFLG] = 0                    # STW,1 BOOTFLG: "SET RUNNING"
            sched.t_gjobstrt("RBBAT")             # START SYMBIONT GHOST
            if m.mem.get_byte(BOOTTYPE) == 0:     # MTB,0 X'2A' / BNEZ LOGRCVG
                sched.t_gjobstrt("ANLZ")
            # RVGHOST only with a dump file (DUMPFILE > 0), and the auto-start file
            # (75BUF, FNAME): neither is modeled.
            sched.t_gjobstrt("ERR:FIL")
            sched.t_gjobstrt("MOOSE")             # NSCPU = 0: GOGJOB
            sched.rename_ghost(u, "FILL")         # CHANGE GHOST1 ENTRY INTO FILL

        yield Call(up, "GHOST1: BOOTFLG = 0, start RBBAT, ANLZ, ERR:FIL, MOOSE; become FILL")
        yield Cal1(9, address=1, regs={6: "FILL"})    # CAL1,9 1 (M:EXIT): EXIT TO FILL
    return program


def step_exit(cal, u):
    """T:EXIT stand-in (STPNR.txt:506): with TEL in control, the step function. Here it
    starts the program named in R6 (GHOST1's FILL) in the same user, else T:DELUS."""
    s = cal.s
    name = s.uregs[u][6]
    factory = s.ghost_programs.get(name) if isinstance(name, str) else None
    if factory is None:
        return s.t_delus(u)
    s.trace(f"T:EXIT user {u}: step to {name}")
    s.stacks[u] = [factory(s, u)]
    s.programs[u] = s.stacks[u][0]
    return ("RUN", u)                             # the same user goes on with the new program


def boot_scheduler(m, mon, sysgen):
    """The scheduler for a booted monitor: its page pool, ghost table and BOOTFLG."""
    s = Scheduler(smuis=sysgen.SMUIS, ming=sysgen.MING, pages=mon.M_FPPC or 64,
                  maxg=sysgen.MAXG, ghost_names=sysgen.GHOSTS,
                  bootflg=lambda: m.mem[BOOTFLG])
    s.ghost_programs.update({"ALLOCAT": allocat, "RBBAT": rbbat, "GHOST1": ghost1(m),
                             "ANLZ": ends, "ERR:FIL": ends, "MOOSE": ends, "FILL": ends})
    s.cal = CalProcessor(s, date=mon.DATE)
    s.cal.hooks["T:EXIT"] = step_exit
    # The public disc's file system: a disc of its own (the swap disc isn't modeled
    # as granules), with the :SYS account (SUPER would create accounts). The disc
    # stays with the machine, so its files outlive a recovery or a reboot.
    if m.public_disc is None:
        m.public_disc = Disc(2048)
    disc = m.public_disc
    disc.cat = lambda: s.t_gjobstrt("ALLOCAT")         # THRESH: GRAN.txt:337
    s.buffers[1] = disc.stack                          # HGPSTK's pack stack, for STUQFAC
    s.cal.fs = FileSystem(disc, s.log, ad_fda=disc.ad_fda or None)
    disc.ad_fda = s.cal.fs.ad.FDA
    s.cal.fs.add_account(":SYS")
    s.program_loader = pyprog.loader(s)           # GJOB NAME: a Python program (pyprog.py)
    return s
