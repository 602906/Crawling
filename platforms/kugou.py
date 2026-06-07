import hashlib
import json
import re
import time
import io
import base64
import segno
from .base import MusicPlatform, Song, SearchResult


class KuGouPlatform(MusicPlatform):
    name = "酷狗音乐"
    platform_id = "kugou"
    supported_login_methods = ["cookie"]

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer": "https://www.kugou.com/",
            "Origin": "https://www.kugou.com",
        })
        self._qr_ticket = None

    async def get_qr_code(self) -> str:
        async with self._client() as client:
            resp = await client.get(
                "https://login-user.kugou.com/v2/get_qrcode",
                params={
                    "appid": "1014",
                    "type": "1",
                },
            )
            data = resp.json()

        if data.get("status") == 1:
            qr_url = data["data"]["qrcode"]
            self._qr_key = data["data"].get("ticket", "")
            qr = segno.make(qr_url, error='M')
            buf = io.BytesIO()
            qr.save(buf, kind='png', scale=8)
            return base64.b64encode(buf.getvalue()).decode()
        return ""

    async def check_qr_status(self) -> dict:
        if not self._qr_key:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}

        async with self._client() as client:
            resp = await client.get(
                "https://login-user.kugou.com/v2/check_qrcode",
                params={
                    "appid": "1014",
                    "ticket": self._qr_key,
                    "type": "1",
                },
            )
            data = resp.json()

        status_code = data.get("data", {}).get("status", 0)
        if status_code == 4:
            self.logged_in = True
            token = data["data"].get("token", "")
            userid = data["data"].get("userid", "")
            self.cookies["kg_mid"] = hashlib.md5(str(userid).encode()).hexdigest()
            self.cookies["kg_dfid"] = ""
            self.cookies["KUGOU_TOKEN"] = token
            self.user_info = {"id": userid, "name": data["data"].get("nickname", "用户")}
            return {"status": "success", "msg": "登录成功"}
        elif status_code == 2:
            return {"status": "scanned", "msg": "已扫码，请在手机上确认"}
        elif status_code == 0:
            return {"status": "waiting", "msg": "等待扫码"}
        else:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}

    async def login_cookie(self, cookie_str: str) -> dict:
        cookies = self._parse_cookie_string(cookie_str)
        if not cookies:
            return {"success": False, "msg": "Cookie 为空"}
        self.cookies.update(cookies)

        token = cookies.get("KUGOU_TOKEN") or cookies.get("t", "")
        mid = cookies.get("kg_mid") or cookies.get("mid", "")
        ku_info = cookies.get("KuGoo", "")

        if not token and not ku_info:
            return {"success": False, "msg": "Cookie 缺少关键字段 (t / KuGoo / KUGOU_TOKEN)"}

        nickname = ""
        user_id = ""
        avatar = ""
        if ku_info:
            for part in ku_info.split("&"):
                k, _, v = part.partition("=")
                if k == "NickName":
                    nickname = re.sub(r"%u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), v)
                elif k == "KugooID":
                    user_id = v
                elif k == "Pic":
                    avatar = v

        async with self._client() as client:
            resp = await client.get(
                "https://mobileservice.kugou.com/api/v3/user/info",
                params={"version": "9209", "plat": "0"},
            )
            try:
                data = resp.json()
                status = data.get("status", 0)
                if status == 1 and data.get("data"):
                    self.logged_in = True
                    info = data["data"]
                    self.user_info = {
                        "name": info.get("nickname") or info.get("username") or nickname or "酷狗用户",
                        "id": info.get("userid") or user_id,
                        "avatar": info.get("pic") or info.get("avatar") or avatar,
                    }
                    return {"success": True, "msg": "Cookie 登录成功"}
            except Exception:
                pass

        if token:
            self.logged_in = True
            self.user_info = {
                "name": nickname or "酷狗用户",
                "id": user_id,
                "avatar": avatar,
            }
            return {"success": True, "msg": "Cookie 登录成功"}
        return {"success": False, "msg": "Cookie 无效或已过期"}

    async def login_phone(self, phone: str, code: str = "") -> dict:
        if not code:
            try:
                async with self._client() as client:
                    resp = await client.post(
                        "https://login-user.kugou.com/v1/sendcode",
                        json={"mobile": phone, "appid": "1014"},
                    )
                    data = resp.json()
                if data.get("status") == 1:
                    return {"success": True, "msg": "验证码已发送", "need_code": True}
                return {"success": False, "msg": data.get("error_msg", "发送失败")}
            except Exception as e:
                return {"success": False, "msg": f"发送验证码失败: {e}"}

        try:
            async with self._client() as client:
                resp = await client.post(
                    "https://login-user.kugou.com/v1/loginbyverifycode",
                    json={"mobile": phone, "code": code, "appid": "1014"},
                )
                data = resp.json()

            if data.get("status") == 1:
                self.logged_in = True
                token = data["data"].get("token", "")
                self.cookies["KUGOU_TOKEN"] = token
                self.user_info = {"name": data["data"].get("nickname", "用户")}
                return {"success": True, "msg": "登录成功"}
            return {"success": False, "msg": data.get("error_msg", "登录失败")}
        except Exception as e:
            return {"success": False, "msg": f"登录失败: {e}"}

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        async with self._client() as client:
            resp = await client.get(
                "https://songsearch.kugou.com/song_search_v2",
                params={
                    "keyword": keyword,
                    "page": page,
                    "pagesize": page_size,
                    "platform": "WebFilter",
                },
            )
            data = resp.json()

        songs = []
        for item in data.get("data", {}).get("lists", []):
            img_tpl = item.get("Image", "")
            cover = img_tpl.replace("{size}", "240") if img_tpl else ""
            song = Song(
                id=item.get("FileHash", ""),
                name=item.get("SongName", "").replace("<em>", "").replace("</em>", ""),
                artist=item.get("SingerName", ""),
                album=item.get("AlbumName", ""),
                cover=cover,
                platform="kugou",
                duration=item.get("HQDuration", 0) or item.get("Duration", 0),
                extra={
                    "hash": item.get("FileHash", ""),
                    "album_id": item.get("AlbumID", ""),
                    "sq_hash": item.get("SQFileHash", ""),
                    "hq_hash": item.get("HQFileHash", ""),
                },
            )
            songs.append(song)

        return SearchResult(
            songs=songs,
            total=data.get("data", {}).get("total", 0),
            page=page,
        )

    async def get_play_url(self, song: Song) -> str:
        song_hash = song.extra.get("hash", song.id)
        async with self._client() as client:
            resp = await client.get(
                "https://m.kugou.com/app/i/getSongInfo.php",
                params={
                    "cmd": "playInfo",
                    "hash": song_hash,
                },
                headers={
                    "User-Agent": "Android511-AndroidPhone-8983-18-0-NetMusic-wifi",
                },
            )
            data = resp.json()

        play_url = data.get("url", "")
        if not play_url:
            backup = data.get("backup_url", "")
            if isinstance(backup, list) and backup:
                play_url = backup[0]
            elif isinstance(backup, str):
                play_url = backup
        return play_url

    async def get_download_url(self, song: Song) -> str:
        return await self.get_play_url(song)

    async def get_lyrics(self, song: Song) -> str:
        keyword = f"{song.name} {song.artist}"
        duration_ms = (song.duration or 0) * 1000
        song_hash = song.extra.get("hash", song.id)

        async with self._client() as client:
            resp = await client.get(
                "https://lyrics.kugou.com/search",
                params={
                    "ver": "1",
                    "man": "yes",
                    "client": "pc",
                    "keyword": keyword,
                    "duration": str(duration_ms),
                    "hash": song_hash,
                },
            )
            data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return ""

        best = candidates[0]
        lyric_id = best.get("id", "")
        accesskey = best.get("accesskey", "")
        if not lyric_id or not accesskey:
            return ""

        async with self._client() as client:
            resp = await client.get(
                "https://lyrics.kugou.com/download",
                params={
                    "ver": "1",
                    "client": "pc",
                    "id": lyric_id,
                    "accesskey": accesskey,
                    "fmt": "lrc",
                    "charset": "utf8",
                },
            )
            dl_data = resp.json()

        content_b64 = dl_data.get("content", "")
        if not content_b64:
            return ""

        try:
            return base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:
            return ""
