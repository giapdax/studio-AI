from .errors import StudioError
import os
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


def ffmpeg():
    executable = os.getenv('FFMPEG_EXE') or shutil.which('ffmpeg')
    if not executable:
        try:
            import imageio_ffmpeg
            executable = imageio_ffmpeg.get_ffmpeg_exe()
        except (ImportError, RuntimeError):
            raise RuntimeError('Thiếu FFmpeg. Chạy INSTALL_APP.bat hoặc cài FFmpeg vào PATH.') from None
    return executable


def run(arguments):
    result = subprocess.run([ffmpeg(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', *map(str, arguments)], capture_output=True, timeout=600)
    if result.returncode:
        raise RuntimeError('FFmpeg không xử lý được video. Kiểm tra ảnh/clip đầu vào và dung lượng ổ đĩa.')


@lru_cache(maxsize=4)
def available_encoders(executable):
    result = subprocess.run([executable, '-hide_banner', '-encoders'], capture_output=True, timeout=15, check=True)
    return {line.split()[1] for line in result.stdout.decode(errors='replace').splitlines() if len(line.split()) >= 2 and line.strip().startswith('V')}


def encoder_options(preset='fast'):
    available = available_encoders(ffmpeg())
    requested = os.getenv('STUDIO_H264_ENCODER')
    encoder = requested or ('libx264' if 'libx264' in available else 'h264_mf' if os.name == 'nt' and 'h264_mf' in available else None)
    if encoder not in {'libx264', 'h264_mf'} or encoder not in available:
        raise StudioError('FFmpeg không có bộ mã hóa H.264 tương thích. Cài imageio-ffmpeg hoặc FFmpeg có libx264.')
    if encoder == 'libx264':
        return ['-c:v', 'libx264', '-preset', preset]
    return ['-c:v', 'h264_mf', '-hw_encoding', '0', '-b:v', '5M']


def still_clip(image, output, seconds, width=1080, height=1920):
    temporary = output.with_name(output.stem + '.partial.mp4')
    run(['-loop', '1', '-i', image, '-t', seconds, '-an', '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30', *encoder_options('ultrafast'), '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart', temporary])
    temporary.replace(output)


def normalize(source, output, seconds, width=1080, height=1920):
    temporary = output.with_name(output.stem + '.partial.mp4')
    run(['-i', source, '-t', seconds, '-an', '-vf', f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps=30', *encoder_options(), '-pix_fmt', 'yuv420p', '-threads', '2', '-movflags', '+faststart', temporary])
    temporary.replace(output)


def assemble(clips, output):
    # All generated filenames are controlled; relative names avoid escaping Windows paths.
    listing = output.parent / 'concat.txt'
    if any(p.parent != output.parent or "'" in p.name for p in clips):
        raise StudioError('Clip phải nằm trong cùng thư mục công việc.')
    listing.write_text(''.join(f"file '{p.name}'\n" for p in clips), encoding='utf-8')
    temporary = output.with_name('final.partial.mp4')
    run(['-f', 'concat', '-safe', '1', '-i', listing, '-c', 'copy', '-movflags', '+faststart', temporary])
    temporary.replace(output)


def check():
    result = subprocess.run([ffmpeg(), '-version'], capture_output=True, timeout=15)
    if result.returncode:
        raise RuntimeError('FFmpeg không khởi động được.')
    encoder_options()
    return result.stdout.decode(errors='replace').splitlines()[0]


def last_frame(source, output):
    """Get the last frame of the trimmed clip, not the discarded Veo tail."""
    temporary = output.with_name(output.stem + '.partial.png')
    run(['-sseof', '-0.05', '-i', source, '-frames:v', '1', '-update', '1', temporary])
    if not temporary.exists():
        raise StudioError('Không trích được khung cuối của cảnh trước.')
    temporary.replace(output)


def probe(source):
    sibling = Path(ffmpeg()).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    executable = os.getenv('FFPROBE_EXE') or shutil.which('ffprobe') or (str(sibling) if sibling.exists() else None)
    if executable:
        result = subprocess.run([executable, '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=codec_name,width,height,r_frame_rate:format=duration', '-of', 'json', str(source)], capture_output=True, timeout=30, check=True)
        data = json.loads(result.stdout)
        stream = data['streams'][0]
        numerator, denominator = stream['r_frame_rate'].split('/')
        return {'size': [stream['width'], stream['height']], 'fps': float(numerator) / float(denominator), 'duration': float(data['format']['duration']), 'codec': stream['codec_name']}
    import imageio_ffmpeg
    frames = imageio_ffmpeg.read_frames(str(source))
    try:
        metadata = next(frames)
        return {key: metadata[key] for key in ('size', 'fps', 'duration', 'codec')}
    finally:
        frames.close()


def validate_video(source, width, height, seconds):
    metadata = probe(source)
    if list(metadata['size']) != [width, height] or abs(metadata['fps'] - 30) > 0.01 or abs(metadata['duration'] - seconds) > 0.15 or metadata['codec'] != 'h264':
        raise StudioError('Video cuối không đạt kích thước, thời lượng hoặc định dạng H.264/30fps yêu cầu.')
    return metadata
