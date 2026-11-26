"""Các cấu trúc dữ liệu dùng chung."""
from dataclasses import dataclass, field
from typing import List, Optional

from . import rights


@dataclass
class ScanOptions:
    root: str
    output: str
    max_depth: int = 3
    expand_groups: bool = True
    hide_system: bool = True
    hide_admin: bool = False
    hide_disabled: bool = True
    big_group_threshold: int = 500


@dataclass
class AceInfo:
    sid: str
    is_deny: bool
    mask: int        # đã quy đổi GENERIC_*
    raw_mask: int    # mã gốc trong ACL
    flags: int
    ace_type: int

    @property
    def inherited(self) -> bool:
        return bool(self.flags & rights.INHERITED_ACE)

    @property
    def applies_folder(self) -> bool:
        """ACE có hiệu lực trên chính thư mục này."""
        return not self.flags & rights.INHERIT_ONLY_ACE

    @property
    def applies_files(self) -> bool:
        """ACE được áp xuống các file nằm trong thư mục này."""
        return bool(self.flags & rights.OBJECT_INHERIT_ACE)


@dataclass
class FolderInfo:
    path: str
    level: int
    name: str
    owner_sid: Optional[str] = None
    protected: bool = False
    null_dacl: bool = False
    aces: List[AceInfo] = field(default_factory=list)
    error: Optional[str] = None        # không đọc được ACL
    list_error: Optional[str] = None   # không liệt kê được thư mục con
    unsupported_aces: int = 0
