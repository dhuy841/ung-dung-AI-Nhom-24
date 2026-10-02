# ClubSpace — Hệ thống quản lý câu lạc bộ sinh viên

Ứng dụng web Flask + SQLite cho phép quản lý thành viên, ban chuyên môn, hoạt động, điểm danh, nhiệm vụ và thông báo. Ba trợ lý AI hỗ trợ soạn thông báo, tóm tắt ghi chú/phản hồi, và gợi ý phân công dựa trên kỹ năng/lịch rảnh thành viên.

## Chạy ứng dụng

Yêu cầu Python 3.10 trở lên.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Mở `http://127.0.0.1:5000`.

| Vai trò | Tên đăng nhập | Mật khẩu |
| --- | --- | --- |
| Chủ nhiệm | `admin` | `admin123` |
| Thành viên | `member` | `member123` |

Chỉ có hai tài khoản demo: chủ nhiệm và thành viên. Khi nâng cấp cơ sở dữ liệu cũ, ứng dụng sẽ xóa tài khoản demo trưởng ban cũ (`lead@club.local`); vai trò trưởng ban vẫn được hỗ trợ và chủ nhiệm có thể tạo tài khoản với vai trò đó khi cần. Dữ liệu mặc định nằm trong `club.db`.

## Cấu hình AI

AI sử dụng OpenAI Chat Completions. Không cần API key để dùng phần quản lý; để sử dụng AI, cần có OpenAI API key. API key có thể chịu phí theo mức sử dụng OpenAI.

```powershell
# Mở cùng cửa sổ PowerShell nơi chạy ứng dụng và thay bằng key của bạn.
$env:AI_API_KEY = "your-openai-api-key"
python app.py
```

Giữ PowerShell đó mở khi dùng ứng dụng. Nếu ứng dụng đang chạy, nhấn `Ctrl+C`, đặt biến môi trường rồi chạy lại `python app.py`. Biến `$env:AI_API_KEY` chỉ có hiệu lực trong cửa sổ PowerShell hiện tại. Không gửi hoặc commit API key. Tùy chọn thay endpoint/model nếu cần:

```powershell
$env:AI_BASE_URL = "https://api.openai.com/v1"
$env:AI_MODEL = "gpt-4o-mini"
$env:CLUB_SECRET_KEY = "replace-with-a-long-random-secret"
python app.py
```

Nếu chưa đặt `AI_API_KEY`, hệ thống quản lý vẫn hoạt động nhưng các chức năng AI sẽ báo rõ là cần cấu hình OpenAI API key.

## Email xác minh và khôi phục mật khẩu

Đăng ký tài khoản cần họ tên, tên đăng nhập, email và mật khẩu tối thiểu 8 ký tự; mã 6 chữ số được gửi qua email, có hạn 10 phút và giới hạn 5 lần nhập. Quên mật khẩu sẽ gửi mã dùng một lần đến email của tài khoản. Việc nhận được mã xác nhận người dùng có thể truy cập hộp thư đó; ứng dụng không thể tra cứu danh sách tài khoản Google riêng tư.

Để gửi email thật qua Gmail, bật xác minh 2 bước cho tài khoản gửi và tạo **App Password** (không dùng mật khẩu Gmail thông thường). Trong PowerShell đặt các biến sau trước khi chạy ứng dụng:

```powershell
$env:MAIL_USERNAME = "club.manager@gmail.com"
$env:MAIL_PASSWORD = "your-16-character-app-password"
$env:MAIL_FROM = $env:MAIL_USERNAME
$env:MAIL_SERVER = "smtp.gmail.com"
$env:MAIL_PORT = "587"
python app.py
```

Không chia sẻ hoặc commit App Password. Nếu SMTP chưa được cấu hình, các chức năng quản lý vẫn dùng được nhưng đăng ký/xác minh/khôi phục email sẽ báo lỗi cấu hình thay vì giả vờ đã gửi mã. Email do chủ nhiệm tạo cũng phải xác minh; tài khoản có thể đăng nhập nhưng cần vào avatar → **Hồ sơ của tôi** để xác minh email trước khi dùng các chức năng khác.

Thông tin tài khoản demo vẫn nằm trong bảng hướng dẫn phía trên nhưng không hiển thị trên màn hình đăng nhập.

## Chức năng

- Đăng nhập bằng session cookie; phân quyền chủ nhiệm, trưởng ban và thành viên.
- Đăng ký và khôi phục mật khẩu bằng mã OTP gửi email; tài khoản chưa xác minh chỉ vào được trang hồ sơ để hoàn tất xác minh.
- Thao tác làm thay đổi dữ liệu (thêm, sửa, điểm danh, xác minh/đặt lại mật khẩu) yêu cầu xác nhận trước và báo kết quả sau khi xong. Đăng nhập, đăng xuất, gửi mã OTP và tạo nội dung AI không hiện hộp xác nhận.
- Quản lý hồ sơ/kỹ năng/lịch rảnh thành viên và ban chuyên môn (tạo hồ sơ/ban bằng vai trò chủ nhiệm).
- Nhấn avatar để xem và cập nhật hồ sơ của tài khoản đang đăng nhập; mọi vai trò có thể sửa thông tin cá nhân và đổi mật khẩu (cần nhập mật khẩu hiện tại). Vai trò và tên đăng nhập không thể tự sửa.
- Đổi email từ trang hồ sơ sẽ gửi mã OTP đến địa chỉ mới; chỉ cập nhật sau khi xác minh.
- Tạo hoạt động, cập nhật trạng thái, ghi nhận điểm danh và tra cứu lịch sử tham gia.
- Trang **Lịch sử của tôi** cho biết từng sự kiện ở đâu, thời gian nào và trạng thái điểm danh cá nhân.
- Giao nhiệm vụ, cập nhật trạng thái và theo dõi hạn hoàn thành; mức ưu tiên bình thường/quan trọng/khẩn cấp được phân biệt bằng màu.
- Đăng thông báo, xem thống kê tổng quan.
- AI sinh thông báo, tóm tắt hoạt động, gợi ý phân công; yêu cầu kiểm tra nội dung AI trước khi sử dụng.

## Kiểm thử

```powershell
python -m unittest discover -s tests -v
```

Các kiểm thử bao gồm xác minh email/đăng ký, đặt lại mật khẩu, phân quyền hoạt động, điểm danh và lịch sử, trạng thái nhiệm vụ, và lỗi cấu hình/đầu vào AI.

Khi chạy lần đầu, ứng dụng bổ sung dữ liệu demo gồm thành viên, hoạt động đã diễn ra/sắp tới, lịch sử điểm danh cá nhân và nhiệm vụ có mức ưu tiên. Dữ liệu được thêm theo cách idempotent, không tạo bản sao khi khởi động lại.

## Ghi chú triển khai

Đây là bản MVP phục vụ học tập và demo. Trước khi triển khai công khai, cần đặt `CLUB_SECRET_KEY` riêng, chuyển sang HTTPS, bổ sung chính sách mật khẩu/CSRF và quy trình sao lưu cơ sở dữ liệu phù hợp.
