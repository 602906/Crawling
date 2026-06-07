import asyncio
import json
import os
import time
import random
import string
import io
import base64
import hashlib
import segno
import httpx
from .base import MusicPlatform, Song, SearchResult


class NetEasePlatform(MusicPlatform):
    name = "网易云音乐"
    platform_id = "netease"

    NONCE = "0CoJUm6Qyw8W8jud"
    PUB_KEY = "010001"
    MODULUS = (
        "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7"
        "b725152b3ab17a876aea8a5aa76d2e417629ec4ee341f56135fccf695280"
        "104e0312ecbda92557c93870114af6c9d05c4f7f0c3685b7a46bee255932"
        "575cce10b424d813cfe4875d3e82047b97ddef52741d546b8e289dc6935b"
        "3ece0462db0a22b8e7"
    )
    IV = "0102030405060708"
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
    CSRF_TOKEN = ""

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer": "https://music.163.com/",
            "Origin": "https://music.163.com",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        self._qr_cookie_key = None

    def _persist_session(self):
        super()._persist_session()
        with open(os.path.join(self.SESSION_DIR, f"{self.platform_id}_extra.json"), "w", encoding="utf-8") as f:
            json.dump({"csrf_token": self.CSRF_TOKEN}, f)

    def _load_session(self) -> bool:
        result = super()._load_session()
        extra_path = os.path.join(self.SESSION_DIR, f"{self.platform_id}_extra.json")
        if os.path.exists(extra_path):
            try:
                with open(extra_path, "r", encoding="utf-8") as f:
                    extra = json.load(f)
                self.CSRF_TOKEN = extra.get("csrf_token", "")
            except Exception:
                pass
        return result

    def _create_secret_key(self, size: int = 16) -> str:
        return "".join(random.choices(string.ascii_letters + string.digits, k=size))

    def _aes_encrypt(self, text: str, key: str) -> str:
        from Crypto.Cipher import AES

        pad = 16 - len(text) % 16
        text = text + chr(pad) * pad
        cipher = AES.new(key.encode(), AES.MODE_CBC, self.IV.encode())
        encrypted = cipher.encrypt(text.encode())
        return base64.b64encode(encrypted).decode()

    def _rsa_encrypt(self, text: str) -> str:
        text_reversed = text[::-1]
        encrypted = pow(
            int(text_reversed.encode().hex(), 16),
            int(self.PUB_KEY, 16),
            int(self.MODULUS, 16),
        )
        return format(encrypted, "x").zfill(256)

    def _encrypt_request(self, data: dict) -> dict:
        text = json.dumps(data)
        sec_key = self._create_secret_key()
        enc_text = self._aes_encrypt(self._aes_encrypt(text, self.NONCE), sec_key)
        enc_sec_key = self._rsa_encrypt(sec_key)
        return {"params": enc_text, "encSecKey": enc_sec_key}

    async def get_qr_code(self) -> str:
        payload = self._encrypt_request({"type": "1", "csrf_token": self.CSRF_TOKEN})
        async with self._client() as client:
            resp = await client.post(
                "https://music.163.com/weapi/login/qrcode/unikey",
                data=payload,
            )
            data = resp.json()

        if data.get("code") == 200:
            self._qr_cookie_key = data["unikey"]
            qr_url = f"https://music.163.com/login?codekey={self._qr_cookie_key}"
            qr = segno.make(qr_url, error='M')
            buf = io.BytesIO()
            qr.save(buf, kind='png', scale=8)
            return base64.b64encode(buf.getvalue()).decode()
        return ""

    async def check_qr_status(self) -> dict:
        if not self._qr_cookie_key:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}

        payload = self._encrypt_request({
            "key": self._qr_cookie_key,
            "type": "1",
            "csrf_token": self.CSRF_TOKEN,
        })
        async with self._client() as client:
            resp = await client.post(
                "https://music.163.com/weapi/login/qrcode/unikey",
                data=payload,
            )
            data = resp.json()

        code = data.get("code", 0)
        if code == 803:
            self.logged_in = True
            for cookie in resp.cookies.jar:
                self.cookies[cookie.name] = cookie.value
            self.CSRF_TOKEN = self.cookies.get("__csrf", "")
            self.user_info = {"name": "网易云用户"}
            try:
                async with self._client() as c2:
                    r2 = await c2.get("https://music.163.com/api/nuser/account/get")
                    d2 = r2.json()
                    if d2.get("code") == 200 and d2.get("profile"):
                        p = d2["profile"]
                        self.user_info = {
                            "id": p.get("userId"),
                            "name": p.get("nickname", "网易云用户"),
                            "avatar": p.get("avatarUrl", ""),
                            "vip": p.get("vipType", 0) > 0,
                        }
            except Exception:
                pass
            return {"status": "success", "msg": "登录成功"}
        elif code == 802:
            return {"status": "scanned", "msg": "已扫码，请在手机上确认"}
        elif code == 801:
            return {"status": "waiting", "msg": "等待扫码"}
        elif code == 800:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}
        return {"status": "waiting", "msg": "等待扫码"}

    async def login_cookie(self, cookie_str: str) -> dict:
        cookies = self._parse_cookie_string(cookie_str)
        self.cookies.update(cookies)
        self.CSRF_TOKEN = cookies.get("__csrf", "")

        async with self._client() as client:
            resp = await client.get(
                "https://music.163.com/api/nuser/account/get",
            )
            data = resp.json()

        if data.get("code") == 200 and data.get("profile"):
            self.logged_in = True
            profile = data["profile"]
            self.user_info = {
                "id": profile.get("userId"),
                "name": profile.get("nickname", "用户"),
                "avatar": profile.get("avatarUrl", ""),
                "vip": profile.get("vipType", 0) > 0,
            }
            return {"success": True, "msg": "Cookie 登录成功"}
        return {"success": False, "msg": "Cookie 无效或已过期"}

    async def login_phone(self, phone: str, code: str = "") -> dict:
        if not code:
            payload = self._encrypt_request({
                "cellphone": phone,
                "csrf_token": self.CSRF_TOKEN,
            })
            async with self._client() as client:
                resp = await client.post(
                    "https://music.163.com/weapi/sms/captcha/sent",
                    data=payload,
                )
                data = resp.json()
            if data.get("code") == 200:
                return {"success": True, "msg": "验证码已发送", "need_code": True}
            return {"success": False, "msg": data.get("message", "发送失败")}

        payload = self._encrypt_request({
            "phone": phone,
            "captcha": code,
            "csrf_token": self.CSRF_TOKEN,
        })
        async with self._client() as client:
            resp = await client.post(
                "https://music.163.com/weapi/login/cellphone",
                data=payload,
            )
            data = resp.json()

        if data.get("code") == 200:
            self.logged_in = True
            for cookie in resp.cookies.jar:
                self.cookies[cookie.name] = cookie.value
            self.CSRF_TOKEN = self.cookies.get("__csrf", "")
            profile = data.get("profile", {})
            self.user_info = {
                "id": profile.get("userId"),
                "name": profile.get("nickname", "用户"),
            }
            return {"success": True, "msg": "登录成功"}
        return {"success": False, "msg": data.get("message", "登录失败")}

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        offset = (page - 1) * page_size
        async with self._client() as client:
            resp = await client.post(
                "https://music.163.com/api/search/get",
                data={
                    "s": keyword,
                    "type": "1",
                    "limit": str(page_size),
                    "offset": str(offset),
                },
            )
            data = resp.json()

        songs = []
        result = data.get("result", {})
        song_ids = []
        for item in result.get("songs", []):
            artists = "/".join([a.get("name", "") for a in item.get("artists", [])])
            album_info = item.get("album", {})
            cover = album_info.get("picUrl", "") or ""
            sid = str(item.get("id", ""))
            song = Song(
                id=sid,
                name=item.get("name", ""),
                artist=artists,
                album=album_info.get("name", ""),
                cover=cover,
                platform="netease",
                duration=item.get("duration", 0) // 1000,
                extra={
                    "fee": item.get("fee", 0),
                },
            )
            songs.append(song)
            if sid:
                song_ids.append(sid)

        if song_ids:
            cover_map = {}
            chunk_size = 20
            for i in range(0, len(song_ids), chunk_size):
                chunk = song_ids[i:i + chunk_size]
                ids_str = ",".join(chunk)
                try:
                    async with self._client() as client:
                        r = await client.get(
                            "https://music.163.com/api/song/detail",
                            params={"ids": f"[{ids_str}]", "cs": "[]"},
                        )
                        d = r.json()
                        for s in d.get("songs", []):
                            pic_url = s.get("album", {}).get("picUrl", "")
                            if pic_url:
                                cover_map[str(s.get("id", ""))] = pic_url
                except Exception:
                    pass

            for s in songs:
                if not s.cover:
                    s.cover = cover_map.get(s.id, "")

        return SearchResult(
            songs=songs,
            total=result.get("songCount", 0),
            page=page,
        )

    async def get_play_url(self, song: Song) -> str:
        url = f"https://music.163.com/song/media/outer/url?id={song.id}.mp3"
        async with self._client() as client:
            resp = await client.head(url)
            if resp.status_code == 302:
                return resp.headers.get("location", url)
            if resp.status_code == 200:
                return url
        return url

    async def get_download_url(self, song: Song) -> str:
        payload = self._encrypt_request({
            "ids": [int(song.id)],
            "br": 320000,
            "csrf_token": self.CSRF_TOKEN,
        })
        async with self._client() as client:
            resp = await client.post(
                "https://music.163.com/weapi/song/enhance/player/url",
                data=payload,
            )
            data = resp.json()

        urls = data.get("data", [])
        if urls and urls[0].get("url"):
            return urls[0]["url"]
        return await self.get_play_url(song)

    async def get_lyrics(self, song: Song) -> str:
        async with self._client() as client:
            resp = await client.get(
                "https://music.163.com/api/song/lyric",
                params={"id": song.id, "lv": "1", "kv": "1", "tv": "-1"},
            )
            data = resp.json()
        lrc = data.get("lrc", {}).get("lyric", "")
        tlrc = data.get("tlyric", {}).get("lyric", "")
        if lrc and tlrc:
            lrc = lrc + "\n" + tlrc
        return lrc
