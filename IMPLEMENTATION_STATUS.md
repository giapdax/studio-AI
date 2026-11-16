# Báo cáo triển khai — 16/11/2026

Đã đọc `AGENT.md`, `app.py`, `scripts.json`, `requirements.txt`, `README.md` trước khi sửa. Repo không có `.codegraph/`, nên không dùng hoặc tự tạo index. Thư mục cũng chưa có `.git`; chưa tạo commit, push hay deploy.

## Tệp thay đổi

- Viết lại `app.py`: UI tiếng Việt, đơn giản/nâng cao, tạo theo lô, phiên bản thư viện/kịch bản, kết quả, retry, download, settings và Drive.
- Thêm `studio/__init__.py`, `storage.py`, `errors.py`, `jobs.py`, `providers.py`, `media.py`, `secrets.py`, `backup.py`, `drive.py`.
- Thêm `INSTALL_APP.bat`, `START_APP.bat`, `tools/check_environment.py`, `tools/mock_smoke.py`.
- Thêm `tests/test_studio.py`, `tests/test_ui.py`, `.github/workflows/tests.yml`.
- Cập nhật `requirements.txt`, `.gitignore`, `README.md`; thêm báo cáo này.
- Giữ nguyên `scripts.json` và `AGENT.md`. Không thấy thư mục dữ liệu người dùng trong lúc kiểm tra ban đầu; migration vẫn được kiểm thử với DB schema cũ do test tạo.

## Đã có mã triển khai

- Tải nhiều ảnh độc lập hoặc nhóm ảnh một sản phẩm; lưu ảnh nguồn và ảnh chuẩn hóa, hash và manifest.
- Thư viện phông nền có tên, preview, phiên bản, chọn lại, ẩn, xuất/nhập; mỗi công việc chụp snapshot riêng.
- Giữ đủ sáu kịch bản mặc định, chỉnh sửa và lưu phiên bản mới.
- Prompt nhận diện sản phẩm và môi trường; 5 tham chiếu, anchor ảnh đầu cho ảnh sau; riêng hanger-only không yêu cầu chạm vải.
- Mock end-to-end đã có code tạo composite ảnh có nhãn, clip ảnh tĩnh và MP4 qua FFmpeg. **Chưa chạy xuất MP4 thật tại môi trường này.**
- Worker chạy nền với SQLite status/claim/heartbeat, hạn mức 1–3 sản phẩm đồng thời qua cấu hình; retry độc lập, tiếp tục từ bước đã lưu, tạo lại riêng cảnh và lưu lịch sử.
- Hạn mức request/ngân sách ước tính từng sản phẩm; xác nhận có phí trước khi gọi thật. Không có request AI có phí nào được chạy trong phiên này.
- Adapter OpenAI phân tích/sửa ảnh, Google tạo ảnh, Veo GA Google Cloud với clip 4/6/8 giây và operation lưu bền; không tự retry request suy luận trong SDK.
- FFmpeg chuẩn hóa và ghép H.264 portrait 1080×1920/30fps, timeout và thay đầu ra bằng tệp tạm.
- Khóa trong bộ nhớ phiên/biến môi trường hoặc OS keyring; không lưu vào SQLite/JSON thường. OAuth Drive dùng OS vault, không dùng token JSON cũ.
- Sao lưu ZIP không credentials, khôi phục sang thư mục mới; chống path traversal/tên đặc biệt Windows, symlink, duplicate và giới hạn dung lượng.
- Drive OAuth, mapping mặc định sửa được, kiểm tra tài khoản/mapping, tạo bộ thư mục, upload theo hash và backup; đồng bộ thủ công để người dùng chủ động di chuyển tài khoản.
- README tiếng Việt: Windows, credentials/ADC, backup/chuyển máy, GitHub/hosting tùy chọn và giới hạn.

## Kiểm tra đã chạy

Lệnh cuối:

```text
python -m unittest discover -s tests -v
Ran 28 tests — OK (skipped=2)
python -m compileall -q app.py studio tools tests
Exit 0
```

**26 kiểm thử đạt**, bao gồm migration và bảo toàn dữ liệu cũ, snapshot/phiên bản, nhóm ảnh/ảnh gốc, claim đồng thời, recovery, hạn mức/authorization, retry từng bước/cảnh, backup roundtrip, nhập thư viện, ZIP độc hại trên Windows, kho bí mật và contract duration/resume Veo bằng SDK giả.

Hai test bỏ qua vì thiếu dependency:

1. Render UI thật với Streamlit AppTest.
2. Pipeline MOCK dùng Pillow và FFmpeg thật, xuất/giải mã MP4.

Kiểm thử orchestration dùng provider/media giả để kiểm tra trạng thái và retry; không thay thế kiểm thử mã hóa MP4 hay API thật.

Đã thử `python -m pip install -r requirements.txt keyring imageio-ffmpeg pytest`: mạng bị chặn với WinError 10013. Thử cài offline cũng thiếu gói. `python tools/check_environment.py` xác nhận thiếu Streamlit, Pillow, OpenAI, Google Gen AI, keyring; FFmpeg cũng không có trong PATH. Vì vậy chưa chạy ứng dụng trong trình duyệt hoặc `tools/mock_smoke.py` ở đây. Không yêu cầu hoặc thực hiện vượt quyền sandbox.

Phát hiện/sửa qua kiểm thử: đóng SQLite connection trước khi xóa tệp backup trên Windows; kiểm tra tên ZIP gốc trước chuẩn hóa backslash của Python trên Windows; giữ retry không chạy lại cảnh đã xong.

## Chưa xác minh hoặc chưa triển khai

- **Chưa xác minh live** OpenAI, Google ảnh, Veo Cloud, OAuth Drive, upload Drive và OS keyring. Cần dependency, tài khoản/quota và credentials của người dùng. Không khẳng định các tích hợp này đã hoạt động thực tế.
- Chưa có kiểm tra drift tự động; có cảnh báo chưa xác minh và đánh giá thủ công lưu theo sản phẩm.
- Chưa nối cảnh bằng last-frame hoặc dùng bộ asset-reference nhiều ảnh cho Veo. Cảnh độc lập có thể thiếu liên tục; trim có thể cắt hành động.
- Chưa tải video trả về chỉ bằng GCS URI. Adapter hiện yêu cầu video bytes.
- Worker chưa tách thành daemon/service; restart cần thao tác tiếp tục. Có cửa sổ không xác định nếu tắt đúng lúc provider nhận request nhưng chưa lưu operation; người dùng cần kiểm tra trước khi tiếp tục để tránh phí lặp.
- Ngân sách dựa trên đơn giá tự nhập, chưa đọc hóa đơn thực tế. Hạn mức lưu theo công việc; muốn thay đổi cho công việc hiện có cần tính năng quản lý bổ sung, UI hiện áp dụng cài đặt cho công việc mới.
- Drive là upload/backup thủ công; chưa đồng bộ hai chiều hoặc tải từng tệp trong UI. Tải ZIP backup bằng Drive để khôi phục.
- Delete phông nền là soft delete, chưa có xóa vật lý/garbage collection.
- Công việc `legacy` giữ preview/download nhưng chưa có tự nâng cấp sang pipeline mới.
- ZIP chuẩn bị trong RAM, chưa thích hợp cho nhiều GB; app localhost chưa có auth/multi-user isolation.
- CI đã thêm cấu hình, **chưa chạy trên GitHub**. Không deploy hay thay đổi Drive bên ngoài.

## Checklist tiếp nối, theo thứ tự

1. Trên máy có Internet, chạy `INSTALL_APP.bat`, rồi `START_APP.bat`.
2. Chạy lại bộ unittest để hai test phụ thuộc không bị skip; chạy `tools/mock_smoke.py` và kiểm tra MP4 thật 1080×1920, 30fps, đúng tổng thời lượng bằng ffprobe nếu có.
3. Kiểm tra UI thực tế: lưu/version/import phông nền, sửa kịch bản, tạo batch/group, retry lỗi/cảnh, restart giữa job, tải MP4/ZIP và restore sang dữ liệu mới.
4. Nhập khóa riêng trên máy, cấu hình Google Cloud ADC/project/quota; thử list model. Chỉ chạy smoke API thật sau khi đồng ý có phí trong UI. Kiểm tra Veo với SDK/tài khoản hiện tại; bổ sung GCS download nếu cần.
5. Kết nối Drive bằng OAuth Desktop; kiểm tra mapping mới, sync hai lần để xác minh không nhân đôi, đổi tài khoản rồi chuyển dữ liệu một cách chủ động.
6. Nếu dùng sản xuất: drift/quality checks, review trước khi chi video, kiểm soát chi phí từ provider, GCS support, worker riêng, persistent volume, auth và OAuth web. Chỉ triển khai hosting khi có chấp thuận.
