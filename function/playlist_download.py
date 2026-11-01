"""
歌单下载模块（流式拼接，文件不保存到服务端）。

协议（统一 4 字节大端，长度前缀不加换行）：
  1) [4 字节 manifest 长度][manifest]
     manifest = {"name": 歌单名, "count": 歌曲数, "total_bytes": 所有音频的总字节数,
                 "songs": [{"id", "platform", "name", "artist", "cached": true/false}, ...]}
  2) 每首输出 [4 字节音频长度][音频 bytes]（失败歌曲在该位置发零长度，客户端自动跳过）

取歌逻辑：
  - 主循环按 range(total) 顺序遍历，每首一定对应一次 _bytes4(n)（n 可为 0）
  - n=0 表示本首不可用（已缓存或取播失败），客户端从 IndexedDB 读或跳过
  - 成功歌曲在输出过程中预取下一首（不阻塞当前输出）

日志级别约定：
  - DEBUG：单曲高频细节（开始取第 N 首、取到多少字节、cached 跳过、发送 N 字节）
  - INFO ：每调用一次的里程碑（歌单下载开始、生成器启动）
  - WARNING：单曲失败的具体原因（获取地址失败 / HTTP 非 200 / 非音频 / 空数据 / 平台缺失）
  - ERROR ：本模块不产生（整体失败由 main.py 抛 HTTPException 处理）
"""

import asyncio
import json
import logging
import struct
import time
from collections.abc import AsyncGenerator
from typing import Any, Mapping, MutableMapping, Optional, Sequence
from urllib.parse import urlparse

import httpx
from fastapi.responses import StreamingResponse

import config
from platforms.base import MusicPlatform, Song

logger = logging.getLogger(__name__)

# 分片输出块大小（字节）
_CHUNK = 64 * 1024
# 下一首取歌触发点：当前歌曲完成度达到这个比例时
_NEXT_SWEEP = 0.9


def _bytes4(n: int) -> bytes:
    return struct.pack(">I", n)


def _make_song(d: Mapping[str, Any]) -> Song:
    """把前端传来的本地歌单歌曲 dict 转为 Song（只保留必要字段，过滤多余状态）。"""
    valid_keys = {"id", "name", "artist", "album", "cover", "platform", "duration", "extra"}
    d_clean = {k: v for k, v in d.items() if k in valid_keys}
    d_clean["extra"] = {**(d_clean.get("extra") or {})}
    for k in ("id", "name", "artist", "album", "cover", "platform"):
        if k in d_clean and d_clean[k] is not None:
            d_clean[k] = str(d_clean[k]) or ""
    d_clean["duration"] = int(d_clean.get("duration") or 0)
    song = Song(**d_clean)
    song.is_cached = bool(d.get("_cached"))
    return song


def _is_audio_bytes(head: bytes, ct: str) -> bool:
    """判断响应是否为音频/视频：content-type 或文件头魔数任一命中即视为成功。

    CDN 常返回 application/octet-stream（甚至缺失 content-type），
    仅靠 content-type 会误杀正常音频，必须用文件头魔数兜底
    （判定规则与 main.py 的 /api/download 保持一致）。
    """
    if ct.startswith("audio/") or ct.startswith("video/"):
        return True
    if not head:
        return False
    if head[:4] == b"fLaC":                                       # FLAC
        return True
    if head[:3] == b"ID3":                                        # MP3（带 ID3 标签）
        return True
    if head[:2] == b"\xff\xfb" or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0):
        return True                                               # MPEG 帧头/同步字
    if head[:4] == b"OggS":                                       # Ogg
        return True
    if len(head) >= 8 and head[4:8] == b"ftyp":                   # m4a / mp4
        return True
    if head[:4] == b"RIFF":                                       # wav
        return True
    return False


async def _fetch_one(client: httpx.AsyncClient, song: Song, platform: MusicPlatform) -> bytes | None:
    """获取单首歌曲的音频数据（失败/非音频返回 None，不写盘）。

    必须携带 User-Agent / Referer 等请求头，否则部分平台 CDN 会拒绝（与 /api/proxy 保持一致）。
    http 直链会尝试升级 https，规避部分部署环境禁 80 出站导致的 ConnectError。
    """
    try:
        url = await platform.get_play_url(song)
    except Exception as e:
        logger.warning("歌单下载：平台 %s 歌曲 %s 获取播放地址失败 %s", song.platform, song.id, e)
        return None
    if not url:
        logger.warning("歌单下载：平台 %s 歌曲 %s 无可用音频地址", song.platform, song.id)
        return None

    # http → https 升级：部分部署环境禁 80 出站，CDN 返回 http 直链会 ConnectError
    if url.lower().startswith("http://"):
        url = "https://" + url[len("http://"):]

    # 根据 URL 域名匹配 Referer / Origin（与 proxy_audio 保持一致）
    domain = (urlparse(url).hostname or "").lower()
    referer = ""
    for suffix, ref in config.PROXY_REFERER_MAP:
        if domain == suffix or domain.endswith("." + suffix):
            referer = ref
            break
    headers = {"User-Agent": config.HTTP_USER_AGENT}
    if referer:
        headers["Referer"] = referer
    if any(domain == s or domain.endswith("." + s) for s in
           ("bilibili.com", "bilivideo.com", "hdslb.com", "akamaized.net")):
        headers["Origin"] = "https://www.bilibili.com"

    try:
        async with client.stream("GET", url, headers=headers) as resp:
            if resp.status_code != 200:
                logger.warning(
                    "歌单下载：平台 %s 歌曲 %s HTTP %s（url=%s）",
                    song.platform, song.id, resp.status_code, url[:120],
                )
                return None
            ct = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
            data = await resp.aread()
            if not data:
                logger.warning("歌单下载：平台 %s 歌曲 %s 返回空数据（content-type=%s）",
                               song.platform, song.id, ct or "-")
                return None

            # 明确的错误响应（防盗链 HTML / 权限错误 JSON / XML）：直接拒绝并打印响应头
            if ct.startswith("text/") or ct in ("application/json", "application/xml"):
                logger.warning(
                    "歌单下载：平台 %s 歌曲 %s 返回错误响应 content-type=%s head=%r",
                    song.platform, song.id, ct, data[:64],
                )
                return None

            # content-type 或文件头魔数，任一命中即视为音频/视频
            if not _is_audio_bytes(data[:16], ct):
                logger.warning(
                    "歌单下载：平台 %s 歌曲 %s 非音频 content-type=%s head=%r size=%d",
                    song.platform, song.id, ct or "-", data[:16], len(data),
                )
                return None
            return data
    except Exception as e:
        logger.warning("歌单下载：平台 %s 歌曲 %s 拉取失败 %s", song.platform, song.id, e)
        return None


async def stream_playlist_songs(playlist_name: str, songs: Sequence[Mapping[str, Any]],
                                sessions: Mapping[str, MusicPlatform]) -> StreamingResponse:
    """流式输出歌单音频（文件不保存到服务端）。"""
    songs = [s for s in songs if isinstance(s, dict)]
    total = len(songs)
    if total == 0:
        raise ValueError("空歌单，无可下载的歌曲")

    logger.info("歌单下载：开始，%s 首（歌单：%s）", total, playlist_name)

    async def gen() -> AsyncGenerator[bytes, None]:
        logger.info("歌单下载：生成器启动")

        results: MutableMapping[int, Optional[bytes]] = {}
        issues: MutableMapping[int, bool] = {}

        async def _fetch(idx: int) -> None:
            if idx >= total or idx in issues:
                return
            logger.debug("歌单下载：开始取第 %s 首 (%s)", idx, songs[idx].get('name', '?'))
            s = _make_song(songs[idx])
            if getattr(s, 'is_cached', False):
                logger.debug("歌单下载：歌曲 %s 已由前端缓存，跳过服务器下载", s.name)
                issues[idx] = False
                return
            platform = sessions.get(s.platform)
            if platform is None:
                logger.warning("歌单下载：平台 %s 无对应实例，已忽略 %s（%s）",
                               s.platform, s.name, s.id)
                issues[idx] = False
                return

            # 分域超时：connect 用 CONNECT_TIMEOUT（短），read 用 READ_TIMEOUT（长）
            # 原来 timeout=READ 会把 connect 也设成 300s，连接卡住时整条歌单都挂死
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(config.DOWNLOAD_TIMEOUT_CONNECT, read=config.DOWNLOAD_TIMEOUT_READ),
                follow_redirects=True,
                headers={"User-Agent": config.HTTP_USER_AGENT},
            ) as client:
                try:
                    res = await _fetch_one(client, s, platform)
                except Exception as e:
                    logger.warning("歌单下载：平台 %s 歌曲 %s 拉取失败 %s", s.platform, s.id, e)
                    res = None
                if res is not None:
                    logger.debug("歌单下载：歌曲 %s - %s 取到音频 %s 字节",
                                 s.artist, s.name, len(res))
                    results[idx] = res
                    issues[idx] = True
                else:
                    # _fetch_one 内部已打出具体原因（WARNING 级），此处标记 skip 即可
                    logger.warning("歌单下载：歌曲 %s - %s（%s/%s）取播失败，已标记 skip",
                                   s.artist, s.name, s.platform, s.id)
                    issues[idx] = False

        # ---- manifest 先播 ----
        mf = {"name": playlist_name, "count": total, "total_bytes": 0,
              "songs": [
                  {"id": str(s.get("id") or ""), "platform": str(s.get("platform") or ""),
                   "name": str(s.get("name") or ""), "artist": str(s.get("artist") or ""),
                   "cached": bool(s.get("_cached"))}
                  for s in songs
              ]}
        mf_b = json.dumps(mf, ensure_ascii=False, separators=(",", ":")).encode()
        yield _bytes4(len(mf_b))
        yield mf_b
        del mf, mf_b

        # ---- 主循环：每首都必须发 _bytes4(n) ----
        for i in range(total):
            # 1) 本首未取，先取
            if i not in issues:
                await _fetch(i)

            # 2) cached：发 0 占位，客户端从 IndexedDB 读
            if songs[i].get("_cached"):
                logger.debug("歌单下载：第 %s 首 %s 已缓存，发送 0 字节标记",
                             i, songs[i].get('name', '?'))
                yield _bytes4(0)
                continue

            # 3) 失败：也必须发 0 占位（客户端读到 0 会跳过）
            if not issues.get(i, False) or results.get(i) is None:
                logger.warning("歌单下载：第 %s 首 %s 不可用，发送 0 字节占位",
                               i, songs[i].get('name', '?'))
                results.pop(i, None)
                yield _bytes4(0)
                continue

            # 4) 成功：发 [4B len][len B data]，同时顺带预取下一首
            data = results[i]
            all_bytes = len(data)
            head = int(all_bytes * _NEXT_SWEEP)
            logger.debug("歌单下载：第 %s 首 %s 发送 %s 字节", i, songs[i].get('name', '?'), all_bytes)
            yield _bytes4(all_bytes)
            for start in range(0, all_bytes, _CHUNK):
                end = min(start + _CHUNK, all_bytes)
                if start >= head and i + 1 < total and (i + 1) not in issues:
                    await _fetch(i + 1)  # 只取，不跳索引
                yield data[start:end]
            del results[i]

    return StreamingResponse(gen(), media_type="application/octet-stream")