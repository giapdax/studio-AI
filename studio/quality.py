"""Free local checks. These detect technical issues, not semantic identity fidelity."""
import hashlib
from pathlib import Path

from .storage import dump


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def reference_signature(references):
    return [fingerprint(path) for path in references]


def inspect_references(references, background, mode='real'):
    from PIL import Image, ImageStat
    issues, details = [], []
    histograms = []
    for i, path in enumerate(references, 1):
        try:
            with Image.open(path) as im:
                im.load()
                rgb = im.convert('RGB')
                brightness = ImageStat.Stat(rgb.convert('L'))
                entry = {'view': i, 'width': im.width, 'height': im.height, 'luma_mean': round(brightness.mean[0], 2), 'luma_stddev': round(brightness.stddev[0], 2)}
                details.append(entry)
                if min(im.size) < 256:
                    issues.append({'view': i, 'code': 'low_resolution', 'message': 'Ảnh tham chiếu có cạnh nhỏ hơn 256 px.'})
                if brightness.mean[0] < 5 or brightness.mean[0] > 250 or brightness.stddev[0] < 2:
                    issues.append({'view': i, 'code': 'near_blank', 'message': 'Ảnh gần như trống hoặc mất chi tiết; cần kiểm tra.'})
                # Compare only first/last full views, not intentional fabric close-ups.
                small = rgb.resize((64, 64))
                histogram = small.histogram()
                histograms.append([sum(histogram[channel * 256 + j:channel * 256 + j + 32]) / (64 * 64) for channel in range(3) for j in range(0, 256, 32)])
        except (OSError, ValueError):
            issues.append({'view': i, 'code': 'unreadable_image', 'message': 'Không đọc được ảnh tham chiếu.'})
            histograms.append(None)
    if mode == 'real' and len(histograms) == 5 and histograms[0] and histograms[-1]:
        delta = sum(abs(a - b) for a, b in zip(histograms[0], histograms[-1])) / 6
        if delta > 0.45:
            issues.append({'view': 5, 'code': 'possible_color_drift', 'message': 'Phân bố màu khác nhiều giữa hai góc toàn thân. Đây là cảnh báo sơ bộ, có thể do góc chụp/ánh sáng.'})
    return {'schema': 1, 'method': 'local_image_statistics', 'mode': mode, 'status': 'flagged' if issues else 'unverified', 'issues': issues, 'images': details, 'reference_hashes': reference_signature(references), 'semantic_identity_verified': False, 'background_source_sha256': fingerprint(background), 'limitations': 'Thống kê ảnh không xác minh logo, chữ, chất vải hoặc bố cục. Cần duyệt thủ công hoặc đánh giá AI tùy chọn.'}


def review_is_current(folder, references):
    import json
    path = Path(folder) / 'quality_review.json'
    if not path.exists():
        return False
    review = json.loads(path.read_text(encoding='utf-8'))
    return review.get('decision') == 'approved' and review.get('reference_hashes') == reference_signature(references)


def save_review(folder, references, approved, note=''):
    if len(references) != 5 or any(not p.exists() for p in references):
        from .errors import StudioError
        raise StudioError('Cần đủ 5 ảnh tham chiếu để duyệt.')
    dump(Path(folder) / 'quality_review.json', {'decision': 'approved' if approved else 'rejected', 'status': 'Đã duyệt thủ công' if approved else 'Phát hiện sai lệch', 'note': note[:2000], 'reference_hashes': reference_signature(references), 'automatic_check': False})
