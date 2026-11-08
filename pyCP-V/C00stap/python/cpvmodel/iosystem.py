"""I/O: devices, and the queues of requests waiting for them."""

from dataclasses import dataclass, field

from .glossary import cpv, modelOnly
from .scheduler import Event
from .usercontext import UserContext


@cpv("IOQUEUE", source="IORT.txt:1407-1528", note="An entry in IOQ's request tables")
@dataclass(eq=False)
class IoRequest:
    """One transfer a user waits for."""
    user: object
    ticks: int

    cpvNames = {
        "user": cpv("S:CUN", source="TCATCH.txt:173"),
        "ticks": modelOnly("How long the device takes for it"),
    }


@cpv("QUEUE", "FRONTEND", source="IOQ.txt:183, IOQ.txt:604",
     note="CP-V queues requests per device and channel, and starts the next at each "
          "completion")
@dataclass(eq=False)
class Device:
    """A device that serves one request at a time, in the order they came."""
    name: str
    ticksPerTransfer: int = 10
    queue: list = field(default_factory=list)
    current: IoRequest = None

    cpvNames = {
        "name": modelOnly("Its name, as DCBs are assigned to it"),
        "ticksPerTransfer": modelOnly("How long one transfer takes"),
        "queue": cpv("QUEUE", source="IOQ.txt:604", note="Requests waiting"),
        "current": cpv("FRONTEND", source="IOQ.txt:183", note="The request being served"),
    }


@cpv("IOQ", "REQCOM", source="IOQ.txt:1, IOQ.txt:1649",
     note="Queues requests and completes them at interrupt level, reporting E:IC")
class IoSystem:
    """The devices, and transfers on them. A transfer puts a request on the device's queue,
    and the user waits for it in ``IO_WAIT``. The device serves its queue one request at a
    time; each completion comes at interrupt level, reports ``IO_COMPLETE`` for the user
    who asked, and starts the next.

    Work the monitor does outside any user (at a job step's end, say) doesn't wait.
    """

    def __init__(self, system):
        self.system = system
        self.devices = {}

    cpvNames = {
        "system": modelOnly("The system"),
        "devices": cpv("DCT1", source="IOQ.txt:33", note="CP-V's device control tables"),
    }

    @modelOnly("Adds a device, or changes its speed")
    def addDevice(self, name, ticksPerTransfer):
        device = self.devices.get(name) or Device(name)
        device.ticksPerTransfer = ticksPerTransfer
        self.devices[name] = device
        return device

    @cpv("T:IOREG", "E:IIP", source="SCHED.txt:780-787",
         note="Start the I/O and wait for it (STIIP)")
    def transfer(self, user, deviceName, count=1):
        """``count`` transfers' worth of time on ``deviceName``, as one request; the user
        waits for it."""
        device = self.devices[deviceName]
        ticks = count * device.ticksPerTransfer
        if ticks == 0 or not UserContext.inUser():
            return
        user.ioInFlight += 1
        self.submit(device, IoRequest(user, ticks))
        self.system.scheduler.report(user, Event.IO_STARTED)
        if user is not self.system.scheduler.currentUser:
            self.system.contexts[user].suspend()

    @cpv("QUEUE", source="IOQ.txt:604")
    def submit(self, device, request):
        device.queue.append(request)
        if device.current is None:
            self.start(device)

    @cpv("FRONTEND", source="IOQ.txt:183")
    def start(self, device):
        device.current = device.queue.pop(0)
        self.system.futureEvents.schedule(self.system.clock + device.current.ticks,
                                          lambda: self.complete(device))

    @cpv("REQCOM", source="IOQ.txt:1649", note="Reports E:IC for the requester")
    def complete(self, device):
        request, device.current = device.current, None
        self.system.scheduler.report(request.user, Event.IO_COMPLETE)
        if device.queue:
            self.start(device)

    @cpv("MSRRED", source="IORT.txt:675", note="A device read: the next record, or None")
    def read(self, user, dcb):
        self.transfer(user, dcb.device)
        return dcb.records.pop(0) if dcb.records else None

    @cpv("MSRWRT", source="WRTD.txt:140")
    def write(self, user, dcb, text):
        self.transfer(user, dcb.device)
        dcb.records.append(text)
