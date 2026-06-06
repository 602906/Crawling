import json
import time
import io
import base64
import hashlib
import segno
from .base import MusicPlatform, Song, SearchResult


class QQMusicPlatform(MusicPlatform):
    name = "QQ音乐"
    platform_id = "qqmusic"
    supported_login_methods = ["qrcode", "cookie"]

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer": "https://y.qq.com/",
            "Origin": "https://y.qq.com",
        })
        self._qr_key = None

    async def get_qr_code(self) -> str:
        async with self._client() as client:
            resp = await client.get(
                "https://c.y.qq.com/qrcode/fcgi-bin/fcg_qrcode.fcgp",
                params={
                    "appid": "501",
                    "redirect_uri": "https://y.qq.com/",
                    "login_type": "2",
                },
            )
            data = resp.json() if resp.status_code == 200 else {}

        qr_url = data.get("data", {}).get("qrcode_url", "")
        self._qr_key = data.get("data", {}).get("token", "")

        if not qr_url and not self._qr_key:
            qr_url = f"https://open.weixin.qq.com/connect/qrconnect?appid=wx48058cd749799968&redirect_uri=https%3A%2F%2Fy.qq.com%2Fportal%2Fwx_redirect.html%3Flogin_type%3D1%26surl%3Dhttps%253A%252F%252Fy.qq.com%252F&response_type=code&scope=snsapi_login&state=STATE&display=tab"
            self._qr_key = "wx_" + str(int(time.time()))

        qr = segno.make(qr_url, error='M')
        buf = io.BytesIO()
        qr.save(buf, kind='png', scale=8)
        return base64.b64encode(buf.getvalue()).decode()

    async def check_qr_status(self) -> dict:
        if not self._qr_key:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}

        async with self._client() as client:
            resp = await client.get(
                "https://c.y.qq.com/qrcode/fcgi-bin/fcg_qrcode_check.fcgp",
                params={
                    "token": self._qr_key,
                    "login_type": "2",
                },
            )
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = {}
            else:
                data = {}

        status = data.get("data", {}).get("status", -1)
        if status == 2:
            self.logged_in = True
            self.cookies.update(dict(resp.cookies))
            self.user_info = {"name": "QQ音乐用户"}
            return {"status": "success", "msg": "登录成功"}
        elif status == 1:
            return {"status": "scanned", "msg": "已扫码，请在手机上确认"}
        elif status == 0:
            return {"status": "waiting", "msg": "等待扫码"}
        else:
            return {"status": "expired", "msg": "二维码已过期，请刷新"}

    async def login_cookie(self, cookie_str: str) -> dict:
        cookies = self._parse_cookie_string(cookie_str)
        self.cookies.update(cookies)

        uin = cookies.get("uin", cookies.get("qqmusic_uin", ""))
        qmkey = cookies.get("qm_keyst", cookies.get("qqmusic_key", ""))

        if uin and qmkey:
            self.logged_in = True
            self.user_info = {"name": f"QQ用户({uin})"}
            return {"success": True, "msg": "Cookie 登录成功"}

        if cookies:
            self.logged_in = True
            self.user_info = {"name": "Cookie用户"}
            return {"success": True, "msg": "Cookie 已加载"}

        return {"success": False, "msg": "Cookie 无效，请检查是否包含 uin 和 qqmusic_key"}

    async def login_phone(self, phone: str, code: str = "") -> dict:
        return {"success": False, "msg": "QQ音乐请使用扫码或Cookie登录"}

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        params = {
            "w": keyword,
            "p": page,
            "n": page_size,
            "format": "json",
            "cr": "1",
            "new_json": "1",
        }
        async with self._client() as client:
            resp = await client.get(
                "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                params=params,
            )
            data = resp.json()

        songs = []
        song_list = (
            data.get("data", {})
            .get("song", {})
            .get("list", [])
        )
        for item in song_list:
            singers = "/".join([s.get("name", "") for s in item.get("singer", [])])
            album = item.get("album", {})
            mid = item.get("mid", "")
            song_id = str(item.get("id", ""))

            cover = ""
            album_mid = album.get("mid", "")
            if album_mid:
                cover = f"https://y.qq.com/music/photo_new/T002R300x300M000{album_mid}.jpg"

            song = Song(
                id=song_id,
                name=item.get("name", ""),
                artist=singers,
                album=album.get("name", ""),
                cover=cover,
                platform="qqmusic",
                duration=item.get("interval", 0),
                extra={
                    "mid": mid,
                    "album_mid": album_mid,
                    "strMediaMid": item.get("file", {}).get("media_mid", mid),
                },
            )
            songs.append(song)

        total = data.get("data", {}).get("song", {}).get("totalnum", 0)
        return SearchResult(songs=songs, total=total, page=page)

    async def get_play_url(self, song: Song) -> str:
        mid = song.extra.get("mid", "")
        if not mid:
            return ""

        guid = str(int(time.time() * 1000) % 100000000)
        uin = self.cookies.get("uin", "0")

        req_data = {
            "req_0": {
                "module": "vkey.GetVkeyServer",
                "method": "CgiGetVkey",
                "param": {
                    "guid": guid,
                    "loginflag": 1,
                    "songmid": [mid],
                    "songtype": [0],
                    "uin": uin,
                    "platform": "20",
                },
            },
            "comm": {
                "uin": int(uin) if uin.isdigit() else 0,
                "format": "json",
                "ct": 24,
                "cv": 0,
            },
        }

        async with self._client() as client:
            resp = await client.get(
                "https://u.y.qq.com/cgi-bin/musicu.fcg",
                params={"data": json.dumps(req_data)},
            )
            data = resp.json()

        midurlinfo = (
            data.get("req_0", {})
            .get("data", {})
            .get("midurlinfo", [])
        )
        sip = (
            data.get("req_0", {})
            .get("data", {})
            .get("sip", ["https://dl.stream.qqmusic.qq.com/"])
        )

        if midurlinfo and midurlinfo[0].get("purl"):
            base_url = sip[0] if sip else "https://dl.stream.qqmusic.qq.com/"
            return base_url + midurlinfo[0]["purl"]
        return ""

    async def get_download_url(self, song: Song) -> str:
        return await self.get_play_url(song)
