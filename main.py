"""Điểm khởi chạy. Không có tham số: mở giao diện. Có tham số: chạy dòng lệnh."""
import argparse
import sys
import threading


def cli(argv):
    from ntfs_audit.models import ScanOptions
    from ntfs_audit.runner import run

    ap = argparse.ArgumentParser(description="Kiểm tra phân quyền NTFS và xuất Excel")
    ap.add_argument("--path", required=True, help="Thư mục gốc")
    ap.add_argument("--out", required=True, help="File Excel xuất ra")
    ap.add_argument("--depth", type=int, default=3, help="Số cấp thư mục (mặc định 3)")
    ap.add_argument("--no-expand", action="store_true", help="Không bung nhóm thành user")
    ap.add_argument("--show-system", action="store_true", help="Hiện tài khoản hệ thống")
    ap.add_argument("--hide-admin", action="store_true", help="Ẩn nhóm quản trị")
    ap.add_argument("--show-disabled", action="store_true", help="Hiện user bị vô hiệu hóa")
    ap.add_argument("--big-group", type=int, default=500, help="Ngưỡng nhóm lớn")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    opts = ScanOptions(root=a.path, output=a.out, max_depth=a.depth, expand_groups=not a.no_expand,
                       hide_system=not a.show_system, hide_admin=a.hide_admin,
                       hide_disabled=not a.show_disabled, big_group_threshold=a.big_group)
    run(opts, print, lambda m: None, threading.Event())


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cli(sys.argv[1:])
    else:
        from ntfs_audit.gui import main
        main()
