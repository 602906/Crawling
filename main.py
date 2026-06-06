import os
import asyncio
from dataclasses import asdict
from typing import Optional

import httpx
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from platforms import PLATFORMS
from platforms.base import MusicPlatform

app = FastAPI(title="Music Catch", version="1.0.0")

app.mount("/static", StaticFiles(directory=os.path.join(config.BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(config.BASE_DIR, "templates"))

_sessions: dict[str, MusicPlatform] = {}


def _restore_sessions():
    for name, cls in PLATFORMS.items():
        instance = cls()
        if instance._load_session() and instance.logged_in:
            _sessions[name] = instance


_restore_sessions()


def _get_platform(name: str) -> MusicPlatform:
    if name not in _sessions:
        cls = PLATFORMS.get(name)
        if not cls:
            raise HTTPException(400, f"不支持的平台: {name}")
        _sessions[name] = cls()
    return _sessions[name]


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    logged_in = {k: v.logged_in for k, v in _sessions.items()}
    return templates.TemplateResponse("index.html", {
        "request": request,
        "logged_in": logged_in,
        "platforms": PLATFORMS,
    })


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    platform_info = {}
    for pid, cls in PLATFORMS.items():
        platform_info[pid] = {
            "name": cls.name,
            "methods": cls.supported_login_methods,
        }
    return templates.TemplateResponse("login.html", {
        "request": request,
        "platforms": PLATFORMS,
        "platform_info": platform_info,
    })


@app.get("/api/login/qrcode/{platform}")
async def get_qr_code(platform: str):
    p = _get_platform(platform)
    qr = await p.get_qr_code()
    if not qr:
        raise HTTPException(500, "获取二维码失败")
    return {"qr_image": qr}


@app.get("/api/login/qrcode/{platform}/check")
async def check_qr_status(platform: str):
    p = _get_platform(platform)
    result = await p.check_qr_status()
    if result.get("status") == "success":
        p._persist_session()
    return result


@app.post("/api/login/cookie/{platform}")
async def login_cookie(platform: str, request: Request):
    body = await request.json()
    cookie_str = body.get("cookie", "")
    p = _get_platform(platform)
    result = await p.login_cookie(cookie_str)
    if result.get("success"):
        p._persist_session()
    return result


@app.post("/api/login/phone/{platform}")
async def login_phone(platform: str, request: Request):
    body = await request.json()
    phone = body.get("phone", "")
    code = body.get("code", "")
    p = _get_platform(platform)
    result = await p.login_phone(phone, code)
    if result.get("success"):
        p._persist_session()
    return result


@app.post("/api/login/phone/{platform}/send_code")
async def send_phone_code(platform: str, request: Request):
    body = await request.json()
    phone = body.get("phone", "")
    p = _get_platform(platform)
    result = await p.send_phone_code(phone)
    return result


@app.get("/api/search")
async def search(
    keyword: str = Query(..., min_length=1),
    platform: str = Query("all"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    if platform == "all":
        targets = list(PLATFORMS.keys())
    else:
        targets = [platform]

    all_songs = []
    total = 0
    errors = {}

    async def _search_one(name: str):
        p = _get_platform(name)
        try:
            result = await p.search(keyword, page, page_size)
            return result.songs, result.total
        except Exception as e:
            errors[name] = str(e)
            return [], 0

    results = await asyncio.gather(*[_search_one(t) for t in targets])
    for songs, count in results:
        all_songs.extend(songs)
        total += count

    return {
        "songs": [asdict(s) for s in all_songs],
        "total": total,
        "page": page,
        "errors": errors,
    }


@app.get("/api/play/{platform}/{song_id}")
async def get_play_url(platform: str, song_id: str, request: Request):
    extra_str = request.query_params.get("extra", "")
    import json as _json

    extra = {}
    if extra_str:
        try:
            extra = _json.loads(extra_str)
        except Exception:
            pass

    from platforms.base import Song

    song = Song(
        id=song_id,
        name="",
        artist="",
        platform=platform,
        extra=extra,
    )

    p = _get_platform(platform)
    url = await p.get_play_url(song)
    if not url:
        raise HTTPException(404, "无法获取播放地址")
    return {"url": url}


@app.get("/api/download/{platform}/{song_id}")
async def download_song(platform: str, song_id: str, request: Request):
    extra_str = request.query_params.get("extra", "")
    name = request.query_params.get("name", "unknown")
    artist = request.query_params.get("artist", "unknown")
    stream = request.query_params.get("stream", "video")
    import json as _json

    extra = {}
    if extra_str:
        try:
            extra = _json.loads(extra_str)
        except Exception:
            pass

    from platforms.base import Song

    song = Song(id=song_id, name=name, artist=artist, platform=platform, extra=extra)

    p = _get_platform(platform)
    is_bilibili = platform == "bilibili"
    if is_bilibili:
        url = await p.get_download_url(song, stream_type=stream)
    else:
        url = await p.get_download_url(song)
    if not url:
        raise HTTPException(404, "无法获取下载地址")

    dl_client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"},
        follow_redirects=True,
        timeout=httpx.Timeout(30, read=300),
    )
    from urllib.parse import urlparse as _urlparse
    dl_domain = _urlparse(url).hostname or ""
    if "163.com" in dl_domain or "126.net" in dl_domain:
        dl_referer = "https://music.163.com/"
    elif "kugou.com" in dl_domain:
        dl_referer = "https://www.kugou.com/"
    elif "bilibili.com" in dl_domain or "bilivideo.com" in dl_domain or "hdslb.com" in dl_domain:
        dl_referer = "https://www.bilibili.com/"
    elif "qq.com" in dl_domain:
        dl_referer = "https://y.qq.com/"
    else:
        dl_referer = ""
    dl_headers = {}
    if dl_referer:
        dl_headers["Referer"] = dl_referer
    if "bilibili.com" in dl_domain or "bilivideo.com" in dl_domain or "hdslb.com" in dl_domain:
        dl_headers["Origin"] = "https://www.bilibili.com"
    dl_req = dl_client.build_request("GET", url, headers=dl_headers)
    dl_resp = await dl_client.send(dl_req, stream=True)

    if dl_resp.status_code != 200:
        await dl_resp.aclose()
        await dl_client.aclose()
        raise HTTPException(500, "下载失败")

    content_type = dl_resp.headers.get("content-type", "application/octet-stream")

    _ext_map = {
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "video/mp4": ".mp4",
        "audio/flac": ".flac",
        "audio/x-flac": ".flac",
        "audio/ogg": ".ogg",
        "audio/aac": ".aac",
    }
    ext = ".mp3"
    for ct, e in _ext_map.items():
        if ct in content_type:
            ext = e
            break

    filename = f"{artist} - {name}{ext}"
    safe_filename = "".join(c for c in filename if c not in r'\/:*?"<>|')
    from urllib.parse import quote
    encoded_filename = quote(safe_filename)

    resp_headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
    }
    content_length = dl_resp.headers.get("content-length", "")
    if content_length:
        resp_headers["Content-Length"] = content_length

    async def dl_stream():
        try:
            async for chunk in dl_resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await dl_resp.aclose()
            await dl_client.aclose()

    return StreamingResponse(dl_stream(), media_type=content_type, headers=resp_headers)


@app.get("/api/status")
async def get_status():
    result = {}
    for name, p in _sessions.items():
        result[name] = {
            "logged_in": p.logged_in,
            "name": p.name,
            "user": p.user_info,
        }
    for name, cls in PLATFORMS.items():
        if name not in result:
            result[name] = {
                "logged_in": False,
                "name": cls.name,
                "user": None,
            }
    return result


@app.post("/api/logout/{platform}")
async def logout(platform: str):
    p = _sessions.pop(platform, None)
    if p:
        session_file = os.path.join(p.SESSION_DIR, f"{platform}.json")
        if os.path.exists(session_file):
            os.remove(session_file)
        extra_file = os.path.join(p.SESSION_DIR, f"{platform}_extra.json")
        if os.path.exists(extra_file):
            os.remove(extra_file)
    return {"success": True, "msg": "已退出登录"}


@app.get("/api/proxy")
async def proxy_audio(request: Request, url: str = Query(...)):
    range_header = request.headers.get("range")
    from urllib.parse import urlparse
    domain = urlparse(url).hostname or ""
    if "163.com" in domain or "126.net" in domain:
        referer = "https://music.163.com/"
    elif "kugou.com" in domain:
        referer = "https://www.kugou.com/"
    elif "bilibili.com" in domain or "bilivideo.com" in domain or "hdslb.com" in domain:
        referer = "https://www.bilibili.com/"
    else:
        referer = "https://y.qq.com/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
    }
    if "bilibili.com" in domain or "bilivideo.com" in domain or "hdslb.com" in domain:
        headers["Origin"] = "https://www.bilibili.com"
    if range_header:
        headers["Range"] = range_header

    client = httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(30, read=300))
    req = client.build_request("GET", url, headers=headers)
    resp = await client.send(req, stream=True)

    if resp.status_code not in (200, 206):
        await resp.aclose()
        await client.aclose()
        raise HTTPException(500, "代理请求失败")

    content_type = resp.headers.get("content-type", "application/octet-stream")
    content_length = resp.headers.get("content-length", "")

    async def stream():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=65536):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    resp_headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
    }
    if content_length:
        resp_headers["Content-Length"] = content_length
    if resp.status_code == 206:
        resp_headers["Content-Range"] = resp.headers.get("content-range", "")

    return StreamingResponse(stream(), status_code=resp.status_code, headers=resp_headers)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=config.HOST, port=config.PORT)
