"""In nội dung file báo cáo ra file text UTF-8 để kiểm tra nhanh."""
import sys

from openpyxl import load_workbook

src, dst = sys.argv[1], sys.argv[2]
max_rows = int(sys.argv[3]) if len(sys.argv) > 3 else 60
wb = load_workbook(src, read_only=True)
with open(dst, "w", encoding="utf-8") as out:
    for ws in wb.worksheets:
        out.write(f"===== {ws.title} =====\n")
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= max_rows:
                out.write("...\n")
                break
            out.write(" | ".join("" if v is None else str(v) for v in row).rstrip(" |") + "\n")
