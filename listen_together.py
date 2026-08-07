"""一起听歌：10 个常驻房间 + 双传输实时同步播放（config.LT_TRANSPORT 全局统一切换）。

传输层两种实现，同一房间同一配置（不做混合/降级）：
- http（默认，长轮询）：GET /api/listen-together/poll?room_id=N&version=V
  房间 version 变化时立即返回全量快照，无变化时挂起至超时（LT_POLL_TIMEOUT）后
  返回当前快照，客户端随即发起下一轮，形成连续轮询链（轮询本身即心跳保活）
- ws（低延迟推送）：/api/listen-together/ws?room_id=N&name=X（需 uvicorn[standard]）
  握手即进房并推初始快照，之后服务端主动推送状态；客户端 30s 心跳续期成员在线；
  连接断开不立即踢成员，由 LT_MEMBER_TTL 兜底清理（与 HTTP 断线一致）

两种模式共用同一套状态与动作语义：
- 状态变更：POST /api/listen-together/action?room_id=N（add/play/pause/next/prev/
  seek/remove/transfer/rename_room/sync），仅房主可执行播放控制与上报
- 成员在线：轮询/心跳即续期 last_seen；显式离开走 POST leave；超时（LT_MEMBER_TTL）
  由 _gc_room_members 兜底清理，房主离开自动转让

- 门禁：进入页面 / 调用接口均需有效门禁 token（/api/ 中间件统一校验；WS 握手不走
  HTTP 中间件，由 WS 端点内手动校验）；token 失效时前端自动重新注册并重连
- 用户标识：听客户端的，用户名即身份，服务端不绑定 IP；进房时下发会话 cookie
  （mc_lt_sid，HttpOnly；HTTP 模式由 poll/action 响应下发，WS 模式在 accept 时下发），
  刷新页面凭 cookie 识别本人会话
- 同名进房：房间内已有同名成员且非本人会话（cookie 不匹配）时拒绝进入（403 进入失败）
- 改名：无次数限制（客户端直接传新名字，保存在浏览器 localStorage）
- 房间：10 个常驻；空房恢复默认名"x号房"；第一个进入者成为房主，
  进入时房间名未被自定义则自动命名为"{房主名} 的房间"；房主可自定义房间名、
  可转让房主；房主离开但房间还有人时自动转让给最早加入的成员
- 队列：任何成员可添加歌曲；仅房主可删除歌曲
- 播放同步：播放/暂停/切歌/拖动仅房主，位置由房主周期心跳上报（全员对齐房主进度）
"""
import asyncio
import json
import logging
import secrets
import time

from fastapi import APIRouter, Request, HTTPException, WebSocket
from fastapi.responses import JSONResponse

import config
import anti_devtools

logger = logging.getLogger(__name__)

router = APIRouter()


# ── 用户（听客户端的：用户名即身份，服务端不绑定 IP、不做全局唯一占用）──
# name -> {"last_seen": float}
_USERS: dict[str, dict] = {}
_USER_MAX = 20000  # 键数量上限，超限删最旧一半（防内存溢出）


def _gc_users() -> None:
    """清理失效用户记录（仅保证内存有界；名字不占用，随时可再次使用）。"""
    now = time.time()
    for name in [n for n, u in _USERS.items() if now - u["last_seen"] > config.LT_NAME_TTL]:
        _USERS.pop(name, None)
    # 容量上限兜底：删最旧一半（大量一次性访问时保证内存有界）
    if len(_USERS) > _USER_MAX:
        cutoff = sorted(u["last_seen"] for u in _USERS.values())[len(_USERS) // 2]
        for name in [n for n, u in _USERS.items() if u["last_seen"] < cutoff]:
            _USERS.pop(name, None)


def _sanitize_name(raw, field="名称") -> str:
    """清理用户输入名称：去首尾空白、剔除控制字符、限制长度。"""
    name = "".join(c for c in (raw or "").strip() if c >= " " and c != "\x7f")
    if not name:
        raise HTTPException(400, f"{field}不能为空")
    if len(name) > config.LT_NAME_MAX_LEN:
        raise HTTPException(400, f"{field}过长（最多 {config.LT_NAME_MAX_LEN} 个字符）")
    return name


def _request_name(request: Request) -> str:
    """从请求 query 取客户端用户名（一起听歌所有接口统一带 ?name=，服务端信任）。"""
    return _sanitize_name(request.query_params.get("name"), "用户名")


# ── 房间 ──
class LTRoom:
    def __init__(self, idx: int):
        self.idx = idx
        self.default_name = f"{idx + 1}号房"
        self.name = self.default_name
        self.name_customized = False  # 房主自定义过名称后，进人不再自动改名
        self.owner: str | None = None     # 房主用户名
        self.members: dict[str, dict] = {}  # 用户名 -> {"joined": float, "last_seen": float, "sid": str}
        self.queue: list[dict] = []         # 歌曲项（含 added_by_name）
        self.current_index = -1
        self.playing = False
        self.position = 0.0
        self.version = 0                    # 状态版本号，客户端据此判断变化


_ROOMS = [LTRoom(i) for i in range(config.LT_ROOM_COUNT)]


def reinit_rooms() -> None:
    """按 config.LT_ROOM_COUNT 重建常驻房间（仅启动时调用；启动前房间为空，无状态损失）。"""
    global _ROOMS
    _ROOMS = [LTRoom(i) for i in range(config.LT_ROOM_COUNT)]


# room_idx -> asyncio.Event：状态变更时 set 唤醒所有挂起的长轮询。
# 惰性创建：Python 3.8 的 asyncio.Event() 构造时即绑定 get_event_loop() 返回的 loop，
# 模块导入期创建会绑定到主线程隐式 loop，与 uvicorn 的事件循环不一致，wait() 抛
# "attached to a different loop"。故仅在请求协程内（running loop 存在时）创建。
_POLL_EVENTS: dict[int, asyncio.Event] = {}


def _poll_event(room_idx: int) -> asyncio.Event:
    ev = _POLL_EVENTS.get(room_idx)
    if ev is None:
        ev = asyncio.Event()
        _POLL_EVENTS[room_idx] = ev
    return ev


def _room_state(room: LTRoom) -> dict:
    members = [
        {"name": m_name}
        for m_name, m in sorted(room.members.items(), key=lambda kv: kv[1]["joined"])
    ]
    return {
        "id": room.idx + 1,
        "name": room.name,
        "owner": room.owner,
        "members": members,
        "queue": room.queue,
        "current_index": room.current_index,
        "playing": room.playing,
        "position": room.position,
        "version": room.version,
        "ts": time.time(),
    }


def _bump_state(room: LTRoom) -> None:
    """状态变更：版本号 +1 并唤醒挂起的长轮询；WS 在线时推送房间快照与列表摘要。"""
    room.version += 1
    _poll_event(room.idx).set()
    _ws_broadcast(room)
    _ws_send_rooms()  # 房间变化 → 列表页实时刷新（人数/当前播放）
    _gc_room_cache(room)  # 顺带清理过期播放缓存（当前播放歌曲视为活跃，不删）


# ── 房间播放缓存（同一房间多人听同一首歌复用播放地址，避免反复请求平台 API）──
# room_idx -> song_key -> {"url": str, "video": bool, "expire": float}
# 生命周期绑定"正在播放时间 ± LT_CACHE_MARGIN"：当前播放歌曲每次状态变更（含房主
# 位置心跳）自动续期，播放中一直有效；切歌/停止后不再续期，超过余量（默认 5 分钟）
# 未命中自动删除，供快速切回/新成员加入时复用
_ROOM_CACHE: dict[int, dict[str, dict]] = {}
_CACHE_MAX_KEYS = 32  # 单房间缓存键数上限，超限删最旧一半（防内存溢出）


def _cache_key(platform: str, song_id: str, extra: dict | None) -> str:
    """缓存键：平台 + 歌曲 id + extra（extra 影响播放地址，如音质/清晰度）。"""
    return f"{platform}|{song_id}|{json.dumps(extra or {}, sort_keys=True, ensure_ascii=False)}"


def _is_current_song(room: LTRoom, key: str) -> bool:
    """缓存键是否对应房间当前正在播放的歌曲。"""
    if 0 <= room.current_index < len(room.queue):
        s = room.queue[room.current_index]
        return _cache_key(s["platform"], s["id"], s.get("extra")) == key
    return False


def _room_cache_get(room: LTRoom, platform: str, song_id: str, extra: dict | None):
    """取缓存播放条目（命中续期）；过期条目删除，但当前播放歌曲即使过期也保留续期。"""
    bucket = _ROOM_CACHE.setdefault(room.idx, {})
    key = _cache_key(platform, song_id, extra)
    ent = bucket.get(key)
    if ent is None:
        return None
    if time.time() >= ent["expire"] and not _is_current_song(room, key):
        bucket.pop(key, None)
        return None
    ent["expire"] = time.time() + config.LT_CACHE_MARGIN  # 命中续期
    return ent


def _room_cache_put(room: LTRoom, platform: str, song_id: str, extra: dict | None, url: str, video: bool) -> None:
    """写入缓存条目；超容量时删最旧一半（防内存溢出）。"""
    bucket = _ROOM_CACHE.setdefault(room.idx, {})
    bucket[_cache_key(platform, song_id, extra)] = {
        "url": url, "video": video, "expire": time.time() + config.LT_CACHE_MARGIN,
    }
    if len(bucket) > _CACHE_MAX_KEYS:
        cutoff = sorted(e["expire"] for e in bucket.values())[len(bucket) // 2]
        for k in [k for k, e in bucket.items() if e["expire"] < cutoff]:
            bucket.pop(k, None)


def _gc_room_cache(room: LTRoom) -> None:
    """清理过期缓存条目；当前正在播放的歌曲视为活跃（播放中不删除）。"""
    bucket = _ROOM_CACHE.get(room.idx)
    if not bucket:
        return
    now = time.time()
    for k in [k for k, e in bucket.items() if not _is_current_song(room, k) and now >= e["expire"]]:
        bucket.pop(k, None)


def cached_play_url(room_id: int, platform: str, song_id: str, extra: dict | None):
    """供 main.py 播放端点调用：房间播放缓存命中返回 {"url","video"}，否则 None。"""
    try:
        room = _get_room(room_id)
    except HTTPException:
        return None
    ent = _room_cache_get(room, platform, song_id, extra)
    if ent is None:
        return None
    return {"url": ent["url"], "video": ent["video"]}


def cache_play_url(room_id: int, platform: str, song_id: str, extra: dict | None, url: str, video: bool) -> None:
    """供 main.py 播放端点调用：写入房间播放缓存（房间不存在静默跳过）。"""
    try:
        room = _get_room(room_id)
    except HTTPException:
        return
    _room_cache_put(room, platform, song_id, extra, url, video)


# ── WebSocket 实时通道（config.LT_TRANSPORT="ws" 时使用；HTTP 长轮询模式不受影响）──
# 全局连接：列表页即建立（未进房时订阅房间列表推送，进房后订阅房间状态，进房/离开/动作均走消息）。
# ws -> {"name": str, "sid": str, "room_idx": int | None}（room_idx=None 表示列表模式）
_WS_CLIENTS: dict[WebSocket, dict] = {}
_WS_BY_ROOM: dict[int, set] = {}  # room_idx -> {WebSocket}（房间内连接，用于广播）


def _ws_send_to(ws: WebSocket, obj: dict) -> None:
    """向单个连接推送 JSON（fire-and-forget，发送失败的连接由对端断开兜底）。"""
    asyncio.create_task(_ws_send_safe(ws, json.dumps(obj, ensure_ascii=False)))


def _ws_broadcast(room: LTRoom) -> None:
    """向房间内所有 WS 连接推送最新快照（fire-and-forget，发送失败的连接由对端断开兜底）。"""
    conns = _WS_BY_ROOM.get(room.idx)
    if not conns:
        return
    payload = json.dumps({"type": "state", "room": _room_state(room)}, ensure_ascii=False)
    for ws in list(conns):
        asyncio.create_task(_ws_send_safe(ws, payload))


async def _ws_send_safe(ws: WebSocket, payload: str) -> None:
    try:
        await ws.send_text(payload)
    except Exception:
        pass  # 连接已断：由 receive 循环清理或成员 TTL 兜底


def _rooms_summary() -> list[dict]:
    """房间列表摘要（ws 推送与 http 轮询共用同一数据源）。"""
    out = []
    for room in _ROOMS:
        cur = ""
        if 0 <= room.current_index < len(room.queue):
            s = room.queue[room.current_index]
            cur = f"{s['name']} - {s['artist']}".strip(" -")
        out.append({
            "id": room.idx + 1,
            "name": room.name,
            "online": len(room.members),
            "owner_name": room.owner or "",
            "current_song": cur,
        })
    return out


def _ws_send_rooms() -> None:
    """向所有列表模式连接推送房间列表摘要（fire-and-forget；房间状态变化时随 _bump_state 触发，
    替代前端 10s HTTP 轮询——列表页长驻连接即可实时刷新人数/当前播放）。"""
    payload = json.dumps({"type": "rooms", "rooms": _rooms_summary()}, ensure_ascii=False)
    for ws, info in list(_WS_CLIENTS.items()):
        if info.get("room_idx") is None:
            asyncio.create_task(_ws_send_safe(ws, payload))


def _ask_owner_sync(room: LTRoom) -> None:
    """新成员进房时询问房主当前播放进度（房主 WS 在线且播放中才问）。

    房主应答 {"t":"sync","pos":X} 后由消息循环更新进度并广播；不应答无妨
    （新成员按房间已记录位置对齐，下次动作/切歌自然校准）。按需询问替代房主周期上报。
    """
    if not room.playing or not room.owner:
        return
    for ws, info in list(_WS_CLIENTS.items()):
        if info.get("room_idx") == room.idx and info.get("name") == room.owner:
            _ws_send_to(ws, {"type": "ask_sync"})
            return


# ── 进出房间 ──
_LT_SID_COOKIE = "mc_lt_sid"


def _sid_cookie(sid: str) -> str:
    """房间会话 cookie：HttpOnly 防 JS 读取，30 天有效期（成员离线由 TTL 清理后自然失效）。"""
    return f"{_LT_SID_COOKIE}={sid}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"


def _on_enter(room: LTRoom, name: str, sid: str = "") -> str:
    """成员进房：无 sid 或 sid 已被房间内其他成员占用时重新分配会话 id。

    返回 sid，由调用方通过 Set-Cookie 下发（刷新页面凭它识别本人会话）。
    """
    if not sid or any(m.get("sid") == sid for m in room.members.values()):
        sid = secrets.token_hex(16)
    first = not room.members
    room.members[name] = {"joined": time.time(), "last_seen": time.time(), "sid": sid}
    if first:
        # 空房第一个进入者成为房主；房间名未被自定义时自动命名"xxx 的房间"
        room.owner = name
        if not room.name_customized:
            room.name = f"{name} 的房间"
    logger.info("成员进房：%s → %s（房主=%s，共 %s 人）", name, room.name, room.owner, len(room.members))
    return sid


def _on_leave(room: LTRoom, name: str) -> None:
    room.members.pop(name, None)
    if not room.members:
        # 房间空了：恢复默认名，清空播放状态（队列保留，供下一个人接着用）
        room.owner = None
        room.name = room.default_name
        room.name_customized = False
        room.current_index = -1
        room.playing = False
        room.position = 0.0
        _ROOM_CACHE.pop(room.idx, None)  # 无人听歌，缓存一并清空
        logger.info("成员离开：%s（%s 已空，播放状态重置）", name, room.name)
    elif room.owner == name:
        # 房主离开但房间还有人：自动转让给最早加入的成员（房间名保持不变）
        room.owner = min(room.members, key=lambda n: room.members[n]["joined"])
        logger.info("成员离开：%s（房主转让给 %s，剩余 %s 人）", name, room.owner, len(room.members))
    else:
        logger.info("成员离开：%s（%s，剩余 %s 人）", name, room.name, len(room.members))


def _gc_room_members(room: LTRoom) -> bool:
    """清理停止轮询超过宽限的成员（断网/关页兜底），返回是否有成员被清理。"""
    now = time.time()
    changed = False
    for name in [n for n, m in room.members.items() if now - m["last_seen"] > config.LT_MEMBER_TTL]:
        _on_leave(room, name)
        changed = True
    return changed


# ── 房间内消息处理（HTTP action 语义：错误抛 400，由客户端 toast）──
def _handle_message(room: LTRoom, name: str, msg: dict) -> None:
    mtype = msg.get("type")

    if mtype == "add":
        # 任何成员可添加歌曲（队列上限防内存滥用；空队列自动开播第一首）
        song = msg.get("song")
        if not isinstance(song, dict):
            raise HTTPException(400, "歌曲信息不完整")
        sid = str(song.get("id") or "").strip()
        sname = str(song.get("name") or "").strip()
        platform = str(song.get("platform") or "").strip()
        if not sid or not sname or not platform or len(sid) > 200 or len(sname) > 200:
            raise HTTPException(400, "歌曲信息不完整")
        if len(room.queue) >= config.LT_QUEUE_MAX:
            raise HTTPException(400, f"队列已满（最多 {config.LT_QUEUE_MAX} 首）")
        extra = song.get("extra") if isinstance(song.get("extra"), dict) else {}
        room.queue.append({
            "id": sid,
            "name": sname,
            "artist": str(song.get("artist") or "").strip(),
            "album": str(song.get("album") or "").strip(),
            "cover": str(song.get("cover") or "").strip(),
            "platform": platform,
            "duration": int(song.get("duration") or 0),
            "extra": extra,
            "added_by_name": name,
        })
        if room.current_index < 0:
            room.current_index = 0
            room.playing = True
            room.position = 0.0
        _bump_state(room)
        logger.info("加歌：%s 添加「%s - %s」（%s，队列 %s 首）", name, sname, song.get("artist") or "", platform, len(room.queue))

    elif mtype == "remove":
        # 仅房主可删除
        if room.owner != name:
            return
        index = int(msg.get("index", -1))
        if index < 0 or index >= len(room.queue):
            return
        room.queue.pop(index)
        if room.current_index > index:
            room.current_index -= 1
        elif room.current_index == index:
            if room.queue:
                room.current_index = min(index, len(room.queue) - 1)
            else:
                room.current_index = -1
                room.playing = False
                room.position = 0.0
        _bump_state(room)

    elif mtype == "play":
        # 仅房主可控制播放（暂停/切歌/拖动进度同）
        if room.owner != name:
            logger.debug("非房主尝试播放被忽略：%s（房主=%s）", name, room.owner)
            return
        index = int(msg.get("index", -1))
        if index < 0 or index >= len(room.queue):
            return
        room.current_index = index
        room.playing = True
        room.position = 0.0
        _bump_state(room)
        logger.info("播放：%s → %s 第 %s 首", name, room.name, index + 1)

    elif mtype == "pause":
        if room.owner != name:
            logger.debug("非房主尝试暂停被忽略：%s（房主=%s）", name, room.owner)
            return
        room.playing = False
        _bump_state(room)
        logger.info("暂停：%s（%s）", name, room.name)

    elif mtype == "next":
        if room.owner != name:
            return
        if room.current_index + 1 < len(room.queue):
            room.current_index += 1
            room.playing = True
            room.position = 0.0
        else:
            room.playing = False  # 播完队列末尾：停止
            room.position = 0.0
        _bump_state(room)
        logger.info("切歌：%s → 第 %s 首（%s）", name, room.current_index + 1, "播放" if room.playing else "队列末尾停止")

    elif mtype == "prev":
        if room.owner != name:
            return
        if room.current_index > 0:
            room.current_index -= 1
        room.playing = True
        room.position = 0.0
        _bump_state(room)
        logger.info("上一首：%s → 第 %s 首", name, room.current_index + 1)

    elif mtype == "seek":
        if room.owner != name:
            return
        room.position = max(0.0, float(msg.get("position", 0) or 0))
        _bump_state(room)
        logger.info("拖动进度：%s → %.1f 秒", name, room.position)

    elif mtype == "sync":
        # 位置心跳仅房主上报（全员对齐房主进度，避免多人上报互相覆盖）；
        # 暂停状态以 pause 消息为准；version+1 驱动轮询立即返回最新进度
        if room.owner != name:
            return
        if room.playing:
            room.position = max(0.0, float(msg.get("position", 0) or 0))
            _bump_state(room)
            logger.debug("房主位置上报：%s → %.1f 秒（%s）", name, room.position, room.name)

    elif mtype == "transfer":
        # 仅房主可转让
        if room.owner != name:
            return
        target = str(msg.get("target") or "")
        if target in room.members:
            room.owner = target
            _bump_state(room)
            logger.info("房主转让：%s → %s（%s）", name, target, room.name)

    elif mtype == "rename_room":
        # 仅房主可修改房间名（自定义后进人不再自动改名；房间空了恢复默认名）
        if room.owner != name:
            return
        room.name = _sanitize_name(msg.get("name"), "房间名")
        room.name_customized = True
        _bump_state(room)
        logger.info("房间改名：%s 改为「%s」", name, room.name)


def _require_user(request: Request) -> str:
    """听客户端的：用户名由请求自带（?name=），服务端信任并续期活动时间。

    门禁（/api/ 中间件）负责站点验证；此处不做 IP 绑定、不做名字占用校验。
    """
    _gc_users()
    name = _request_name(request)
    user = _USERS.setdefault(name, {"last_seen": 0.0})
    user["last_seen"] = time.time()  # 接口调用即活动
    return name


def _get_room(room_id: int) -> LTRoom:
    idx = room_id - 1
    if idx < 0 or idx >= config.LT_ROOM_COUNT:
        raise HTTPException(404, "房间不存在")
    return _ROOMS[idx]


# ── HTTP API ──
@router.get("/api/listen-together/rooms")
async def lt_rooms(request: Request):
    """房间列表摘要（http 模式前端轮询；ws 模式由 WS 推送，此接口保留作降级）。"""
    _gc_users()
    name = (request.query_params.get("name") or "").strip()
    if name:
        u = _USERS.setdefault(_sanitize_name(name, "用户名"), {})
        u["last_seen"] = time.time()  # 列表页停留也视为活跃
    return {"rooms": _rooms_summary()}


@router.post("/api/listen-together/join")
async def lt_join(request: Request):
    """确认用户名（听客户端的：名字即身份，不做 IP 绑定、不做占用检查）。

    不带 name 调用仅探测：直接返回 need_input=true 由前端弹窗输入。
    """
    _gc_users()
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    name = (body.get("name") or "").strip()
    if not name:
        return {"need_input": True}
    name = _sanitize_name(name, "用户名")
    _USERS.setdefault(name, {})["last_seen"] = time.time()
    return {"need_input": False, "name": name}


@router.post("/api/listen-together/rename")
async def lt_rename(request: Request):
    """修改用户名（听客户端的：直接信任新名字，无每日次数限制）。"""
    _gc_users()
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    name = _sanitize_name(body.get("name"), "用户名")
    _USERS.setdefault(name, {})["last_seen"] = time.time()
    return {"name": name}


@router.get("/api/listen-together/config")
async def lt_config():
    """一起听歌前端配置：输入长度限制、传输方式等（跟随 config.py，改配置即改提示/行为）。"""
    return {
        "nameMaxLen": config.LT_NAME_MAX_LEN,
        "transport": config.LT_TRANSPORT,  # "http"（长轮询）或 "ws"（WebSocket）
        "wsUrl": config.LT_WS_URL,  # WebSocket 连接地址覆盖（配置了则从该地址连接，空=当前域名）
    }


@router.get("/api/listen-together/precheck")
async def lt_precheck(request: Request, room_id: int):
    """进房前重名预检：零副作用（不清理成员、不修改房间状态）。

    房间内已有同名成员且非本人会话（cookie 不匹配）时 403。
    前端点击进入前先调用，重名直接拦截，避免进房请求触发成员清理链（房主
    轮询稍慢被误清会重置播放状态、导致房主的歌自动暂停）。
    """
    name = _require_user(request)
    room = _get_room(room_id)
    sid = request.cookies.get(_LT_SID_COOKIE, "")
    if name in room.members and room.members[name].get("sid") != sid:
        raise HTTPException(403, "该用户名已在房间中，进入失败")
    return {"ok": True}


@router.get("/api/listen-together/poll")
async def lt_poll(request: Request, room_id: int, version: int = -1):
    """长轮询：version 变化立即返回全量快照，否则挂起至超时后返回当前快照。

    轮询即心跳（续期成员 last_seen）；不在房间则自动进房；顺带清理离线成员。
    """
    name = _require_user(request)
    room = _get_room(room_id)
    sid = request.cookies.get(_LT_SID_COOKIE, "")

    changed = _gc_room_members(room)
    if name in room.members:
        # 同名成员已存在：仅当携带匹配的会话 cookie 才视为本人刷新续期，否则拒绝进入
        if not sid or room.members[name].get("sid") != sid:
            raise HTTPException(403, "该用户名已在房间中，进入失败")
        room.members[name]["last_seen"] = time.time()
    else:
        sid = _on_enter(room, name, sid)
        changed = True
    if changed:
        _bump_state(room)

    if room.version == version:
        ev = _poll_event(room.idx)
        ev.clear()
        try:
            await asyncio.wait_for(ev.wait(), timeout=config.LT_POLL_TIMEOUT)
        except asyncio.TimeoutError:
            pass
    return JSONResponse(
        {"type": "state", "room": _room_state(room)},
        headers={"Cache-Control": "no-store", "Set-Cookie": _sid_cookie(sid)},  # 防 CDN 缓存轮询响应
    )


@router.post("/api/listen-together/action")
async def lt_action(request: Request, room_id: int):
    """房间动作：add/play/pause/next/prev/seek/remove/transfer/rename_room/sync。"""
    name = _require_user(request)
    room = _get_room(room_id)
    sid = request.cookies.get(_LT_SID_COOKIE, "")
    _gc_room_members(room)
    if name in room.members:
        # 同名成员已存在：仅当携带匹配的会话 cookie 才视为本人，否则拒绝进入
        if not sid or room.members[name].get("sid") != sid:
            raise HTTPException(403, "该用户名已在房间中，进入失败")
        room.members[name]["last_seen"] = time.time()
    else:
        sid = _on_enter(room, name, sid)
        _bump_state(room)
    body = {}
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "无效请求")
    _handle_message(room, name, body)
    return JSONResponse(
        {"room": _room_state(room)},
        headers={"Cache-Control": "no-store", "Set-Cookie": _sid_cookie(sid)},
    )


@router.post("/api/listen-together/leave")
async def lt_leave(request: Request, room_id: int):
    """显式离开房间：立即移除成员并唤醒轮询（断网/关页由 TTL 兜底清理）。"""
    name = _require_user(request)
    room = _get_room(room_id)
    if name in room.members:
        _on_leave(room, name)
        _bump_state(room)
    return {"ok": True}


@router.websocket("/api/listen-together/ws")
async def lt_ws(websocket: WebSocket, name: str):
    """WebSocket 实时通道（config.LT_TRANSPORT="ws" 时前端使用；列表页即建立全局连接）。

    连接不带房间参数：列表模式下服务端推送房间列表，进房/离开/动作均通过消息完成，
    刷新页面重建连接后重新 enter 即恢复（凭会话 cookie 识别本人）。
    客户端消息：{"t":"enter","room":N} / {"t":"leave"} / {"t":"action","a":{动作}} /
                {"t":"sync","pos":X}（房主应答询问进度）/ {"t":"ping"}。
    服务端消息：{"t":"rooms",...} / {"t":"state",...} / {"t":"ask_sync"} /
                {"t":"enter_ok","room":...} / {"t":"enter_fail","reason":...}。
    任何消息均续期成员在线（客户端 30s 心跳 < 成员 TTL 90s）；连接断开不立即
    踢成员，由 TTL 兜底清理（与 HTTP 断线一致，避免网络抖动瞬间房主被转让）。
    """
    # 门禁：WS 握手不走 HTTP 中间件，此处手动校验（宽松指纹：握手头可能缺 Sec-CH-UA）
    if not anti_devtools.validate_gate_token(websocket, strict_fp=False):
        logger.warning("WS 握手门禁校验失败被拒：%s", name)
        await websocket.close(code=1008, reason="Forbidden")
        return
    name = _sanitize_name(name, "用户名")
    # 会话 id：复用浏览器携带的 cookie（刷新后凭它识别本人），无则生成并在 accept 时下发。
    # WS 握手没有后续 HTTP 响应，accept 是唯一能持久化 sid 的时机。
    sid = websocket.cookies.get(_LT_SID_COOKIE, "") or secrets.token_hex(16)
    await websocket.accept(headers=[(b"set-cookie", _sid_cookie(sid).encode())])
    info = {"name": name, "sid": sid, "room_idx": None}
    _WS_CLIENTS[websocket] = info
    logger.info("WS 连接建立：%s（列表模式）", name)
    try:
        # 初始推送房间列表（列表模式的数据来源，替代 10s HTTP 轮询）
        _ws_send_to(websocket, {"type": "rooms", "rooms": _rooms_summary()})
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except Exception:
                continue  # 非法消息忽略，不断连
            mt = msg.get("t")
            if mt == "enter":
                try:
                    rid = int(msg.get("room") or 0)
                    room = _get_room(rid)
                except (ValueError, HTTPException):
                    _ws_send_to(websocket, {"type": "enter_fail", "reason": "房间不存在"})
                    continue
                if name in room.members and room.members[name].get("sid") != sid:
                    # 同名成员已存在且非本人：拒绝（与 HTTP 进房一致，仅提示不进房）
                    logger.warning("WS 同名进房被拒：%s（%s）", name, room.name)
                    _ws_send_to(websocket, {"type": "enter_fail", "reason": "该用户名已在房间中，进入失败"})
                    continue
                is_new = name not in room.members
                sid = _on_enter(room, name, sid)  # 新成员：分配/续用会话 id（返回 sid 供 accept cookie 一致）
                info["sid"] = sid
                info["room_idx"] = room.idx
                _WS_BY_ROOM.setdefault(room.idx, set()).add(websocket)
                _bump_state(room)
                _ws_send_to(websocket, {"type": "enter_ok", "room": _room_state(room)})
                if is_new:
                    _ask_owner_sync(room)  # 新成员：询问房主当前进度（按需，替代周期上报）
                logger.info("WS 进房：%s → %s（房主=%s，共 %s 人）", name, room.name, room.owner, len(room.members))
            elif mt == "leave" and info["room_idx"] is not None:
                room = _ROOMS[info["room_idx"]]
                info["room_idx"] = None  # 先回列表模式：_bump_state 的列表推送本连接也会收到
                conns = _WS_BY_ROOM.get(room.idx)
                if conns:
                    conns.discard(websocket)
                    if not conns:
                        _WS_BY_ROOM.pop(room.idx, None)
                _on_leave(room, name)
                _bump_state(room)
                logger.info("WS 离开：%s ← %s（剩余 %s 人）", name, room.name, len(room.members))
            elif mt == "action" and isinstance(msg.get("a"), dict) and info["room_idx"] is not None:
                room = _ROOMS[info["room_idx"]]
                try:
                    _handle_message(room, name, msg["a"])  # 有效动作内部已 _bump_state
                except (HTTPException, ValueError, TypeError):
                    pass  # 非法动作忽略，不断连（HTTP 模式返回 400，WS 无错误通道）
            elif mt == "sync" and info["room_idx"] is not None:
                # 房主应答"询问进度"（仅新成员进房时触发，替代周期上报；暂停状态以 pause 为准）
                room = _ROOMS[info["room_idx"]]
                if room.owner == name and room.playing:
                    room.position = max(0.0, float(msg.get("pos", 0) or 0))
                    _bump_state(room)
                    logger.debug("房主同步应答：%s → %.1f 秒（%s）", name, room.position, room.name)
            # 任何有效消息均续期成员在线，并顺带清理其他断线成员（有清理则广播，与 HTTP 轮询一致）
            if info["room_idx"] is not None:
                room = _ROOMS[info["room_idx"]]
                if name in room.members:
                    room.members[name]["last_seen"] = time.time()
                if _gc_room_members(room):
                    _bump_state(room)
    except Exception:
        pass  # 客户端断开（WebSocketDisconnect/网络异常）
    finally:
        _WS_CLIENTS.pop(websocket, None)
        idx = info["room_idx"]
        if idx is not None:
            conns = _WS_BY_ROOM.get(idx)
            if conns:
                conns.discard(websocket)
                if not conns:
                    _WS_BY_ROOM.pop(idx, None)
        logger.info("WS 连接断开：%s", name)
