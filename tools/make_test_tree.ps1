# Tạo cây thư mục mẫu với nhiều kiểu phân quyền để kiểm thử công cụ.
param([string]$Root = "$env:TEMP\ntfs_test")

Remove-Item $Root -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path `
    "$Root\KeToan\BaoCao\2026", "$Root\KeToan\HoaDon", "$Root\NhanSu\HoSo\Cap4", `
    "$Root\ChungChung\TaiLieu" | Out-Null

$me = "$env:USERDOMAIN\$env:USERNAME"
# Ngắt kế thừa, chỉ Administrators, SYSTEM và user hiện tại (Modify)
icacls "$Root\NhanSu" /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "${me}:(OI)(CI)M"
# Everyone chỉ đọc
icacls "$Root\ChungChung" /grant "*S-1-1-0:(OI)(CI)RX"
# Deny ghi cho BUILTIN\Users
icacls "$Root\KeToan\HoaDon" /deny "*S-1-5-32-545:(OI)(CI)W"
# Users được Modify chỉ trên thư mục (không áp xuống file)
icacls "$Root\KeToan\BaoCao" /grant "*S-1-5-32-545:(CI)M"
# Nhóm AD: Domain Admins (nhóm nhỏ) và Domain Users (nhóm lớn, thành viên qua primaryGroupID)
$domSid = ([Security.Principal.WindowsIdentity]::GetCurrent().User.AccountDomainSid).Value
icacls "$Root\KeToan" /grant "*$domSid-512:(OI)(CI)M" "*$domSid-513:(OI)(CI)RX"
# Quyền lẻ: chỉ duyệt thư mục
icacls "$Root\KeToan\BaoCao\2026" /grant "*S-1-5-32-546:(X)"
