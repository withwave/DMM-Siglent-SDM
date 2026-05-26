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
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
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
    """
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
        self.subscribers: set[asyncio.Queue] = set()
        self._poll_task: asyncio.Task | None = None
        self._connected = False

    def connect(self):
        self.instr = SCPISocket(self.host, self.port)
        self.instr.timeout = 10
        try:
            self.instr.write("TRIGGER:SOURCE IMMEDIATE;TRIGGER:COUNT 1;"
                             "SAMPLE:COUNT 1;TRIG:DEL:AUTO 1")
            self.idn = self.instr.ask("*IDN?")
            print(f"[web] IDN: {self.idn}", file=sys.stderr)
            self.set_mode("DCI", "AUTO")
        finally:
            self.instr.timeout = 2
        self._connected = True

    def close(self):
        if self.instr:
            try:
                self.instr.write("ABORt\n*CLS\nSYSTem:LOCal")
            except Exception:
                pass
            try:
                self.instr.close()
            except Exception:
                pass
            self.instr = None
            self._connected = False

    def set_mode(self, mode: str, range_arg: str = "AUTO"):
        if mode not in MODES:
            raise ValueError(f"unknown mode: {mode}")
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
        self.min_val = None
        self.max_val = None
        print(f"[web] mode={mode} range={range_arg} -> {cmd}", file=sys.stderr)

    def reset_minmax(self):
        self.min_val = None
        self.max_val = None

    def poll_once(self) -> dict | None:
        """One READ? + format. Called by the asyncio loop in a thread to
        avoid blocking the event loop on socket I/O."""
        try:
            raw = self.instr.ask("READ?")
            v = float(raw)
        except Exception as e:
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

    async def poll_loop(self):
        loop = asyncio.get_running_loop()
        while True:
            reading = await loop.run_in_executor(None, self.poll_once)
            self.last_reading = reading
            # Fan out to all WebSocket subscribers without blocking each other.
            dead = []
            for q in list(self.subscribers):
                try:
                    q.put_nowait(reading)
                except asyncio.QueueFull:
                    dead.append(q)
            for q in dead:
                self.subscribers.discard(q)
            await asyncio.sleep(0.25)


# ---------- FastAPI app ----------

cfg = load_ini()
dmm = DMMController(cfg["host"], cfg["port"])


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        dmm.connect()
    except Exception as e:
        print(f"[web] DMM connect failed: {type(e).__name__}: {e}",
              file=sys.stderr)
        # Start anyway so the UI can show a clear error; poll_once will
        # raise and stream the message until reconnect succeeds.
    dmm._poll_task = asyncio.create_task(dmm.poll_loop())
    try:
        yield
    finally:
        if dmm._poll_task:
            dmm._poll_task.cancel()
        dmm.close()


app = FastAPI(title="Siglent SDM Web", lifespan=lifespan)

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
        "modes": {k: {"label": v[0], "ranges": [list(r) for r in v[2]]}
                  for k, v in MODES.items()},
        "current_mode": dmm.current_mode,
        "current_range": dmm.current_range,
    }


@app.post("/api/mode/{mode}")
async def set_mode(mode: str, range: str = "AUTO"):
    if mode not in MODES:
        raise HTTPException(status_code=400, detail=f"unknown mode: {mode}")
    try:
        dmm.set_mode(mode, range)
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
