"""
QQ 音乐平台接入（基于 qqmusic-api-python 库）。

依赖：pip install qqmusic-api-python
- 搜索、歌词（含官方翻译）无需登录即可获取
- 播放/下载 URL 需要 QQ 登录凭证（vkey 鉴权），未登录时返回空串并提示
"""

import asyncio
import base64
import io
import logging
import re
import time
from typing import Optional

from qqmusic_api import Client, Credential, Platform
from qqmusic_api.modules.login import QRLoginType, QRCodeLoginEvents, PhoneLoginEvents
from qqmusic_api.modules.login_utils import PhoneLoginSession, QRCodeLoginSession
from qqmusic_api.modules.search import SearchType
from qqmusic_api.modules.song import SongFileInfo, SongFileType, SongQueryInfo

from .base import MusicPlatform, Song, SearchResult

logger = logging.getLogger(__name__)

# QQ 音乐公开 CDN 域名（无 vkey 时大概率 403，仅作兜底）
_QM_PUBLIC_CDN = "https://ws.stream.qqmusic.qq.com/"

# 音质映射（前端 quality: 128/320/lossless）
_QM_QUALITY_MAP = {
    "128": SongFileType.MP3_128,
    "320": SongFileType.MP3_320,
    "lossless": SongFileType.FLAC,
}
_QM_QUALITY_FALLBACK = SongFileType.MP3_128

# 单次获取 vkey 的 mid 上限（库内限制）
_QM_VKEY_MAX_MID = 100


class QQMusicPlatform(MusicPlatform):
    name = "QQ 音乐"
    platform_id = "qqmusic"
    supported_login_methods = ["qrcode", "cookie", "phone"]

    def __init__(self):
        super().__init__()
        self._cached_client: Optional[Client] = None
        self._client_ts = 0.0
        # QQ 音乐客户端有效期约 2 小时，超时重建避免凭证静默失效
        self._CLIENT_TTL = 7200
        # 二维码登录（MOBILE 类型走 MQTT 推送，需要后台任务消费事件流）
        self._qr_session: Optional[QRCodeLoginSession] = None
        self._qr_task: Optional[asyncio.Task] = None
        self._qr_state: dict = {"status": "waiting", "msg": "请使用 QQ 音乐 APP 扫码"}
        # 手机验证码登录会话（跨请求保存，供验证码校验时复用）
        self._phone_session: Optional[PhoneLoginSession] = None

    # ── 客户端管理 ──

    def _make_client(self) -> Client:
        """创建（或复用）QQMusic API 客户端，自动注入已登录凭证。"""
        credential = None
        if self.cookies and self.cookies.get("musickey"):
            try:
                cred_dict = {
                    "musicid": int(self.cookies.get("musicid", "0") or 0),
                    "musickey": self.cookies["musickey"],
                }
                # 恢复 OAuth 相关字段
                for field in ["openid", "refresh_token", "access_token", "unionid", "str_musicid", "refresh_key"]:
                    if field in self.cookies:
                        cred_dict[field] = self.cookies[field]
                credential = Credential(**cred_dict)
            except Exception:
                credential = None
        return Client(credential=credential, platform=Platform.ANDROID)

    async def _get_client(self) -> Client:
        """获取可用客户端（TTL 内复用，避免频繁重建连接池）。"""
        now = time.time()
        if self._cached_client is None or now - self._client_ts > self._CLIENT_TTL:
            self._cached_client = self._make_client()
            self._client_ts = now
        return self._cached_client

    async def _close_client(self) -> None:
        if self._cached_client is not None:
            try:
                await self._cached_client.close()
            except Exception:
                pass
            self._cached_client = None

    # ── 搜索 ──

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        client = await self._get_client()
        try:
            resp = await client.search.search_by_type(
                keyword, SearchType.SONG, num=page_size
            )
        except Exception as e:
            logger.warning("QQ音乐搜索失败 %r: %s", keyword, e)
            return SearchResult(songs=[], total=0, page=page)

        raw_songs = getattr(resp, "song", None) or []
        songs = []
        for s in raw_songs:
            singer = getattr(s, "singer", None) or []
            artist = ", ".join(getattr(x, "name", "") for x in singer if getattr(x, "name", None))
            album = getattr(s, "album", None) or {}
            songs.append(Song(
                id=str(getattr(s, "mid", "") or getattr(s, "id", "")),
                name=getattr(s, "name", "") or "",
                artist=artist or "",
                album=getattr(album, "name", "") or "",
                cover=getattr(s, "cover_url", lambda size=None: "")(300) if callable(getattr(s, "cover_url", None)) else "",
                platform="qqmusic",
                duration=int(getattr(s, "interval", 0) or 0),
                extra={"mid": getattr(s, "mid", ""), "songid": getattr(s, "id", "")},
            ))
        return SearchResult(songs=songs, total=len(songs), page=page)

    # ── 歌曲详情 ──

    async def get_song_detail(self, song_id: str) -> Optional[Song]:
        mid = song_id
        client = await self._get_client()
        try:
            resp = await client.song.query_song([SongQueryInfo(mid=mid)])
        except Exception as e:
            logger.warning("QQ音乐获取歌曲详情失败 %s: %s", mid, e)
            return None
        data = getattr(resp, "data", None) or []
        if not data:
            return None
        s = data[0]
        singer = getattr(s, "singer", None) or []
        artist = ", ".join(getattr(x, "name", "") for x in singer if getattr(x, "name", None))
        album = getattr(s, "album", None) or {}
        return Song(
            id=str(getattr(s, "mid", "") or getattr(s, "id", "")),
            name=getattr(s, "name", "") or "",
            artist=artist or "",
            album=getattr(album, "name", "") or "",
            cover=getattr(s, "cover_url", lambda size=None: "")(300) if callable(getattr(s, "cover_url", None)) else "",
            platform="qqmusic",
            duration=int(getattr(s, "interval", 0) or 0),
            extra={"mid": getattr(s, "mid", ""), "songid": getattr(s, "id", "")},
        )

    # ── 歌词 ──

    async def get_lyrics(self, song: Song) -> str:
        """返回 LRC 格式歌词（无翻译）。"""
        mid = song.extra.get("mid") or song.id
        if not mid:
            return ""
        client = await self._get_client()
        try:
            resp = await client.lyric.get_lyric(mid, trans=False)
        except Exception as e:
            logger.warning("QQ音乐获取歌词失败 %s: %s", mid, e)
            return ""
        lyric = getattr(resp, "lyric", "") or ""
        return lyric

    async def get_lyrics_with_translation(self, song: Song) -> Optional[dict]:
        """
        获取 QQ 音乐官方歌词 + 翻译（原生支持，无需第三方引擎）。
        返回 {"lyrics": "原文LRC", "translated": "原文+译文合并"} 或 None。
        """
        mid = song.extra.get("mid") or song.id
        if not mid:
            return None
        client = await self._get_client()
        try:
            resp = await client.lyric.get_lyric(mid, trans=True)
        except Exception as e:
            logger.warning("QQ音乐获取翻译歌词失败 %s: %s", mid, e)
            return None

        original = getattr(resp, "lyric", "") or ""
        trans = getattr(resp, "trans", "") or ""
        if not original:
            return None

        # 无翻译数据时只返回原文，让上层走本地翻译 fallback
        if not trans:
            logger.info("QQ音乐 %s 无官方翻译，回退本地翻译", mid)
            return {"lyrics": original, "translated": ""}

        merged = self._merge_trans_lyric(original, trans)
        logger.info("QQ音乐 %s 官方翻译可用（原文 %d 行，译文 %d 行）",
                    mid, original.count("\n") + 1, trans.count("\n") + 1)
        return {"lyrics": original, "translated": merged}

    @staticmethod
    def _merge_trans_lyric(original: str, trans: str) -> str:
        """
        按时间戳把原文与译文逐行交替合并。

        QQ 音乐官方返回的 trans 行与原文行一一对应（含相同时间戳），
        但元信息块（[ti:] / [ar:] / [al:] / [by:] / [offset:] / [re:] / [ve:]）
        在两者中都会出现，合并时只保留一份，避免重复。
        """
        META_PREFIX = ("[ti:", "[ar:", "[al:", "[by:", "[offset:", "[re:", "[ve:")
        orig_lines = [ln for ln in original.split("\n") if ln.strip()]
        # 译文中的元信息行与原文重复，直接过滤掉
        trans_lines = [ln for ln in trans.split("\n")
                       if ln.strip() and not ln.startswith(META_PREFIX)]

        out = []
        ti = 0
        for line in orig_lines:
            out.append(line)
            if ti < len(trans_lines):
                out.append(trans_lines[ti])
                ti += 1
        # 剩余译文补到末尾（通常是尾部多余的元信息或空行）
        out.extend(trans_lines[ti:])
        return "\n".join(out)

    # ── 播放地址 ──

    async def get_play_url(self, song: Song) -> str:
        """获取播放 URL（需要登录凭证；未登录返回空串）。"""
        mid = song.extra.get("mid") or song.id
        if not mid:
            return ""
        client = await self._get_client()
        try:
            resp = await client.song.get_song_urls(
                [SongFileInfo(mid=mid, file_type=SongFileType.MP3_320)]
            )
        except Exception as e:
            logger.warning("QQ音乐获取播放地址失败 %s: %s", mid, e)
            return ""

        items = getattr(resp, "data", None) or []
        for item in items:
            vkey = getattr(item, "vkey", "") or ""
            purl = getattr(item, "purl", "") or ""
            result = getattr(item, "result", -1)
            if result == 0 and vkey:
                # 有 vkey：拼接完整地址
                filename = getattr(item, "filename", "") or f"M800{mid}{mid}.mp3"
                return f"{_QM_PUBLIC_CDN.rstrip('/')}/{purl.lstrip('/') or filename}"
            if result == 0 and purl:
                return f"{_QM_PUBLIC_CDN.rstrip('/')}/{purl.lstrip('/')}"

        logger.warning("QQ音乐 %s 无播放权限（result=%s，需登录 QQ 账号）", mid, result)
        return ""

    async def get_download_url(self, song: Song, quality: str = "320") -> str:
        """获取下载 URL（需要登录凭证）。"""
        mid = song.extra.get("mid") or song.id
        if not mid:
            return ""
        file_type = _QM_QUALITY_MAP.get(quality, _QM_QUALITY_FALLBACK)
        client = await self._get_client()
        try:
            resp = await client.song.get_song_urls(
                [SongFileInfo(mid=mid, file_type=file_type)]
            )
        except Exception as e:
            logger.warning("QQ音乐获取下载地址失败 %s: %s", mid, e)
            return ""

        items = getattr(resp, "data", None) or []
        for item in items:
            vkey = getattr(item, "vkey", "") or ""
            purl = getattr(item, "purl", "") or ""
            result = getattr(item, "result", -1)
            if result == 0 and vkey:
                filename = getattr(item, "filename", "") or f"M800{mid}{mid}.mp3"
                return f"{_QM_PUBLIC_CDN.rstrip('/')}/{purl.lstrip('/') or filename}"
            if result == 0 and purl:
                return f"{_QM_PUBLIC_CDN.rstrip('/')}/{purl.lstrip('/')}"

        logger.warning("QQ音乐 %s 无下载权限（需登录 QQ 账号）", mid)
        return ""

    def get_available_qualities(self, song: Song) -> list[dict]:
        return [
            {"value": "128", "label": "标准 128k"},
            {"value": "320", "label": "高品质 320k"},
            {"value": "lossless", "label": "无损 FLAC"},
        ]

    # ── 歌单导入 ──

    async def import_playlist(self, ref: str, page: int = 1, page_size: int = 30) -> dict:
        """导入 QQ 音乐歌单（分页），返回 {name, cover, creator, total, songs}。

        支持格式：
        - 歌单 ID：如 "123456789"
        - 短链：如 "https://c6.y.qq.com/base/fcgi-bin/u?__=xxx"（自动跟随重定向）
        - 官方链接：如 "https://y.qq.com/n/ryqq/playlist/123456789"
        - 分享链接：如 "https://i.y.qq.com/n/ryqq/playlist/123456789"

        无需登录即可获取公开歌单。
        """
        import re

        # 提取歌单 ID（可能跟随短链重定向）
        playlist_id, error = await self._extract_playlist_id(ref)
        if error:
            raise ValueError(error)
        if not playlist_id:
            raise ValueError("未能识别 QQ 音乐歌单链接/ID，请确认粘贴的是歌单链接（专辑/歌手链接暂不支持）")

        try:
            playlist_id = int(playlist_id)
        except ValueError:
            raise ValueError("QQ 音乐歌单 ID 必须是数字")

        client = await self._get_client()
        try:
            resp = await client.songlist.get_detail(
                songlist_id=playlist_id,
                num=page_size,
                page=page,
                tag=True,
                userinfo=True,
            )
        except Exception as e:
            logger.error("QQ 音乐获取歌单详情失败 %s: %s", playlist_id, e)
            raise ValueError(f"获取歌单失败：{e}")

        # 检查响应状态
        code = getattr(resp, "code", -1)
        if code != 0:
            msg = getattr(resp, "msg", "") or f"返回码 {code}"
            raise ValueError(f"歌单不存在或已失效：{msg}")

        # 解析歌单信息
        info = getattr(resp, "info", None)
        if not info:
            raise ValueError("歌单信息为空")

        creator_info = getattr(info, "creator", None)
        creator_name = getattr(creator_info, "nick", "") if creator_info else ""
        cover_url = getattr(info, "picurl", "") or ""

        # 解析歌曲列表
        songs = []
        raw_songs = getattr(resp, "songs", []) or []
        total = getattr(resp, "total", len(raw_songs)) or len(raw_songs)

        for s in raw_songs:
            # 从 Song 模型提取字段
            song_id = str(getattr(s, "mid", "") or getattr(s, "id", ""))
            if not song_id:
                continue

            singer_list = getattr(s, "singer", []) or []
            artist_names = [getattr(si, "name", "") for si in singer_list if getattr(si, "name", "")]
            artist = ", ".join(artist_names)

            album_info = getattr(s, "album", None)
            album_name = getattr(album_info, "name", "") if album_info else ""

            cover = getattr(s, "cover_url", "") or ""
            duration_sec = int(getattr(s, "interval", 0) or 0)

            # 构建 extra 字段（保留 mid 用于后续播放）
            extra = {"mid": song_id}

            songs.append(Song(
                id=song_id,
                name=getattr(s, "name", "") or "",
                artist=artist,
                album=album_name,
                cover=cover,
                platform="qqmusic",
                duration=duration_sec,
                extra=extra,
            ))

        return {
            "name": getattr(info, "title", "") or f"QQ 音乐歌单 {playlist_id}",
            "cover": cover_url,
            "creator": creator_name,
            "total": total,
            "songs": songs,
        }

    async def _extract_playlist_id(self, ref: str) -> tuple[str | None, str | None]:
        """从链接或 ID 字符串中提取 QQ 音乐歌单 ID。

        返回 (playlist_id, error)：
        - (数字字符串, None)：成功提取
        - (None, None)：无法识别（不是 QQ 音乐链接）
        - (None, 错误提示)：识别为非歌单链接（如专辑/歌手）
        """
        if not ref:
            return None, None
        ref = ref.strip()

        # 纯数字 ID
        if re.match(r"^\d+$", ref):
            return ref, None

        url = ref if re.match(r"^https?://", ref) else "https://" + ref

        # 常见短链域名（跟随重定向）
        if re.search(r"(?:^|\.)c6\.y\.qq\.com/", url) or re.search(r"(?:^|\.)t\.qq\.com/", url):
            final = await self._follow_redirects(url)
            if final:
                pid, err = self._extract_playlist_id_from_url(final)
                if err:
                    return None, err
                return pid, None
            return None, None

        # 普通链接直接解析
        return self._extract_playlist_id_from_url(url)

    @staticmethod
    def _extract_playlist_id_from_url(url: str) -> tuple[str | None, str | None]:
        """从已解析的完整 URL 中提取歌单 ID。

        返回 (playlist_id, error)：
        - 非歌单页面（专辑/歌手/单曲/MV/电台）返回 (None, 提示)
        """
        # 专辑/歌手/单曲/MV/电台等非歌单页面：明确拒绝
        if re.search(r"/(?:albumDetail|singer|songDetail|mv|radio|artist)/", url):
            return None, "这不是歌单链接（可能是专辑、歌手或单曲），请粘贴 QQ 音乐歌单链接"
        # 歌单链接：y.qq.com/n/ryqq/playlist/{id} 或带 # 锚点 / ?id= 参数
        m = re.search(r"(?:^|\?|&)id=(\d+)", url)
        if m:
            return m.group(1), None
        m = re.search(r"/playlist[/#](\d+)", url)
        if m:
            return m.group(1), None
        return None, None

    async def _follow_redirects(self, url: str) -> str | None:
        """跟随 HTTP 重定向，返回最终 URL（失败返回 None）。"""
        try:
            import httpx
            async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            }) as client:
                resp = await client.get(url)
                return str(resp.url)
        except Exception as e:
            logger.warning("QQ 音乐短链跟随重定向失败 %s: %s", url, e)
            return None

    # ── 登录（扫码） ──

    async def get_qr_code(self) -> str:
        """返回 base64 编码的登录二维码图片（纯 base64，不含 data: 前缀）。

        使用 QQ 音乐 APP 扫码（QRLoginType.MOBILE）：该类型的状态通过 MQTT 推送，
        因此会启动后台任务消费事件流，check_qr_status 只读取最新状态。
        """
        client = await self._get_client()
        # 取消上一次的后台事件任务
        await self._stop_qr_task()

        session = QRCodeLoginSession(
            client.login,
            QRLoginType.MOBILE,
            interval=1.5,
            timeout_seconds=180.0,
        )
        try:
            qr = await session.get_qrcode()
        except Exception as e:
            logger.error("QQ音乐获取二维码失败: %s", e)
            raise

        self._qr_session = session
        self._qr_state = {"status": "waiting", "msg": "请使用 QQ 音乐 APP 扫码"}
        self._qr_task = asyncio.create_task(self._consume_qr_events(session))

        data = getattr(qr, "data", None) or b""
        logger.info("QQ音乐二维码已生成（APP 扫码），identifier=%s", qr.identifier)
        if isinstance(data, bytes):
            return base64.b64encode(data).decode()
        return str(data)

    async def _consume_qr_events(self, session: QRCodeLoginSession) -> None:
        """后台消费二维码登录事件流（MQTT 推送），更新 _qr_state。"""
        try:
            async for result in session.iter_events():
                event = result.event
                logger.info("QQ音乐二维码事件：%s", event)
                if event == QRCodeLoginEvents.DONE:
                    if result.credential is None:
                        self._qr_state = {"status": "error", "msg": "登录结果缺少凭证"}
                    else:
                        self._save_credential(result.credential)
                        client = await self._get_client()
                        client.credential = result.credential
                        logger.info("QQ音乐登录成功，musicid=%s", result.credential.musicid)
                        self._qr_state = {"status": "success", "msg": "登录成功"}
                    return
                if event == QRCodeLoginEvents.CONF:
                    self._qr_state = {"status": "scanned", "msg": "已扫码，请在手机上确认授权"}
                elif event == QRCodeLoginEvents.SCAN:
                    self._qr_state = {"status": "waiting", "msg": "请使用 QQ 音乐 APP 扫码"}
                elif event == QRCodeLoginEvents.TIMEOUT:
                    self._qr_state = {"status": "expired", "msg": "二维码已过期"}
                    return
                elif event == QRCodeLoginEvents.REFUSE:
                    self._qr_state = {"status": "expired", "msg": "已拒绝登录"}
                    return
        except Exception as e:
            logger.error("QQ音乐二维码登录流程异常: %s", e)
            self._qr_state = {"status": "error", "msg": str(e)}

    async def _stop_qr_task(self) -> None:
        """停止并清理二维码后台任务。"""
        if self._qr_task is not None and not self._qr_task.done():
            self._qr_task.cancel()
            try:
                await self._qr_task
            except (asyncio.CancelledError, Exception):
                pass
        self._qr_task = None
        self._qr_session = None

    async def check_qr_status(self) -> dict:
        """返回二维码登录最新状态（前端轮询此接口）。"""
        return dict(self._qr_state)

    def _save_credential(self, cred: Credential) -> None:
        """把凭证持久化到 self.cookies，后续请求自动注入。

        保存所有必要字段（musicid/musickey/access_token/refresh_token 等），
        因为部分歌曲播放需要完整的 OAuth 令牌。
        """
        data = {
            "musicid": str(getattr(cred, "musicid", 0) or 0),
            "musickey": str(getattr(cred, "musickey", "") or ""),
        }
        # 保留 OAuth 相关字段（扫码登录可能返回 access_token/refresh_token）
        for field in ["openid", "refresh_token", "access_token", "unionid", "str_musicid", "refresh_key"]:
            val = getattr(cred, field, None)
            if val:
                data[field] = str(val)
        self.cookies = data
        self.logged_in = True
        self.user_info = {"musicid": data["musicid"]}
        # 凭证变更：让缓存的 Client 立即失效，下次请求重建为带凭证的实例
        self._cached_client = None
        self._client_ts = 0.0
        self._persist_session()

    async def login_cookie(self, cookie_str: str) -> dict:
        """通过 musicid+musickey 登录。"""
        parsed = self._parse_cookie_string(cookie_str)
        musicid = parsed.get("musicid", parsed.get("uin", ""))
        musickey = parsed.get("musickey", "")
        if not musickey:
            return {"success": False, "msg": "缺少 musickey"}
        try:
            cred = Credential(musicid=int(musicid), musickey=musickey)
        except Exception as e:
            return {"success": False, "msg": f"凭证格式错误: {e}"}
        client = await self._get_client()
        try:
            is_expired = await client.login.check_expired(cred)
        except Exception as e:
            return {"success": False, "msg": f"凭证校验失败: {e}"}
        if not is_expired:
            self.cookies = {"musicid": str(musicid), "musickey": musickey}
            self.logged_in = True
            self.user_info = {"musicid": str(musicid)}
            # 凭证变更：让缓存的 Client 立即失效
            self._cached_client = None
            self._client_ts = 0.0
            self._persist_session()
            return {"success": True, "msg": "登录成功"}
        return {"success": False, "msg": "凭证已过期"}

    async def send_phone_code(self, phone: str) -> dict:
        """发送手机验证码（需国家代码，默认 86）。

        QQ 音乐可能要求人机验证，此时返回 need_captcha=True 和 captcha_url，
        用户在浏览器完成验证后再次点击发送即可。
        """
        client = await self._get_client()
        try:
            # 库要求 int 类型；传 str 会被当成加密手机号
            phone_int = int(str(phone).strip())
        except ValueError:
            return {"success": False, "msg": "手机号格式不正确"}

        session = PhoneLoginSession(client.login, phone=phone_int, country_code=86)
        try:
            result = await session.send_authcode()
        except Exception as e:
            return {"success": False, "msg": f"发送失败: {e}"}

        # 保存会话，供后续验证码校验复用
        self._phone_session = session

        event = result.event
        if event == PhoneLoginEvents.SEND:
            return {"success": True, "msg": "验证码已发送", "need_code": True}
        if event == PhoneLoginEvents.CAPTCHA:
            return {
                "success": False,
                "msg": "需要先完成人机验证，完成后请重新点击发送验证码",
                "need_captcha": True,
                "captcha_url": result.info or "",
            }
        if event == PhoneLoginEvents.FREQUENCY:
            return {"success": False, "msg": "操作过于频繁，请稍后再试"}
        return {"success": False, "msg": f"发送异常：{event}"}

    async def login_phone(self, phone: str, code: str = "") -> dict:
        """手机验证码登录。

        code 为空 → 发送验证码；code 非空 → 校验验证码并登录。
        （与其他平台保持一致的调用约定）
        """
        if not code:
            return await self.send_phone_code(phone)

        client = await self._get_client()
        try:
            # 库要求 int 类型；传 str 会被当成加密手机号
            phone_int = int(str(phone).strip())
        except ValueError:
            return {"success": False, "msg": "手机号格式不正确"}

        # 优先复用发送验证码时的会话（保证 phone/加密手机号一致）
        session = self._phone_session
        if session is None or session.phone != phone_int:
            session = PhoneLoginSession(client.login, phone=phone_int, country_code=86)
        try:
            cred = await session.authorize(code)
        except Exception as e:
            return {"success": False, "msg": f"登录失败: {e}"}
        self._save_credential(cred)
        return {"success": True, "msg": "登录成功"}

    async def close(self) -> None:
        await self._stop_qr_task()
        await self._close_client()
