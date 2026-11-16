"""Vietnamese UI. Run: python -m streamlit run app.py."""
import json
import os
from pathlib import Path

import streamlit as st

from studio import backup, drive, media, quality, secrets
from studio.errors import StudioError
from studio.jobs import Runner
from studio.providers import MODELS, MODEL_SOURCES, clip_duration, test_connection, test_veo_credentials
from studio.storage import Store, uid

BASE = Path(__file__).resolve().parent
DATA = Path(os.getenv('STUDIO_DATA_DIR', str(BASE / 'data'))).resolve()


@st.cache_resource
def resources(directory):
    store = Store(directory)
    store.seed_scripts(BASE / 'scripts.json')
    return store, Runner(store, int(os.getenv('STUDIO_CONCURRENCY', '1')))


def error_notice(error):
    # Provider errors can contain URLs/keys. Do not display or persist their text.
    if isinstance(error, StudioError):
        st.error(str(error))
    else:
        st.error(f'Thao tác thất bại ({type(error).__name__}). Kiểm tra kết nối, quyền truy cập, cấu hình và thư viện đã cài.')


def settings():
    with st.sidebar:
        st.header('Cài đặt AI')
        advanced = st.toggle('Chế độ nâng cao', value=False)
        mode = st.radio('Chế độ tạo', ['mock', 'real'], format_func=lambda x: 'Thử nghiệm miễn phí (MOCK)' if x == 'mock' else 'API thật (có phí)')
        st.caption('MOCK tạo ảnh ghép và video ảnh tĩnh có nhãn; không mô phỏng chất lượng AI.')
        openai_key = st.text_input('Khóa OpenAI', value=secrets.read('openai'), type='password')
        google_key = st.text_input('Khóa Google cho tạo ảnh', value=secrets.read('google'), type='password')
        if st.button('Lưu khóa vào kho bí mật hệ điều hành'):
            try:
                if openai_key:
                    secrets.save('openai', openai_key)
                if google_key:
                    secrets.save('google', google_key)
                st.success('Đã lưu an toàn trên máy này.')
            except Exception as error:
                error_notice(error)
        for provider, label, key in [('openai', 'OpenAI', openai_key), ('google', 'Google ảnh', google_key)]:
            if st.button('Kiểm tra kết nối ' + label, disabled=not key):
                try:
                    models = test_connection(provider, key)
                    st.success(f'Đã kết nối; đọc được {len(models)} model. Chưa gọi suy luận có phí.')
                except Exception as error:
                    error_notice(error)
        options = {'mode': mode, 'analysis_model': MODELS['analysis'][0], 'image_provider': 'openai', 'image_model': MODELS['openai_image'][0], 'video_model': MODELS['video'][0], 'width': 1080, 'height': 1920, 'extra_prompt': '', 'max_calls': 20, 'budget_usd': 20.0, 'analysis_cost': 0.05, 'image_cost': 0.25, 'video_cost': 0.5, 'cloud_project': os.getenv('GOOGLE_CLOUD_PROJECT', '')}
        options.update(video_conditioning='first_frame', output_gcs_uri='', review_before_video=False, ai_quality_review=False, review_cost=0.10, external_worker=False)
        if advanced:
            options['analysis_model'] = st.selectbox('Model phân tích OpenAI', MODELS['analysis'])
            options['image_provider'] = st.selectbox('Nhà cung cấp ảnh', ['openai', 'google'])
            options['image_model'] = st.selectbox('Model tạo/sửa ảnh', MODELS[options['image_provider'] + '_image'])
            options['video_model'] = st.selectbox('Model Veo GA (Google Cloud)', MODELS['video'])
            conditioning = ['first_frame', 'continuity'] + (['asset_references'] if options['video_model'] == 'veo-3.1-generate-001' else [])
            options['video_conditioning'] = st.selectbox('Giữ nhất quán giữa cảnh', conditioning, format_func=lambda x: {'first_frame': 'Mỗi cảnh dùng một ảnh tham chiếu', 'continuity': 'Dùng khung cuối cảnh trước để nối cảnh', 'asset_references': 'Bộ ba ảnh sản phẩm + phông nền + góc tham chiếu (8 giây/cảnh)'}[x])
            options['review_before_video'] = st.checkbox('Dừng để tôi duyệt 5 ảnh trước khi tạo video', value=False)
            options['ai_quality_review'] = mode == 'real' and st.checkbox('Đánh giá sai lệch bằng OpenAI (thêm 1 yêu cầu có phí / bộ ảnh)')
            if options['ai_quality_review']:
                options['review_cost'] = st.number_input('Ước tính USD / đánh giá AI', 0.001, 10.0, 0.10, format='%.3f')
            options['output_gcs_uri'] = st.text_input('Thư mục kết quả GCS (tùy chọn)', placeholder='gs://your-bucket/fashion-output/')
            options['external_worker'] = st.checkbox('Xếp hàng cho worker riêng', value=False)
            if options['external_worker']:
                st.caption('Worker riêng cần khóa trong biến môi trường/kho bí mật, không đọc khóa chỉ nhập trong phiên này. Xem README để chạy worker.')
            options['extra_prompt'] = st.text_area('Chỉ dẫn bổ sung (English)', max_chars=2000)
            options['max_calls'] = st.number_input('Giới hạn yêu cầu có phí / sản phẩm', 1, 100, 20)
            options['budget_usd'] = st.number_input('Ngân sách ước tính USD / sản phẩm', 0.1, 1000.0, 20.0)
            for field, label, default in [('analysis_cost', 'USD / phân tích', 0.05), ('image_cost', 'USD / ảnh', 0.25), ('video_cost', 'USD / giây Veo sinh ra', 0.5)]:
                options[field] = st.number_input('Ước tính ' + label, 0.001, 10.0, default, format='%.3f')
            st.caption('Hạn mức dựa trên đơn giá bạn nhập, không phải hóa đơn thực tế. Đặt thêm hạn mức trong tài khoản API. Đặt STUDIO_CONCURRENCY=1..3 rồi khởi động lại để đổi số sản phẩm chạy đồng thời.')
            if st.button('Xóa khóa AI trong kho bí mật'):
                try:
                    secrets.delete('openai')
                    secrets.delete('google')
                    st.success('Đã xóa khóa đã lưu. Tải lại trang để xóa khóa trong phiên.')
                except Exception as error:
                    error_notice(error)
        if mode == 'real':
            options['cloud_project'] = st.text_input('Google Cloud project cho Veo', value=options['cloud_project'])
            st.caption('Veo dùng ADC trên máy và quyền/quota Cloud. Khóa Gemini chỉ dùng tạo ảnh. Xem README để cấu hình.')
            if st.button('Kiểm tra ADC cho Veo (không tạo video)'):
                try:
                    st.json(test_veo_credentials(options['cloud_project']))
                    st.caption('Xác thực ADC không xác nhận quyền model hoặc quota Veo.')
                except Exception as error:
                    error_notice(error)
        options['authorized'] = mode == 'real' and st.checkbox('Tôi đồng ý gọi API có phí cho các sản phẩm tạo trong lần bấm tiếp theo.')
        return options, (openai_key, google_key), advanced


def dispatch_job(store, runner, identity, keys):
    snapshot = json.loads(store.job(identity)['snapshot'])
    if snapshot['options'].get('external_worker'):
        store.execute("UPDATE jobs SET status='queued',pause_requested=0 WHERE id=? AND status IN ('failed','paused','interrupted')", (identity,))
        return True
    return runner.submit(identity, keys)


def backgrounds_tab(store):
    st.subheader('Thư viện phông nền')
    backgrounds = store.rows('SELECT * FROM backgrounds WHERE deleted=0 ORDER BY created DESC,version DESC')
    source = st.selectbox('Lưu mới hoặc thêm phiên bản', [None] + backgrounds, format_func=lambda b: 'Phông nền mới' if b is None else f"{b['name']} · v{b['version']}")
    with st.form('background_form'):
        name = st.text_input('Tên phông nền', value=source['name'] if source else '')
        description = st.text_area('Mô tả phòng, giá treo, đạo cụ và ánh sáng (English)', max_chars=4000)
        uploaded = st.file_uploader('Ảnh phông nền', type=['png', 'jpg', 'jpeg', 'webp'])
        if st.form_submit_button('Lưu phiên bản phông nền'):
            try:
                if not uploaded:
                    raise StudioError('Cần ảnh phông nền.')
                store.add_background(name, uploaded.getvalue(), description, source['family'] if source else None)
                st.rerun()
            except Exception as error:
                error_notice(error)
    if st.checkbox('Hiện các phiên bản đã ẩn'):
        for bg in store.rows('SELECT * FROM backgrounds WHERE deleted=1 ORDER BY created DESC'):
            st.caption(f"{bg['name']} · v{bg['version']}")
            if st.button('Khôi phục vào thư viện', key='restore_bg_' + bg['id']):
                store.execute('UPDATE backgrounds SET deleted=0 WHERE id=?', (bg['id'],))
                st.rerun()
    for bg in backgrounds:
        with st.expander(f"{bg['name']} · phiên bản {bg['version']}"):
            try:
                st.image(str(store.path(bg['file'])), width=320)
                st.json(json.loads(bg['manifest']))
            except Exception as error:
                error_notice(error)
            confirm = st.checkbox('Xác nhận ẩn phiên bản khỏi thư viện', key='hide_confirm_' + bg['id'])
            if st.button('Xóa khỏi thư viện', key='hide_' + bg['id'], disabled=not confirm):
                store.execute('UPDATE backgrounds SET deleted=1 WHERE id=?', (bg['id'],))
                st.rerun()
    if st.button('Chuẩn bị xuất thư viện'):
        st.session_state['backgrounds_archive'] = backup.export_backup(store, backgrounds_only=True)
    if 'backgrounds_archive' in st.session_state:
        st.download_button('Tải ZIP thư viện', st.session_state['backgrounds_archive'], 'backgrounds.zip', 'application/zip')
    imported = st.file_uploader('Nhập ZIP thư viện', type=['zip'], key='background_import')
    if st.button('Nhập phông nền thành các mục mới', disabled=not imported):
        try:
            count = backup.import_backgrounds(store, imported.getvalue())
            st.success(f'Đã nhập {count} phông nền. Làm mới trang để xem.')
        except Exception as error:
            error_notice(error)


def scripts_tab(store):
    st.subheader('Sáu kịch bản và lịch sử phiên bản')
    script = st.selectbox('Phiên bản kịch bản', store.scripts(), format_func=lambda s: f"{s['name']} · v{s['version']} · {sum(s['durations'])} giây")
    st.caption('Mỗi dòng: số giây | hành động bằng tiếng Anh. Lưu tạo phiên bản mới; công việc cũ giữ nguyên kịch bản.')
    with st.form('script_editor'):
        name = st.text_input('Tên kịch bản', value=script['name'])
        text = st.text_area('Các cảnh', value='\n'.join(f'{d} | {a}' for d, a in zip(script['durations'], script['actions'])), height=230)
        if st.form_submit_button('Lưu phiên bản kịch bản'):
            try:
                scenes = [line.split('|', 1) for line in text.splitlines() if line.strip()]
                if any(len(s) != 2 for s in scenes):
                    raise StudioError('Mỗi dòng cần có số giây | hành động.')
                updated = {'id': script['id'], 'name': name, 'durations': [int(s[0].strip()) for s in scenes], 'actions': [s[1].strip() for s in scenes]}
                store.save_script(updated)
                st.rerun()
            except Exception as error:
                error_notice(error)


def create_tab(store, runner, options, keys, advanced):
    st.subheader('Tạo một video cho mỗi sản phẩm')
    backgrounds = store.rows('SELECT * FROM backgrounds WHERE deleted=0 ORDER BY name, version DESC')
    if not backgrounds:
        st.info('Lưu một phông nền trong tab Thư viện trước khi tạo video.')
        return
    uploaded = st.file_uploader('Ảnh sản phẩm — mặc định mỗi ảnh là một sản phẩm', type=['png', 'jpg', 'jpeg', 'webp'], accept_multiple_files=True, key='products')
    grouped = st.checkbox('Gộp toàn bộ ảnh vừa chọn thành một sản phẩm (nhiều góc chụp)', value=False)
    background = st.selectbox('Phông nền đã lưu', backgrounds, format_func=lambda b: f"{b['name']} · v{b['version']}")
    script = st.selectbox('Kịch bản đã lưu', store.scripts(), format_func=lambda s: f"{s['name']} · v{s['version']} · {sum(s['durations'])} giây", key='create_script')
    st.image(str(store.path(background['file'])), width=240)
    if advanced:
        st.caption('Đổi thời lượng bằng cách lưu phiên bản ở tab Kịch bản rồi chọn tại đây.')
    count = 1 if grouped and uploaded else len(uploaded)
    clip_seconds = sum(clip_duration(d, options['video_conditioning']) for d in script['durations'])
    estimate = options['analysis_cost'] + 5 * options['image_cost'] + clip_seconds * options['video_cost'] + (options['review_cost'] if options['ai_quality_review'] else 0)
    if options['mode'] == 'real':
        st.warning(f'{count} sản phẩm; ước tính lần chạy đầu {count * estimate:.2f} USD theo đơn giá cài đặt. Veo sinh {clip_seconds} giây/sản phẩm rồi cắt còn {sum(script["durations"])} giây. Có thể đứt mạch giữa cảnh.')
    else:
        st.info('MOCK: tạo 5 ảnh tham chiếu và MP4 9:16 từ ảnh tĩnh, không gọi AI.')
    if st.button('Tạo video', type='primary', disabled=not uploaded or (options['mode'] == 'real' and not options['authorized'])):
        try:
            media.check()
            if len(uploaded) > 30:
                raise StudioError('Mỗi đợt tối đa 30 ảnh.')
            if options['mode'] == 'real':
                missing_keys = not keys[0] or (options['image_provider'] == 'google' and not keys[1])
                if not options['cloud_project'] or (missing_keys and not options['external_worker']):
                    raise StudioError('Cần khóa OpenAI, project Cloud và khóa Google nếu dùng ảnh Google.')
                if estimate > options['budget_usd'] or 6 + len(script['actions']) + int(options['ai_quality_review']) > options['max_calls']:
                    raise StudioError('Hạn mức hiện tại chưa đủ cho một sản phẩm.')
            groups = [[f.getvalue() for f in uploaded]] if grouped else [[f.getvalue()] for f in uploaded]
            for images in groups:
                identity = store.create_job(images, background, script, dict(options))
                dispatch_job(store, runner, identity, keys)
            st.success(f'Đã xếp hàng {len(groups)} sản phẩm. Xem tiến độ tại Công việc & kết quả.')
        except Exception as error:
            error_notice(error)


@st.fragment(run_every=5)
def results_tab(store, runner, options, keys):
    store.recover()
    st.subheader('Công việc & kết quả')
    st.caption('Tự cập nhật mỗi 5 giây. Công việc tiếp tục khi đổi tab; khi tắt ứng dụng, dữ liệu đã hoàn tất vẫn được giữ.')
    if st.button('Chuẩn bị ZIP tất cả video hoàn tất'):
        st.session_state['videos_archive'] = backup.videos_zip(store)
    if 'videos_archive' in st.session_state:
        st.download_button('Tải ZIP video', st.session_state['videos_archive'], 'videos.zip', 'application/zip')
    for job in store.rows('SELECT * FROM jobs ORDER BY created DESC'):
        label = {'queued': 'Chờ xử lý', 'running': 'Đang xử lý', 'failed': 'Lỗi', 'complete': 'Hoàn tất', 'interrupted': 'Bị ngắt', 'created': 'Dữ liệu cũ', 'awaiting_review': 'Chờ duyệt ảnh', 'paused': 'Tạm dừng', 'editing': 'Đang cập nhật'}.get(job['status'], job['status'])
        with st.expander(f"{job['id'][:10]} · {job['mode'].upper()} · {label}"):
            folder = store.path(f"jobs/{job['id']}")
            st.caption(f"Lần chạy: {job['attempts']} · yêu cầu đã giữ hạn mức: {job['calls']} · chi phí ước tính đã giữ: {job['reserved_usd']:.2f} USD")
            st.caption('Bước hiện tại: ' + job['stage'])
            if job['error']:
                st.warning(job['error'])
            snapshot = json.loads(job['snapshot'])
            if snapshot:
                st.write(f"{snapshot['script']['name']} · {sum(snapshot['script']['durations'])} giây")
                st.caption('Kiểm tra kỹ thuật ảnh tự động không chứng minh độ đúng của logo/chữ/vải. Đánh giá AI cũng có thể sai; hãy duyệt nguồn và 5 góc tham chiếu.')
                sources = st.columns(2)
                sources[0].image(str(store.path(snapshot['products'][0])), caption='Ảnh sản phẩm nguồn', width=180)
                sources[1].image(str(store.path(snapshot['background_file'])), caption='Phông nền đã khóa', width=180)
                columns = st.columns(5)
                for i in range(5):
                    ref = folder / f'reference_{i + 1:02}.png'
                    if ref.exists():
                        columns[i].image(str(ref), caption=f'Góc {i + 1}')
                review_path = folder / 'quality_review.json'
                if review_path.exists():
                    st.caption('Đánh giá đã lưu: ' + json.loads(review_path.read_text(encoding='utf-8'))['status'])
                for filename, title in [('quality_report.json', 'Kiểm tra ảnh miễn phí'), ('ai_quality_report.json', 'Đánh giá AI (không bảo đảm chính xác)')]:
                    report_path = folder / filename
                    if report_path.exists():
                        st.caption(title)
                        st.json(json.loads(report_path.read_text(encoding='utf-8')), expanded=False)
            final = folder / f"final_{job['id']}.mp4"
            if final.exists():
                st.video(str(final))
                st.download_button('Tải MP4', final.read_bytes(), f"{job['mode']}_{final.name}", 'video/mp4', key='download_' + job['id'])
            if job['mode'] == 'legacy':
                st.info('Công việc bản cũ được giữ để xem/tải. Tạo công việc mới để dùng pipeline mới; sao lưu vẫn giữ tệp cũ.')
                continue
            can_retry = job['status'] in ('failed', 'interrupted', 'queued', 'paused')
            paid_confirm = job['mode'] == 'mock' or st.checkbox('Tôi cho phép tiếp tục công việc này, gồm yêu cầu có phí còn thiếu.', key='paid_retry_' + job['id'])
            if job['status'] in ('running', 'queued'):
                if st.button('Tạm dừng sau bước hiện tại', key='pause_' + job['id']):
                    store.pause(job['id'])
                    st.info('Đã yêu cầu dừng. Yêu cầu đã gửi đến nhà cung cấp cần hoàn tất trước khi dừng.')
            if snapshot['options'].get('external_worker'):
                st.info('Công việc dùng worker riêng. Worker cần --allow-paid để xử lý API thật; khóa cần nằm trong biến môi trường/kho bí mật của worker.')
            if st.button('Tiếp tục / thử lại bước lỗi', key='retry_' + job['id'], disabled=not can_retry or not paid_confirm):
                if dispatch_job(store, runner, job['id'], keys):
                    st.success('Đã đưa vào hàng đợi.')
                else:
                    st.info('Công việc đã có trong hàng đợi của phiên này.')
            stopped = job['status'] in ('failed', 'interrupted', 'complete', 'awaiting_review', 'paused')
            references = [folder / f'reference_{i:02}.png' for i in range(1, 6)]
            if stopped and all(ref.exists() for ref in references):
                note = st.text_input('Ghi chú đánh giá', max_chars=2000, key='review_note_' + job['id'])
                if job['status'] == 'awaiting_review':
                    if st.button('Duyệt 5 ảnh và tiếp tục tạo video', key='approve_' + job['id'], disabled=not paid_confirm):
                        try:
                            runner.approve_references(job['id'], True, note)
                            dispatch_job(store, runner, job['id'], keys)
                            st.success('Đã duyệt đúng bộ ảnh hiện tại và xếp hàng tạo video.')
                        except Exception as error:
                            error_notice(error)
                    if st.button('Đánh dấu ảnh sai lệch', key='reject_' + job['id']):
                        try:
                            runner.approve_references(job['id'], False, note)
                            st.warning('Đã lưu sai lệch; chọn ảnh cần tạo lại bên dưới.')
                        except Exception as error:
                            error_notice(error)
            if snapshot and stopped:
                view = st.number_input('Góc tham chiếu cần tạo lại', 1, 5, 1, key='ref_retry_' + job['id'])
                st.caption('Tạo lại ảnh sẽ vô hiệu hóa các clip để tránh dùng ảnh cũ; tạo lại góc 1 còn tạo lại cả bộ ảnh theo anchor mới. Kết quả cũ được lưu trong lịch sử; có thể phát sinh phí cho ảnh/video mới.')
                if st.button('Tạo lại ảnh tham chiếu', key='regenerate_ref_' + job['id'], disabled=not paid_confirm):
                    try:
                        runner.retry_reference(job['id'], view)
                        dispatch_job(store, runner, job['id'], keys)
                        st.success('Đã xếp hàng tạo lại ảnh và các clip phụ thuộc.')
                    except Exception as error:
                        error_notice(error)
                scene = st.number_input('Cảnh cần tạo lại', 1, len(snapshot['script']['actions']), 1, key='scene_' + job['id'])
                st.caption('Tạo lại cảnh gửi yêu cầu mới. Operation cũ được lưu vào lịch sử; kiểm tra nó đã dừng trước khi tạo lại. Chế độ nối cảnh sẽ tạo lại cả các cảnh sau đó.')
                if st.button('Tạo lại riêng cảnh đã chọn', key='regenerate_' + job['id'], disabled=not paid_confirm):
                    try:
                        runner.retry_scene(job['id'], scene)
                        dispatch_job(store, runner, job['id'], keys)
                        st.success('Đã xếp hàng tạo lại cảnh.')
                    except Exception as error:
                        error_notice(error)
                if job['mode'] == 'real':
                    with st.form('limits_' + job['id']):
                        budget = st.number_input('Ngân sách mới USD', min_value=0.1, max_value=1000.0, value=float(snapshot['options']['budget_usd']), key='budget_' + job['id'])
                        calls = st.number_input('Số yêu cầu tối đa mới', 1, 100, int(snapshot['options']['max_calls']), key='calls_' + job['id'])
                        if st.form_submit_button('Cập nhật hạn mức công việc này', disabled=not paid_confirm):
                            try:
                                store.update_limits(job['id'], budget, calls, authorized=True)
                                st.success('Đã cập nhật hạn mức, giữ nguyên chi phí đã dùng.')
                            except Exception as error:
                                error_notice(error)


def storage_tab(store):
    st.subheader('Sao lưu & chuyển máy')
    st.caption(f'Dữ liệu hiện tại: {store.root}. Sao lưu không chứa khóa hay OAuth.')
    running = store.rows("SELECT id FROM jobs WHERE status IN ('running','editing')")
    st.caption('Xuất và đồng bộ khi mọi công việc đã dừng để ảnh/video khớp SQLite.')
    if st.button('Chuẩn bị sao lưu đầy đủ', disabled=bool(running)):
        try:
            st.session_state['full_archive_path'] = str(backup.export_backup(store, destination=store.path(f'exports/full_backup_{uid()}.zip')))
        except Exception as error:
            error_notice(error)
    if 'full_archive_path' in st.session_state:
        archive_path = Path(st.session_state['full_archive_path'])
        if archive_path.exists():
            st.caption(f'Bản sao lưu đã lưu trên máy: {archive_path}')
            if archive_path.stat().st_size <= 128 * 1024 * 1024:
                st.download_button('Tải bản sao lưu ZIP', archive_path.read_bytes(), 'fashion_studio_backup.zip', 'application/zip')
            else:
                st.info('Bản sao lưu lớn hơn 128 MB đã được lưu trên ổ đĩa. Sao chép tệp ở đường dẫn trên để tránh nạp ZIP lớn vào bộ nhớ trình duyệt.')
    uploaded = st.file_uploader('Khôi phục bản sao lưu', type=['zip'], key='backup_import')
    if st.button('Khôi phục vào thư mục mới', disabled=not uploaded):
        try:
            target = backup.restore_backup(uploaded.getvalue(), BASE / 'restores')
            st.success(f'Đã khôi phục tại {target}. Đặt STUDIO_DATA_DIR tới thư mục này rồi khởi động lại. Dữ liệu hiện tại được giữ.')
        except Exception as error:
            error_notice(error)
    st.subheader('Google Drive (chỉ lưu trữ)')
    st.caption('Đồng bộ thủ công các ảnh, clip, manifest và sao lưu. Thay tài khoản cần lưu mapping mới rồi chủ động bấm đồng bộ.')
    config = st.file_uploader('OAuth Desktop client JSON', type=['json'], key='oauth_config')
    if st.button('Kết nối / kiểm tra Google Drive'):
        try:
            svc = drive.connect(config.getvalue().decode('utf-8') if config else None)
            st.success('Đã kết nối: ' + drive.account(svc)['emailAddress'])
        except Exception as error:
            error_notice(error)
    if st.button('Ngắt kết nối để đổi tài khoản'):
        try:
            secrets.delete('drive_token')
            st.success('Đã xóa token trên máy. Kết nối lại và chọn tài khoản khác. Tệp Drive vẫn giữ nguyên.')
        except Exception as error:
            error_notice(error)
    existing = store.setting('drive_mapping', {})
    mapping_text = st.text_area('Mapping thư mục Drive (có thể sửa)', json.dumps(existing.get('folders', drive.DEFAULT_MAPPING), indent=2), height=250)
    if st.button('Xác minh và lưu mapping cho tài khoản đang kết nối'):
        try:
            svc = drive.service()
            mapping = json.loads(mapping_text)
            drive.verify_mapping(svc, mapping)
            store.set_setting('drive_mapping', {'account': drive.account(svc)['emailAddress'], 'folders': mapping})
            st.success('Đã lưu mapping.')
        except Exception as error:
            error_notice(error)
    if st.button('Tạo bộ thư mục mới trên Drive đang kết nối'):
        try:
            svc = drive.service()
            store.set_setting('drive_mapping', {'account': drive.account(svc)['emailAddress'], 'folders': drive.create_mapping(svc)})
            st.success('Đã tạo và lưu mapping mới. Làm mới trang để xem.')
        except Exception as error:
            error_notice(error)
    if st.button('Đồng bộ dữ liệu và sao lưu lên Drive', disabled=bool(running)):
        try:
            with st.spinner('Đang đồng bộ; giữ trang này mở…'):
                count, failures = drive.sync(store)
            st.success(f'Đã xử lý {count} tệp; {failures} tệp lỗi. Bấm lại để tiếp tục; tệp không đổi được bỏ qua.')
        except Exception as error:
            error_notice(error)
    if st.button('Đọc danh sách bản sao lưu trên Drive'):
        try:
            st.session_state['drive_backups'] = drive.list_backups(store)
            if not st.session_state['drive_backups']:
                st.info('Chưa có ZIP sao lưu trong thư mục Backups.')
        except Exception as error:
            error_notice(error)
    remote = st.session_state.get('drive_backups', [])
    if remote:
        selected = st.selectbox('Bản sao lưu Drive cần khôi phục', remote, format_func=lambda f: f"{f['name']} · {f.get('modifiedTime', '')}")
        if st.button('Tải và khôi phục Drive vào thư mục mới'):
            try:
                with st.spinner('Đang tải và xác minh bản sao lưu…'):
                    target = drive.restore_remote_backup(store, selected['id'], BASE / 'restores')
                st.success(f'Đã khôi phục tại {target}. Đặt STUDIO_DATA_DIR tới thư mục này rồi khởi động lại; dữ liệu hiện tại được giữ.')
            except Exception as error:
                error_notice(error)


def main():
    st.set_page_config(page_title='Fashion AI Studio', page_icon='🎬', layout='wide')
    st.title('🎬 Fashion AI Studio')
    st.caption('Studio video thời trang • Lưu trên máy • Một sản phẩm = một MP4')
    options, keys, advanced = settings()
    store, runner = resources(str(DATA))
    tabs = st.tabs(['Tạo video', 'Thư viện phông nền', 'Kịch bản', 'Công việc & kết quả', 'Lưu trữ & Drive'])
    with tabs[0]:
        create_tab(store, runner, options, keys, advanced)
    with tabs[1]:
        backgrounds_tab(store)
    with tabs[2]:
        scripts_tab(store)
    with tabs[3]:
        results_tab(store, runner, options, keys)
    with tabs[4]:
        storage_tab(store)
    with st.sidebar.expander('Tài liệu model chính thức'):
        for name, url in MODEL_SOURCES.items():
            st.markdown(f'[{name}]({url})')


if __name__ == '__main__':
    main()
