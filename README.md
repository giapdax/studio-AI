# Fashion AI Studio — hướng dẫn sử dụng

Studio tạo video affiliate thời trang, dùng Python/Streamlit, SQLite và thư mục dữ liệu trên máy. Mặc định chạy **MOCK**, không cần tài khoản và không gọi API có phí.

## Cài đặt trên Windows

1. Cài Python **3.11–3.13**, chọn **Add Python to PATH**. Khuyên dùng 3.13.
2. Mở `INSTALL_APP.bat`. Cần Internet để tải thư viện. Script tạo `.venv`, cài gói và kiểm tra FFmpeg.
3. Mở `START_APP.bat`. Trình duyệt mở ứng dụng tại địa chỉ localhost hiện trong terminal.
4. Giữ cửa sổ terminal mở trong lúc tạo video. Dùng Ctrl+C để dừng sau khi công việc hoàn tất.

FFmpeg được cung cấp qua `imageio-ffmpeg` nếu máy chưa có bản trong PATH. Có thể đặt `FFMPEG_EXE` tới bản FFmpeg riêng và `FFPROBE_EXE` nếu ffprobe nằm ở nơi khác. Ưu tiên libx264; trên Windows có thể dùng H.264 Media Foundation (software) khi FFmpeg không có libx264. Có thể chọn bằng `STUDIO_H264_ENCODER=libx264` hoặc `h264_mf`. FFmpeg đi kèm trình duyệt có thể thiếu bộ mã hóa H.264 và sẽ bị từ chối. Nếu không có ffprobe, ứng dụng đọc metadata bằng imageio-ffmpeg.

Cài/chạy thủ công trong PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/check_environment.py
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

## Luồng sử dụng

1. Vào **Thư viện phông nền**, đặt tên, tải ảnh và mô tả phòng/giá treo/đạo cụ/ánh sáng bằng tiếng Anh.
2. Vào **Tạo video**, tải ảnh sản phẩm. Mặc định mỗi ảnh là một sản phẩm/video độc lập. Chọn gộp nếu nhiều ảnh cùng một sản phẩm.
3. Chọn phiên bản phông nền và kịch bản; bấm **Tạo video**.
4. Ứng dụng lần lượt phân tích, lưu manifest sản phẩm, tạo 5 ảnh tham chiếu, tạo các cảnh, cắt và ghép MP4.
5. Vào **Công việc & kết quả** để xem tiến độ (cập nhật 5 giây), preview, đánh giá sai lệch, tải từng MP4 hoặc ZIP các video hoàn tất.
6. Khi lỗi, bấm **Tiếp tục / thử lại bước lỗi**. Những bước đã hoàn tất được giữ. Có thể tạo lại riêng một cảnh; clip và operation cũ được chuyển vào `history/`.

MOCK tạo **ảnh ghép và video ảnh tĩnh có nhãn MOCK**, không phân tích quần áo và không tạo chuyển động AI. Đây là chế độ kiểm tra luồng lưu trữ/xử lý/FFmpeg; không dùng nó để đánh giá chất lượng AI.

Mục tiêu đầu ra: H.264 MP4, 1080×1920, 30fps, không âm thanh. Video Veo được chuẩn hóa bằng FFmpeg. Ảnh OpenAI 1024×1536 được dùng làm đầu vào cho video 9:16; ảnh tham chiếu gốc không nhất thiết có tỷ lệ 9:16 chính xác.

## Phông nền, kịch bản và độ đồng nhất

Thư viện hỗ trợ đặt tên, xem trước, lưu phiên bản, chọn lại, ẩn khỏi thư viện và xuất/nhập ZIP. Xóa trên UI là ẩn phiên bản; không xóa tệp vật lý để giữ công việc cũ và cho phép sao lưu. Công việc luôn dùng bản sao phông nền và snapshot kịch bản đã chọn lúc tạo, nên việc sửa thư viện không thay đổi video đang chạy.

Giữ nguyên sáu kịch bản ban đầu trong `scripts.json`. Bản mặc định được đưa vào SQLite một lần; chỉnh sửa ở tab **Kịch bản** sẽ tạo phiên bản mới. Mỗi cảnh từ 1–8 giây, tối đa 12 cảnh. Các phiên bản cũ vẫn chọn lại được.

Năm góc mặc định: toàn thân treo; nhấc gấu; véo vải; macro vải/đường may; toàn thân kết. Kịch bản **Cầm móc áo POV** có bộ góc riêng, yêu cầu chỉ chạm móc, không chạm vải.

Prompt dùng mọi ảnh sản phẩm đã nhóm, phông nền nguồn và ảnh tham chiếu đầu tiên làm mốc cho những ảnh tiếp theo. Khóa nhận diện yêu cầu giữ màu, kiểu dáng, chữ/logo, vải, đường may, tỷ lệ; không suy đoán phần chưa nhìn thấy. Manifest lưu nguồn gốc/hash, thông tin nhận diện và trạng thái đồng nhất chưa xác minh. Có kiểm tra kỹ thuật miễn phí (ảnh lỗi/trống, độ phân giải, phân bố màu giữa hai góc toàn thân), tùy chọn đánh giá sai lệch bằng OpenAI có phí và duyệt thủ công. Thống kê ảnh không hiểu logo/chữ/chất vải; AI đánh giá cũng có thể sai. Giữ đúng logo, chữ nhỏ, cấu trúc vải và bàn tay tuyệt đối chưa được đảm bảo. Nguồn sản phẩm/phông nền được kiểm tra hash trước khi xử lý; sửa tệp nguồn sẽ chặn công việc.

## Kết nối AI thật và quản lý khóa

OpenAI, Google tạo ảnh và Google Drive là ba kết nối riêng. Veo GA dùng thêm danh tính Google Cloud ADC.

- OpenAI: phân tích với `gpt-4.1-mini`; sửa ảnh với `gpt-image-1.5` hoặc `gpt-image-1-mini`.
- Google ảnh: `gemini-2.5-flash-image` qua Google Gen AI SDK. Chọn nhà cung cấp ảnh trong chế độ nâng cao.
- Veo Google Cloud: `veo-3.1-generate-001` hoặc `veo-3.1-fast-generate-001`, region `us-central1`, Google Cloud project và Application Default Credentials có quyền/quota phù hợp.

Đây là danh sách có tài liệu hỗ trợ, không bảo đảm tài khoản của bạn có quyền dùng. Nút **Kiểm tra kết nối** chỉ đọc danh sách model OpenAI/Google ảnh, không suy luận có phí; nút kiểm tra ADC cho Veo chỉ làm mới xác thực, chưa kiểm tra quyền model hoặc quota tạo video. Không có nút kiểm thử video có phí tự động.

Nhập khóa tại ô mật khẩu trong ứng dụng, **không gửi khóa vào chat**. Khóa dùng trong bộ nhớ phiên; tùy chọn lưu dùng Windows Credential Manager qua `keyring`. Ứng dụng từ chối backend lưu bí mật bằng văn bản thuần. Có thể dùng biến môi trường `OPENAI_API_KEY`, `GOOGLE_API_KEY`; không lưu vào source/SQLite/manifest. Thay khóa trong ô nhập sẽ áp dụng cho công việc mới hoặc lần tiếp tục sau; công việc đang chạy giữ khóa đã nhận lúc bắt đầu.

Chuẩn bị Veo (sau khi cài Google Cloud CLI):

```powershell
gcloud auth application-default login
$env:GOOGLE_CLOUD_PROJECT = 'your-project-id'
.\START_APP.bat
```

Bật dịch vụ Cloud và xin quyền/quota theo tài liệu của Google. Cấu hình SDK hiện dùng `vertexai=True`; tài liệu Google hiện đổi tên một số trang Vertex AI thành Gemini Enterprise Agent Platform. Tích hợp này cần được xác minh thực tế với SDK/tài khoản trước khi sử dụng sản xuất.

Veo tạo clip dài **4, 6 hoặc 8 giây**; ứng dụng chọn độ dài đủ dài rồi cắt còn thời lượng kịch bản. Trong nâng cao có ba chế độ: mỗi cảnh một ảnh; lấy khung cuối của clip đã cắt làm khung đầu cảnh sau; hoặc bộ ba asset (sản phẩm, phông nền, góc tham chiếu). Chế độ asset hiện chỉ bật cho Veo 3.1 Generate tiêu chuẩn và luôn sinh 8 giây/cảnh; UI tính chi phí theo thời lượng này. Nối cảnh chỉ giúp giảm gián đoạn, không bảo đảm chuyển động/hành động liền mạch. Có thể đặt thư mục kết quả `gs://bucket/prefix/`; kết quả GCS được tải bằng ADC, kiểm tra kích thước/generation/checksum, không dùng khóa Gemini. Chỉ chấp nhận URI gs://, giới hạn tải mỗi video 1 GB.

Tài liệu chính thức đã đối chiếu ngày 16/11/2026:

- [Veo và thông báo ngừng Veo Preview trên Gemini API](https://ai.google.dev/gemini-api/docs/video).
- [Veo 3.1 GA: model ID, thời lượng và input](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/veo/3-1-generate).
- [Google tạo/chỉnh sửa ảnh](https://ai.google.dev/gemini-api/docs/image-generation).
- [OpenAI sửa ảnh](https://developers.openai.com/api/reference/python/resources/images/methods/edit).
- [OpenAI GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

## Chi phí, hàng đợi và khởi động lại

Chọn **API thật** và đánh dấu đồng ý có phí trước khi bấm tạo. UI hiển thị ước tính tổng cho số sản phẩm đang chọn. Chế độ nâng cao cho phép đặt hạn mức số yêu cầu và ngân sách ước tính **cho từng sản phẩm**, kèm đơn giá tự nhập. Đây không phải thông tin thanh toán thực tế; đặt thêm quota/hạn mức tại nhà cung cấp. Mọi lần thử lại vẫn tính vào hạn mức đã lưu, không hoàn lại khi request lỗi. Có thể chỉnh ngân sách/số yêu cầu tối đa của công việc đang dở sau khi tạm dừng hoặc lỗi; cần xác nhận có phí và không được giảm dưới số đã giữ. Các cài đặt model/prompt khác vẫn chỉ áp dụng cho công việc mới.

Công việc lưu bền trong SQLite; worker chạy trong process Streamlit, mặc định một sản phẩm đồng thời. Có thể đặt `STUDIO_CONCURRENCY=1`, `2` hoặc `3` rồi khởi động lại. Bấm tạo chỉ xếp hàng; worker xử lý nền, tiếp tục qua các lần rerun/đổi tab. Có worker CLI chạy riêng để tiếp tục khi đóng giao diện; xem mục Worker riêng bên dưới.

Worker giữ heartbeat 10 giây và claim công việc nguyên tử. Sau khi bị tắt đột ngột, đợi khoảng 2 phút: công việc running cũ chuyển thành **Bị ngắt**; bấm tiếp tục để chạy lại. Công việc queued sau restart cũng cần bấm tiếp tục. Không tự động chạy lại API thật sau restart. Operation Veo đã lưu được poll lại thay vì gửi mới. Nếu process bị ngắt đúng lúc nhà cung cấp nhận request nhưng trước khi operation/ảnh được lưu, không thể bảo đảm exactly-once: kiểm tra phía nhà cung cấp trước khi cho phép tiếp tục vì có thể phát sinh phí lặp. Google/OpenAI SDK đã tắt retry suy luận tự động.

Log SQLite chỉ chứa mã công việc, bước, loại lỗi và thời gian; không lưu raw exception của SDK. Không bật chế độ debug HTTP hoặc ghi khóa vào log bên ngoài ứng dụng.

## Google Drive và chuyển tài khoản

1. Bật Drive API trong Google Cloud, tạo OAuth **Desktop** client và tải JSON.
2. Ở **Lưu trữ & Drive**, chọn JSON rồi bấm kết nối. OAuth mở trình duyệt trên máy đang chạy ứng dụng.
3. Token và OAuth client được lưu trong kho bí mật hệ điều hành; không ghi `.private/drive_token.json` như bản cũ.
4. Kiểm tra mapping mẫu từ `AGENT.md`, sửa và **Xác minh và lưu mapping**. Hoặc **Tạo bộ thư mục mới** trong tài khoản hiện tại.
5. Bấm **Đồng bộ dữ liệu và sao lưu lên Drive** khi các công việc đã dừng. Đồng bộ gồm ảnh gốc/ảnh chuẩn hóa, phông nền, tham chiếu, clip, video cuối, manifest, lịch sử và backup ZIP. Hash giúp bỏ qua tệp không đổi và cập nhật tệp đã có.

Scope `drive.file` chỉ truy cập tệp/thư mục ứng dụng được phép. Mapping cũ có thể không truy cập được qua OAuth client mới dù bạn nhìn thấy chúng trong Drive; khi đó tạo bộ thư mục mới. Mapping không phải hằng số bắt buộc.

Đổi tài khoản: ngắt kết nối, kết nối lại trong trình duyệt với tài khoản khác, lưu mapping mới rồi chủ động đồng bộ để di chuyển dữ liệu. Ứng dụng chặn đồng bộ nếu email hiện tại khác email của mapping đã lưu. Không tự chuyển hay xóa dữ liệu ở tài khoản cũ. Drive là lưu trữ, không chạy job. Có thể đọc danh sách ZIP trong Backups rồi bấm tải và khôi phục ngay trong ứng dụng. Tệp được tải theo chunk, xác minh kích thước/hash và chỉ nhập vào thư mục mới. Chưa có đồng bộ hai chiều từng tệp; phục hồi cả dự án qua ZIP.

Nếu còn `client_secret.json`/`.private/drive_token.json` từ bản cũ, ứng dụng mới không đọc chúng; kết nối lại. Giữ hoặc dọn các tệp cũ theo chính sách riêng của bạn, tránh chia sẻ công khai.

## Sao lưu, khôi phục và dữ liệu cũ

**Chuẩn bị sao lưu đầy đủ** tạo ZIP chứa SQLite nhất quán bằng backup API, thư viện và toàn bộ tệp dự án; không chứa credentials hay source code. Chờ mọi công việc dừng trước khi sao lưu. Source code có thể sao lưu riêng/Git, còn credentials cần nhập lại trên máy mới.

**Khôi phục vào thư mục mới** giải nén vào `restores/restored_<id>`; không ghi đè dữ liệu hiện tại. Kiểm tra đường dẫn ZIP, symlink, tên đặc biệt Windows, bản ghi trùng và giới hạn giải nén 4 GB. Chỉ nhập backup từ nguồn tin cậy.

Để mở bản khôi phục:

```powershell
$env:STUDIO_DATA_DIR = 'D:\fashion-ai-studio-lite\restores\restored_<id>'
.\START_APP.bat
```

Nhập lại khóa, cấu hình ADC và kết nối lại Drive. Công việc cũ được bảo toàn qua migration SQLite schema v3 (định dạng backup vẫn là v2). Công việc tạo từ bản ứng dụng ban đầu được đánh dấu `legacy`: vẫn xem/tải video đã có, không tự chuyển sang pipeline mới; tải lại ảnh để tạo công việc mới. `scripts.json` gốc không bị sửa.

Sao lưu đầy đủ được ghi trực tiếp vào `data/exports/`; ZIP lớn hơn 128 MB hiện đường dẫn trên máy thay vì nạp vào nút download. Upload Drive dùng tệp/chunk; khôi phục ZIP giải nén theo luồng. Nút ZIP video/thư viện vẫn chuẩn bị trong RAM nên chia đợt khi số lượng lớn. Với bản sao lưu lớn hơn giới hạn upload Streamlit, dùng CLI backup bên dưới.

## Kiến trúc và kiểm thử

- `app.py`: UI tiếng Việt, form thao tác, kiểm soát việc đồng ý gọi API.
- `studio/storage.py`: SQLite/migration, phiên bản, snapshot, manifest, hạn mức và đường dẫn an toàn.
- `studio/jobs.py`: worker nền, claim/heartbeat, tiếp tục, lịch sử tạo lại cảnh.
- `studio/providers.py`: mock và adapter SDK OpenAI/Google; prompt khóa nhận diện.
- `studio/media.py`: FFmpeg không qua shell, timeout, normalize/assemble, thay tệp đầu ra nguyên tử.
- `studio/secrets.py`, `drive.py`, `backup.py`: kho bí mật, Drive và backup di chuyển máy.
- `tests/`: unittest và integration test không dùng API có phí.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py studio tools tests
.\.venv\Scripts\python.exe tools/mock_smoke.py
```

`mock_smoke.py` xuất video mock 1080×1920 thật ở `.test-data/smoke/jobs/<id>/`. Integration test còn giải mã đầu ra bằng FFmpeg. Test UI dùng Streamlit AppTest; các test phụ thuộc thư viện sẽ báo skipped nếu chưa cài. `.github/workflows/tests.yml` chuẩn bị chạy các kiểm tra trên Windows khi bạn đưa source lên GitHub; workflow chưa được chạy trong phiên phát triển này.

Kết quả thực tế và checklist tiếp nối xem `IMPLEMENTATION_STATUS.md`.

## GitHub và hosting tùy chọn

Thư mục hiện tại chưa phải Git repository. Nếu muốn lưu source trên GitHub: tạo repo riêng, xem kỹ `.gitignore`, chỉ đưa source/scripts/test/docs vào Git; không đưa `data/`, `restores/`, `.private/`, `.env`, JSON OAuth và khóa lên repo. Có thể dùng GitHub Actions ở trên để kiểm tra mock.

Streamlit Community Cloud có subdomain `*.streamlit.app`: tạo ứng dụng từ repo, chọn `app.py`, đặt secrets qua cấu hình hosting. Chưa triển khai ứng dụng trong phiên này. Hosting miễn phí có thể sleep, hạn chế CPU/RAM/thời gian, không có ổ đĩa bền, không hỗ trợ Windows Credential Manager hoặc OAuth Desktop loopback trên máy người dùng. Không coi đó là nơi đáng tin cậy để chạy job video dài. Bản hiện tại ưu tiên localhost; không đưa trực tiếp lên Internet vì chưa có đăng nhập/phân quyền/cách ly dữ liệu nhiều người dùng.

Để host thật cần persistent volume, giám sát worker CLI bằng dịch vụ hệ điều hành, xác thực người dùng, secret manager và OAuth web redirect. Có thể cấu hình domain riêng của hosting sau khi được bạn cho phép; tên miền miễn phí tùy nhà cung cấp, không mặc định có tính bền vững hay SLA.


## Duyệt ảnh, tạm dừng và tạo lại

Mặc định pipeline tự chạy hết sau khi bấm Tạo video và xác nhận có phí (nếu dùng API thật). Có thể bật dừng sau 5 tham chiếu trong nâng cao để duyệt trước khi trả phí tạo video. Ảnh bị kiểm tra kỹ thuật hoặc đánh giá AI gắn cờ luôn cần duyệt. Bấm **Duyệt 5 ảnh và tiếp tục tạo video** sau khi xem nguồn/ảnh. Quyết định duyệt gắn với hash của đúng 5 ảnh; ảnh thay đổi thì cần duyệt lại. Tùy chọn đánh giá AI thêm một request OpenAI/bộ ảnh và được cộng vào hạn mức/ước tính.

**Tạm dừng sau bước hiện tại** không hủy request đã gửi cho nhà cung cấp: app chờ request đó hoàn tất, lưu kết quả rồi dừng trước bước tiếp theo. Tiếp tục sẽ dùng lại kết quả đã có. Có thể cập nhật hạn mức công việc đã dừng mà không xóa số đã dùng.

Tạo lại góc 1 sẽ tạo lại cả bộ tham chiếu vì góc 1 là anchor. Tạo lại một góc khác chỉ tạo lại ảnh đó, nhưng vô hiệu hóa các clip/video để không dùng kết quả theo bộ ảnh cũ. Trong chế độ nối cảnh, tạo lại cảnh N còn tạo lại các cảnh từ N trở về sau. Mọi kết quả cũ được lưu trong `history/`, có thể phát sinh phí mới khi chọn API thật.

Video ghép phải qua kiểm tra codec H.264, kích thước, 30fps và tổng thời lượng trước khi có tên `final_<id>.mp4`. Metadata được lưu trong `video_metadata.json`.

## Worker riêng

Chọn **Xếp hàng cho worker riêng** trong nâng cao nếu muốn giao diện chỉ tạo job. Worker cần truy cập cùng thư mục dữ liệu và có dependencies/FFmpeg. Mở `WORKER_APP.bat` để xử lý MOCK mặc định; không gọi API có phí.

```powershell
# Worker liên tục: chỉ MOCK, tự tiếp tục MOCK bị ngắt.
.\.venv\Scripts\python.exe -m studio.worker --data-dir data --concurrency 2 --resume-mock
# Xử lý lô MOCK đang chờ rồi thoát.
.\.venv\Scripts\python.exe -m studio.worker --data-dir data --once
# CHỈ chạy khi bạn đồng ý có phí; chọn rõ job cần tiếp tục.
.\.venv\Scripts\python.exe -m studio.worker --data-dir data --job YOUR_JOB_ID --allow-paid --once
```

Worker API thật cần khóa trong biến môi trường/OS vault, Cloud project trong job và ADC trên máy worker; không đọc khóa chỉ tồn tại trong phiên trình duyệt. `--allow-paid` cho phép job real đã được xác nhận trong UI; không chạy job real chưa được xác nhận. Job lỗi/chờ duyệt không tự lặp. Ctrl+C yêu cầu dừng sau bước hiện tại. SQLite claim và hạn mức đồng thời bảo vệ khi worker/giao diện cùng chạy. Khóa bảo trì chặn worker/đổi tệp trong lúc sao lưu hoặc sync, tránh backup nửa chừng.

## Backup lớn bằng CLI

```powershell
.\.venv\Scripts\python.exe tools/backup_project.py export --data-dir data --output D:\Backups\studio-new.zip
.\.venv\Scripts\python.exe tools/backup_project.py restore --input D:\Backups\studio-new.zip --parent D:\StudioRestores
```

Không ghi đè tệp backup đã có. Restore tạo thư mục `restored_<id>` riêng; dùng `STUDIO_DATA_DIR` để mở. Không cần khóa hoặc Internet. Nhập thư viện phông nền giữ nhóm phiên bản, ảnh gốc và trạng thái ẩn; có nút khôi phục phiên bản đã ẩn trong thư viện.

Tài liệu kỹ thuật bổ sung: [Veo asset references](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/video/generate-videos-from-references), [Google Cloud Storage download](https://docs.cloud.google.com/python/docs/reference/storage/latest/google.cloud.storage.blob.Blob).
