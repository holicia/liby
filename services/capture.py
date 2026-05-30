import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
import yt_dlp

log = logging.getLogger(__name__)

_no_ffmpeg_warned = False


def _capture_one_sync(url: str, t: int, out_jpg: str) -> bool:
    """단일 챕터 시각 t의 영상 프레임을 out_jpg로 저장. 성공 시 True.
    yt-dlp로 [t, t+2] 슬라이스만 다운 후 ffmpeg로 첫 프레임 추출."""
    global _no_ffmpeg_warned
    tmp_dir = tempfile.mkdtemp(prefix="liby-cap-")
    tmp_template = os.path.join(tmp_dir, "slice.%(ext)s")
    try:
        ydl_opts = {
            "format": "best[height<=720]/best",
            "outtmpl": tmp_template,
            "download_ranges": yt_dlp.utils.download_range_func(None, [(t, t + 2)]),
            "force_keyframes_at_cuts": False,
            "quiet": True, "no_warnings": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        files = os.listdir(tmp_dir)
        if not files:
            return False
        tmp_video = os.path.join(tmp_dir, files[0])
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", "0", "-i", tmp_video, "-frames:v", "1", "-q:v", "5", out_jpg],
            timeout=30, capture_output=True,
        )
        return result.returncode == 0 and os.path.exists(out_jpg)
    except FileNotFoundError:
        if not _no_ffmpeg_warned:
            log.warning("ffmpeg not found in PATH — chapter screenshots disabled")
            _no_ffmpeg_warned = True
        return False
    except Exception as e:
        log.warning(f"capture failed at t={t}: {e}")
        return False
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


async def capture_chapter_screenshots(
    url: str,
    chapters: list[dict],
    vault_path: str,
    note_slug: str,
) -> list[dict]:
    """각 챕터 시작 시각의 영상 프레임을 vault/youtube/<note_slug>/ch-N.jpg로 저장.
    실패한 챕터는 image 키 없이 반환(부분 성공). 빈 chapters는 그대로 반환."""
    if not chapters:
        return chapters
    out_dir = os.path.join(vault_path, "youtube", note_slug)
    os.makedirs(out_dir, exist_ok=True)
    loop = asyncio.get_running_loop()

    out_chapters = []
    for i, ch in enumerate(chapters, start=1):
        out_jpg = os.path.join(out_dir, f"ch-{i}.jpg")
        ok = await loop.run_in_executor(None, _capture_one_sync, url, ch["t"], out_jpg)
        new_ch = dict(ch)
        if ok:
            new_ch["image"] = f"{note_slug}/ch-{i}.jpg"
        out_chapters.append(new_ch)
    return out_chapters
