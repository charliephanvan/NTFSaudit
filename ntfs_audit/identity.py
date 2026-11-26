"""Phân giải SID thành tên tài khoản, bung nhóm (AD và nhóm cục bộ) thành danh sách user."""
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

import pywintypes
import win32com.client
import win32net
import win32security

# Loại SID trả về từ LookupAccountSid
SID_USER, SID_GROUP, SID_DOMAIN, SID_ALIAS, SID_WELLKNOWN = 1, 2, 3, 4, 5
SID_DELETED, SID_INVALID, SID_UNKNOWN, SID_COMPUTER, SID_LABEL = 6, 7, 8, 9, 10

KIND_USER = "User"
KIND_AD_GROUP = "Nhóm AD"
KIND_LOCAL_GROUP = "Nhóm cục bộ"
KIND_WELLKNOWN = "Nhóm đặc biệt"
KIND_COMPUTER = "Máy tính"
KIND_UNRESOLVED = "Không xác định (SID mồ côi)"
GROUP_KINDS = {KIND_AD_GROUP, KIND_LOCAL_GROUP, KIND_WELLKNOWN}

# Nhóm mà mọi user đăng nhập đều thuộc về
UNIVERSAL_SIDS = {"S-1-1-0", "S-1-5-11"}  # Everyone, Authenticated Users

SYSTEM_SIDS = {
    "S-1-5-18",  # SYSTEM
    "S-1-5-19",  # LOCAL SERVICE
    "S-1-5-20",  # NETWORK SERVICE
    "S-1-3-0",   # CREATOR OWNER
    "S-1-3-1",   # CREATOR GROUP
    "S-1-3-4",   # OWNER RIGHTS
}
SYSTEM_PREFIXES = ("S-1-5-80-", "S-1-15-", "S-1-5-83-", "S-1-5-90-", "S-1-5-96-")
ADMIN_RIDS = {"512", "519"}  # Domain Admins, Enterprise Admins
ADMIN_SIDS = {"S-1-5-32-544"}  # BUILTIN\Administrators

UF_ACCOUNTDISABLE = 0x2


def is_system_sid(sid: str) -> bool:
    return sid in SYSTEM_SIDS or sid.startswith(SYSTEM_PREFIXES)


def is_admin_sid(sid: str) -> bool:
    if sid in ADMIN_SIDS:
        return True
    return sid.startswith("S-1-5-21-") and sid.rsplit("-", 1)[-1] in ADMIN_RIDS


@dataclass
class Principal:
    sid: str
    name: str                    # DOMAIN\tên
    kind: str
    display: str = ""
    disabled: bool = False
    sid_type: int = 0
    members: Set[str] = field(default_factory=set)  # SID user (đệ quy)
    member_count: int = 0
    universal: bool = False      # nhóm áp dụng cho mọi user (Everyone, Authenticated Users...)
    expanded: bool = False
    big: bool = False            # nhóm quá lớn, không bung ra từng user trong báo cáo
    expand_note: str = ""

    @property
    def is_group(self) -> bool:
        return self.kind in GROUP_KINDS

    @property
    def status(self) -> str:
        if self.kind != KIND_USER:
            return ""
        return "Vô hiệu hóa" if self.disabled else "Hoạt động"


class Directory:
    """Cache tra cứu tài khoản. Không dùng chung giữa các thread (COM)."""

    def __init__(self, server: Optional[str], log, big_group_threshold: int = 500):
        self.server = server  # máy chứa thư mục (để tra nhóm cục bộ BUILTIN\...)
        self.log = log
        self.big_threshold = big_group_threshold
        self.cache: Dict[str, Principal] = {}
        self._ado = None
        self._ado_failed = False
        self._expanding: Set[str] = set()

    def close(self):
        """Đóng kết nối ADO (phải gọi trước CoUninitialize)."""
        if self._ado is not None:
            try:
                self._ado.Close()
            except pywintypes.com_error:
                pass
            self._ado = None

    # ------------------------------------------------------------------ AD/ADO
    def _ado_conn(self):
        if self._ado is None and not self._ado_failed:
            try:
                conn = win32com.client.Dispatch("ADODB.Connection")
                conn.Provider = "ADsDSOObject"
                conn.Open("Active Directory Provider")
                self._ado = conn
            except pywintypes.com_error as e:
                self._ado_failed = True
                self.log(f"CẢNH BÁO: Không kết nối được Active Directory ({e}). Không bung được nhóm AD.")
        return self._ado

    def _ado_query(self, base_dn: str, ldap_filter: str, attrs: str, limit: int):
        conn = self._ado_conn()
        if conn is None:
            return None
        cmd = win32com.client.Dispatch("ADODB.Command")
        cmd.ActiveConnection = conn
        cmd.Properties("Page Size").Value = 1000
        cmd.Properties("Timeout").Value = 120
        cmd.CommandText = f"<LDAP://{base_dn}>;{ldap_filter};{attrs};subtree"
        rs = cmd.Execute()[0]
        rows = []
        names = attrs.split(",")
        while not rs.EOF:
            rows.append({n: rs.Fields(n).Value for n in names})
            if len(rows) >= limit:
                break
            rs.MoveNext()
        rs.Close()
        return rows

    def _ad_object(self, sid: str):
        try:
            return win32com.client.GetObject(f"LDAP://<SID={sid}>")
        except pywintypes.com_error:
            return None

    @staticmethod
    def _ldap_get(obj, attr, default=None):
        try:
            return obj.Get(attr)
        except pywintypes.com_error:
            return default

    # --------------------------------------------------------------- Phân giải
    def resolve(self, sid: str) -> Principal:
        p = self.cache.get(sid)
        if p is not None:
            return p
        try:
            psid = win32security.ConvertStringSidToSid(sid)
            name, domain, sid_type = win32security.LookupAccountSid(self.server, psid)
            full = f"{domain}\\{name}" if domain else name
        except pywintypes.error:
            p = Principal(sid, sid, KIND_UNRESOLVED)
            self.cache[sid] = p
            return p

        if sid_type == SID_USER:
            kind = KIND_USER
        elif sid_type == SID_GROUP:
            kind = KIND_AD_GROUP
        elif sid_type == SID_ALIAS:
            kind = KIND_LOCAL_GROUP
        elif sid_type == SID_WELLKNOWN:
            kind = KIND_WELLKNOWN
        elif sid_type == SID_COMPUTER:
            kind = KIND_COMPUTER
        else:
            kind = KIND_UNRESOLVED
        p = Principal(sid, full, kind, sid_type=sid_type)
        p.universal = sid in UNIVERSAL_SIDS
        if kind == KIND_USER:
            self._fill_user_info(p, domain, name)
        self.cache[sid] = p
        return p

    def _fill_user_info(self, p: Principal, domain: str, name: str):
        obj = self._ad_object(p.sid) if not self._ado_failed else None
        if obj is not None:
            p.display = self._ldap_get(obj, "displayName", "") or ""
            uac = self._ldap_get(obj, "userAccountControl", 0) or 0
            p.disabled = bool(int(uac) & UF_ACCOUNTDISABLE)
            return
        try:  # tài khoản cục bộ trên máy chứa thư mục
            info = win32net.NetUserGetInfo(self.server, name, 2)
            p.display = info.get("full_name", "") or ""
            p.disabled = bool(info.get("flags", 0) & UF_ACCOUNTDISABLE)
        except pywintypes.error:
            pass

    # --------------------------------------------------------------- Bung nhóm
    def expand(self, sid: str) -> Principal:
        """Bung nhóm thành tập SID user (đệ quy, có xử lý nhóm lồng nhau)."""
        p = self.resolve(sid)
        if p.expanded or not p.is_group:
            return p
        if sid in self._expanding:  # vòng lặp nhóm lồng nhau
            return p
        self._expanding.add(sid)
        try:
            if p.universal:
                p.expand_note = "Áp dụng cho mọi user"
            elif p.kind == KIND_AD_GROUP:
                self._expand_ad_group(p)
            elif p.kind in (KIND_LOCAL_GROUP, KIND_WELLKNOWN):
                self._expand_local_group(p)
            p.member_count = len(p.members)
            p.big = (not p.universal) and p.member_count > self.big_threshold
            if p.big:
                p.expand_note = (f"Nhóm lớn ({p.member_count} user), không liệt kê từng user "
                                 f"(ngưỡng {self.big_threshold})")
        finally:
            self._expanding.discard(sid)
            p.expanded = True
        return p

    def _expand_ad_group(self, p: Principal):
        obj = self._ad_object(p.sid)
        if obj is None:
            p.expand_note = "Không tra được nhóm trên AD"
            return
        dn = self._ldap_get(obj, "distinguishedName")
        if not dn:
            p.expand_note = "Không lấy được DN của nhóm"
            return
        base = dn[dn.upper().index("DC="):] if "DC=" in dn.upper() else dn
        domain = p.name.split("\\", 1)[0]
        dn_escaped = dn.replace("\\", "\\5c").replace("(", "\\28").replace(")", "\\29").replace("*", "\\2a")
        attrs = "objectSid,sAMAccountName,displayName,userAccountControl"
        limit = 200000
        try:
            rows = self._ado_query(
                base, f"(&(objectCategory=person)(objectClass=user)"
                      f"(memberOf:1.2.840.113556.1.4.1941:={dn_escaped}))", attrs, limit) or []
            # Thành viên qua Primary Group (vd: Domain Users) không nằm trong thuộc tính member
            rid = p.sid.rsplit("-", 1)[-1]
            rows += self._ado_query(
                base, f"(&(objectCategory=person)(objectClass=user)(primaryGroupID={rid}))",
                attrs, limit) or []
        except pywintypes.com_error as e:
            p.expand_note = f"Lỗi truy vấn AD: {e}"
            self.log(f"CẢNH BÁO: Không bung được nhóm {p.name}: {e}")
            return
        for r in rows:
            raw = r["objectSid"]
            if raw is None:
                continue
            try:
                usid = win32security.ConvertSidToStringSid(pywintypes.SID(bytes(raw)))
            except (pywintypes.error, TypeError, ValueError):
                continue
            p.members.add(usid)
            if usid not in self.cache:
                uac = int(r["userAccountControl"] or 0)
                self.cache[usid] = Principal(
                    usid, f"{domain}\\{r['sAMAccountName']}", KIND_USER,
                    display=r["displayName"] or "", disabled=bool(uac & UF_ACCOUNTDISABLE),
                    sid_type=SID_USER)
        if not rows:
            p.expand_note = "Nhóm không có user"

    def _expand_local_group(self, p: Principal):
        group_name = p.name.split("\\", 1)[-1]
        members = []
        resume = 0
        try:
            while True:
                data, _, resume = win32net.NetLocalGroupGetMembers(self.server, group_name, 2, resume)
                members.extend(data)
                if not resume:
                    break
        except pywintypes.error:
            if p.kind == KIND_WELLKNOWN:
                p.expand_note = "Nhóm đặc biệt của Windows, không có danh sách thành viên"
            else:
                p.expand_note = "Không đọc được thành viên nhóm cục bộ"
            return
        member_sids = [win32security.ConvertSidToStringSid(m["sid"]) for m in members]
        # Nhóm chứa Everyone/Authenticated Users thì áp dụng cho mọi user, không cần bung tiếp
        for msid in member_sids:
            if msid in UNIVERSAL_SIDS:
                p.universal = True
                p.expand_note = f"Chứa {self.resolve(msid).name}: áp dụng cho mọi user"
                return
        for msid in member_sids:
            child = self.resolve(msid)
            if child.kind == KIND_USER:
                p.members.add(msid)
            elif child.is_group:
                self.expand(msid)
                if child.universal:
                    p.universal = True
                    p.expand_note = f"Chứa {child.name}: áp dụng cho mọi user"
                    p.members.clear()
                    return
                p.members |= child.members
