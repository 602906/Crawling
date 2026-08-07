import os
import asyncio
import hashlib
import ipaddress
import logging
import secrets
import socket
import time
from dataclasses import asdict
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, Request, Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
from platforms import PLATFORMS
from platforms.base import MusicPlatform
import anti_devtools
import listen_together

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """按 config.DEBUG 配置应用日志级别：开启时输出 DEBUG+ 调试日志（进房/动作/缓存/门禁等），
    关闭时仅 WARNING+（重要异常）。幂等，可重复调用（命令行 --debug 覆盖后需再调一次生效）。"""
    level = logging.DEBUG if config.DEBUG else logging.WARNING
    for name in {__name__, "listen_together", "anti_devtools"}:
        lg = logging.getLogger(name)
        lg.setLevel(level)
        if not lg.handlers:  # uvicorn 不接管应用 logger，显式挂 stderr
            _h = logging.StreamHandler()
            _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%H:%M:%S"))
            lg.addHandler(_h)


_configure_logging()  # 立即生效（uvicorn main:app 导入方式；--debug 覆盖后由 __main__ 再调）

# 生产环境禁用 Swagger/OpenAPI 文档，避免暴露 API 结构与端点清单
app = FastAPI(
    title="Music Catch",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ── IP 速率限制（按限速档位分桶计数，互不挤占）──
_RATE_LIMITS: dict[str, list[float]] = {}
_RATE_LAST: dict[str, float] = {}   # key → 最后访问时间（用于空闲键清理）
_RATE_CALLS = 0                     # 限速检查计数（采样触发全量清理）
_RATE_CLEAN_INTERVAL = 600          # 键空闲超过 10 分钟即清理
_RATE_CLEAN_EVERY = 100             # 每 N 次限速检查采样清理一次
_RATE_MAX_KEYS = 5000               # 键数量上限，超限删最旧一半（防内存溢出）


def _sweep_rate_keys(now: float) -> None:
    """清理限速键：空闲超时的删除；键数超上限时删最旧一半（防内存溢出）。"""
    # 1) 空闲超过 10 分钟的键
    stale = [k for k, last in _RATE_LAST.items() if now - last > _RATE_CLEAN_INTERVAL]
    for k in stale:
        _RATE_LIMITS.pop(k, None)
        _RATE_LAST.pop(k, None)
    # 2) 容量上限兜底：删最旧一半（攻击者灌大量唯一 IP 时保证内存有界）
    if len(_RATE_LIMITS) > _RATE_MAX_KEYS:
        cutoff = sorted(_RATE_LAST.values())[len(_RATE_LAST) // 2]
        for k in [k for k, last in _RATE_LAST.items() if last < cutoff]:
            _RATE_LIMITS.pop(k, None)
            _RATE_LAST.pop(k, None)


def _check_rate(request: Request, max_req: int | None = None, window: int | None = None, bucket: str = "default") -> bool:
    """检查 IP 速率，未超限返回 True，超限返回 False。不同 bucket 独立计数。

    纯同步执行（事件循环内无 await 点），单 worker 下天然原子；
    setdefault 初始化防御未来迁移线程池/异步执行时出现竞态。
    max_req/window 默认取 config 当前值（运行时读取，支持命令行覆盖）。"""
    if max_req is None:
        max_req = config.RATE_MAX
    if window is None:
        window = config.RATE_WINDOW
    global _RATE_CALLS
    ip = request.client.host if request.client else "unknown"
    key = f"{ip}|{bucket}"
    now = time.time()
    _RATE_LAST[key] = now
    _RATE_CALLS += 1
    # 采样触发全量清理（避免每次请求 O(n) 扫描）
    if _RATE_CALLS % _RATE_CLEAN_EVERY == 0:
        _sweep_rate_keys(now)
    hist = _RATE_LIMITS.setdefault(key, [])
    cutoff = now - window
    _RATE_LIMITS[key] = [t for t in hist if t > cutoff]
    if len(_RATE_LIMITS[key]) >= max_req:
        return False
    _RATE_LIMITS[key].append(now)
    return True


# ── CSP 头（方案一：防 XSS 数据外泄）──
_CSP_POLICY = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-eval' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "media-src 'self' https:; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self'"
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    # ── 请求体大小限制：JSON 等载荷上限，防超大包内存耗尽（DoS）──
    if request.method in ("POST", "PUT", "PATCH"):
        cl = request.headers.get("content-length")
        if cl and cl.isdigit() and int(cl) > config.MAX_BODY_SIZE:
            return JSONResponse({"detail": "请求体过大"}, status_code=413)
    # ── 浏览器门禁：所有 /api/ 接口强制校验 gate token ──
    # 仅精确豁免 gate 注册/心跳两个端点，其余 /api/gate/* 一律走校验
    path = request.url.path
    if path.startswith("/api/") and path not in ("/api/gate/register", "/api/gate/heartbeat"):
        # 流式端点（代理/下载）放宽指纹校验：移动端下载由浏览器下载管理器
        # 二次发起，请求头（UA/语言/客户端提示）与页面不同，严格指纹会误杀；
        # 仍强制 IP 匹配，且这些端点另有 IP 限速兜底
        stream = path.startswith("/api/proxy") or path.startswith("/api/download")
        if not anti_devtools.validate_gate_token(request, strict_fp=not stream):
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        # token 校验通过后仍按 IP 限速：杜绝脚本持有有效 token 无限量调用 API
        # 流式端点（视频/音频代理、下载）放宽，避免误伤正常播放
        if not _check_rate(request, max_req=config.STREAM_RATE_MAX if stream else config.API_RATE_MAX, bucket="api" if not stream else "stream"):
            _client_ip = request.client.host if request.client else "?"
            logger.warning("限速触发：IP=%s %s %s", _client_ip, request.method, path)
            return JSONResponse({"detail": "请求过于频繁，请稍后再试"}, status_code=429)

    response = await call_next(request)
    # CSP：禁止 connect-src 外联，废掉 XSS 窃取能力
    csp = _CSP_POLICY
    if config.HTTPS or config.SSL:
        csp += "; upgrade-insecure-requests"
    response.headers["Content-Security-Policy"] = csp
    # 禁止被 iframe 嵌套（防点击劫持）
    response.headers["X-Frame-Options"] = "DENY"
    # 禁止 MIME 类型嗅探
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


app.mount("/static", StaticFiles(directory=os.path.join(config.BASE_DIR, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(config.BASE_DIR, "templates"))

# 一起听歌：10 个常驻房间 + HTTP 长轮询实时同步（API 均走门禁中间件）
app.include_router(listen_together.router)

# ── 反 F12 脚本路由（固定路径，真实页面使用）──
@app.get(anti_devtools.get_route_path(), response_class=Response)
async def anti_devtools_js(request: Request):
    enabled = not _is_authed(request)
    return Response(
        content=anti_devtools.get_js_content(enabled),
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


# ── 挑战页脚本路由（动态路径，每次随机，3s 过期）──
@app.get("/gate/{token}", response_class=Response)
async def gate_script_route(token: str):
    js = anti_devtools.get_gate_script(token)
    if js is None:
        raise HTTPException(404, "expired")
    return Response(
        content=js,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )

# ── 浏览器门禁（token 挑战）──
@app.get("/api/gate/register")
async def gate_register(request: Request):
    if not _check_rate(request, bucket="gate_register"):
        raise HTTPException(429, "请求过于频繁，请稍后再试")
    # 动态 cookie 名：真实名混入随机串加密后作为实际 cookie 名，由服务端直接 Set-Cookie，
    # 客户端 JS 完全无感，验证时服务端解密 cookie 名即可识别
    token, cookie_name = anti_devtools.register_gate_token(request)
    resp = JSONResponse({"token": token})
    resp.set_cookie(
        cookie_name, token,
        max_age=config.GATE_COOKIE_MAX_AGE,
        samesite="lax",
        secure=config.HTTPS or config.SSL,
    )
    return resp


@app.post("/api/gate/heartbeat")
async def gate_heartbeat(request: Request):
    # 心跳限速：防止脚本批量保活 token（正常浏览器每 10s 一次 ≈ 6 次/分钟）
    if not _check_rate(request, max_req=config.HEARTBEAT_RATE_MAX, bucket="gate_heartbeat"):
        raise HTTPException(429, "请求过于频繁，请稍后再试")
    ok = anti_devtools.heartbeat_gate_token(request)
    return {"ok": ok}


@app.api_route("/api/gate/kill-report", methods=["POST", "GET"])
async def gate_kill_report(request: Request):
    """反 F12 销毁上报：仅记录日志，用于排查误杀原因。"""
    reason = request.query_params.get("r", "?") or "?"
    ip = request.client.host if request.client else "?"
    print(f"[AF12] kill reason={reason} ip={ip}")
    return Response(status_code=204)


_sessions: dict[str, MusicPlatform] = {}


def _restore_sessions():
    for name, cls in PLATFORMS.items():
        try:
            instance = cls()
            if instance._load_session() and instance.logged_in:
                _sessions[name] = instance
        except Exception:
            pass


_restore_sessions()


def _get_platform(name: str) -> MusicPlatform:
    if name not in _sessions:
        cls = PLATFORMS.get(name)
        if not cls:
            raise HTTPException(400, f"不支持的平台: {name}")
        _sessions[name] = cls()
    return _sessions[name]


def _is_private_ip(ip_str: str) -> bool:
    """判断 IP 是否为内网/环回/保留/非公网地址（含 IPv6）。"""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        or not ip.is_global
    )


def _upgrade_scheme(url: str) -> str:
    """http:// → https:// 升级：CDN 普遍支持 https，规避服务器 80 出站受限环境。"""
    if url.lower().startswith("http://"):
        return "https://" + url[len("http://"):]
    return url


async def _to_thread(func, *args):
    """Python 3.8 兼容的 asyncio.to_thread（服务器为 3.8，to_thread 需 3.9+）。"""
    return await asyncio.get_event_loop().run_in_executor(None, func, *args)


def _validate_proxy_url(raw: str) -> bool:
    """校验代理 URL：协议/端口/域名白名单/解析 IP 非内网（防 SSRF）。"""
    try:
        parsed = urlparse(raw)
        port = parsed.port
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    if port not in config.ALLOWED_PROXY_PORTS:
        return False
    host = (parsed.hostname or "").lower()
    # 域名白名单（拒绝 IP 直连与仿冒域名）
    if not any(host == d or host.endswith("." + d) for d in config.ALLOWED_PROXY_DOMAINS):
        return False
    # 解析全部 A/AAAA 记录，任一内网/保留地址即拒绝（防 DNS 重绑定到内网）
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except Exception:
        return False
    return all(not _is_private_ip(info[4][0]) for info in infos)


# === 敏感接口密码保护 ===
# 令牌每次启动随机生成，服务重启后所有已验证会话失效
_auth_token = secrets.token_hex(32)


def _is_authed(request: Request) -> bool:
    if not config.PASSWORD:
        return True
    # 登录态 cookie 为动态名：遍历解密匹配，恒定时间比较防时序侧信道
    for name, value in request.cookies.items():
        if anti_devtools.is_auth_cookie_name(name):
            return secrets.compare_digest(value, _auth_token)
    return False


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException):
    # 401 时顺带下发删除指令，清掉浏览器里已失效的登录 cookie（含动态名）。
    # 注意：绝不能删门禁 cookie —— 门禁是“普通用户”凭证，401 只代表未登录
    if exc.status_code == 401:
        resp = JSONResponse({"detail": exc.detail}, status_code=401)
        for name in request.cookies:
            if anti_devtools.is_auth_cookie_name(name):
                resp.delete_cookie(name, path="/")
        resp.delete_cookie(config.AUTH_COOKIE_NAME, path="/")
        return resp
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


def _require_auth(request: Request):
    if not _is_authed(request):
        raise HTTPException(401, "需要密码验证")


@app.post("/api/auth/verify")
async def verify_password(request: Request):
    # 限速：防密码爆破（正常用户每次输入只提交 1 次）
    if not _check_rate(request, max_req=config.AUTH_VERIFY_RATE_MAX, bucket="auth_verify"):
        raise HTTPException(429, "尝试次数过多，请稍后再试")
    if not config.PASSWORD:
        return {"success": True}
    body = await request.json()
    pwd = str(body.get("password", ""))
    if config.PASSWORD_HASH:
        # 哈希模式：$sha256$<salt>$<hexdigest>，明文不落盘
        salt, hexdigest = config.PASSWORD_HASH
        ok = secrets.compare_digest(hashlib.sha256((salt + pwd).encode()).hexdigest(), hexdigest)
    else:
        ok = secrets.compare_digest(pwd, config.PASSWORD)
    if not ok:
        # 密码错误 → 触发反 F12 销毁；只清登录 cookie，保留门禁 cookie（门禁是普通用户凭证）
        resp = JSONResponse({"success": False, "destroy": True})
        for name in request.cookies:
            if anti_devtools.is_auth_cookie_name(name):
                resp.delete_cookie(name, path="/")
        resp.delete_cookie(config.AUTH_COOKIE_NAME, path="/")
        return resp
    resp = JSONResponse({"success": True})
    resp.set_cookie(
        anti_devtools.gen_auth_cookie_name(), _auth_token,
        max_age=config.AUTH_COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        # HTTPS 模式（反代终止 TLS 或本地证书）下 cookie 仅允许加密传输
        secure=config.HTTPS or config.SSL,
    )
    return resp


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    # 浏览器门禁：无有效 token 则返回挑战页
    if not anti_devtools.validate_gate_token(request):
        return anti_devtools.challenge_response(
            anti_f12_enabled=not _is_authed(request), request=request
        )

    logged_in = {k: v.logged_in for k, v in _sessions.items()}
    ctx = {
        "request": request,
        "logged_in": logged_in,
        "platforms": PLATFORMS,
        "anti_devtools_script_url": anti_devtools.get_script_url(),
    }
    return templates.TemplateResponse("index.html", ctx)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    # 浏览器门禁：无有效 token 则返回挑战页
    if not anti_devtools.validate_gate_token(request):
        return anti_devtools.challenge_response(
            anti_f12_enabled=not _is_authed(request), request=request
        )

    # 启用密码保护且未验证时，先显示密码验证页
    if not _is_authed(request):
        resp = templates.TemplateResponse("verify.html", {
            "request": request,
            "anti_devtools_script_url": anti_devtools.get_script_url(),
        })
        # 清理浏览器里已失效的登录 cookie（服务重启后 token 变化，旧 cookie 作废）
        for name in request.cookies:
            if anti_devtools.is_auth_cookie_name(name):
                resp.delete_cookie(name, path="/")
        resp.delete_cookie(config.AUTH_COOKIE_NAME, path="/")
        return resp
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
        "anti_devtools_script_url": anti_devtools.get_script_url(),
    })


@app.get("/listen-together", response_class=HTMLResponse)
async def listen_together_page(request: Request):
    # 浏览器门禁：无有效 token 则返回挑战页（一起听歌接口同样受门禁保护）
    if not anti_devtools.validate_gate_token(request):
        return anti_devtools.challenge_response(
            anti_f12_enabled=not _is_authed(request), request=request
        )
    return templates.TemplateResponse("listen_together.html", {
        "request": request,
        "anti_devtools_script_url": anti_devtools.get_script_url(),
    })


@app.get("/api/login/qrcode/{platform}")
async def get_qr_code(platform: str, request: Request):
    _require_auth(request)
    p = _get_platform(platform)
    qr = await p.get_qr_code()
    if not qr:
        raise HTTPException(500, "获取二维码失败")
    return {"qr_image": qr}


@app.get("/api/login/qrcode/{platform}/check")
async def check_qr_status(platform: str, request: Request):
    _require_auth(request)
    p = _get_platform(platform)
    result = await p.check_qr_status()
    if result.get("status") == "success":
        p._persist_session()
        result["user"] = p.user_info
    return result


@app.post("/api/login/cookie/{platform}")
async def login_cookie(platform: str, request: Request):
    _require_auth(request)
    body = await request.json()
    cookie_str = body.get("cookie", "")
    p = _get_platform(platform)
    result = await p.login_cookie(cookie_str)
    if result.get("success"):
        p._persist_session()
        result["user"] = p.user_info
    return result


@app.post("/api/login/phone/{platform}")
async def login_phone(platform: str, request: Request):
    _require_auth(request)
    body = await request.json()
    phone = body.get("phone", "")
    code = body.get("code", "")
    p = _get_platform(platform)
    result = await p.login_phone(phone, code)
    if result.get("success"):
        p._persist_session()
        result["user"] = p.user_info
    return result


@app.post("/api/login/phone/{platform}/send_code")
async def send_phone_code(platform: str, request: Request):
    _require_auth(request)
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

    logger.info("搜索：%s（%s），命中 %s 首，失败平台 %s", keyword, ",".join(targets), total, errors or "无")
    return {
        "songs": [asdict(s) for s in all_songs],
        "total": total,
        "page": page,
        "errors": errors,
    }


@app.get("/api/play/{platform}/{song_id}")
async def get_play_url(platform: str, song_id: str, request: Request):
    extra_str = request.query_params.get("extra", "")
    room_id = int(request.query_params.get("room_id", "0") or "0")  # 一起听歌房间缓存（0=不走缓存）
    import json as _json

    extra = {}
    if extra_str:
        try:
            extra = _json.loads(extra_str)
        except Exception:
            pass

    # 一起听歌：同房间多人听同一首歌复用播放地址（缓存命中免请求平台 API）
    if room_id > 0:
        cached = listen_together.cached_play_url(room_id, platform, song_id, extra)
        if cached:
            logger.info("房间 %s 播放缓存命中，免请求平台：%s/%s", room_id, platform, song_id)
            return cached
        logger.info("房间 %s 播放缓存未命中，请求平台：%s/%s", room_id, platform, song_id)

    from platforms.base import Song

    song = Song(
        id=song_id,
        name="",
        artist="",
        platform=platform,
        extra=extra,
    )

    p = _get_platform(platform)
    is_bilibili = platform == "bilibili"
    if is_bilibili and not config.VIDEO_PLAYBACK_ENABLED:
        # 视频播放开关关闭：B 站只返回音频流（DASH audio）
        url = await p.get_download_url(song, stream_type="audio")
    else:
        url = await p.get_play_url(song)
    if not url:
        raise HTTPException(404, "无法获取播放地址")
    result = {"url": url, "video": is_bilibili and config.VIDEO_PLAYBACK_ENABLED}
    if room_id > 0:
        listen_together.cache_play_url(room_id, platform, song_id, extra, url, result["video"])
        logger.info("房间 %s 播放缓存已写入：%s/%s", room_id, platform, song_id)
    return result


@app.get("/api/lyrics/{platform}/{song_id}")
async def get_lyrics(platform: str, song_id: str, request: Request):
    extra_str = request.query_params.get("extra", "")
    name = request.query_params.get("name", "")
    artist = request.query_params.get("artist", "")
    duration = request.query_params.get("duration", "0")
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
        name=name,
        artist=artist,
        platform=platform,
        duration=int(duration) if duration.isdigit() else 0,
        extra=extra,
    )

    p = _get_platform(platform)
    try:
        lrc = await p.get_lyrics(song)
    except Exception:
        lrc = ""
    logger.info("歌词：%s/%s（%s）", platform, song_id, "有" if lrc else "无")
    return {"lyrics": lrc}


@app.api_route("/api/download/{platform}/{song_id}", methods=["GET", "HEAD"])
async def download_song(platform: str, song_id: str, request: Request):
    extra_str = request.query_params.get("extra", "")
    name = request.query_params.get("name", "unknown")
    artist = request.query_params.get("artist", "unknown")
    quality = request.query_params.get("quality", "320")
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
        # 视频播放开关关闭时，仅允许音频档下载（video/大小写变体/非法值全拦）
        if not config.VIDEO_PLAYBACK_ENABLED and quality != "audio":
            raise HTTPException(403, "视频功能已停用")
        url = await p.get_download_url(song, stream_type=quality)
    else:
        url = await p.get_download_url(song, quality=quality)
    if not url:
        raise HTTPException(404, "无法获取下载地址")
    logger.info("下载：%s - %s（%s/%s，%s）", artist, name, platform, song_id, quality)

    # ── HEAD 请求：仅获取响应头，不下载数据体 ──
    if request.method == "HEAD":
        dl_client = httpx.AsyncClient(
            headers={"User-Agent": config.HTTP_USER_AGENT},
            follow_redirects=True,
            timeout=httpx.Timeout(config.DOWNLOAD_TIMEOUT_CONNECT, read=config.HEAD_TIMEOUT_READ),
        )
        from urllib.parse import urlparse as _urlparse
        dl_domain = _urlparse(url).hostname or ""
        if "163.com" in dl_domain or "126.net" in dl_domain:
            dl_referer = "https://music.163.com/"
        elif "kugou.com" in dl_domain:
            dl_referer = "https://www.kugou.com/"
        elif "bilibili.com" in dl_domain or "bilivideo.com" in dl_domain or "hdslb.com" in dl_domain:
            dl_referer = "https://www.bilibili.com/"
        else:
            dl_referer = ""
        dl_headers = {}
        if dl_referer:
            dl_headers["Referer"] = dl_referer
        if "bilibili.com" in dl_domain or "bilivideo.com" in dl_domain or "hdslb.com" in dl_domain:
            dl_headers["Origin"] = "https://www.bilibili.com"
        try:
            head_req = dl_client.build_request("HEAD", url, headers=dl_headers)
            head_resp = await dl_client.send(head_req)
        except Exception:
            await dl_client.aclose()
            raise HTTPException(500, "获取文件信息失败")
        content_type = head_resp.headers.get("content-type", "application/octet-stream")
        content_length = head_resp.headers.get("content-length", "")
        await head_resp.aclose()
        await dl_client.aclose()

        _ext_map = {
            "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "video/mp4": ".mp4",
            "audio/flac": ".flac", "audio/x-flac": ".flac",
            "audio/ogg": ".ogg", "audio/aac": ".aac",
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
            "Cache-Control": "no-store",
        }
        if content_length:
            resp_headers["Content-Length"] = content_length
        from starlette.responses import Response as _HeadResp
        return _HeadResp(status_code=200, headers=resp_headers, media_type=content_type)

    # ── GET 请求：流式下载 ──
    dl_client = httpx.AsyncClient(
        headers={"User-Agent": config.HTTP_USER_AGENT},
        follow_redirects=True,
        timeout=httpx.Timeout(config.DOWNLOAD_TIMEOUT_CONNECT, read=config.DOWNLOAD_TIMEOUT_READ),
    )
    from urllib.parse import urlparse as _urlparse
    dl_domain = _urlparse(url).hostname or ""
    if "163.com" in dl_domain or "126.net" in dl_domain:
        dl_referer = "https://music.163.com/"
    elif "kugou.com" in dl_domain:
        dl_referer = "https://www.kugou.com/"
    elif "bilibili.com" in dl_domain or "bilivideo.com" in dl_domain or "hdslb.com" in dl_domain:
        dl_referer = "https://www.bilibili.com/"
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

    first_chunk = b""
    raw_iter = dl_resp.aiter_raw()
    try:
        first_chunk = await raw_iter.__anext__()
    except StopAsyncIteration:
        first_chunk = b""
    except Exception:
        await dl_resp.aclose()
        await dl_client.aclose()
        raise HTTPException(500, "读取下载数据失败")

    if first_chunk:
        peek = first_chunk[:16]
        if peek[:4] == b"fLaC":
            ext = ".flac"
        elif peek[:3] == b"ID3" or (len(peek) >= 2 and peek[0:2] == b"\xff\xfb") or (len(peek) >= 2 and peek[0] == 0xff and (peek[1] & 0xe0) == 0xe0):
            ext = ".mp3"
        elif peek[:4] == b"ftyp" or peek[4:8] == b"ftyp":
            ext = ".m4a"
        elif peek[:4] == b"OggS":
            ext = ".ogg"

    if quality == "lossless" and ext == ".mp3":
        import logging
        logging.getLogger(__name__).warning("Requested lossless for %s/%s but server returned MP3", platform, song_id)

    filename = f"{artist} - {name}{ext}"
    safe_filename = "".join(c for c in filename if c not in r'\/:*?"<>|')
    from urllib.parse import quote
    encoded_filename = quote(safe_filename)

    resp_headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        "Cache-Control": "no-store",
    }
    content_length = dl_resp.headers.get("content-length", "")
    if content_length:
        resp_headers["Content-Length"] = content_length

    async def dl_stream():
        try:
            if first_chunk:
                yield first_chunk
            async for chunk in raw_iter:
                yield chunk
        finally:
            await dl_resp.aclose()
            await dl_client.aclose()

    return StreamingResponse(dl_stream(), media_type=content_type, headers=resp_headers)


@app.get("/api/resolve-song/{platform}/{song_id}")
async def resolve_song(platform: str, song_id: str):
    p = _get_platform(platform)
    song = await p.get_song_detail(song_id)
    if song is None:
        raise HTTPException(404, "无法获取歌曲信息")
    logger.info("歌曲详情：%s/%s（%s - %s）", platform, song_id, song.artist, song.name)
    return asdict(song)


@app.get("/api/info/{platform}/{song_id}")
async def get_song_info(platform: str, song_id: str, request: Request):
    extra_str = request.query_params.get("extra", "")
    name = request.query_params.get("name", "")
    artist = request.query_params.get("artist", "")
    album = request.query_params.get("album", "")
    duration = request.query_params.get("duration", "0")
    import json as _json

    extra = {}
    if extra_str:
        try:
            extra = _json.loads(extra_str)
        except Exception:
            pass

    from platforms.base import Song

    song = Song(
        id=song_id, name=name, artist=artist, album=album,
        platform=platform,
        duration=int(duration) if duration.isdigit() else 0,
        extra=extra,
    )

    p = _get_platform(platform)
    qualities = p.get_available_qualities(song)
    if platform == "bilibili" and not config.VIDEO_PLAYBACK_ENABLED:
        # 视频开关关闭：详情面板不展示视频下载档
        qualities = [q for q in qualities if q.get("value") != "video"]

    return {
        "name": song.name,
        "artist": song.artist,
        "album": song.album,
        "platform": platform,
        "platform_name": p.name,
        "duration": song.duration,
        "id": song.id,
        "qualities": qualities,
        "extra": extra,
    }


@app.get("/api/status")
async def get_status(request: Request):
    _require_auth(request)
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
    # 下发视频播放开关状态（前端据此隐藏“下载视频”等入口）
    result["video_playback"] = config.VIDEO_PLAYBACK_ENABLED
    return result


@app.post("/api/logout/{platform}")
async def logout(platform: str, request: Request):
    _require_auth(request)
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
    # ── SSRF 防护：域名白名单 + 解析 IP 非内网 + 端口限制 ──
    if not await _to_thread(_validate_proxy_url, url):
        raise HTTPException(400, "代理目标不合法")
    range_header = request.headers.get("range")
    domain = urlparse(url).hostname or ""
    logger.debug("代理流：%s%s（range=%s）", domain, urlparse(url).path[:60], range_header or "-")
    # 防盗链头（域名已通过白名单校验）
    referer = ""
    for suffix, ref in config.PROXY_REFERER_MAP:
        if domain == suffix or domain.endswith("." + suffix):
            referer = ref
            break
    headers = {
        "User-Agent": config.HTTP_USER_AGENT,
    }
    if referer:
        headers["Referer"] = referer
    if any(domain == s or domain.endswith("." + s) for s in ("bilibili.com", "bilivideo.com", "hdslb.com", "akamaized.net")):
        headers["Origin"] = "https://www.bilibili.com"
    if range_header:
        headers["Range"] = range_header

    # 关闭自动重定向，手动逐跳校验（每跳重新过白名单/IP 检查，防重定向到内网）
    client = httpx.AsyncClient(follow_redirects=False, timeout=httpx.Timeout(config.DOWNLOAD_TIMEOUT_CONNECT, read=config.DOWNLOAD_TIMEOUT_READ))
    current = url
    resp = None
    try:
        for _ in range(config.PROXY_MAX_REDIRECTS + 1):
            try:
                req = client.build_request("GET", current, headers=headers)
                resp = await client.send(req, stream=True)
            except httpx.ConnectError as e:
                # http 源站连接失败（常见：服务器禁 80 出站）→ 升级 https 重试一次
                if current.lower().startswith("http://"):
                    current = _upgrade_scheme(current)
                    print(f"[proxy] http connect failed, upgraded to https: {current[:120]}")
                    try:
                        req = client.build_request("GET", current, headers=headers)
                        resp = await client.send(req, stream=True)
                    except Exception as e2:
                        await client.aclose()
                        print(f"[proxy] FAIL url={current} type={type(e2).__name__}: {e2}")
                        raise HTTPException(500, "代理请求失败")
                else:
                    await client.aclose()
                    print(f"[proxy] FAIL url={current} type={type(e).__name__}: {e}")
                    raise HTTPException(500, "代理请求失败")
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                await resp.aclose()
                resp = None
                if not loc:
                    raise HTTPException(500, "代理请求失败")
                current = str(httpx.URL(current).join(loc))
                # 302 到 http 明文（网易/酷狗 CDN 典型行为）→ 优先升级 https，规避 80 出站受限
                if current.lower().startswith("http://"):
                    https_url = _upgrade_scheme(current)
                    if await _to_thread(_validate_proxy_url, https_url):
                        current = https_url
                if not await _to_thread(_validate_proxy_url, current):
                    raise HTTPException(400, "代理目标不合法")
                continue
            break
        if resp is None:
            raise HTTPException(500, "代理请求失败")
        if resp.status_code not in (200, 206):
            await resp.aclose()
            await client.aclose()
            raise HTTPException(500, "代理请求失败")
    except HTTPException:
        await client.aclose()
        raise
    except Exception as e:
        await client.aclose()
        # 服务器端日志：记录具体失败原因（超时/连接拒绝/SSL 等），便于定位
        print(f"[proxy] FAIL url={current} type={type(e).__name__}: {e}")
        raise HTTPException(500, "代理请求失败")

    content_type = resp.headers.get("content-type", "application/octet-stream")
    content_length = resp.headers.get("content-length", "")

    async def stream():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=config.PROXY_CHUNK_SIZE):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    resp_headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Cache-Control": "no-store",
    }
    if content_length:
        resp_headers["Content-Length"] = content_length
    if resp.status_code == 206:
        resp_headers["Content-Range"] = resp.headers.get("content-range", "")

    return StreamingResponse(stream(), status_code=resp.status_code, headers=resp_headers)


if __name__ == "__main__":
    import uvicorn

    args = config.parse_args()
    _configure_logging()  # --debug 可能覆盖了 DEBUG：按最终值重配日志级别

    # 一起听歌房间数可能被命令行参数覆盖：按最终值重建常驻房间（启动前房间为空，无状态损失）
    listen_together.reinit_rooms()

    # 部署自检（防运维配置陷阱）
    # 1) 反代模式：forwarded_allow_ips 未改则所有客户端共享代理 IP（限速变全局限流、
    #    token 的 IP 指纹绑定失效）。默认值 127.0.0.1 仅对"Nginx 与后端同机"正确。
    if args.https and config.FORWARDED_ALLOW_IPS == "127.0.0.1":
        print("[警告] 反代模式(https=true)下 FORWARDED_ALLOW_IPS 仍为默认 127.0.0.1："
              "仅当 Nginx 与后端同机时正确；若不在同一台机器，请将 config.py 的 "
              "FORWARDED_ALLOW_IPS 改为 Nginx 服务器实际 IP，否则所有客户端将共享同一 IP。")
    # 2) 本程序为单进程设计（限速/token 均为内存态）：请勿用 `uvicorn main:app --workers N`
    #    多进程部署，否则限速阈值按 Worker 数放大、门禁 token 不共享，安全防线失效。
    if os.environ.get("MUSICCATCH_WORKERS"):
        print("[警告] 检测到多进程部署意图（MUSICCATCH_WORKERS）：本程序限速/token 为内存态，"
              "多进程下限速阈值放大、门禁 token 不共享。请保持单进程，或接入 Redis 后自行改造。")

    if config.IS_FROZEN:
        import threading
        import webbrowser
        scheme = "https" if args.ssl else "http"
        threading.Timer(config.FROZEN_BROWSER_OPEN_DELAY, lambda: webbrowser.open(f"{scheme}://localhost:{args.port}")).start()

    uvicorn_kwargs = {"host": args.host, "port": args.port}
    if args.https:
        # 反向代理终止 TLS：信任代理的 X-Forwarded-Proto/For 头，
        # 让 FastAPI 正确识别外部 https 协议和客户端真实 IP
        uvicorn_kwargs["proxy_headers"] = True
        # 可信代理 IP 白名单（config.py FORWARDED_ALLOW_IPS）：
        # 防止攻击者直连后端伪造 X-Forwarded-For 绕过限速与 token 指纹绑定
        uvicorn_kwargs["forwarded_allow_ips"] = config.FORWARDED_ALLOW_IPS
    if args.ssl:
        # 本程序直接加载证书提供 HTTPS
        uvicorn_kwargs["ssl_certfile"] = args.ssl_certfile
        uvicorn_kwargs["ssl_keyfile"] = args.ssl_keyfile

    uvicorn.run(app, **uvicorn_kwargs)
