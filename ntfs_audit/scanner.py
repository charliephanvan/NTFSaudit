"""Duyệt cây thư mục và đọc ACL (DACL) của từng thư mục."""
import os

import ntsecuritycon
import pywintypes
import win32api
import win32file
import win32security

from . import rights
from .models import AceInfo, FolderInfo

FILE_ATTRIBUTE_REPARSE_POINT = 0x400
SE_DACL_PROTECTED = 0x1000
ACCESS_ALLOWED_ACE_TYPE = 0
ACCESS_DENIED_ACE_TYPE = 1
ERROR_NOT_ALL_ASSIGNED = 1300


def to_long_path(path: str) -> str:
    """Thêm tiền tố \\\\?\\ để hỗ trợ đường dẫn dài hơn 260 ký tự."""
    p = os.path.abspath(path)
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def enable_privilege(name: str) -> bool:
    """Bật một privilege cho tiến trình (cần chạy bằng quyền Administrator)."""
    try:
        token = win32security.OpenProcessToken(
            win32api.GetCurrentProcess(),
            ntsecuritycon.TOKEN_ADJUST_PRIVILEGES | ntsecuritycon.TOKEN_QUERY)
        luid = win32security.LookupPrivilegeValue(None, name)
        win32security.AdjustTokenPrivileges(
            token, False, [(luid, ntsecuritycon.SE_PRIVILEGE_ENABLED)])
        return win32api.GetLastError() != ERROR_NOT_ALL_ASSIGNED
    except pywintypes.error:
        return False


_SEC_INFO = win32security.DACL_SECURITY_INFORMATION | win32security.OWNER_SECURITY_INFORMATION


def _get_sd(path: str):
    """Đọc security descriptor. Nếu bị Access Denied thì thử mở bằng Backup semantics
    (dùng SeBackupPrivilege của Administrator)."""
    long_path = to_long_path(path)
    try:
        return win32security.GetNamedSecurityInfo(long_path, win32security.SE_FILE_OBJECT, _SEC_INFO)
    except pywintypes.error as e:
        if e.winerror != 5:
            raise
    handle = win32file.CreateFile(
        long_path, ntsecuritycon.READ_CONTROL,
        win32file.FILE_SHARE_READ | win32file.FILE_SHARE_WRITE | win32file.FILE_SHARE_DELETE,
        None, win32file.OPEN_EXISTING, win32file.FILE_FLAG_BACKUP_SEMANTICS, None)
    try:
        return win32security.GetSecurityInfo(handle, win32security.SE_FILE_OBJECT, _SEC_INFO)
    finally:
        handle.Close()


def read_security(info: FolderInfo) -> None:
    try:
        sd = _get_sd(info.path)
    except pywintypes.error as e:
        info.error = f"Không đọc được phân quyền: {e.strerror} (mã {e.winerror})"
        return

    owner = sd.GetSecurityDescriptorOwner()
    if owner is not None:
        info.owner_sid = win32security.ConvertSidToStringSid(owner)
    control, _ = sd.GetSecurityDescriptorControl()
    info.protected = bool(control & SE_DACL_PROTECTED)

    dacl = sd.GetSecurityDescriptorDacl()
    if dacl is None:
        # NULL DACL: mọi người đều có toàn quyền
        info.null_dacl = True
        flags = rights.OBJECT_INHERIT_ACE | rights.CONTAINER_INHERIT_ACE
        info.aces.append(AceInfo("S-1-1-0", False, rights.FILE_ALL_ACCESS,
                                 rights.FILE_ALL_ACCESS, flags, ACCESS_ALLOWED_ACE_TYPE))
        return

    for i in range(dacl.GetAceCount()):
        try:
            ace = dacl.GetAce(i)
        except pywintypes.error:
            info.unsupported_aces += 1
            continue
        ace_type, ace_flags = ace[0]
        if ace_type not in (ACCESS_ALLOWED_ACE_TYPE, ACCESS_DENIED_ACE_TYPE):
            info.unsupported_aces += 1
            continue
        raw = ace[1] & 0xFFFFFFFF
        sid = win32security.ConvertSidToStringSid(ace[-1])
        info.aces.append(AceInfo(sid, ace_type == ACCESS_DENIED_ACE_TYPE,
                                 rights.map_generic(raw), raw, ace_flags, ace_type))


def scan(root: str, max_depth: int, cancel, log, progress):
    """Duyệt cây thư mục theo thứ tự cây (cha trước, con sau, sắp xếp theo tên).

    Cấp 1 là thư mục gốc. max_depth = 3 nghĩa là Gốc\\Con\\Cháu.
    """
    root = os.path.abspath(root)
    folders = []

    def walk(path, level):
        if cancel.is_set():
            return
        name = os.path.basename(path.rstrip("\\")) or path
        info = FolderInfo(path=path, level=level, name=name)
        read_security(info)
        folders.append(info)
        progress(len(folders), path)
        if level >= max_depth:
            return
        subs = []
        try:
            with os.scandir(to_long_path(path)) as it:
                for entry in it:
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        attrs = entry.stat(follow_symlinks=False).st_file_attributes
                    except OSError:
                        continue
                    if attrs & FILE_ATTRIBUTE_REPARSE_POINT:
                        log(f"Bỏ qua junction/symlink: {os.path.join(path, entry.name)}")
                        continue
                    subs.append(entry.name)
        except OSError as e:
            info.list_error = f"Không liệt kê được thư mục con: {e.strerror}"
            log(f"LỖI: {path}: {info.list_error}")
            return
        for sub in sorted(subs, key=str.casefold):
            walk(os.path.join(path, sub), level + 1)

    walk(root, 1)
    return folders
