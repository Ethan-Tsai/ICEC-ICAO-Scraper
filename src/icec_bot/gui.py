import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext
import threading
import argparse
from pathlib import Path
import asyncio
import logging
import queue
import sys

from .cli import _main_async

class QueueHandler(logging.Handler):
    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            msg = self.format(record)
            self.log_queue.put_nowait(msg)
        except Exception:
            self.handleError(record)

class IcecApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ICEC 自動化爬蟲代理 - 企業版")
        self.geometry("850x650")
        
        self.target_csv = tk.StringVar(value=str(Path("configs/List.csv").absolute()))
        self.log_queue = queue.Queue()
        self.worker_thread = None
        self.worker_task = None
        
        self._build_ui()
        self._setup_logging()
        self.after(100, self._process_log_queue)

    def _build_ui(self):
        frame_top = tk.Frame(self)
        frame_top.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Label(frame_top, text="目標 CSV 清單:").pack(side=tk.LEFT)
        self.entry_csv = tk.Entry(frame_top, textvariable=self.target_csv, width=60, state="readonly")
        self.entry_csv.pack(side=tk.LEFT, padx=5)
        
        tk.Button(frame_top, text="瀏覽檔案...", command=self._select_csv).pack(side=tk.LEFT, padx=5)
        
        frame_mid = tk.Frame(self)
        frame_mid.pack(fill=tk.X, padx=10, pady=5)
        
        self.btn_start = tk.Button(frame_mid, text="▶ 開始 / 繼續", command=self._start, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), width=15)
        self.btn_start.pack(side=tk.LEFT, padx=5)
        
        self.btn_stop = tk.Button(frame_mid, text="⏹ 停止並儲存", command=self._stop, bg="#f44336", fg="white", font=("Arial", 10, "bold"), state=tk.DISABLED, width=15)
        self.btn_stop.pack(side=tk.LEFT, padx=5)

        self.lbl_status = tk.Label(frame_mid, text="狀態: 就緒", fg="gray", font=("Arial", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT, padx=20)
        
        frame_bot = tk.Frame(self)
        frame_bot.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.txt_log = scrolledtext.ScrolledText(frame_bot, state=tk.DISABLED, bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 10))
        self.txt_log.pack(fill=tk.BOTH, expand=True)

    def _setup_logging(self):
        formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
        queue_handler = QueueHandler(self.log_queue)
        queue_handler.setFormatter(formatter)
        
        # Attach to the root logger so it catches everything setup by setup_logger() in cli.py
        root_logger = logging.getLogger()
        root_logger.addHandler(queue_handler)
        root_logger.setLevel(logging.INFO)

        self.log_queue.put("系統已初始化就緒，點擊 [開始] 按鈕即可啟動。注意：第一次開始會自動偵測 out/list_results.json 判斷是否續跑。")

    def _select_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv")])
        if path:
            self.target_csv.set(path)

    def _process_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.txt_log.config(state=tk.NORMAL)
            self.txt_log.insert(tk.END, msg + "\n")
            self.txt_log.see(tk.END)
            self.txt_log.config(state=tk.DISABLED)
        
        if self.worker_thread and not self.worker_thread.is_alive():
            self.btn_start.config(state=tk.NORMAL)
            self.btn_stop.config(state=tk.DISABLED)
            self.lbl_status.config(text="狀態: 已結算 / 任務結束", fg="blue")
            self.worker_thread = None

        self.after(100, self._process_log_queue)

    def _start(self):
        if not self.target_csv.get():
            self.log_queue.put("錯誤: 請先選擇目標 CSV 檔案！")
            return
            
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.lbl_status.config(text="狀態: 執行中...", fg="green")
        self.txt_log.config(state=tk.NORMAL)
        # We don't wipe logs, we keep appending
        self.txt_log.config(state=tk.DISABLED)
        
        # Default cli arguments mocked to namespace automatically!
        args = argparse.Namespace(
            command="run",
            config=Path("configs/site.config.json"),
            output_json=Path("out/list_results.json"),
            target_csv=Path(self.target_csv.get()),
            max_pairs=None,
            skip_departures=0,
            max_departures=None,
            max_destinations_per_departure=None,
            headful=False
        )

        self.worker_thread = threading.Thread(target=self._run_async, args=(args,), daemon=True)
        self.worker_thread.start()

    def _run_async(self, args):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.worker_task = loop.create_task(_main_async(args))
        try:
            loop.run_until_complete(self.worker_task)
        except asyncio.CancelledError:
            self.log_queue.put("系統提醒: 爬蟲程序已經被您成功中止且所有資料已結算！")
        except Exception as e:
            self.log_queue.put(f"嚴重錯誤: {e}")
        finally:
            loop.close()

    def _stop(self):
        self.btn_stop.config(state=tk.DISABLED)
        self.lbl_status.config(text="狀態: 正在中斷程序...請稍等防呆儲存", fg="orange")
        if self.worker_thread and self.worker_thread.is_alive():
            if self.worker_task:
                self.worker_task.get_loop().call_soon_threadsafe(self.worker_task.cancel)

def run_gui():
    app = IcecApp()
    app.mainloop()

if __name__ == "__main__":
    run_gui()
