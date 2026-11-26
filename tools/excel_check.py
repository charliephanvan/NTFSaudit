"""Mở báo cáo bằng Microsoft Excel (COM) để chắc chắn file không bị lỗi, xuất ảnh PDF sheet ma trận."""
import sys

import win32com.client

src, pdf = sys.argv[1], sys.argv[2]
xl = win32com.client.DispatchEx("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False
try:
    wb = xl.Workbooks.Open(src, 0, True)
    print("Sheets:", [ws.Name for ws in wb.Worksheets])
    wb.Worksheets("Ma trận user").ExportAsFixedFormat(0, pdf.replace(".pdf", "_user.pdf"))
    wb.Worksheets("Tổng quan").ExportAsFixedFormat(0, pdf)
    wb.Close(False)
finally:
    xl.Quit()
