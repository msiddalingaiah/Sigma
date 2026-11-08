"""Terminals over TCP (docs/online.md): each connection is a COC line, speaking telnet
in character mode. NOT a translation: it stands in for the 7611 and the data sets.

- connect: the line comes ready with no user, as for a BREAK (coc.Coc.ready);
- a character: input (coc.Coc.input); telnet BREAK or interrupt (IAC BRK, IAC IP), or
  Ctrl-C from a client that sends it raw, is a BREAK;
- disconnect: the line drops (coc.Coc.drop, E:OFF);
- when the line's user is gone (OFF, or no log-on), the connection is closed.

The server says WILL ECHO and WILL SUPPRESS-GO-AHEAD, so COC does the echo and the
editing. It listens on localhost unless told otherwise: there is no authentication.
"""

import select
import socket

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
BRK, IP, NUL, ETX = 243, 244, 0, 3
ECHO, SGA = 1, 3
HELLO = bytes([IAC, WILL, ECHO, IAC, WILL, SGA, IAC, DO, SGA])


class Connection:
    def __init__(self, sock, line):
        self.sock, self.line = sock, line
        self.out = bytearray(HELLO)
        self.state = None              # telnet parsing: None (data), IAC, a verb, SB
        self.user = 0                  # the user the line got at log-on
        self.closing = False

    def send(self, data):
        self.out += bytes(data).replace(bytes([IAC]), bytes([IAC, IAC]))

    def parse(self, data):
        """Telnet: the data characters and the BREAKs, in order; negotiation answered."""
        for c in data:
            st = self.state
            if st is None:
                if c == IAC:
                    self.state = IAC
                elif c == ETX:
                    yield "BREAK"
                elif c != NUL:                         # CR NUL: just CR
                    yield c
            elif st == IAC:
                self.state = None
                if c == IAC:
                    yield c
                elif c in (BRK, IP):
                    yield "BREAK"
                elif c in (DO, DONT, WILL, WONT):
                    self.state = c
                elif c == SB:
                    self.state = SB
            elif st == SB:
                if c == IAC:
                    self.state = "SB-IAC"
            elif st == "SB-IAC":
                self.state = None if c == SE else SB
            else:                                      # the option of DO/DONT/WILL/WONT
                self.state = None
                if st == DO and c not in (ECHO, SGA):
                    self.out += bytes([IAC, WONT, c])
                elif st == WILL and c != SGA:
                    self.out += bytes([IAC, DONT, c])


class TerminalServer:
    """The listening socket and the lines' connections, for one Coc."""

    def __init__(self, coc, port=2323, bind="127.0.0.1", log=None):
        self.coc = coc
        self.log = log if log is not None else (lambda msg: None)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((bind, port))
        self.sock.listen()
        self.sock.setblocking(False)
        self.address = self.sock.getsockname()
        self.conns = {}                                # line -> Connection

    def free_line(self):
        for n in range(len(self.coc.lines)):
            if n not in self.conns and not self.coc.user(n):
                return n
        return None

    def poll(self, timeout=0.0):
        """Wait up to ``timeout`` seconds for something to arrive; hand it to COC."""
        socks = [self.sock] + [c.sock for c in self.conns.values()]
        writers = [c.sock for c in self.conns.values() if c.out]
        try:
            readable, writable, _ = select.select(socks, writers, [], timeout)
        except OSError:
            return
        if self.sock in readable:
            self._accept()
        for conn in list(self.conns.values()):
            if conn.sock in readable:
                self._receive(conn)
        self.flush()

    def _accept(self):
        try:
            sock, peer = self.sock.accept()
        except OSError:
            return
        sock.setblocking(False)
        n = self.free_line()
        if n is None:
            sock.sendall(b"ALL LINES BUSY\r\n")
            sock.close()
            return
        conn = self.conns[n] = Connection(sock, n)
        self.log(f"line {n}: connected from {peer[0]}:{peer[1]}")
        conn.user = self.coc.ready(n, conn.send)       # T:COCHC: ready, log-on
        if not conn.user:
            conn.send(b"SYSTEM FULL\r\n")              # LOGON found no room
            conn.closing = True

    def _receive(self, conn):
        try:
            data = conn.sock.recv(4096)
        except (BlockingIOError, InterruptedError):
            return
        except OSError:
            data = b""
        if not data:
            self.log(f"line {conn.line}: disconnected")
            self._close(conn, drop=True)
            return
        for item in conn.parse(data):
            if not self.coc.user(conn.line):
                break
            if item == "BREAK":
                self.coc.brk(conn.line)
            else:
                self.coc.input(conn.line, item)

    def flush(self):
        """Send what the lines have written; close a line whose user has gone."""
        for conn in list(self.conns.values()):
            if conn.user and not conn.closing and self.coc.user(conn.line) != conn.user:
                self.coc.finish(conn.line)             # logged off (or never on)
                conn.closing = True
            if conn.out:
                try:
                    sent = conn.sock.send(conn.out)
                    del conn.out[:sent]
                except (BlockingIOError, InterruptedError):
                    pass
                except OSError:
                    conn.out.clear()
                    self._close(conn, drop=True)
                    continue
            if conn.closing and not conn.out:
                self._close(conn, drop=False)

    def _close(self, conn, drop):
        if drop and self.coc.user(conn.line) == conn.user and conn.user:
            self.coc.drop(conn.line)                   # E:OFF: the user is removed
        elif self.coc.lines[conn.line].send == conn.send:
            self.coc.lines[conn.line].send = None
        try:
            conn.sock.close()
        except OSError:
            pass
        self.conns.pop(conn.line, None)
        if not drop:
            self.log(f"line {conn.line}: closed")

    def close(self):
        for conn in list(self.conns.values()):
            try:
                conn.sock.close()
            except OSError:
                pass
        self.conns.clear()
        self.sock.close()


# --- real time ---------------------------------------------------------------------------

UNIT = 0.002                            # seconds per scheduler clock unit (2 ms)


def operator_line(con, text):
    """One operator key-in typed while the system runs in real time: INTERRUPT, then
    KEYIN reads it (keyin.session's loop body, for one line)."""
    from .devices import ConsoleExhausted
    from .monitor import NotTranslated
    console = con.m.console
    console.typed()
    oc = con.io.devices.get(con.oc)
    waiting = oc is not None and oc.busy and getattr(oc.unit, "reading", lambda: False)()
    console.replies.append(text)
    try:
        if waiting:                                    # a read is waiting (KEYERR's new
            con.io.pending.append(oc)                  # prompt): the line completes it
            con.io.run()
            con.ctiop()
        else:
            con.interrupt()
    except ConsoleExhausted:
        return
    except NotTranslated as e:
        con.ioctq.clear()
        con.state.log.append((con.keyinbuf.rstrip("\n"), f"not translated: {e}"))
    console.replies.clear()
    con.idle()


def realtime(con, server, keyins=None, stop=None, poll=0.02):
    """Run the system against the wall clock: the terminals' input to COC, the
    operator's key-ins (a queue.Queue of lines; None at the end), and the scheduler for
    the time that passed. Ends at a shutdown, at ``stop()``, or on Ctrl-C."""
    import queue
    import time
    s = con.sched
    t0, n0 = time.monotonic(), s.now
    try:
        while con.shutdown is None and not (stop and stop()):
            server.poll(poll)
            if keyins is not None:
                con.m.console.show_prompt()            # live: ready for a key-in
            while keyins is not None:
                try:
                    text = keyins.get_nowait()
                except queue.Empty:
                    break
                if text is None:
                    keyins = None                      # end of the operator's input
                    break
                operator_line(con, text)
                t0, n0 = time.monotonic(), s.now       # a key-in's own time has passed
            target = n0 + int((time.monotonic() - t0) / UNIT)
            if s.now < target:
                s.GOODNGT = con.state.GOODNGT
                s.symbionts_busy = con.state.symbionts_busy
                outcome = s.run(until=target)
                if outcome == "shutdown":
                    break
                if outcome == "idle" and s.now < target:
                    s.clock(target - s.now)            # nothing to run: the idle loop
                con.state.S_CUIS = s.S_CUIS
            server.flush()
    except KeyboardInterrupt:
        pass
    finally:
        server.flush()
        server.close()
