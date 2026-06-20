import asyncio
import hashlib
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

API_KEY = os.getenv("API_KEY", "")
PORT = int(os.getenv("PORT", "8000"))
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
FILE_TTL = int(os.getenv("FILE_TTL", "3600"))

app = FastAPI(
    title="Video Downloader API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def verify_api_key(x_api_key: str | None = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def detect_platform(url: str) -> str | None:
    patterns = {
        "tiktok": r"(tiktok\.com|vm\.tiktok\.com)",
        "instagram": r"(instagram\.com|instagr\.am)",
        "youtube": r"(youtube\.com|youtu\.be)",
    }
    for platform, pattern in patterns.items():
        if re.search(pattern, url, re.IGNORECASE):
            return platform
    return None


def cleanup_old_files():
    now = time.time()
    for f in DOWNLOADS_DIR.iterdir():
        if f.is_file() and (now - f.stat().st_mtime) > FILE_TTL:
            f.unlink(missing_ok=True)


async def run_ytdlp(args: list[str]) -> tuple[str, str, int]:
    process = await asyncio.create_subprocess_exec(
        "yt-dlp", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return (
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
        process.returncode,
    )


async def get_video_info(url: str) -> dict:
    stdout, stderr, code = await run_ytdlp([
        "--no-playlist",
        "--no-warnings",
        "--impersonate", "chrome",
        "--skip-download",
        "--print", "%(id)s",
        "--print", "%(title)s",
        "--print", "%(duration)s",
        "--print", "%(thumbnail)s",
        "--print", "%(uploader)s",
        "--print", "%(view_count)s",
        url,
    ])
    if code != 0:
        raise HTTPException(status_code=400, detail=f"Ошибка: {stderr}")

    lines = stdout.split("\n")
    return {
        "id": lines[0] if len(lines) > 0 else "",
        "title": lines[1] if len(lines) > 1 else "",
        "duration": lines[2] if len(lines) > 2 else "0",
        "thumbnail": lines[3] if len(lines) > 3 else "",
        "uploader": lines[4] if len(lines) > 4 else "",
        "views": lines[5] if len(lines) > 5 else "0",
        "platform": detect_platform(url),
    }


async def download_video(url: str, platform: str) -> dict:
    cleanup_old_files()

    url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
    output_template = str(DOWNLOADS_DIR / f"{platform}_{url_hash}_%(id)s.%(ext)s")

    stdout, stderr, code = await run_ytdlp([
        "--no-playlist",
        "--no-warnings",
        "--impersonate", "chrome",
        "--format", "best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--output", output_template,
        "--print", "after_move:filepath",
        "--print", "%(title)s",
        "--print", "%(duration)s",
        "--print", "%(thumbnail)s",
        url,
    ])

    if code != 0:
        raise HTTPException(status_code=400, detail=f"Ошибка загрузки: {stderr}")

    lines = stdout.split("\n")
    if not lines or not lines[0]:
        raise HTTPException(status_code=500, detail="Не удалось скачать видео")

    filepath = lines[0].strip()
    title = lines[1].strip() if len(lines) > 1 else "video"
    duration = lines[2].strip() if len(lines) > 2 else "0"
    thumbnail = lines[3].strip() if len(lines) > 3 else ""

    if not Path(filepath).exists():
        existing = list(DOWNLOADS_DIR.glob(f"{platform}_{url_hash}_*"))
        if existing:
            filepath = str(existing[0])
        else:
            raise HTTPException(status_code=500, detail="Файл не найден после загрузки")

    filename = Path(filepath).name
    file_size = Path(filepath).stat().st_size

    return {
        "filename": filename,
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "size": file_size,
        "platform": platform,
        "download_url": f"/download/{filename}",
    }


# ── Web UI ──

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ── API endpoints ──

@app.get("/api/health")
async def health():
    stdout, _, code = await run_ytdlp(["--version"])
    return {
        "status": "ok",
        "ytdlp_version": stdout if code == 0 else "unavailable",
    }


@app.post("/api/info")
async def api_info(request: Request, x_api_key: str | None = Header(None)):
    verify_api_key(x_api_key)
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL не указан")
    platform = detect_platform(url)
    if not platform:
        raise HTTPException(status_code=400, detail="Неподдерживаемая платформа")
    info = await get_video_info(url)
    return info


@app.post("/api/download")
async def api_download(request: Request, x_api_key: str | None = Header(None)):
    verify_api_key(x_api_key)
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL не указан")

    platform = detect_platform(url)
    if not platform:
        raise HTTPException(
            status_code=400,
            detail="Поддерживаются только TikTok, Instagram Reels и YouTube Shorts",
        )

    result = await download_video(url, platform)
    return result


@app.post("/api/download/direct")
async def api_download_direct(request: Request, x_api_key: str | None = Header(None)):
    """Download and immediately return the video file as a stream."""
    verify_api_key(x_api_key)
    body = await request.json()
    url = body.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL не указан")

    platform = detect_platform(url)
    if not platform:
        raise HTTPException(status_code=400, detail="Неподдерживаемая платформа")

    result = await download_video(url, platform)
    filepath = DOWNLOADS_DIR / result["filename"]

    return FileResponse(
        filepath,
        media_type="video/mp4",
        filename=f"{result['title']}.mp4",
        headers={"X-Video-Title": result["title"], "X-Video-Duration": result["duration"]},
    )


@app.get("/download/{filename}")
async def serve_file(filename: str):
    safe_name = Path(filename).name
    filepath = DOWNLOADS_DIR / safe_name
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(filepath, media_type="video/mp4", filename=safe_name)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
