import traceback
from fastapi import FastAPI, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from pathlib import Path
import asyncio
import logging
import json
import argparse
import sys
import os
import threading
import csv
from typing import List

from .cli import _main_async
from .logging_utils import setup_logger

app = FastAPI(title="ICEC Smart Assistant")

def get_project_root() -> Path:
    if getattr(sys, 'frozen', False):
        # When packaged by PyInstaller, paths should resolve against the executable location
        return Path(sys.executable).parent
    # When running from source, app.py is in src/icec_bot/
    return Path(__file__).parent.parent.parent

@app.get("/api/download/csv")
async def download_csv():
    file_path = get_project_root() / "out/list_results.csv"
    if file_path.exists():
        return FileResponse(path=str(file_path), filename="ICEC_Flight_Emissions.csv", media_type="text/csv")
    return {"error": "File not found"}

@app.get("/api/download/json")
async def download_json():
    file_path = get_project_root() / "out/list_results.json"
    if file_path.exists():
        return FileResponse(path=str(file_path), filename="ICEC_Flight_Emissions.json", media_type="application/json")
    return {"error": "File not found"}

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        try:
            self.active_connections.remove(websocket)
        except ValueError:
            pass

    async def broadcast(self, message: str):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

# Static files path: must work in both dev and frozen PyInstaller mode
if getattr(sys, 'frozen', False):
    # PyInstaller 6+ puts --add-data files inside _internal (sys._MEIPASS)
    _MEIPASS = getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    STATIC_DIR = Path(_MEIPASS) / "src" / "icec_bot" / "static"
else:
    STATIC_DIR = Path(__file__).parent / "static"

STATIC_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

class StartJobRequest(BaseModel):
    csv_path: str

class WsLogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast(msg))
        except RuntimeError:
            pass

ws_handler = WsLogHandler()
ws_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S'))

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)
root_logger.addHandler(ws_handler)

global_worker_task = None
global_worker_loop = None

@app.get("/")
async def get_index():
    path = STATIC_DIR / "index.html"
    return FileResponse(str(path))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    await manager.broadcast("SYSTEM: Dashboard connected. Ready internally.")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        
        # Anti-Zombie Feature: Shut down if UI is closed and doesn't reconnect
        def suicide_check():
            import time
            import os
            time.sleep(3)
            # If no active connections are present after 3 seconds, user closed Edge
            if len(manager.active_connections) == 0:
                print("App window closed. Auto-shutting down background server...")
                os._exit(0)

        threading.Thread(target=suicide_check, daemon=True).start()

def _run_worker_sync(args, main_loop):
    global global_worker_task, global_worker_loop
    new_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(new_loop)
    global_worker_loop = new_loop
    global_worker_task = new_loop.create_task(_main_async(args))
    try:
        new_loop.run_until_complete(global_worker_task)
    except asyncio.CancelledError:
        asyncio.run_coroutine_threadsafe(manager.broadcast("INFO: Engine manually stopped or canceled."), main_loop)
    except Exception as e:
        asyncio.run_coroutine_threadsafe(manager.broadcast(f"ERROR: {str(e)}"), main_loop)
    finally:
        new_loop.close()
        global_worker_loop = None
        global_worker_task = None

@app.post("/api/preview")
async def preview_list(req: StartJobRequest):
    root = get_project_root()
    # Normalize path (handle absolute or relative dynamically)
    csv_path = Path(req.csv_path)
    if not csv_path.is_absolute():
        csv_path = root / csv_path
        
    json_path = root / "out/list_results.json"
    
    pairs = []
    if csv_path.exists():
        try:
            with open(csv_path, "r", encoding="utf-8-sig") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip():
                        pairs.append({"dep": row[0].strip(), "dst": row[1].strip()})
        except UnicodeDecodeError:
            with open(csv_path, "r", encoding="big5") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    if len(row) >= 2 and row[0].strip():
                        pairs.append({"dep": row[0].strip(), "dst": row[1].strip()})
                        
    results_map = {}
    if json_path.exists():
        try:
            data = json.loads(json_path.read_text("utf-8"))
            for item in data:
                key = f"{item['departure_code']}-{item['destination_code']}"
                results_map[key] = {
                    "fuel": item.get("fuel_value_kg"),
                    "co2": item.get("target_value_kg"),
                    "dist": item.get("distance_value_km"),
                    "status": item.get("status")
                }
        except Exception:
            pass

    return {"targets": pairs, "results": results_map}

@app.get("/api/select-file")
async def select_file():
    """Open a native Windows file dialog silently using PowerShell to avoid Tkinter thread freezing in FastAPI."""
    import subprocess
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$f = New-Object System.Windows.Forms.OpenFileDialog; "
        "$f.Title = 'Select Target CSV'; "
        "$f.Filter = 'CSV Files (*.csv)|*.csv|All Files (*.*)|*.*'; "
        "$f.ShowDialog() | Out-Null; "
        "$f.FileName"
    )
    try:
        # Hide the powershell CMD window
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, startupinfo=startupinfo
        )
        file_path = result.stdout.strip()
        if file_path:
            return {"path": file_path}
    except Exception as e:
        print("Dialog err:", e)
    return {"path": ""}

@app.post("/api/start")
async def start_scraper(req: StartJobRequest):
    global global_worker_task
    if global_worker_task and not global_worker_task.done():
        return {"status": "already_running"}

    root = get_project_root()
    csv_path = Path(req.csv_path)
    if not csv_path.is_absolute():
        csv_path = root / csv_path

    if not csv_path.exists():
        await manager.broadcast(f"ERROR: Can not find CSV at {csv_path}")
        return {"status": "error", "message": "CSV not found"}

    args = argparse.Namespace(
        command="run",
        config=root / "configs/site.config.json",
        output_json=root / "out/list_results.json",
        target_csv=csv_path,
        max_pairs=None,
        skip_departures=0,
        max_departures=None,
        max_destinations_per_departure=None,
        headful=False
    )
    
    main_loop = asyncio.get_running_loop()
    threading.Thread(target=_run_worker_sync, args=(args, main_loop), daemon=True).start()
    return {"status": "started"}

@app.post("/api/stop")
async def stop_scraper():
    global global_worker_task, global_worker_loop
    if global_worker_loop and global_worker_task:
        global_worker_loop.call_soon_threadsafe(global_worker_task.cancel)
    return {"status": "stopped"}
