"""Xuất báo cáo Excel."""
import getpass
import os
import platform
from collections import Counter

from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, NamedStyle, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import rights
from .analysis import Report
from .identity import KIND_USER

EXCEL_MAX_ROWS = 1_048_575
EXCEL_MAX_COLS = 16_380

LEVEL_COLORS = {
    rights.LEVEL_FULL: ("63BE7B", "000000"),
    rights.LEVEL_RW: ("9BC2E6", "000000"),
    rights.LEVEL_RO: ("FFE699", "000000"),
    rights.LEVEL_SPECIAL: ("D9D9D9", "000000"),
    rights.LEVEL_DENY: ("FF7C80", "FFFFFF"),
}
HEADER_FILL = "1F4E78"
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _clean(value):
    """Bỏ ký tự điều khiển mà Excel không chấp nhận (thường gặp trong displayName của AD)."""
    if isinstance(value, str):
        value = ILLEGAL_CHARACTERS_RE.sub("", value)
        return value[:32767]
    return value


def _style_name(level):
    return "lv_" + rights.LEVEL_CODE[level]


def _register_styles(wb):
    header = NamedStyle(name="hdr")
    header.font = Font(bold=True, color="FFFFFF")
    header.fill = PatternFill("solid", fgColor=HEADER_FILL)
    header.alignment = Alignment(vertical="center", wrap_text=True)
    header.border = BORDER
    wb.add_named_style(header)

    vhdr = NamedStyle(name="vhdr")
    vhdr.font = Font(bold=True, color="FFFFFF")
    vhdr.fill = PatternFill("solid", fgColor=HEADER_FILL)
    vhdr.alignment = Alignment(text_rotation=90, horizontal="center", vertical="bottom")
    vhdr.border = BORDER
    wb.add_named_style(vhdr)

    for level, (bg, fg) in LEVEL_COLORS.items():
        st = NamedStyle(name=_style_name(level))
        st.fill = PatternFill("solid", fgColor=bg)
        st.font = Font(color=fg, bold=level == rights.LEVEL_DENY)
        st.alignment = Alignment(horizontal="center", vertical="center")
        st.border = BORDER
        wb.add_named_style(st)

    warn = NamedStyle(name="warn")
    warn.fill = PatternFill("solid", fgColor="F8CBAD")
    warn.font = Font(bold=True, color="9C0006")
    wb.add_named_style(warn)

    for i in range(10):
        st = NamedStyle(name=f"indent{i}")
        st.alignment = Alignment(indent=i * 2)
        st.font = Font(bold=i == 0)
        wb.add_named_style(st)


class _Sheet:
    """Tiện ích ghi sheet ở chế độ write-only."""

    def __init__(self, wb, title, headers, widths, freeze="A2", vertical_from=None):
        self.ws = wb.create_sheet(title)
        self.headers = headers
        for i, w in enumerate(widths, 1):
            self.ws.column_dimensions[get_column_letter(i)].width = w
        self.ws.freeze_panes = freeze
        self.rows = 0
        cells = []
        for i, h in enumerate(headers, 1):
            c = WriteOnlyCell(self.ws, value=h)
            c.style = "vhdr" if vertical_from and i >= vertical_from else "hdr"
            cells.append(c)
        self.ws.append(cells)
        self.truncated = False

    def cell(self, value, style=None):
        c = WriteOnlyCell(self.ws, value=_clean(value))
        if style:
            c.style = style
        return c

    def append(self, values) -> bool:
        if self.rows >= EXCEL_MAX_ROWS - 1:
            self.truncated = True
            return False
        self.ws.append([_clean(v) for v in values])
        self.rows += 1
        return True

    def finish_filter(self):
        if self.rows:
            self.ws.auto_filter.ref = f"A1:{get_column_letter(len(self.headers))}{self.rows + 1}"


def _level_cell(sh, level, text=None):
    if not level:
        return sh.cell(text or "")
    return sh.cell(text or level, _style_name(level))


def write_report(report: Report, out_path: str, log):
    d = report.directory
    name = lambda sid: d.resolve(sid).name  # noqa: E731
    folders = report.folders
    wb = Workbook(write_only=True)
    _register_styles(wb)
    truncated = []

    # Thống kê dùng cho nhiều sheet
    level_counter = Counter(e.level for e in report.user_access.values())
    per_folder = {f.path: Counter() for f in folders}
    per_user = {u: Counter() for u in report.users}
    for (path, u), e in report.user_access.items():
        per_folder[path][e.level] += 1
        per_user[u][e.level] += 1
    broken = [f for f in folders if f.protected and not f.error]
    explicit = [f for f in folders if not f.error and any(not a.inherited for a in f.aces)]
    errors = [f for f in folders if f.error or f.list_error]
    groups = [s for s in report.acl_principals if d.resolve(s).is_group]

    # ------------------------------------------------------------ Tổng quan
    ws = wb.create_sheet("Tổng quan")
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 70
    ws.column_dimensions["C"].width = 14
    ws.column_dimensions["D"].width = 14
    ws.column_dimensions["E"].width = 14

    def cell(v, **kw):
        c = WriteOnlyCell(ws, value=_clean(v))
        for k, val in kw.items():
            setattr(c, k, val)
        return c

    bold = Font(bold=True)
    title_font = Font(bold=True, size=16, color=HEADER_FILL)
    sec_font = Font(bold=True, size=12, color="FFFFFF")
    sec_fill = PatternFill("solid", fgColor=HEADER_FILL)
    row = 0

    def put(*vals):
        nonlocal row
        ws.append([_clean(v) for v in vals])
        row += 1

    def section(text):
        put(cell(text, font=sec_font, fill=sec_fill), cell("", fill=sec_fill))

    o = report.options
    put(cell("BÁO CÁO PHÂN QUYỀN NTFS", font=title_font))
    put()
    section("THÔNG TIN QUÉT")
    for k, v in [
        ("Thư mục gốc", o.root),
        ("Số cấp thư mục quét", f"{o.max_depth} cấp (cấp 1 là thư mục gốc)"),
        ("Bắt đầu", report.started),
        ("Kết thúc", report.finished),
        ("Người chạy", f"{os.environ.get('USERDOMAIN', '')}\\{getpass.getuser()}"),
        ("Máy chạy", platform.node()),
        ("Bung nhóm thành user", "Có" if o.expand_groups else "Không"),
        ("Ẩn tài khoản hệ thống", "Có" if o.hide_system else "Không"),
        ("Ẩn nhóm quản trị", "Có" if o.hide_admin else "Không"),
        ("Ẩn user bị vô hiệu hóa", "Có" if o.hide_disabled else "Không"),
        ("Ngưỡng nhóm lớn", f"{o.big_group_threshold} user"),
    ]:
        put(cell(k, font=bold), v)
    put()
    section("SỐ LIỆU")
    for k, v in [
        ("Số thư mục đã quét", len(folders)),
        ("Số thư mục bị ngắt kế thừa", len(broken)),
        ("Số thư mục có quyền gán trực tiếp", len(explicit)),
        ("Số thư mục lỗi (không đọc được)", len(errors)),
        ("Số tài khoản/nhóm xuất hiện trong ACL", len(report.acl_principals)),
        ("Số nhóm", len(groups)),
        ("Số user được liệt kê (sau khi bung nhóm)", len(report.users)),
        ("Số cảnh báo", len(report.warnings)),
    ]:
        put(cell(k, font=bold), v)
    put()
    section("CHÚ GIẢI MỨC QUYỀN")
    for level in rights.LEVELS:
        put(cell(f"{rights.LEVEL_CODE[level]} = {level}", style=_style_name(level)),
            rights.LEVEL_DESCRIPTION[level])
    put()
    section("PHÂN BỐ QUYỀN (số cặp user - thư mục)")
    put(cell("Mức quyền", style="hdr"), cell("Số cặp user - thư mục", style="hdr"))
    chart_start = row + 1
    for level in rights.LEVELS:
        put(cell(level, style=_style_name(level)), level_counter.get(level, 0))
    chart_end = row
    for _ in range(15):  # chừa chỗ cho biểu đồ
        put()

    section("TOP 10 THƯ MỤC CÓ NHIỀU USER ĐƯỢC GHI NHẤT")
    put(cell("Thư mục", style="hdr"), cell("Đường dẫn", style="hdr"),
        cell("Toàn quyền", style="hdr"), cell("Đọc/Ghi", style="hdr"), cell("Chỉ đọc", style="hdr"))
    top_f = sorted(folders, key=lambda f: -(per_folder[f.path][rights.LEVEL_FULL]
                                            + per_folder[f.path][rights.LEVEL_RW]))[:10]
    for f in top_f:
        c = per_folder[f.path]
        put(f.name, f.path, c[rights.LEVEL_FULL], c[rights.LEVEL_RW], c[rights.LEVEL_RO])
    put()
    section("TOP 10 USER CÓ QUYỀN GHI TRÊN NHIỀU THƯ MỤC NHẤT")
    put(cell("User", style="hdr"), cell("Tên hiển thị", style="hdr"),
        cell("Toàn quyền", style="hdr"), cell("Đọc/Ghi", style="hdr"), cell("Chỉ đọc", style="hdr"))
    top_u = sorted(report.users, key=lambda u: -(per_user[u][rights.LEVEL_FULL]
                                                 + per_user[u][rights.LEVEL_RW]))[:10]
    for u in top_u:
        c = per_user[u]
        put(name(u), d.resolve(u).display, c[rights.LEVEL_FULL], c[rights.LEVEL_RW], c[rights.LEVEL_RO])
    put()
    section("HƯỚNG DẪN ĐỌC BÁO CÁO")
    for k, v in [
        ("Danh sách thư mục", "Cây thư mục, chủ sở hữu, kế thừa, số user theo từng mức quyền"),
        ("Thư mục - Quyền", "Thư mục có những ai được truy cập: từng dòng quyền (ACE) đúng như trong tab Security"),
        ("User - Thư mục", "Mỗi user truy cập được những thư mục nào, quyền hiệu lực sau khi gộp nhóm và Deny"),
        ("Ma trận nhóm", "Bảng thư mục x tài khoản/nhóm có trong ACL (quyền gán cho chính tài khoản đó)"),
        ("Ma trận user", "Bảng thư mục x user, quyền hiệu lực của từng user"),
        ("Thành viên nhóm", "Thành viên của từng nhóm, đã bung nhóm lồng nhau"),
        ("Lỗi - Cảnh báo", "Thư mục không đọc được, SID mồ côi, nhóm lớn không bung..."),
        ("Lưu ý", "Báo cáo chỉ tính quyền NTFS, không tính Share permission"),
    ]:
        put(cell(k, font=bold), v)

    chart = BarChart()
    chart.type = "bar"
    chart.title = "Phân bố mức quyền (user - thư mục)"
    chart.legend = None
    chart.height = 7
    chart.width = 16
    chart.add_data(Reference(ws, min_col=2, min_row=chart_start - 1, max_row=chart_end), titles_from_data=True)
    chart.set_categories(Reference(ws, min_col=1, min_row=chart_start, max_row=chart_end))
    ws.add_chart(chart, f"A{chart_end + 2}")
    log("Đã ghi sheet Tổng quan")

    # ------------------------------------------------------ Danh sách thư mục
    sh = _Sheet(wb, "Danh sách thư mục",
                ["Cấp", "Thư mục", "Đường dẫn", "Chủ sở hữu", "Kế thừa quyền", "Số quyền gán trực tiếp",
                 "Số tài khoản trong ACL", "User Toàn quyền", "User Đọc/Ghi", "User Chỉ đọc",
                 "User bị Từ chối", "Trạng thái"],
                [6, 40, 60, 28, 16, 12, 12, 12, 12, 12, 12, 40], freeze="C2")
    for f in folders:
        c = per_folder[f.path]
        inherit = sh.cell("BỊ NGẮT", "warn") if f.protected else "Có"
        status = f.error or f.list_error or "OK"
        sh.append([f.level, sh.cell(f.name, f"indent{min(f.level - 1, 9)}"), f.path,
                   name(f.owner_sid) if f.owner_sid else "",
                   inherit if not f.error else "",
                   sum(1 for a in f.aces if not a.inherited) if not f.error else "",
                   len({a.sid for a in f.aces}) if not f.error else "",
                   c[rights.LEVEL_FULL], c[rights.LEVEL_RW], c[rights.LEVEL_RO], c[rights.LEVEL_DENY],
                   sh.cell(status, "warn") if status != "OK" else status])
    sh.finish_filter()
    log("Đã ghi sheet Danh sách thư mục")

    # -------------------------------------------------------- Thư mục - Quyền
    sh = _Sheet(wb, "Thư mục - Quyền",
                ["Cấp", "Đường dẫn", "Tài khoản", "Tên hiển thị", "Loại", "Mức quyền", "Quyền chi tiết",
                 "Cho phép/Từ chối", "Nguồn", "Áp dụng cho", "Số user thành viên", "Mã quyền"],
                [6, 60, 34, 26, 16, 13, 30, 15, 14, 34, 18, 12], freeze="C2")
    for f in folders:
        for a in f.aces:
            p = d.resolve(a.sid)
            level = rights.LEVEL_DENY if a.is_deny else (rights.classify(a.mask) or rights.LEVEL_SPECIAL)
            if p.universal:
                members = "Mọi user"
            elif p.is_group and p.expanded:
                members = p.member_count
            else:
                members = ""
            if not sh.append([f.level, f.path, p.name, p.display, p.kind, _level_cell(sh, level),
                              rights.detail_text(a.mask), "Từ chối" if a.is_deny else "Cho phép",
                              "Kế thừa" if a.inherited else "Gán trực tiếp",
                              rights.apply_to_text(a.flags), members, f"0x{a.raw_mask:08X}"]):
                break
    sh.finish_filter()
    if sh.truncated:
        truncated.append("Thư mục - Quyền")
    log("Đã ghi sheet Thư mục - Quyền")

    # --------------------------------------------------------- User - Thư mục
    sh = _Sheet(wb, "User - Thư mục",
                ["User", "Tên hiển thị", "Trạng thái", "Cấp", "Đường dẫn", "Mức quyền",
                 "Quyền trên thư mục", "Quyền trên file bên trong", "Có quyền qua", "Bị chặn bởi (Deny)",
                 "Ghi chú"],
                [30, 26, 13, 6, 60, 13, 30, 30, 45, 30, 30], freeze="B2")
    order = {f.path: i for i, f in enumerate(folders)}
    folder_level = {f.path: f.level for f in folders}
    by_user = {}
    for (path, u), e in report.user_access.items():
        by_user.setdefault(u, []).append((order[path], path, e))

    def via_text(u, sids):
        return ", ".join("Trực tiếp" if s == u else name(s) for s in sids)

    stop = False
    for u in report.users:
        p = d.resolve(u)
        for _, path, e in sorted(by_user.get(u, [])):
            if not sh.append([p.name, p.display, p.status, folder_level[path], path,
                              _level_cell(sh, e.level), e.folder_text, e.file_text,
                              via_text(u, e.via), via_text(u, e.deny_via), e.note]):
                stop = True
                break
        if stop:
            break
    sh.finish_filter()
    if sh.truncated:
        truncated.append("User - Thư mục")
    log("Đã ghi sheet User - Thư mục")

    # ----------------------------------------------------------------- Ma trận
    def matrix(title, columns, access):
        cols = columns[:EXCEL_MAX_COLS]
        if len(columns) > len(cols):
            truncated.append(f"{title} (chỉ {len(cols)} cột đầu)")
        sh = _Sheet(wb, title, ["Cấp", "Thư mục", "Đường dẫn"] + [name(s) for s in cols],
                    [6, 40, 50] + [4.5] * len(cols), freeze="D2", vertical_from=4)
        sh.ws.row_dimensions[1].height = 180
        for f in folders:
            vals = [f.level, sh.cell(f.name, f"indent{min(f.level - 1, 9)}"), f.path]
            for s in cols:
                e = access.get((f.path, s))
                vals.append(_level_cell(sh, e.level, rights.LEVEL_CODE[e.level]) if e else None)
            sh.append(vals)
        sh.finish_filter()

    matrix("Ma trận nhóm", report.acl_principals, report.principal_access)
    log("Đã ghi sheet Ma trận nhóm")
    matrix("Ma trận user", report.users, report.user_access)
    log("Đã ghi sheet Ma trận user")

    # --------------------------------------------------------- Thành viên nhóm
    sh = _Sheet(wb, "Thành viên nhóm",
                ["Nhóm", "Loại nhóm", "Số user", "Ghi chú", "User thành viên", "Tên hiển thị", "Trạng thái"],
                [34, 16, 10, 50, 30, 28, 13], freeze="B2")
    for g in groups:
        gp = d.resolve(g)
        count = "Mọi user" if gp.universal else (gp.member_count if gp.expanded else "")
        # Nhóm áp dụng cho mọi user hoặc nhóm quá lớn: chỉ ghi 1 dòng ghi chú
        members = [] if gp.universal or gp.big else sorted(gp.members, key=lambda s: name(s).casefold())
        if not members:
            sh.append([gp.name, gp.kind, count, gp.expand_note or
                       ("Chưa bung (đã tắt tùy chọn)" if not gp.expanded else ""), "", "", ""])
            continue
        for m in members:
            mp = d.resolve(m)
            if not sh.append([gp.name, gp.kind, count, gp.expand_note, mp.name, mp.display, mp.status]):
                break
    sh.finish_filter()
    log("Đã ghi sheet Thành viên nhóm")

    # ---------------------------------------------------------- Lỗi - Cảnh báo
    sh = _Sheet(wb, "Lỗi - Cảnh báo", ["Loại", "Đối tượng", "Chi tiết"], [14, 70, 80])
    for f in errors:
        for msg in (f.error, f.list_error):
            if msg:
                sh.append([sh.cell("Lỗi", "warn"), f.path, msg])
    for w in report.warnings:
        obj, _, detail = w.partition(": ")
        sh.append(["Cảnh báo", obj, detail])
    for t in truncated:
        sh.append(["Cảnh báo", t, "Vượt giới hạn của Excel, dữ liệu bị cắt bớt"])
    if not sh.rows:
        sh.append(["", "Không có lỗi hay cảnh báo", ""])
    sh.finish_filter()

    wb.save(out_path)
    log(f"Đã lưu báo cáo: {out_path}")
