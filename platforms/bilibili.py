import asyncio
import io
import base64
import hashlib
import re
import time
import segno
from functools import reduce
from urllib.parse import urlencode
from .base import MusicPlatform, Song, SearchResult


class BilibiliPlatform(MusicPlatform):
    name = "Bilibili"
    platform_id = "bilibili"
    supported_login_methods = ["qrcode", "cookie"]

    _MIXIN_KEY_ENC_TAB = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
        27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
        37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
        22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
    ]

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
        })
        self._qr_key = None
        self._wbi_key = ""

    async def _get_wbi_key(self) -> str:
        if self._wbi_key:
            return self._wbi_key
        async with self._client() as client:
            resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
            data = resp.json()
        wbi_img = data.get("data", {}).get("wbi_img", {})
        img_url = wbi_img.get("img_url", "")
        sub_url = wbi_img.get("sub_url", "")
        if not img_url or not sub_url:
            return ""
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
        raw = img_key + sub_key
        self._wbi_key = reduce(lambda s, i: s + raw[i], self._MIXIN_KEY_ENC_TAB, "")[:32]
        return self._wbi_key

    def _sign_wbi(self, params: dict) -> dict:
        params["wts"] = int(time.time())
        params = dict(sorted(params.items()))
        query = urlencode(params)
        w_rid = hashlib.md5((query + self._wbi_key).encode()).hexdigest()
        params["w_rid"] = w_rid
        return params

    async def get_qr_code(self) -> str:
        async with self._client() as client:
            resp = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
            )
            data = resp.json()

        if data.get("code") == 0:
            qr_url = data["data"]["url"]
            self._qr_key = data["data"]["qrcode_key"]
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
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": self._qr_key},
            )
            data = resp.json()

        code = data.get("code", -1)
        d = data.get("data", {})
        status_code = d.get("code", -1)

        if status_code == 0:
            self.logged_in = True
            for cookie in resp.cookies.jar:
                self.cookies[cookie.name] = cookie.value
            self.user_info = await self._fetch_user_info()
            return {"status": "success", "msg": "登录成功"}
        elif status_code == 86038:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}
        elif status_code == 86090:
            return {"status": "scanned", "msg": "已扫码，请在手机上确认"}
        elif status_code == 86101:
            return {"status": "waiting", "msg": "等待扫码"}
        return {"status": "waiting", "msg": "等待扫码"}

    async def _fetch_user_info(self) -> dict:
        try:
            async with self._client() as client:
                resp = await client.get("https://api.bilibili.com/x/web-interface/nav")
                data = resp.json()
            if data.get("code") == 0 and data.get("data"):
                d = data["data"]
                return {
                    "name": d.get("uname") or f"UID {d.get('mid', '')}",
                    "id": d.get("mid"),
                    "avatar": d.get("face", ""),
                    "level": d.get("level_info", {}).get("current_level", ""),
                    "vip": d.get("vipStatus", 0) == 1,
                }
        except Exception:
            pass
        return {"name": "B站用户"}

    async def login_cookie(self, cookie_str: str) -> dict:
        cookies = self._parse_cookie_string(cookie_str)
        self.cookies.update(cookies)

        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/nav",
            )
            data = resp.json()

        if data.get("code") == 0 and data.get("data", {}).get("isLogin"):
            self.logged_in = True
            self.user_info = await self._fetch_user_info()
            return {"success": True, "msg": "Cookie 登录成功"}
        return {"success": False, "msg": "Cookie 无效或已过期"}

    async def login_phone(self, phone: str, code: str = "") -> dict:
        return {"success": False, "msg": "B站请使用扫码或Cookie登录"}

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        await self._get_wbi_key()
        params = self._sign_wbi({
            "search_type": "video",
            "keyword": keyword,
            "page": page,
            "page_size": page_size,
        })
        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/wbi/search/type",
                params=params,
            )
            data = resp.json()

        songs = []
        result_list = data.get("data", {}).get("result", []) or []
        for item in result_list:
            bvid = item.get("bvid", "")
            title = re.sub(r'<[^>]+>', '', item.get("title", ""))
            author = item.get("author", "")
            pic = item.get("pic", "")
            if pic and not pic.startswith("http"):
                pic = "https:" + pic
            duration_str = item.get("duration", "0:0")
            parts = str(duration_str).split(":")
            try:
                if len(parts) >= 3:
                    duration = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                elif len(parts) == 2:
                    duration = int(parts[0]) * 60 + int(parts[1])
                else:
                    duration = int(parts[0])
            except (ValueError, IndexError):
                duration = 0

            song = Song(
                id=bvid,
                name=title,
                artist=author,
                album="",
                cover=pic,
                platform="bilibili",
                duration=duration,
                extra={"bvid": bvid},
            )
            songs.append(song)

        total = data.get("data", {}).get("numResults", 0)
        return SearchResult(songs=songs, total=total, page=page)

    async def _get_cid(self, bvid: str) -> str:
        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
            )
            data = resp.json()
        if data.get("code") == 0:
            return str(data["data"].get("cid", ""))
        return ""

    async def get_play_url(self, song: Song) -> str:
        bvid = song.extra.get("bvid", song.id)
        _, cid = await asyncio.gather(self._get_wbi_key(), self._get_cid(bvid))
        if not cid:
            return ""

        params = self._sign_wbi({
            "bvid": bvid,
            "cid": cid,
            "fnval": 1,
            "fnver": 0,
            "fourk": 1,
        })
        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/player/wbi/playurl",
                params=params,
            )
            data = resp.json()

        if data.get("code") == 0:
            durl = data.get("data", {}).get("durl", [])
            if durl:
                return durl[0].get("url", "")
            dash = data.get("data", {}).get("dash", {})
            if dash:
                videos = dash.get("video", [])
                if videos:
                    return videos[0].get("baseUrl", "")
        return ""

    async def _get_dash_streams(self, bvid: str, cid: str) -> dict:
        params = self._sign_wbi({
            "bvid": bvid,
            "cid": cid,
            "fnval": 16,
            "fnver": 0,
            "fourk": 1,
        })
        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/player/wbi/playurl",
                params=params,
            )
            data = resp.json()
        result = {"video": "", "audio": ""}
        if data.get("code") == 0:
            dash = data.get("data", {}).get("dash", {})
            if dash:
                videos = dash.get("video", [])
                if videos:
                    result["video"] = videos[0].get("baseUrl", "")
                audios = dash.get("audio", [])
                if audios:
                    result["audio"] = audios[0].get("baseUrl", "")
        return result

    async def get_download_url(self, song: Song, stream_type: str = "video") -> str:
        bvid = song.extra.get("bvid", song.id)
        _, cid = await asyncio.gather(self._get_wbi_key(), self._get_cid(bvid))
        if not cid:
            return ""
        streams = await self._get_dash_streams(bvid, cid)
        if stream_type == "audio":
            return streams.get("audio", "")
        return streams.get("video", "") or await self.get_play_url(song)

    def get_available_qualities(self, song: Song) -> list[dict]:
        return [
            {"value": "video", "label": "下载视频"},
            {"value": "audio", "label": "下载音频"},
        ]

    async def get_song_detail(self, song_id: str) -> Song:
        bvid = song_id
        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
            )
            data = resp.json()
        if data.get("code") != 0:
            return None
        d = data["data"]
        pic = d.get("pic", "")
        if pic and not pic.startswith("http"):
            pic = "https:" + pic
        return Song(
            id=bvid,
            name=d.get("title", ""),
            artist=d.get("owner", {}).get("name", ""),
            album="",
            cover=pic,
            platform="bilibili",
            duration=d.get("duration", 0),
            extra={"bvid": bvid},
        )

    async def get_lyrics(self, song: Song) -> str:
        bvid = song.extra.get("bvid", song.id)
        _, cid = await asyncio.gather(self._get_wbi_key(), self._get_cid(bvid))
        if not cid:
            return ""

        params = self._sign_wbi({"bvid": bvid, "cid": cid})
        async with self._client() as client:
            resp = await client.get(
                "https://api.bilibili.com/x/player/wbi/v2",
                params=params,
            )
            data = resp.json()

        subtitle_info = (
            data.get("data", {})
            .get("subtitle", {})
            .get("subtitles", [])
        )
        if not subtitle_info:
            return ""

        subtitle_url = subtitle_info[0].get("subtitle_url", "")
        if not subtitle_url:
            return ""
        if subtitle_url.startswith("//"):
            subtitle_url = "https:" + subtitle_url

        async with self._client() as client:
            resp = await client.get(subtitle_url)
            sub_data = resp.json()

        body = sub_data.get("body", [])
        if not body:
            return ""

        lines = []
        for item in body:
            start = item.get("from", 0)
            content = item.get("content", "")
            mins = int(start) // 60
            secs = start - mins * 60
            sec_int = int(secs)
            centisec = int(round((secs - sec_int) * 100))
            lines.append(f"[{mins:02d}:{sec_int:02d}.{centisec:02d}]{content}")
        return "\n".join(lines)
