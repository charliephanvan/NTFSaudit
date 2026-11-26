"""Giao diện Tkinter."""
import ctypes
import os
import queue
import threading
import traceback
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .models import ScanOptions
from .runner import Cancelled, run


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"Kiểm tra phân quyền NTFS - v{__version__}")
        self.geometry("860x640")
        self.minsize(720, 520)
        self.queue = queue.Queue()
        self.cancel = threading.Event()
        self.worker = None
        self.last_output = None

        self.var_root = tk.StringVar()
        self.var_out = tk.StringVar()
        self.var_depth = tk.IntVar(value=3)
        self.var_expand = tk.BooleanVar(value=True)
        self.var_hide_system = tk.BooleanVar(value=True)
        self.var_hide_admin = tk.BooleanVar(value=False)
        self.var_hide_disabled = tk.BooleanVar(value=True)
        self.var_big = tk.IntVar(value=500)
        self.var_status = tk.StringVar(value="Sẵn sàng")
        self._build()
        self.after(100, self._poll)
        if not is_admin():
            self._log("CẢNH BÁO: Chương trình không chạy với quyền Administrator. "
                      "Một số thư mục có thể không đọc được. Nên chuột phải > Run as administrator.")

    # ------------------------------------------------------------------ UI
    def _build(self):
        pad = {"padx": 8, "pady": 4}
        frm = ttk.LabelFrame(self, text="Thư mục cần kiểm tra")
        frm.pack(fill="x", **pad)
        frm.columnconfigure(1, weight=1)
        ttk.Label(frm, text="Thư mục gốc:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_root).grid(row=0, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Chọn...", command=self._pick_root).grid(row=0, column=2, **pad)
        ttk.Label(frm, text="File Excel xuất ra:").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(frm, textvariable=self.var_out).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(frm, text="Lưu thành...", command=self._pick_out).grid(row=1, column=2, **pad)

        opt = ttk.LabelFrame(self, text="Tùy chọn")
        opt.pack(fill="x", **pad)
        ttk.Label(opt, text="Số cấp thư mục:").grid(row=0, column=0, sticky="w", **pad)
        ttk.Spinbox(opt, from_=1, to=10, width=5, textvariable=self.var_depth).grid(row=0, column=1, sticky="w", **pad)
        ttk.Label(opt, text="(3 = Gốc\\Con\\Cháu)", foreground="gray").grid(row=0, column=2, sticky="w")
        ttk.Label(opt, text="Ngưỡng nhóm lớn (user):").grid(row=0, column=3, sticky="w", **pad)
        ttk.Spinbox(opt, from_=10, to=100000, increment=100, width=8,
                    textvariable=self.var_big).grid(row=0, column=4, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Bung nhóm AD thành từng user", variable=self.var_expand).grid(
            row=1, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Ẩn tài khoản hệ thống (SYSTEM, CREATOR OWNER...)",
                        variable=self.var_hide_system).grid(row=1, column=3, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Ẩn nhóm quản trị (Administrators, Domain Admins)",
                        variable=self.var_hide_admin).grid(row=2, column=0, columnspan=3, sticky="w", **pad)
        ttk.Checkbutton(opt, text="Ẩn user bị vô hiệu hóa", variable=self.var_hide_disabled).grid(
            row=2, column=3, columnspan=3, sticky="w", **pad)

        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.btn_start = ttk.Button(btns, text="▶ Bắt đầu quét", command=self._start)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(btns, text="■ Dừng", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_open = ttk.Button(btns, text="Mở báo cáo", command=self._open, state="disabled")
        self.btn_open.pack(side="left", padx=4)
        self.btn_folder = ttk.Button(btns, text="Mở thư mục chứa", command=self._open_folder, state="disabled")
        self.btn_folder.pack(side="left", padx=4)

        self.progress = ttk.Progressbar(self, mode="indeterminate")
        self.progress.pack(fill="x", **pad)
        ttk.Label(self, textvariable=self.var_status, anchor="w").pack(fill="x", padx=8)

        logf = ttk.LabelFrame(self, text="Nhật ký")
        logf.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(logf, height=12, wrap="none", font=("Consolas", 9), state="disabled")
        ys = ttk.Scrollbar(logf, orient="vertical", command=self.txt.yview)
        xs = ttk.Scrollbar(logf, orient="horizontal", command=self.txt.xview)
        self.txt.configure(yscrollcommand=ys.set, xscrollcommand=xs.set)
        self.txt.grid(row=0, column=0, sticky="nsew")
        ys.grid(row=0, column=1, sticky="ns")
        xs.grid(row=1, column=0, sticky="ew")
        logf.rowconfigure(0, weight=1)
        logf.columnconfigure(0, weight=1)
        self.txt.tag_configure("err", foreground="#C00000")
        self.txt.tag_configure("warn", foreground="#B36B00")
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _pick_root(self):
        path = filedialog.askdirectory(title="Chọn thư mục cần kiểm tra")
        if path:
            path = os.path.normpath(path)
            self.var_root.set(path)
            name = os.path.basename(path.rstrip("\\")) or path.replace(":", "").replace("\\", "")
            stamp = datetime.now().strftime("%Y%m%d_%H%M")
            docs = os.path.join(os.path.expanduser("~"), "Documents")
            self.var_out.set(os.path.join(docs, f"PhanQuyen_{name}_{stamp}.xlsx"))

    def _pick_out(self):
        path = filedialog.asksaveasfilename(title="Lưu báo cáo", defaultextension=".xlsx",
                                            filetypes=[("Excel", "*.xlsx")],
                                            initialfile=os.path.basename(self.var_out.get()))
        if path:
            self.var_out.set(os.path.normpath(path))

    # ------------------------------------------------------------- Chạy
    def _start(self):
        root = self.var_root.get().strip().strip('"')
        out = self.var_out.get().strip().strip('"')
        if not root or not os.path.isdir(root):
            messagebox.showerror("Lỗi", "Hãy chọn thư mục gốc hợp lệ.")
            return
        if not out:
            messagebox.showerror("Lỗi", "Hãy chọn nơi lưu file Excel.")
            return
        if not out.lower().endswith(".xlsx"):
            out += ".xlsx"
            self.var_out.set(out)
        try:
            depth = int(self.var_depth.get())
            big = int(self.var_big.get())
        except (tk.TclError, ValueError):
            messagebox.showerror("Lỗi", "Số cấp và ngưỡng nhóm lớn phải là số.")
            return
        opts = ScanOptions(root=root, output=out, max_depth=max(1, depth),
                           expand_groups=self.var_expand.get(), hide_system=self.var_hide_system.get(),
                           hide_admin=self.var_hide_admin.get(), hide_disabled=self.var_hide_disabled.get(),
                           big_group_threshold=max(1, big))
        self.cancel.clear()
        self._set_running(True)
        self._log(f"===== Bắt đầu: {datetime.now():%d/%m/%Y %H:%M:%S} =====")
        self.worker = threading.Thread(target=self._work, args=(opts,), daemon=True)
        self.worker.start()

    def _work(self, opts):
        try:
            path = run(opts, lambda m: self.queue.put(("log", m)),
                       lambda m: self.queue.put(("status", m)), self.cancel)
            self.queue.put(("done", path))
        except Cancelled:
            self.queue.put(("cancelled", None))
        except PermissionError as e:
            self.queue.put(("error", f"Không ghi được file (có thể file đang mở trong Excel):\n{e}"))
        except Exception as e:  # noqa: BLE001
            self.queue.put(("log", traceback.format_exc()))
            self.queue.put(("error", str(e)))

    def _stop(self):
        self.cancel.set()
        self.var_status.set("Đang dừng...")

    def _set_running(self, running):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        if running:
            self.btn_open.configure(state="disabled")
            self.btn_folder.configure(state="disabled")
            self.progress.start(12)
        else:
            self.progress.stop()

    def _poll(self):
        try:
            while True:
                kind, msg = self.queue.get_nowait()
                if kind == "log":
                    self._log(msg)
                elif kind == "status":
                    self.var_status.set(msg[:200])
                elif kind == "done":
                    self._set_running(False)
                    self.last_output = msg
                    self.btn_open.configure(state="normal")
                    self.btn_folder.configure(state="normal")
                    self.var_status.set(f"Hoàn tất: {msg}")
                    if messagebox.askyesno("Hoàn tất", f"Đã tạo báo cáo:\n{msg}\n\nMở báo cáo ngay?"):
                        self._open()
                elif kind == "cancelled":
                    self._set_running(False)
                    self.var_status.set("Đã dừng")
                    self._log("Đã dừng theo yêu cầu.")
                elif kind == "error":
                    self._set_running(False)
                    self.var_status.set("Lỗi")
                    self._log(f"LỖI: {msg}")
                    messagebox.showerror("Lỗi", msg)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _log(self, msg):
        tag = "err" if "LỖI" in msg or "Traceback" in msg else ("warn" if "CẢNH BÁO" in msg else None)
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n", tag)
        lines = int(self.txt.index("end-1c").split(".")[0])
        if lines > 5000:
            self.txt.delete("1.0", f"{lines - 5000}.0")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _open(self):
        if self.last_output and os.path.exists(self.last_output):
            os.startfile(self.last_output)

    def _open_folder(self):
        if self.last_output:
            os.startfile(os.path.dirname(self.last_output))

    def _close(self):
        if self.worker and self.worker.is_alive():
            if not messagebox.askyesno("Thoát", "Đang quét. Dừng và thoát?"):
                return
            self.cancel.set()
        self.destroy()


def main():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    App().mainloop()
