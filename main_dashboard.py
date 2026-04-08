import uvicorn
import threading
import sys
import os
import subprocess
import time
import multiprocessing
import socket
import traceback
import io
import contextlib

def find_free_port():
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('', 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]

# Global random port for this specific instance
APP_PORT = find_free_port()
# --- PyInstaller noconsole support ---
# In --noconsole mode, sys.stdout and sys.stderr are None. 
# Uvicorn explicitly calls sys.stdout.isatty(), causing an AttributeError crash.
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# --- PyInstaller frozen exe support ---
# When frozen, ensure the working directory is set to where the exe lives,
# so that relative paths like "configs/" and "out/" resolve correctly.
if getattr(sys, 'frozen', False):
    os.chdir(os.path.dirname(sys.executable))

from src.icec_bot.app import app as fastapi_app

# Crash log: since --noconsole hides all output, write errors to a file
LOG_FILE = os.path.join(os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else '.', 'crash_log.txt')

def write_crash_log(msg):
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

def start_server():
    try:
        uvicorn.run(fastapi_app, host="127.0.0.1", port=APP_PORT, log_level="warning")
    except Exception as e:
        write_crash_log(f"Server crashed: {e}\n{traceback.format_exc()}")

def wait_for_server(host="127.0.0.1", port=APP_PORT, timeout=15):
    """Poll until the server is actually accepting connections, instead of a blind sleep."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.3)
    return False

def open_browser():
    # Safely acquire Program Files path dynamically
    pf_x86 = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
    pf_main = os.environ.get("PROGRAMFILES", r"C:\Program Files")

    edge_paths = [
        os.path.join(pf_x86, r"Microsoft\Edge\Application\msedge.exe"),
        os.path.join(pf_main, r"Microsoft\Edge\Application\msedge.exe")
    ]
    
    for path in edge_paths:
        if os.path.exists(path):
            try:
                subprocess.Popen([path, f"--app=http://127.0.0.1:{APP_PORT}", "--window-size=1250,850"])
                return
            except Exception:
                continue
                
    import webbrowser
    webbrowser.open(f"http://127.0.0.1:{APP_PORT}")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    # Start server in background thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    # Wait until server is truly ready (not a blind 1.5s sleep)
    if wait_for_server():
        open_browser()
    else:
        write_crash_log("Server failed to start within 15 seconds. Check crash_log.txt.")
        # Still try to open browser so user sees something
        open_browser()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        sys.exit(0)
