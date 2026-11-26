"""Hằng số quyền NTFS, quy đổi mã quyền sang mức quyền dễ đọc."""

# --- Quyền cụ thể trên file/thư mục ---
FILE_LIST_DIRECTORY = 0x0001      # Thư mục: liệt kê | File: đọc dữ liệu
FILE_ADD_FILE = 0x0002            # Thư mục: tạo file | File: ghi dữ liệu
FILE_ADD_SUBDIRECTORY = 0x0004    # Thư mục: tạo thư mục con | File: ghi nối
FILE_READ_EA = 0x0008
FILE_WRITE_EA = 0x0010
FILE_TRAVERSE = 0x0020            # Thư mục: duyệt qua | File: thực thi
FILE_DELETE_CHILD = 0x0040
FILE_READ_ATTRIBUTES = 0x0080
FILE_WRITE_ATTRIBUTES = 0x0100
DELETE = 0x00010000
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
WRITE_OWNER = 0x00080000
SYNCHRONIZE = 0x00100000

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
GENERIC_EXECUTE = 0x20000000
GENERIC_ALL = 0x10000000

FILE_ALL_ACCESS = 0x001F01FF
FILE_GENERIC_READ = 0x00120089
FILE_GENERIC_WRITE = 0x00120116
FILE_GENERIC_EXECUTE = 0x001200A0

# Các bộ quyền chuẩn (bỏ bit SYNCHRONIZE khi so sánh)
_STD = FILE_ALL_ACCESS & ~SYNCHRONIZE
_MODIFY = 0x001301BF & ~SYNCHRONIZE
_READ_EXECUTE = 0x001200A9 & ~SYNCHRONIZE
_READ = 0x00120089 & ~SYNCHRONIZE
_WRITE = 0x00100116 & ~SYNCHRONIZE

_NAMED_SETS = [
    (_STD, "Full Control"),
    (_MODIFY, "Modify"),
    (_READ_EXECUTE | _WRITE, "Read & Execute + Write"),
    (_READ_EXECUTE, "Read & Execute"),
    (_READ | _WRITE, "Read + Write"),
    (_READ, "Read"),
    (_WRITE, "Write"),
]

_BIT_NAMES = [
    (FILE_LIST_DIRECTORY, "Liệt kê/Đọc dữ liệu"),
    (FILE_ADD_FILE, "Tạo file/Ghi dữ liệu"),
    (FILE_ADD_SUBDIRECTORY, "Tạo thư mục/Ghi nối"),
    (FILE_READ_EA, "Đọc thuộc tính mở rộng"),
    (FILE_WRITE_EA, "Ghi thuộc tính mở rộng"),
    (FILE_TRAVERSE, "Duyệt thư mục/Thực thi"),
    (FILE_DELETE_CHILD, "Xóa thư mục con và file"),
    (FILE_READ_ATTRIBUTES, "Đọc thuộc tính"),
    (FILE_WRITE_ATTRIBUTES, "Ghi thuộc tính"),
    (DELETE, "Xóa"),
    (READ_CONTROL, "Đọc phân quyền"),
    (WRITE_DAC, "Thay đổi phân quyền"),
    (WRITE_OWNER, "Chiếm quyền sở hữu"),
]

# Bit thể hiện quyền ghi / thay đổi dữ liệu
_WRITE_BITS = (FILE_ADD_FILE | FILE_ADD_SUBDIRECTORY | DELETE | FILE_DELETE_CHILD
               | WRITE_DAC | WRITE_OWNER)

# --- Cờ ACE ---
OBJECT_INHERIT_ACE = 0x01
CONTAINER_INHERIT_ACE = 0x02
NO_PROPAGATE_INHERIT_ACE = 0x04
INHERIT_ONLY_ACE = 0x08
INHERITED_ACE = 0x10

# --- Mức quyền ---
LEVEL_FULL = "Toàn quyền"
LEVEL_RW = "Đọc/Ghi"
LEVEL_RO = "Chỉ đọc"
LEVEL_SPECIAL = "Đặc biệt"
LEVEL_DENY = "Từ chối"

LEVELS = [LEVEL_FULL, LEVEL_RW, LEVEL_RO, LEVEL_SPECIAL, LEVEL_DENY]
LEVEL_RANK = {LEVEL_FULL: 4, LEVEL_RW: 3, LEVEL_RO: 2, LEVEL_SPECIAL: 1, LEVEL_DENY: 0}
LEVEL_CODE = {LEVEL_FULL: "FC", LEVEL_RW: "RW", LEVEL_RO: "R",
              LEVEL_SPECIAL: "ĐB", LEVEL_DENY: "TC"}
LEVEL_DESCRIPTION = {
    LEVEL_FULL: "Full Control: đọc, ghi, xóa và thay đổi phân quyền",
    LEVEL_RW: "Đọc và ghi: tạo, sửa, xóa dữ liệu (Modify / Write)",
    LEVEL_RO: "Chỉ đọc: xem, mở, sao chép (Read / Read & Execute / List)",
    LEVEL_SPECIAL: "Quyền lẻ, không đọc được dữ liệu (vd: chỉ duyệt qua thư mục)",
    LEVEL_DENY: "Bị Deny, không truy cập được",
}


def map_generic(mask: int) -> int:
    """Đổi các bit GENERIC_* sang quyền cụ thể của file, chỉ giữ bit quyền file."""
    mask &= 0xFFFFFFFF
    out = mask & FILE_ALL_ACCESS
    if mask & GENERIC_ALL:
        out |= FILE_ALL_ACCESS
    if mask & GENERIC_READ:
        out |= FILE_GENERIC_READ
    if mask & GENERIC_WRITE:
        out |= FILE_GENERIC_WRITE
    if mask & GENERIC_EXECUTE:
        out |= FILE_GENERIC_EXECUTE
    return out


def classify(mask: int):
    """Trả về mức quyền cho một mask đã quy đổi, hoặc None nếu không có quyền."""
    m = mask & _STD
    if not m:
        return None
    if m == _STD:
        return LEVEL_FULL
    if m & FILE_LIST_DIRECTORY:
        return LEVEL_RW if m & _WRITE_BITS else LEVEL_RO
    return LEVEL_SPECIAL


def detail_text(mask: int) -> str:
    """Tên quyền chuẩn theo Windows (Full Control, Modify, ...) hoặc danh sách quyền lẻ."""
    m = mask & _STD
    if not m:
        return ""
    for value, name in _NAMED_SETS:
        if m == value:
            return name
    names = [name for bit, name in _BIT_NAMES if m & bit]
    return "Đặc biệt: " + ", ".join(names)


def apply_to_text(flags: int) -> str:
    """Phạm vi áp dụng của ACE, giống tab Advanced Security của Windows."""
    oi = bool(flags & OBJECT_INHERIT_ACE)
    ci = bool(flags & CONTAINER_INHERIT_ACE)
    io = bool(flags & INHERIT_ONLY_ACE)
    if not oi and not ci:
        text = "Chỉ thư mục này"
    elif io:
        text = {(True, True): "Chỉ thư mục con và file",
                (False, True): "Chỉ thư mục con",
                (True, False): "Chỉ file"}[(oi, ci)]
    else:
        text = {(True, True): "Thư mục này, thư mục con và file",
                (False, True): "Thư mục này và thư mục con",
                (True, False): "Thư mục này và file"}[(oi, ci)]
    if flags & NO_PROPAGATE_INHERIT_ACE:
        text += " (chỉ 1 cấp)"
    return text


def combine_levels(folder_level, file_level):
    """Gộp mức quyền trên thư mục và trên file bên trong thành một mức tổng."""
    if file_level == LEVEL_DENY:
        file_level = None
    if folder_level is None:
        return LEVEL_RW if file_level == LEVEL_FULL else file_level
    if file_level is None or folder_level in (LEVEL_FULL, LEVEL_DENY):
        return folder_level
    if file_level == LEVEL_FULL:
        # Toàn quyền trên file nhưng không toàn quyền trên thư mục: vẫn ghi được dữ liệu
        return LEVEL_RW
    return max(folder_level, file_level, key=LEVEL_RANK.__getitem__)
