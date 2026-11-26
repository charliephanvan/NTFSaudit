"""Kiểm tra nhanh: mở giao diện, chạy quét thư mục mẫu, đóng khi xong."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tkinter import messagebox  # noqa: E402

from ntfs_audit.gui import App  # noqa: E402

root_dir, out = sys.argv[1], sys.argv[2]
messagebox.askyesno = lambda *a, **k: False
messagebox.showerror = lambda *a, **k: print("ERROR DIALOG:", a)
app = App()
app.var_root.set(root_dir)
app.var_out.set(out)


def check():
    if app.worker and not app.worker.is_alive() and app.queue.empty():
        print("STATUS:", app.var_status.get())
        app.destroy()
        return
    app.after(500, check)


app.after(300, app._start)
app.after(1000, check)
app.mainloop()
