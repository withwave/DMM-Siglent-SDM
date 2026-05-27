#!/usr/bin/env python3
"""FastAPI web app for Siglent SDM3055/3065.

Browser-accessible UI mirroring the desktop app's look:
big green LCD, mode/range buttons, min/max counters. Streams DMM
readings over WebSocket at the same 250 ms cadence as the desktop app.

Run:
    uvicorn web_app:app --host 0.0.0.0 --port 8000
Then open http://<this-mac-IP>:8000 from any device on the LAN.

The desktop PyQt app and this server cannot run at the same time -
SDM3055's SCPI raw socket allows only one client.
"""
import asyncio
import configparser
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from scpi import SCPISocket


# ---------- DMM mode/range catalog (mirrors desktop app constants) ----------

MODES = {
    # key -> (label, SCPI CONF: command, ranges list)
    # ranges: (label, SCPI range arg). First entry is AUTO.
    "DCI": ("DC Current (mA)", "CONF:CURR:DC",
            [("AUTO", "AUTO"), ("200µA", "0.0002"), ("2mA", "0.002"),
             ("20mA", "0.02"), ("200mA", "0.2"), ("2A", "2"), ("10A", "10")]),
    "ACI": ("AC Current", "CONF:CURR:AC",
            [("AUTO", "AUTO"), ("20mA", "0.02"), ("200mA", "0.2"),
             ("2A", "2"), ("10A", "10")]),
    "VDC": ("DC Voltage", "CONF:VOLT:DC",
            [("AUTO", "AUTO"), ("200mV", "0.2"), ("2V", "2"),
             ("20V", "20"), ("200V", "200"), ("1000V", "1000")]),
    "VAC": ("AC Voltage", "CONF:VOLT:AC",
            [("AUTO", "AUTO"), ("200mV", "0.2"), ("2V", "2"),
             ("20V", "20"), ("200V", "200"), ("750V", "750")]),
    "RES": ("Resistance (2W)", "CONF:RES",
            [("AUTO", "AUTO"), ("200Ω", "200"), ("2kΩ", "2000"),
             ("20kΩ", "20000"), ("200kΩ", "200000"), ("2MΩ", "2000000"),
             ("10MΩ", "10000000"), ("100MΩ", "100000000")]),
    "FREQ": ("Frequency", "CONF:FREQ",
             [("AUTO", "AUTO")]),
    "CAP": ("Capacitance", "CONF:CAP",
            [("AUTO", "AUTO"), ("2nF", "2e-9"), ("20nF", "20e-9"),
             ("200nF", "200e-9"), ("2µF", "2e-6"), ("20µF", "20e-6"),
             ("200µF", "200e-6"), ("10mF", "10e-3")]),
}

# Each mode tells the UI what unit prefix to default-display.
DEFAULT_PREFIX = {
    "DCI": "mA", "ACI": "mA", "VDC": "V", "VAC": "V",
    "RES": "Ω", "FREQ": "Hz", "CAP": "F",
}


# ---------- Settings ----------

def load_ini():
    cfg = configparser.ConfigParser()
    cfg.read(Path(__file__).parent / "multimeter.ini")
    return {
        "host": cfg["hw_settings"]["HOST"],
        "port": int(cfg["hw_settings"]["PORT"]),
    }


# ---------- DMM controller ----------

class DMMController:
    """Owns the single SCPISocket and the polling loop.

    All SCPI calls go through SCPISocket which already locks, drains, and
    reconnects on error - so a /mode HTTP request hitting at the same
    instant as a poll just serializes through the lock.

    Reconnect model:
      - connect() never raises. On failure it leaves instr=None and
        returns False; the poll loop retries every RECONNECT_BACKOFF_S.
      - On every successful (re)connect the last selected mode/range is
        replayed so a fresh-booted DMM doesn't sit in its factory
        default (usually VDC).
      - poll_once flips _connected to False on any SCPI error, which
        kicks the loop into the reconnect branch on the next tick.
    """

    # How long to wait between reconnect attempts when the DMM is down.
    # 2 s is short enough that a quick recovery (LAN blip) looks instant
    # to the UI, and long enough that we don't flood the network during
    # a full power-cycle boot (~30-60 s).
    RECONNECT_BACKOFF_S = 2.0

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.instr: SCPISocket | None = None
        self.idn = ""
        self.current_mode = "DCI"
        self.current_range = "AUTO"
        self.last_reading: dict | None = None
        self.min_val: float | None = None
        self.max_val: float | None = None
        self.last_connect_ts: float | None = None
        self.subscribers: set[asyncio.Queue] = set()
        self._poll_task: asyncio.Task | None = None
        self._connected = False

    def connect(self) -> bool:
        """Open the SCPI socket and replay last-known mode/range.
        Never raises — returns True on success, False on any failure.
        Safe to call repeatedly (poll loop drives the retry cadence)."""
        self._close_quietly()
        try:
            # connect_retries=1 so SCPISocket.__init__ doesn't block our
            # poll loop for 18 s; we run our own retry from poll_loop.
            instr = SCPISocket(self.host, self.port,
                               connect_retries=1, retry_delay=0)
            instr.timeout = 10
            instr.write("TRIGGER:SOURCE IMMEDIATE;TRIGGER:COUNT 1;"
                        "SAMPLE:COUNT 1;TRIG:DEL:AUTO 1")
            self.idn = instr.ask("*IDN?")
            self.instr = instr
            # Replay current mode so a freshly booted DMM (factory default
            # is usually VDC) ends up in whatever the user last selected.
            self._apply_mode(self.current_mode, self.current_range)
            instr.timeout = 2
            self._connected = True
            self.last_connect_ts = time.time()
            print(f"[web] connected: {self.idn} "
                  f"(restored {self.current_mode} {self.current_range})",
                  file=sys.stderr)
            return True
        except Exception as e:
            print(f"[web] connect failed: {type(e).__name__}: {e}",
                  file=sys.stderr)
            self._close_quietly()
            self._connected = False
            return False

    def _close_quietly(self):
        if self.instr is not None:
            try:
                self.instr.close()
            except Exception:
                pass
            self.instr = None

    def close(self):
        if self.instr is not None:
            try:
                self.instr.write("ABORt\n*CLS\nSYSTem:LOCal")
            except Exception:
                pass
        self._close_quietly()
        self._connected = False

    def _apply_mode(self, mode: str, range_arg: str):
        """Send CONF: command for mode+range. Caller must hold instr.
        Does not reset min/max — used by both set_mode() and connect()."""
        _, scpi_conf, ranges = MODES[mode]
        valid_ranges = [r[1] for r in ranges]
        if range_arg not in valid_ranges:
            range_arg = "AUTO"
        cmd = scpi_conf if range_arg == "AUTO" else f"{scpi_conf} {range_arg}"
        self.instr.write(cmd)
        try:
            self.instr.write("TRIGger:DELay:AUTO ON")
        except Exception:
            pass
        self.current_mode = mode
        self.current_range = range_arg
        print(f"[web] mode={mode} range={range_arg} -> {cmd}", file=sys.stderr)

    def set_mode(self, mode: str, range_arg: str = "AUTO"):
        """User-initiated mode change. Resets min/max and invalidates
        last_reading so callers can distinguish pre/post-switch."""
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}")
        if self.instr is None or not self._connected:
            raise RuntimeError("DMM not connected")
        try:
            self._apply_mode(mode, range_arg)
        except Exception:
            # Mark broken so the poll loop reconnects and replays.
            self._connected = False
            raise
        self.min_val = None
        self.max_val = None
        # Invalidate last_reading so external HTTP clients can tell that
        # the next sample really is post-switch (503 until the polling
        # task fills it with a fresh value in the new mode).
        self.last_reading = None

    def reset_minmax(self):
        self.min_val = None
        self.max_val = None

    def poll_once(self) -> dict:
        """One READ? + format. Called by the asyncio loop in a thread to
        avoid blocking the event loop on socket I/O. On SCPI error,
        flips _connected=False so the loop runs a fresh reconnect next
        tick (which also replays the last mode)."""
        if self.instr is None or not self._connected:
            return {"error": f"disconnected from {self.host}:{self.port}"}
        try:
            raw = self.instr.ask("READ?")
            v = float(raw)
        except Exception as e:
            self._connected = False
            return {"error": f"{type(e).__name__}: {e}"}
        if self.min_val is None or v < self.min_val:
            self.min_val = v
        if self.max_val is None or v > self.max_val:
            self.max_val = v
        return {
            "value": v,
            "mode": self.current_mode,
            "range": self.current_range,
            "prefix": DEFAULT_PREFIX.get(self.current_mode, ""),
            "min": self.min_val,
            "max": self.max_val,
        }

    def _broadcast(self, reading: dict):
        """Fan out one reading to all WebSocket subscribers. Drops the
        queue (not the socket) if a subscriber is too slow."""
        dead = []
        for q in list(self.subscribers):
            try:
                q.put_nowait(reading)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.subscribers.discard(q)

    async def poll_loop(self):
        """Main loop. Owns reconnect cadence: if _connected is False,
        try to reconnect (blocking call in executor), broadcast an error
        frame on failure and back off, otherwise poll at 4 Hz."""
        loop = asyncio.get_running_loop()
        while True:
            if not self._connected:
                ok = await loop.run_in_executor(None, self.connect)
                if not ok:
                    err = {
                        "error": f"disconnected from {self.host}:{self.port}",
                        "ts": time.time(),
                    }
                    self.last_reading = err
                    self._broadcast(err)
                    await asyncio.sleep(self.RECONNECT_BACKOFF_S)
                    continue
                # Fresh connect: skip straight to the read below so the UI
                # sees a live value as fast as possible.
            reading = await loop.run_in_executor(None, self.poll_once)
            reading["ts"] = time.time()
            self.last_reading = reading
            self._broadcast(reading)
            # On error the next iteration falls into the reconnect branch
            # above; no extra sleep needed beyond the normal 250 ms tick
            # because RECONNECT_BACKOFF_S already gates that path.
            await asyncio.sleep(0.25)


# ---------- FastAPI app ----------

cfg = load_ini()
dmm = DMMController(cfg["host"], cfg["port"])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # First connect attempt. Failure is fine — poll_loop will keep
    # retrying every RECONNECT_BACKOFF_S until the DMM comes back.
    if not dmm.connect():
        # Seed last_reading so HTTP clients see a clear error frame
        # immediately, instead of 503 "no reading yet" until the first
        # poll cycle completes.
        dmm.last_reading = {
            "error": f"disconnected from {dmm.host}:{dmm.port}",
            "ts": time.time(),
        }
    dmm._poll_task = asyncio.create_task(dmm.poll_loop())
    try:
        yield
    finally:
        if dmm._poll_task:
            dmm._poll_task.cancel()
        dmm.close()


app = FastAPI(title="Siglent SDM Web", lifespan=lifespan)

# Open CORS so a UI loaded from one machine can talk to a backend on
# another (e.g. open http://A:8000 in a browser, then point its "Server"
# field at B:8000). This is a LAN tool, not a public service.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(STATIC_DIR / "index.html")


# PWA: service worker has to live at site root so it can claim the
# whole origin as its scope; manifest is conventionally at root too.
@app.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/manifest.json")
async def manifest():
    return FileResponse(STATIC_DIR / "manifest.json",
                        media_type="application/manifest+json")


@app.get("/api/info")
async def info():
    return {
        "idn": dmm.idn,
        "host": dmm.host,
        "port": dmm.port,
        "connected": dmm._connected,
        "last_connect_ts": dmm.last_connect_ts,
        "modes": {k: {"label": v[0], "ranges": [list(r) for r in v[2]]}
                  for k, v in MODES.items()},
        "current_mode": dmm.current_mode,
        "current_range": dmm.current_range,
    }


# Reads the latest reading the polling task already grabbed — no extra
# SCPI traffic to the DMM. Lets `curl http://localhost:8000/api/reading`
# (or tools/ma) get the live value while the web app is running.
@app.get("/api/reading")
async def reading_json():
    if dmm.last_reading is None:
        raise HTTPException(status_code=503, detail="no reading yet")
    return dmm.last_reading


# Human-friendly text response, e.g. "+0.0024 mA  DCI Auto" — perfect
# for shell scripts (`watch -n 0.5 curl -s ...`).
@app.get("/api/reading.txt", response_class=PlainTextResponse)
async def reading_text():
    r = dmm.last_reading
    if r is None:
        raise HTTPException(status_code=503, detail="no reading yet")
    if r.get("error"):
        return f"ERR  {r['error']}\n"
    # Engineering prefix so DCI shows in mA/µA/nA the same way the UI does.
    v = r["value"]
    base = {"DCI": "A", "ACI": "A", "VDC": "V", "VAC": "V",
            "RES": "Ohm", "FREQ": "Hz", "CAP": "F"}.get(r["mode"], "")
    av = abs(v)
    if av >= 1:        scale, prefix = 1, ""
    elif av >= 1e-3:   scale, prefix = 1e3, "m"
    elif av >= 1e-6:   scale, prefix = 1e6, "u"
    elif av >= 1e-9:   scale, prefix = 1e9, "n"
    elif av == 0:      scale, prefix = 1, ""
    else:              scale, prefix = 1e12, "p"
    range_tag = "Auto" if r["range"] == "AUTO" else f"Manual({r['range']})"
    return f"{v*scale:+.4f} {prefix}{base}  {r['mode']} {range_tag}\n"


@app.post("/api/mode/{mode}")
async def set_mode(mode: str, range: str = "AUTO"):
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"unknown mode: {mode}")
    try:
        dmm.set_mode(mode, range)
    except RuntimeError as e:
        # "DMM not connected" — surface as 503 so the UI can show a
        # clear "retry when reconnected" hint instead of a generic 500.
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"{type(e).__name__}: {e}")
    return {"ok": True, "mode": mode, "range": dmm.current_range}


@app.post("/api/reset-minmax")
async def reset_minmax():
    dmm.reset_minmax()
    return {"ok": True}


@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue(maxsize=8)
    dmm.subscribers.add(q)
    try:
        # Send an initial snapshot right away so the UI doesn't sit empty
        # for up to 250 ms after connect.
        if dmm.last_reading is not None:
            await ws.send_text(json.dumps(dmm.last_reading))
        while True:
            reading = await q.get()
            await ws.send_text(json.dumps(reading))
    except WebSocketDisconnect:
        pass
    finally:
        dmm.subscribers.discard(q)
