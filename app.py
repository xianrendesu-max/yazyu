import json
import requests
import random
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, Response, Request, HTTPException
from fastapi.responses import (
    HTMLResponse,
    RedirectResponse,
    StreamingResponse,
    FileResponse
)
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

# ===============================
# 基本設定
# ===============================

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATICS_DIR = BASE_DIR / "statics"

app = FastAPI()

# ===============================
# Static mount（static / statics 両対応）
# ===============================

if STATIC_DIR.exists():
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static"
    )

if STATICS_DIR.exists():
    app.mount(
        "/statics",
        StaticFiles(directory=str(STATICS_DIR)),
        name="statics"
    )

# ===============================
# Static HTML 自動判別
# ===============================

def get_static_file(filename: str) -> Path:
    if (STATIC_DIR / filename).exists():
        return STATIC_DIR / filename
    if (STATICS_DIR / filename).exists():
        return STATICS_DIR / filename
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/", response_class=HTMLResponse)
def root():
    return FileResponse(get_static_file("index.html"))

@app.get("/watch", response_class=HTMLResponse)
def watch():
    return FileResponse(get_static_file("watch.html"))

# ===============================
# API LIST
# ===============================

VIDEO_APIS = [
    "https://iv.melmac.space",
    "https://pol1.iv.ggtyler.dev",
    "https://cal1.iv.ggtyler.dev",
    "https://invidious.0011.lt",
    "https://yt.omada.cafe",
]

SEARCH_APIS = VIDEO_APIS

COMMENTS_APIS = [
    "https://invidious.lunivers.trade",
    "https://invidious.ducks.party",
    "https://super8.absturztau.be",
    "https://invidious.nikkosphere.com",
    "https://yt.omada.cafe",
    "https://iv.melmac.space",
    "https://iv.duti.dev",
]

EDU_STREAM_API_BASE_URL = "https://siawaseok.duckdns.org/api/stream/"
STREAM_YTDL_API_BASE_URL = "https://yudlp.vercel.app/stream/"
SHORT_STREAM_API_BASE_URL = "https://yt-dl-kappa.vercel.app/short/"

TIMEOUT = 6

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ===============================
# Utils
# ===============================

def try_json(url, params=None):
    try:
        r = requests.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT
        )
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def get_360p_single_url(videoid: str) -> str:
    data = try_json(f"{STREAM_YTDL_API_BASE_URL}{videoid}")
    if not data:
        raise ValueError("yt-dlp api failed")

    for f in data.get("formats", []):
        if f.get("itag") == "18" and f.get("url"):
            return f["url"]

    raise ValueError("itag18 not found")

# ===============================
# Search
# ===============================

@app.get("/api/search")
def api_search(q: str):
    random.shuffle(SEARCH_APIS)

    for base in SEARCH_APIS:
        data = try_json(
            f"{base}/api/v1/search",
            {"q": q, "type": "video"}
        )
        if not isinstance(data, list):
            continue

        results = []
        for v in data:
            if not v.get("videoId"):
                continue
            results.append({
                "videoId": v["videoId"],
                "title": v.get("title"),
                "author": v.get("author")
            })

        if results:
            return {
                "count": len(results),
                "results": results,
                "source": base
            }

    raise HTTPException(503, "Search unavailable")

# ===============================
# Video Info
# ===============================

@app.get("/api/video")
def api_video(video_id: str):
    random.shuffle(VIDEO_APIS)

    for base in VIDEO_APIS:
        data = try_json(f"{base}/api/v1/videos/{video_id}")
        if data:
            return {
                "title": data.get("title"),
                "author": data.get("author"),
                "description": data.get("description"),
                "viewCount": data.get("viewCount"),
                "lengthSeconds": data.get("lengthSeconds"),
                "source": base
            }

    raise HTTPException(503, "Video info unavailable")

# ===============================
# Comments
# ===============================

@app.get("/api/comments")
def api_comments(video_id: str):
    random.shuffle(COMMENTS_APIS)

    for base in COMMENTS_APIS:
        data = try_json(f"{base}/api/v1/comments/{video_id}")
        if data:
            return {
                "comments": [
                    {
                        "author": c.get("author"),
                        "content": c.get("content")
                    }
                    for c in data.get("comments", [])
                ],
                "source": base
            }

    return {"comments": [], "source": None}

# ===============================
# Stream（再生用）
# ===============================

@app.get("/api/streamurl")
def api_streamurl(video_id: str, quality: str = "best"):
    # ① 外部 yt-dlp / edu 系
    for base in [
        EDU_STREAM_API_BASE_URL,
        STREAM_YTDL_API_BASE_URL,
        SHORT_STREAM_API_BASE_URL
    ]:
        data = try_json(f"{base}{video_id}", {"quality": quality})
        if data and data.get("url"):
            return RedirectResponse(data["url"])

    # ② Invidious fallback
    random.shuffle(VIDEO_APIS)
    for base in VIDEO_APIS:
        data = try_json(f"{base}/api/v1/videos/{video_id}")
        if not data:
            continue

        for f in data.get("adaptiveFormats", []):
            if f.get("url"):
                return RedirectResponse(f["url"])

    raise HTTPException(503, "Stream unavailable")

# ===============================
# Download（確実・360p）
# ===============================

@app.get("/api/download/{videoid}")
async def download_video(videoid: str):
    try:
        stream_url = await run_in_threadpool(
            get_360p_single_url,
            videoid
        )

        r = requests.get(
            stream_url,
            headers=HEADERS,
            stream=True,
            timeout=15
        )
        r.raise_for_status()

        return StreamingResponse(
            r.iter_content(chunk_size=1024 * 1024),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f'attachment; filename="{videoid}.mp4"',
                "Accept-Ranges": "bytes"
            }
        )

    except Exception as e:
        return Response(
            content=f"Download failed: {str(e)}",
            status_code=503
    )
