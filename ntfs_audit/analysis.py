"""Tính quyền hiệu lực cho từng user / nhóm trên từng thư mục."""
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from . import rights
from .identity import Directory, Principal, KIND_USER, is_admin_sid, is_system_sid
from .models import AceInfo, FolderInfo, ScanOptions

# Bit liên quan đến đọc/ghi để ghi chú khi bị Deny một phần
_IMPORTANT_BITS = (rights.FILE_LIST_DIRECTORY | rights.FILE_ADD_FILE | rights.FILE_ADD_SUBDIRECTORY
                   | rights.DELETE | rights.FILE_DELETE_CHILD | rights.WRITE_DAC)


@dataclass
class Effective:
    level: str
    folder_level: Optional[str]
    file_level: Optional[str]
    folder_text: str
    file_text: str
    via: List[str]          # SID các ACE Allow đã cấp quyền
    deny_via: List[str]     # SID các ACE Deny có hiệu lực
    note: str = ""


@dataclass
class Report:
    options: ScanOptions
    folders: List[FolderInfo]
    directory: Directory
    # SID của các tài khoản xuất hiện trong ACL (sau khi lọc)
    acl_principals: List[str] = field(default_factory=list)
    # SID user được liệt kê trong báo cáo (bung từ nhóm + gán trực tiếp)
    users: List[str] = field(default_factory=list)
    # (đường dẫn, SID user) -> Effective
    user_access: Dict[Tuple[str, str], Effective] = field(default_factory=dict)
    # (đường dẫn, SID tài khoản trong ACL) -> Effective (quyền gán riêng cho tài khoản đó)
    principal_access: Dict[Tuple[str, str], Effective] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    started: str = ""
    finished: str = ""


def _level_from(granted: int, denied: int) -> Optional[str]:
    level = rights.classify(granted)
    if level is None and denied & rights._STD:
        return rights.LEVEL_DENY
    return level


def evaluate(aces: List[AceInfo], member: Callable[[str], bool]) -> Optional[Effective]:
    """Mô phỏng cách Windows duyệt DACL: duyệt ACE theo thứ tự, bit đã bị Deny thì
    không được Allow nữa và ngược lại."""
    results = {}
    via, deny_via = [], []
    for scope in ("folder", "file"):
        granted = denied = 0
        for a in aces:
            if scope == "folder" and not a.applies_folder:
                continue
            if scope == "file" and not a.applies_files:
                continue
            if not member(a.sid):
                continue
            if a.is_deny:
                new = a.mask & ~granted
                if new:
                    denied |= new
                    if a.sid not in deny_via:
                        deny_via.append(a.sid)
            else:
                new = a.mask & ~denied & ~granted
                if new:
                    granted |= new
                    if a.sid not in via:
                        via.append(a.sid)
        results[scope] = (granted, denied)

    (fg, fd), (ig, idn) = results["folder"], results["file"]
    if not (fg or fd or ig or idn):
        return None
    folder_level = _level_from(fg, fd)
    file_level = _level_from(ig, idn)
    level = rights.combine_levels(folder_level, file_level)
    if level is None:
        return None
    notes = []
    if level != rights.LEVEL_DENY and (fd | idn) & _IMPORTANT_BITS:
        notes.append("Bị Deny một phần")
    if folder_level is None and file_level:
        notes.append("Chỉ có quyền trên file, không có quyền trên thư mục")
    return Effective(
        level=level, folder_level=folder_level, file_level=file_level,
        folder_text=rights.detail_text(fg) if fg else ("Deny" if fd else ""),
        file_text=rights.detail_text(ig) if ig else ("Deny" if idn else ""),
        via=via, deny_via=deny_via, note="; ".join(notes))


def build_report(options: ScanOptions, folders: List[FolderInfo], directory: Directory,
                 log, progress, cancel) -> Report:
    report = Report(options, folders, directory)

    def visible(sid: str) -> bool:
        if options.hide_system and is_system_sid(sid):
            return False
        if options.hide_admin and is_admin_sid(sid):
            return False
        return True

    # 1. Phân giải tài khoản trong ACL
    seen = []
    for f in folders:
        f.aces = [a for a in f.aces if visible(a.sid)]
        for a in f.aces:
            if a.sid not in seen:
                seen.append(a.sid)
    log(f"Đang phân giải {len(seen)} tài khoản/nhóm...")
    for i, sid in enumerate(seen, 1):
        if cancel.is_set():
            return report
        directory.resolve(sid)
        progress(i, f"Phân giải: {directory.resolve(sid).name}")
    report.acl_principals = sorted(seen, key=lambda s: _principal_sort_key(directory.resolve(s)))

    # 2. Bung nhóm
    user_set = set()
    for i, sid in enumerate(report.acl_principals, 1):
        if cancel.is_set():
            return report
        p = directory.resolve(sid)
        if p.kind == KIND_USER:
            user_set.add(sid)
        elif p.is_group and options.expand_groups:
            progress(i, f"Bung nhóm: {p.name}")
            directory.expand(sid)
            if p.big or p.universal:
                log(f"  {p.name}: {p.expand_note}")
            else:
                user_set |= p.members
                log(f"  {p.name}: {len(p.members)} user")
    if options.hide_disabled:
        user_set = {u for u in user_set if not directory.resolve(u).disabled}
    report.users = sorted(user_set, key=lambda s: directory.resolve(s).name.casefold())
    log(f"Tổng số user được liệt kê: {len(report.users)}")

    # Danh sách nhóm mà mỗi user thuộc về (chỉ xét các nhóm có trong ACL)
    groups_of: Dict[str, set] = {u: set() for u in report.users}
    universal = set()
    for sid in report.acl_principals:
        p = directory.resolve(sid)
        if p.universal:
            universal.add(sid)
        for u in p.members:
            if u in groups_of:
                groups_of[u].add(sid)

    # 3. Tính quyền, cache theo nội dung ACL (thư mục kế thừa thường có ACL giống nhau)
    acl_cache: Dict[tuple, Tuple[dict, dict]] = {}
    for i, f in enumerate(folders, 1):
        if cancel.is_set():
            return report
        if f.error:
            continue
        key = tuple((a.sid, a.is_deny, a.mask, a.flags) for a in f.aces)
        cached = acl_cache.get(key)
        if cached is None:
            p_res, u_res = {}, {}
            ace_sids = {a.sid for a in f.aces}
            for sid in ace_sids:
                eff = evaluate(f.aces, lambda s, sid=sid: s == sid)
                if eff:
                    p_res[sid] = eff
            if universal & ace_sids:
                candidates = report.users
            else:
                candidates = [u for u in report.users if u in ace_sids or groups_of[u] & ace_sids]
            for u in candidates:
                tok = groups_of[u]
                eff = evaluate(f.aces, lambda s, u=u, tok=tok: s == u or s in tok or s in universal)
                if eff:
                    u_res[u] = eff
            cached = (p_res, u_res)
            acl_cache[key] = cached
        p_res, u_res = cached
        for sid, eff in p_res.items():
            report.principal_access[(f.path, sid)] = eff
        for u, eff in u_res.items():
            report.user_access[(f.path, u)] = eff
        if i % 50 == 0:
            progress(i, f"Tính quyền: {f.path}")

    # 4. Cảnh báo
    for f in folders:
        if f.null_dacl:
            report.warnings.append(f"{f.path}: NULL DACL, mọi người có toàn quyền")
        if f.unsupported_aces:
            report.warnings.append(f"{f.path}: {f.unsupported_aces} ACE loại đặc biệt (object/callback) không được phân tích")
    for sid in report.acl_principals:
        p = directory.resolve(sid)
        if p.kind.startswith("Không xác định"):
            report.warnings.append(f"Tài khoản không xác định (có thể đã bị xóa): {sid}")
        elif p.big:
            report.warnings.append(f"{p.name}: {p.expand_note}")
        elif p.expand_note and p.is_group and not p.universal and options.expand_groups:
            report.warnings.append(f"{p.name}: {p.expand_note}")
    return report


def _principal_sort_key(p: Principal):
    order = {KIND_USER: 1}
    return (order.get(p.kind, 0), p.name.casefold())
