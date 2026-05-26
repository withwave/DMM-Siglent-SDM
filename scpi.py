"""Raw SCPI socket transport for Siglent SDM3055/3065.

Shared by the PyQt desktop app and the FastAPI web app. See SCPISocket
docstring for the why-not-vxi11 story.
"""
import socket
import struct
import sys
import threading
import time


class SCPISocket:
    """vxi11.Instrument-compatible raw SCPI socket (TCP port 5025).

    Why raw SCPI instead of vxi11/RPC on Siglent SDM:
      The SDM3055's VXI-11 daemon allows only one RPC link, and an
      ungraceful client disconnect leaves it stuck for minutes. The raw
      SCPI server on port 5025 has no such limit and recovers cleanly.
    Safety:
      - timeout matches vxi11.Instrument.timeout: SECONDS.
      - SO_LINGER(0): close() sends TCP RST so the DMM frees its session
        immediately (no FIN_WAIT_2 backlog).
      - connect retries with backoff for the rare case where the device
        is still mid-cleanup.
      - ask() drains any stale bytes from a previous timed-out response
        before sending, reconnects on timeout/OSError/empty/binary reply.
      - read_raw() unconditionally reconnects in finally so the next
        ask() always starts on a clean stream.
      - RLock around write/ask/read_raw makes each request atomic when
        a button handler ends up calling SCPI mid-poll.
    """
    def __init__(self, host, port=5025, connect_retries=6, retry_delay=3.0):
        self._host = host
        self._port = int(port)
        self._connect_retries = connect_retries
        self._retry_delay = retry_delay
        self._timeout_s = 5.0
        self._buf = b''
        self._lock = threading.RLock()
        self._connect()

    def _connect(self):
        last_err = None
        for attempt in range(self._connect_retries):
            try:
                self._sock = socket.create_connection(
                    (self._host, self._port), timeout=5)
                break
            except (ConnectionRefusedError, OSError) as e:
                last_err = e
                if attempt < self._connect_retries - 1:
                    print(f"  SCPI connect refused, retry "
                          f"{attempt+1}/{self._connect_retries} in "
                          f"{self._retry_delay}s...", file=sys.stderr)
                    time.sleep(self._retry_delay)
                else:
                    raise
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                              struct.pack('ii', 1, 0))
        self._sock.settimeout(self._timeout_s)
        self._buf = b''

    def _reconnect(self):
        try:
            self._sock.close()
        except Exception:
            pass
        self._buf = b''
        self._connect()

    def _drain(self):
        self._sock.settimeout(0)
        try:
            while True:
                chunk = self._sock.recv(4096)
                if not chunk:
                    break
        except (BlockingIOError, socket.timeout):
            pass
        except OSError:
            pass
        finally:
            self._sock.settimeout(self._timeout_s)
        self._buf = b''

    @property
    def timeout(self):
        return self._timeout_s

    @timeout.setter
    def timeout(self, seconds):
        self._timeout_s = float(seconds)
        self._sock.settimeout(self._timeout_s)

    def write(self, cmd, encoding='utf-8'):
        with self._lock:
            if not cmd.endswith('\n'):
                cmd = cmd + '\n'
            self._sock.sendall(cmd.encode(encoding))

    def _readline(self):
        saved = self._timeout_s
        try:
            while b'\n' not in self._buf:
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                self._buf += chunk
                self._sock.settimeout(0.2)
        finally:
            self._sock.settimeout(saved)
        if b'\n' in self._buf:
            line, _, self._buf = self._buf.partition(b'\n')
            return line
        line, self._buf = self._buf, b''
        return line

    def ask(self, cmd, encoding='utf-8'):
        with self._lock:
            self._drain()
            try:
                self.write(cmd, encoding)
                reply = self._readline().decode(encoding, errors='replace').rstrip('\r')
            except (socket.timeout, OSError, ConnectionError):
                self._reconnect()
                raise
            if reply == '':
                self._reconnect()
                raise IOError("empty SCPI reply, socket resynced")
            if reply and reply[0] < ' ' and reply[0] != '\t':
                self._reconnect()
                raise IOError(f"binary garbage on SCPI stream, socket "
                              f"resynced (prefix={reply[:8]!r})")
            return reply

    def read_raw(self):
        with self._lock:
            try:
                while not self._buf:
                    chunk = self._sock.recv(65536)
                    if not chunk:
                        return b''
                    self._buf += chunk
                if self._buf[:1] == b'#':
                    while len(self._buf) < 2:
                        self._buf += self._sock.recv(65536)
                    n = int(self._buf[1:2])
                    while len(self._buf) < 2 + n:
                        self._buf += self._sock.recv(65536)
                    length = int(self._buf[2:2 + n])
                    header_len = 2 + n
                    total_needed = header_len + length
                    while len(self._buf) < total_needed:
                        self._buf += self._sock.recv(65536)
                    data = bytes(self._buf[header_len:total_needed])
                else:
                    self._sock.settimeout(0.5)
                    try:
                        while True:
                            chunk = self._sock.recv(65536)
                            if not chunk:
                                break
                            self._buf += chunk
                    except (socket.timeout, BlockingIOError):
                        pass
                    finally:
                        self._sock.settimeout(self._timeout_s)
                    data = bytes(self._buf)
            finally:
                self._reconnect()
            return data

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass
