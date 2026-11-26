# NtfsAudit: Kiểm tra phân quyền NTFS và xuất báo cáo Excel

Công cụ quét một thư mục và các thư mục con (mặc định 3 cấp: `Gốc\Con\Cháu`), đọc phân quyền NTFS,
bung nhóm Active Directory thành từng user và xuất báo cáo Excel bằng tiếng Việt.

## Cách dùng

1. Chạy `dist\NtfsAudit.exe` (Windows sẽ hỏi quyền Administrator).
2. Bấm **Chọn...** để chọn thư mục gốc (ổ local hoặc `\\server\share`).
3. Kiểm tra tên file Excel (mặc định lưu ở `Documents`), chỉnh tùy chọn nếu cần.
4. Bấm **Bắt đầu quét**. Xong sẽ hỏi có mở báo cáo không.

| Tùy chọn | Ý nghĩa |
|---|---|
| Số cấp thư mục | 1 = chỉ thư mục gốc, 3 = Gốc\Con\Cháu |
| Bung nhóm AD thành từng user | Cần bật để có sheet "User - Thư mục" và "Ma trận user" |
| Ẩn tài khoản hệ thống | Bỏ SYSTEM, CREATOR OWNER, TrustedInstaller... khỏi báo cáo |
| Ẩn nhóm quản trị | Bỏ Administrators, Domain Admins, Enterprise Admins khỏi báo cáo và khỏi phép tính |
| Ẩn user bị vô hiệu hóa | Không liệt kê user đã bị disable trong AD |
| Ngưỡng nhóm lớn | Nhóm có nhiều user hơn ngưỡng (vd Domain Users) không bị bung ra từng user |

Chạy dòng lệnh (không cần GUI):

```
NtfsAudit.exe --path "D:\Data" --out "D:\BaoCao.xlsx" --depth 3
```

Tham số khác: `--no-expand`, `--show-system`, `--hide-admin`, `--show-disabled`, `--big-group 500`.
Bản exe được build dạng `--windowed` nên chạy dòng lệnh sẽ không in nhật ký ra màn hình. Muốn xem nhật ký thì chạy bằng `python main.py ...`.

## Các sheet trong báo cáo

| Sheet | Nội dung |
|---|---|
| Tổng quan | Thông tin quét, số liệu, chú giải màu, biểu đồ phân bố quyền, top thư mục và user có quyền ghi |
| Danh sách thư mục | Cây thư mục, chủ sở hữu, kế thừa (đánh dấu **BỊ NGẮT**), số user theo từng mức quyền |
| Thư mục - Quyền | **Thư mục có những ai truy cập**: từng dòng quyền (ACE), Allow/Deny, kế thừa hay gán trực tiếp, áp dụng cho |
| User - Thư mục | **User truy cập được thư mục nào**: quyền hiệu lực, có quyền qua nhóm nào, bị Deny bởi nhóm nào |
| Ma trận nhóm | Thư mục × tài khoản/nhóm trong ACL, ô tô màu |
| Ma trận user | Thư mục × user, ô tô màu theo quyền hiệu lực |
| Thành viên nhóm | Thành viên của từng nhóm (đã bung nhóm lồng nhau) |
| Lỗi - Cảnh báo | Thư mục không đọc được, SID mồ côi, nhóm lớn không bung... |

Mức quyền: **FC** Toàn quyền (xanh lá), **RW** Đọc/Ghi (xanh dương), **R** Chỉ đọc (vàng),
**ĐB** Đặc biệt (xám, quyền lẻ không đọc được dữ liệu), **TC** Từ chối (đỏ).

## Cách tính quyền hiệu lực

- Duyệt DACL theo đúng thứ tự Windows: bit nào đã bị Deny thì Allow phía sau không cấp lại được, và ngược lại.
- Token của user gồm: chính user, các nhóm có trong ACL mà user là thành viên (kể cả lồng nhau, kể cả Primary Group),
  Everyone, Authenticated Users và nhóm cục bộ chứa hai nhóm này (vd BUILTIN\Users).
- Tính riêng quyền trên thư mục và quyền trên file bên trong (ACE có cờ OI), rồi gộp thành một mức.
- "Bị Deny một phần" nghĩa là user vẫn có quyền nhưng một số quyền đọc/ghi bị chặn.

## Giới hạn

- Chỉ tính quyền NTFS, **không tính Share permission**.
- User chỉ có quyền qua nhóm lớn (vượt ngưỡng) hoặc Everyone/Authenticated Users sẽ không hiện từng người
  trong "User - Thư mục". Quyền của nhóm đó xem ở "Thư mục - Quyền" và "Ma trận nhóm". Muốn thấy từng user thì tăng ngưỡng.
- Chỉ bung thành viên trong cùng domain với nhóm. Thành viên từ domain khác (Foreign Security Principal) không được bung.
- Không tính quyền ngầm của Owner, các nhóm INTERACTIVE/NETWORK, và privilege như Backup/Restore.
- ACE dạng object/callback (hiếm gặp trên file server) không được phân tích, có ghi trong sheet cảnh báo.
- Bỏ qua junction/symlink để tránh vòng lặp.

## Phát triển

Build trên máy mới: cài Python 3.9+ bản 64-bit, copy mã nguồn (không cần `.venv`, `build`, `dist`), rồi chạy `build.bat`.
Kết quả nằm ở `dist\NtfsAudit.exe`.

Hoặc làm tay:

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python main.py                     # mở GUI
.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed --uac-admin --name NtfsAudit main.py
```

Cấu trúc mã:

| File | Vai trò |
|---|---|
| `ntfs_audit/scanner.py` | Duyệt thư mục, đọc ACL (hỗ trợ đường dẫn dài, Backup semantics) |
| `ntfs_audit/rights.py` | Quy đổi mã quyền sang mức FC/RW/R/ĐB/TC |
| `ntfs_audit/identity.py` | Phân giải SID, bung nhóm AD (LDAP) và nhóm cục bộ |
| `ntfs_audit/analysis.py` | Tính quyền hiệu lực cho từng user và nhóm |
| `ntfs_audit/excel.py` | Xuất Excel |
| `ntfs_audit/gui.py` | Giao diện Tkinter |
| `tools/make_test_tree.ps1` | Tạo cây thư mục mẫu để kiểm thử |
