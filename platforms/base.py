from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import json
import os
import httpx


@dataclass
class Song:
    id: str
    name: str
    artist: str
    album: str = ""
    cover: str = ""
    platform: str = ""
    duration: int = 0
    extra: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    songs: list[Song]
    total: int = 0
    page: int = 1


class MusicPlatform(ABC):
    name: str = ""
    platform_id: str = ""
    supported_login_methods: list[str] = ["qrcode", "cookie", "phone"]
    SESSION_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".sessions")

    def __init__(self):
        self.cookies: dict[str, str] = {}
        self.logged_in = False
        self.user_info: Optional[dict] = None
        self._qr_key: Optional[str] = None
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }

    def _persist_session(self):
        os.makedirs(self.SESSION_DIR, exist_ok=True)
        data = {
            "cookies": self.cookies,
            "logged_in": self.logged_in,
            "user_info": self.user_info,
        }
        with open(os.path.join(self.SESSION_DIR, f"{self.platform_id}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _load_session(self) -> bool:
        path = os.path.join(self.SESSION_DIR, f"{self.platform_id}.json")
        if not os.path.exists(path):
            return False
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.cookies = data.get("cookies", {})
            self.logged_in = data.get("logged_in", False)
            self.user_info = data.get("user_info")
            return True
        except Exception:
            return False

    def _client(self, **kwargs) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            headers=self.headers,
            cookies=self.cookies,
            follow_redirects=True,
            timeout=15,
            **kwargs,
        )

    @abstractmethod
    async def get_qr_code(self) -> str:
        """返回二维码图片的 URL 或 base64"""

    @abstractmethod
    async def check_qr_status(self) -> dict:
        """返回 {"status": "waiting"|"scanned"|"success"|"expired", "msg": "..."}"""

    @abstractmethod
    async def login_cookie(self, cookie_str: str) -> dict:
        """通过 Cookie 字符串登录"""

    @abstractmethod
    async def login_phone(self, phone: str, code: str = "") -> dict:
        """手机号登录，code 为空时发送验证码"""

    @abstractmethod
    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        """搜索歌曲"""

    @abstractmethod
    async def get_play_url(self, song: Song) -> str:
        """获取歌曲播放 URL"""

    @abstractmethod
    async def get_download_url(self, song: Song) -> str:
        """获取歌曲下载 URL"""

    async def send_phone_code(self, phone: str) -> dict:
        """发送手机验证码"""
        return {"success": False, "msg": "该平台不支持手机号登录"}

    async def get_lyrics(self, song: Song) -> str:
        """返回 LRC 格式歌词，无歌词返回空字符串"""
        return ""

    def _parse_cookie_string(self, cookie_str: str) -> dict[str, str]:
        cookie_str = cookie_str.strip()
        if cookie_str.startswith("["):
            try:
                items = json.loads(cookie_str)
                return {item["name"]: item["value"] for item in items if "name" in item and "value" in item}
            except (json.JSONDecodeError, TypeError, KeyError):
                pass
        result = {}
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                result[k.strip()] = v.strip()
        return result
