"""Chạy toàn bộ quy trình: quét -> phân tích -> xuất Excel."""
import gc
import os
from datetime import datetime

import pythoncom

from . import scanner
from .analysis import build_report
from .excel import write_report
from .identity import Directory
from .models import ScanOptions


class Cancelled(Exception):
    pass


def server_of(path: str):
    """Máy chủ chứa thư mục (để tra nhóm cục bộ BUILTIN\\...). None = máy hiện tại."""
    p = os.path.abspath(path)
    if p.startswith("\\\\") and not p.startswith("\\\\?\\"):
        return p[2:].split("\\", 1)[0]
    return None


def run(options: ScanOptions, log, progress, cancel) -> str:
    pythoncom.CoInitialize()
    try:
        return _run(options, log, progress, cancel)
    finally:
        gc.collect()  # giải phóng đối tượng COM trước khi CoUninitialize
        pythoncom.CoUninitialize()


def _run(options: ScanOptions, log, progress, cancel) -> str:
    directory = None
    try:
        started = datetime.now()
        if not os.path.isdir(options.root):
            raise ValueError(f"Thư mục không tồn tại hoặc không truy cập được: {options.root}")
        if not scanner.enable_privilege("SeBackupPrivilege"):
            log("CẢNH BÁO: Không bật được SeBackupPrivilege. Hãy chạy bằng quyền Administrator "
                "để đọc được cả thư mục bị chặn quyền.")
        scanner.enable_privilege("SeSecurityPrivilege")

        log(f"Bước 1/3: Quét thư mục {options.root} ({options.max_depth} cấp)...")
        folders = scanner.scan(options.root, options.max_depth, cancel, log,
                               lambda n, p: progress(f"Đã quét {n} thư mục: {p}"))
        if cancel.is_set():
            raise Cancelled()
        failed = sum(1 for f in folders if f.error)
        for f in folders:
            if f.error:
                log(f"LỖI: {f.path}: {f.error}")
        log(f"Đã quét {len(folders)} thư mục, {failed} thư mục lỗi.")

        log("Bước 2/3: Phân giải tài khoản, bung nhóm và tính quyền hiệu lực...")
        directory = Directory(server_of(options.root), log, options.big_group_threshold)
        report = build_report(options, folders, directory, log,
                              lambda i, msg: progress(msg), cancel)
        if cancel.is_set():
            raise Cancelled()
        report.started = started.strftime("%d/%m/%Y %H:%M:%S")
        report.finished = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

        log("Bước 3/3: Ghi file Excel...")
        progress("Đang ghi file Excel...")
        out_dir = os.path.dirname(os.path.abspath(options.output))
        os.makedirs(out_dir, exist_ok=True)
        write_report(report, options.output, log)
        log(f"Hoàn tất sau {(datetime.now() - started).total_seconds():.1f} giây.")
        return options.output
    finally:
        if directory is not None:
            directory.close()
