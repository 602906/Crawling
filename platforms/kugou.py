import base64
import hashlib
import json
import os
import random
import re
import time

import httpx
from .base import MusicPlatform, Song, SearchResult

LITE_APPID = 3116
LITE_CLIENTVER = 11440
LITE_SIGN_SECRET = "LnT6xpN3khm36zse0QzvmgTZ3waWdRSA"
LITE_SIGNKEY_SECRET = "57ae12eb6890223e355ccfcb74edf70d"
LITE_WEB_SIGN_SECRET = "NVPh5oo715z5DIWAeQlhMDsWXXQV4hwt"
ANDROID_UA = "Android15-1070-11083-46-0-DiscoveryDRADProtocol-wifi"
CHARSET = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ"
LITE_RSA_PUB_KEY = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDECi0Np2UR87scwrvTr72L6oO0"
    "1rBbbBPriSDFPxr3Z5syug0O24QyQO8bg27+0+4kBzTBTBOZ/WWU0WryL1JSXRTX"
    "LgFVxtzIY41Pe7lPOgsfTCn5kZcvKhYKJesKnnJDNr5/abvTGf+rHG3YRwsCHcQ0"
    "8/q6ifSioBszvb3QiwIDAQAB"
)


def _https_url(url: str) -> str:
    """封面/头像等图片链接统一升级为 https，避免 HTTPS 页面下的混合内容告警"""
    if url and url.startswith("http://"):
        return "https://" + url[7:]
    return url


def _md5(data) -> str:
    if isinstance(data, dict):
        data = json.dumps(data, separators=(',', ':'))
    if isinstance(data, str):
        data = data.encode()
    return hashlib.md5(data).hexdigest()


def _random_string(n=24) -> str:
    return "".join(random.choice(CHARSET) for _ in range(n))


def _get_guid() -> str:
    e = lambda: f"{int((1 + random.random()) * 65536):04x}"[1:]
    return f"{e()}{e()}-{e()}-{e()}-{e()}-{e()}{e()}{e()}"


def _calculate_mid(guid_str: str) -> str:
    return str(int(_md5(guid_str), 16))


def _signature_android(params: dict, data: str = "") -> str:
    parts = sorted(params.keys())
    body = "".join(
        f"{k}={json.dumps(params[k], separators=(',', ':')) if isinstance(params[k], dict) else params[k]}"
        for k in parts
    )
    return _md5(f"{LITE_SIGN_SECRET}{body}{data}{LITE_SIGN_SECRET}")


def _signature_web(params: dict) -> str:
    s = LITE_WEB_SIGN_SECRET
    parts = sorted(f"{k}={params[k]}" for k in params.keys())
    body = "".join(parts)
    return _md5(f"{s}{body}{s}")


def _sign_key(hash_val: str, mid: str, userid, appid=None) -> str:
    appid = appid or LITE_APPID
    return _md5(f"{hash_val}{LITE_SIGNKEY_SECRET}{appid}{mid}{userid or 0}")


def _sign_params_key(data) -> str:
    return _md5(f"{LITE_APPID}{LITE_SIGN_SECRET}{LITE_CLIENTVER}{data}")


def _aes_256_cbc_encrypt(data, key: str = None):
    from Crypto.Cipher import AES
    if isinstance(data, dict):
        data = json.dumps(data)
    temp_key = key or _random_string(16).lower()
    aes_key = _md5(temp_key)[:32].encode()
    aes_iv = aes_key[-16:]
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
    raw = data.encode() if isinstance(data, str) else data
    pad = 16 - len(raw) % 16
    raw += bytes([pad]) * pad
    return {"str": cipher.encrypt(raw).hex(), "key": temp_key}


def _aes_256_cbc_decrypt(hex_data: str, key: str):
    from Crypto.Cipher import AES
    aes_key = _md5(key)[:32].encode()
    aes_iv = aes_key[-16:]
    cipher = AES.new(aes_key, AES.MODE_CBC, aes_iv)
    decrypted = cipher.decrypt(bytes.fromhex(hex_data))
    pad_len = decrypted[-1]
    decrypted = decrypted[:-pad_len]
    try:
        return json.loads(decrypted.decode())
    except Exception:
        return decrypted.decode()


def _rsa_encrypt_lite(data) -> str:
    from Crypto.PublicKey import RSA
    pem = f"-----BEGIN PUBLIC KEY-----\n{LITE_RSA_PUB_KEY}\n-----END PUBLIC KEY-----"
    pub_key = RSA.import_key(pem)
    if isinstance(data, dict):
        data = json.dumps(data)
    raw = data.encode() if isinstance(data, str) else data
    padded = raw + b"\x00" * (128 - len(raw))
    m = int.from_bytes(padded, "big")
    c = pow(m, pub_key.e, pub_key.n)
    return format(c, "x").zfill(256)


def _playlist_aes_encrypt(data) -> dict:
    """酷狗 v2 注册加密（参照 KuGouMusicApi playlistAesEncrypt）：
    key=随机 6 位小写，aes_key=md5(key)[:16]，iv=md5(key)[16:32]，CBC/PKCS7 → base64"""
    from Crypto.Cipher import AES
    if isinstance(data, dict):
        data = json.dumps(data)
    key = "".join(random.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(6))
    digest = _md5(key)
    aes_key = digest[:16].encode()
    iv = digest[16:32].encode()
    pad = 16 - len(data) % 16
    data += chr(pad) * pad
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    return {"key": key, "str": base64.b64encode(cipher.encrypt(data.encode())).decode()}


def _playlist_aes_decrypt(str_b64: str, key: str):
    from Crypto.Cipher import AES
    digest = _md5(key)
    aes_key = digest[:16].encode()
    iv = digest[16:32].encode()
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(base64.b64decode(str_b64))
    pad_len = decrypted[-1]
    decrypted = decrypted[:-pad_len]
    try:
        return json.loads(decrypted.decode())
    except Exception:
        return decrypted.decode()


def _rsa_encrypt2(data) -> str:
    """RSAES-PKCS1-V1_5 加密 → hex（v2 注册 p 参数，参照 KuGouMusicApi rsaEncrypt2）"""
    from Crypto.Cipher import PKCS1_v1_5
    from Crypto.PublicKey import RSA
    pem = f"-----BEGIN PUBLIC KEY-----\n{LITE_RSA_PUB_KEY}\n-----END PUBLIC KEY-----"
    pub_key = RSA.import_key(pem)
    cipher = PKCS1_v1_5.new(pub_key)
    if isinstance(data, dict):
        data = json.dumps(data)
    return cipher.encrypt(data.encode()).hex()


class KuGouPlatform(MusicPlatform):
    name = "酷狗音乐"
    platform_id = "kugou"
    supported_login_methods = ["cookie", "phone"]

    def __init__(self):
        super().__init__()
        self.headers.update({
            "Referer": "https://www.kugou.com/",
            "Origin": "https://www.kugou.com",
        })
        self._guid = _get_guid()
        self._dev = _random_string(10)
        self._mac = "02:00:00:00:00:00"
        self._dfid = "-"
        self._mid = _calculate_mid(self._guid)
        self._token = ""
        self._userid = 0
        self._vip_token = ""
        self._vip_type = 0
        self._device_registered = False

    def _persist_session(self):
        os.makedirs(self.SESSION_DIR, exist_ok=True)
        data = {
            "cookies": self.cookies,
            "logged_in": self.logged_in,
            "user_info": self.user_info,
        }
        with open(os.path.join(self.SESSION_DIR, f"{self.platform_id}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        extra = {
            "guid": self._guid,
            "dev": self._dev,
            "mac": self._mac,
            "dfid": self._dfid,
            "mid": self._mid,
            "token": self._token,
            "userid": self._userid,
            "vip_token": self._vip_token,
            "vip_type": self._vip_type,
        }
        with open(os.path.join(self.SESSION_DIR, f"{self.platform_id}_extra.json"), "w", encoding="utf-8") as f:
            json.dump(extra, f, ensure_ascii=False)

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
        except Exception:
            return False
        extra_path = os.path.join(self.SESSION_DIR, f"{self.platform_id}_extra.json")
        if os.path.exists(extra_path):
            try:
                with open(extra_path, "r", encoding="utf-8") as f:
                    extra = json.load(f)
                self._guid = extra.get("guid", self._guid)
                self._dev = extra.get("dev", self._dev)
                self._mac = extra.get("mac", self._mac)
                self._dfid = extra.get("dfid", self._dfid)
                self._mid = extra.get("mid", self._mid)
                self._token = extra.get("token", "")
                self._userid = extra.get("userid", 0)
                self._vip_token = extra.get("vip_token", "")
                self._vip_type = extra.get("vip_type", 0)
                if extra.get("dfid") and extra["dfid"] != "-":
                    self._device_registered = True
            except Exception:
                pass
        return True

    async def _register_device(self):
        """酷狗设备注册 v2（参照 KuGouMusicApi register_dev.js）：
        完整设备信息 AES 加密 + RSA(p) + android 签名，成功换取有效 dfid。
        v1 接口已失效（返回空），仅保留 v2。"""
        if self._device_registered:
            return
        self._device_registered = True
        data_map = {
            "availableRamSize": 4983533568,
            "availableRomSize": 48114719,
            "availableSDSize": 48114717,
            "basebandVer": "",
            "batteryLevel": 100,
            "batteryStatus": 3,
            "brand": "Redmi",
            "buildSerial": "unknown",
            "device": "marble",
            "imei": self._guid,
            "imsi": "",
            "manufacturer": "Xiaomi",
            "uuid": self._guid,
            "accelerometer": False,
            "accelerometerValue": "",
            "gravity": False,
            "gravityValue": "",
            "gyroscope": False,
            "gyroscopeValue": "",
            "light": False,
            "lightValue": "",
            "magnetic": False,
            "magneticValue": "",
            "orientation": False,
            "orientationValue": "",
            "pressure": False,
            "pressureValue": "",
            "step_counter": False,
            "step_counterValue": "",
            "temperature": False,
            "temperatureValue": "",
        }
        try:
            aes = _playlist_aes_encrypt(data_map)
            p = _rsa_encrypt2({"aes": aes["key"], "uid": self._userid, "token": self._token})

            clienttime = int(time.time())
            params = {
                "dfid": self._dfid,
                "mid": self._mid,
                "uuid": _md5(f"{self._dfid}{self._mid}"),
                "appid": LITE_APPID,
                "clientver": LITE_CLIENTVER,
                "clienttime": clienttime,
                "userid": self._userid or 0,
                "part": 1,
                "platid": 1,
                "p": p,
            }
            params["signature"] = _signature_android(params, aes["str"])
            headers = {
                "User-Agent": ANDROID_UA,
                "dfid": self._dfid,
                "clienttime": str(clienttime),
                "mid": self._mid,
                "kg-rc": "1",
                "kg-thash": "5d816a0",
                "kg-rec": "1",
                "kg-rf": "B9EDA08A64250DEFFBCADDEE00F8F25F",
            }
            client = httpx.AsyncClient(follow_redirects=True, timeout=15)
            try:
                resp = await client.post(
                    "https://userservice.kugou.com/risk/v2/r_register_dev",
                    params=params,
                    content=aes["str"].encode(),
                    headers=headers,
                )
                # 响应为 AES 密文：base64 编码后解密
                dec = _playlist_aes_decrypt(base64.b64encode(resp.content).decode(), aes["key"])
                if dec.get("status") == 1 and dec.get("data"):
                    self._dfid = dec["data"].get("dfid", self._dfid)
            finally:
                await client.aclose()
        except Exception:
            pass

    async def _lite_request(self, url: str, method: str = "GET", params: dict = None,
                            data=None, x_router: str = "", base_url: str = "",
                            sign: bool = True, encrypt_key: bool = False,
                            extra_headers: dict = None, clear_defaults: bool = False) -> dict:
        clienttime = int(time.time())
        all_params = {}

        if not clear_defaults:
            all_params.update({
                "dfid": self._dfid,
                "mid": self._mid,
                "uuid": _md5(f"{self._dfid}{self._mid}"),
                "appid": LITE_APPID,
                "clientver": LITE_CLIENTVER,
                "clienttime": clienttime,
            })
            if self._token:
                all_params["token"] = self._token
            all_params["userid"] = self._userid or 0

        if params:
            all_params.update(params)

        if encrypt_key and "hash" in all_params:
            all_params["key"] = _sign_key(
                all_params["hash"], self._mid, self._userid, all_params.get("appid", LITE_APPID)
            )

        data_str = ""
        if isinstance(data, (dict, list)):
            # 数组/对象均紧凑序列化参与签名（酷狗 JS 端 JSON.stringify 输出无空格）
            data_str = json.dumps(data, separators=(',', ':'))
        elif isinstance(data, str):
            data_str = data

        if sign:
            all_params["signature"] = _signature_android(all_params, data_str)

        headers = {
            "User-Agent": ANDROID_UA,
            "dfid": self._dfid,
            "clienttime": str(clienttime),
            "mid": self._mid,
            "kg-rc": "1",
            "kg-thash": "5d816a0",
            "kg-rec": "1",
            "kg-rf": "B9EDA08A64250DEFFBCADDEE00F8F25F",
        }
        if x_router:
            headers["x-router"] = x_router
        if extra_headers:
            headers.update(extra_headers)

        effective_base = base_url or "https://gateway.kugou.com"
        full_url = f"{effective_base}{url}" if not url.startswith("http") else url

        client = httpx.AsyncClient(cookies=self.cookies, follow_redirects=True, timeout=15)
        try:
            if method.upper() == "GET":
                resp = await client.get(full_url, params=all_params, headers=headers)
            else:
                resp = await client.post(full_url, params=all_params, headers=headers,
                                         json=data if isinstance(data, (dict, list)) else None,
                                         content=data_str if isinstance(data, str) else None)
            for cookie in resp.cookies.jar:
                self.cookies[cookie.name] = cookie.value
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        finally:
            await client.aclose()

    async def _web_request(self, url: str, params: dict = None, base_url: str = "") -> dict:
        clienttime = int(time.time())
        all_params = {"appid": LITE_APPID, "clienttime": clienttime}
        if params:
            all_params.update(params)
        all_params["signature"] = _signature_web(all_params)

        headers = {"User-Agent": ANDROID_UA}
        effective_base = base_url or "https://gateway.kugou.com"
        full_url = f"{effective_base}{url}" if not url.startswith("http") else url

        client = httpx.AsyncClient(cookies=self.cookies, follow_redirects=True, timeout=15)
        try:
            resp = await client.get(full_url, params=all_params, headers=headers)
            for cookie in resp.cookies.jar:
                self.cookies[cookie.name] = cookie.value
            try:
                return resp.json()
            except Exception:
                return {"raw": resp.text}
        finally:
            await client.aclose()

    async def get_qr_code(self) -> str:
        return ""

    async def check_qr_status(self) -> dict:
        return {"status": "expired", "msg": "酷狗不支持扫码登录"}

    async def login_cookie(self, cookie_str: str) -> dict:
        cookies = self._parse_cookie_string(cookie_str)
        if not cookies:
            return {"success": False, "msg": "Cookie 为空"}
        self.cookies.update(cookies)

        token = cookies.get("token") or cookies.get("KUGOU_TOKEN") or cookies.get("t", "")
        userid = cookies.get("userid", "0")
        self._token = token
        self._userid = int(userid) if str(userid).isdigit() else 0
        self._vip_token = cookies.get("vip_token", "")
        vip_type_str = cookies.get("vip_type", "0")
        self._vip_type = int(vip_type_str) if vip_type_str.isdigit() else 0

        ku_info = cookies.get("KuGoo", "")
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

        if not token and not ku_info:
            return {"success": False, "msg": "Cookie 缺少关键字段 (token / KuGoo)"}

        try:
            data = await self._lite_request(
                "https://mobileservice.kugou.com/api/v3/user/info",
                params={"version": "9209", "plat": "0"},
                sign=False,
            )
            status = data.get("status", 0)
            if status == 1 and data.get("data"):
                info = data["data"]
                self.logged_in = True
                self.user_info = {
                    "name": info.get("nickname") or info.get("username") or nickname or "酷狗用户",
                    "id": info.get("userid") or user_id or self._userid,
                    "avatar": _https_url(info.get("pic") or info.get("avatar") or avatar),
                }
                self._persist_session()
                return {"success": True, "msg": "Cookie 登录成功"}
        except Exception:
            pass

        if token:
            self.logged_in = True
            self.user_info = {"name": nickname or "酷狗用户", "id": user_id or self._userid, "avatar": _https_url(avatar)}
            self._persist_session()
            return {"success": True, "msg": "Cookie 登录成功"}
        return {"success": False, "msg": "Cookie 无效或已过期"}

    async def send_phone_code(self, phone: str) -> dict:
        try:
            data = await self._lite_request(
                "/v7/send_mobile_code",
                method="POST",
                data={"businessid": 5, "mobile": str(phone), "plat": 3},
                base_url="http://login.user.kugou.com",
            )
            if data.get("status") == 1 or data.get("error_code") == 0:
                return {"success": True, "msg": "验证码已发送", "need_code": True}
            return {"success": False, "msg": data.get("error_msg") or data.get("msg", "发送失败")}
        except Exception as e:
            return {"success": False, "msg": f"发送验证码失败: {e}"}

    async def login_phone(self, phone: str, code: str = "") -> dict:
        if not code:
            return await self.send_phone_code(phone)

        try:
            date_time = int(time.time() * 1000)
            p2 = _rsa_encrypt_lite({"clienttime_ms": date_time, "code": code, "mobile": phone}).upper()

            data_map = {
                "plat": 1,
                "support_multi": 1,
                "t1": 0,
                "t2": 0,
                "clienttime_ms": date_time,
                "mobile": phone,
                "key": _sign_params_key(date_time),
                "p2": p2,
            }

            data = await self._lite_request(
                "/v6/login_by_verifycode",
                method="POST",
                data=data_map,
                x_router="login.user.kugou.com",
            )

            if data.get("status") == 1:
                d = data.get("data", {})
                self.logged_in = True
                self._token = d.get("token", "")
                self._userid = d.get("userid", 0)
                self._vip_token = d.get("vip_token", "")
                self._vip_type = d.get("vip_type", 0)
                self.cookies["token"] = self._token
                self.cookies["userid"] = str(self._userid)
                self.user_info = {"name": d.get("nickname", "酷狗用户"), "id": self._userid}
                self._persist_session()
                return {"success": True, "msg": "登录成功"}
            return {"success": False, "msg": data.get("error_msg") or data.get("msg", "登录失败")}
        except Exception as e:
            return {"success": False, "msg": f"登录失败: {e}"}

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> SearchResult:
        await self._register_device()

        try:
            result = await self._search_android(keyword, page, page_size)
            if result.songs:
                return result
        except Exception:
            pass

        return await self._search_web_fallback(keyword, page, page_size)

    async def _search_android(self, keyword: str, page: int, page_size: int) -> SearchResult:
        params = {
            "platform": "AndroidFilter",
            "keyword": keyword,
            "page": page,
            "pagesize": page_size,
            "category": 1,
        }
        data = await self._lite_request(
            "/v2/search/song",
            params=params,
            x_router="complexsearch.kugou.com",
        )

        songs = []
        total = 0
        song_data = data.get("data", {})
        if isinstance(song_data, dict):
            infos = song_data.get("infos", []) or song_data.get("lists", []) or []
            total = song_data.get("total", 0)
        else:
            infos = []

        for item in infos:
            song_hash = (item.get("FileHash", "") or item.get("hash", "")).lower()
            album_id = str(item.get("AlbumID", "") or item.get("album_id", ""))
            img_tpl = item.get("Image", "") or item.get("cover", "") or ""
            cover = _https_url(img_tpl.replace("{size}", "240") if img_tpl and "{size}" in img_tpl else img_tpl)
            duration = item.get("Duration", 0) or item.get("duration", 0) or 0
            if isinstance(duration, str):
                try:
                    duration = int(duration)
                except ValueError:
                    duration = 0

            song = Song(
                id=song_hash,
                name=(item.get("SongName", "") or item.get("songname", "") or item.get("name", "")).replace("<em>", "").replace("</em>", ""),
                artist=item.get("SingerName", "") or item.get("singername", "") or item.get("singer", ""),
                album=item.get("AlbumName", "") or item.get("album_name", "") or item.get("album", ""),
                cover=cover,
                platform="kugou",
                duration=duration,
                extra={
                    "hash": song_hash,
                    "album_id": album_id,
                    "sq_hash": (item.get("SQFileHash", "") or item.get("sqhash", "")).lower(),
                    "hq_hash": (item.get("HQFileHash", "") or item.get("hqhash", "") or item.get("320hash", "")).lower(),
                },
            )
            songs.append(song)

        return SearchResult(songs=songs, total=total, page=page)

    async def _search_web_fallback(self, keyword: str, page: int, page_size: int) -> SearchResult:
        client = httpx.AsyncClient(follow_redirects=True, timeout=15)
        try:
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
        except Exception:
            return SearchResult(songs=[], total=0, page=page)
        finally:
            await client.aclose()

        songs = []
        for item in data.get("data", {}).get("lists", []):
            img_tpl = item.get("Image", "")
            cover = _https_url(img_tpl.replace("{size}", "240") if img_tpl else "")
            song = Song(
                id=item.get("FileHash", ""),
                name=item.get("SongName", "").replace("<em>", "").replace("</em>", ""),
                artist=item.get("SingerName", ""),
                album=item.get("AlbumName", ""),
                cover=cover,
                platform="kugou",
                duration=item.get("HQDuration", 0) or item.get("Duration", 0),
                extra={
                    "hash": item.get("FileHash", "").lower(),
                    "album_id": item.get("AlbumID", ""),
                    "sq_hash": item.get("SQFileHash", "").lower(),
                    "hq_hash": item.get("HQFileHash", "").lower(),
                },
            )
            songs.append(song)

        return SearchResult(
            songs=songs,
            total=data.get("data", {}).get("total", 0),
            page=page,
        )

    async def get_play_url(self, song: Song) -> str:
        await self._register_device()
        song_hash = song.extra.get("hash", song.id).lower()
        album_id = int(song.extra.get("album_id", 0) or 0)

        try:
            url = await self._get_url_lite(song_hash, album_id)
            if url:
                return url
        except Exception:
            pass

        return await self._get_url_fallback(song_hash)

    async def _get_url_lite(self, song_hash: str, album_id: int, quality_value: int = 128) -> str:
        params = {
            "album_audio_id": 0,
            "area_code": 1,
            "hash": song_hash,
            "behavior": "play",
            "pid": 2,
            "cmd": 26,
            "version": 11709,
            "pidversion": 3001,
            "IsFreePart": 0,
            "album_id": album_id,
            "ssa_flag": "is_fromtrack",
            "page_id": 151369488,
            "quality": quality_value,
            "ppage_id": "463467626,350369493,788954147",
            "cdnBackup": 1,
            "kcard": 0,
            "module": "collection",
        }
        if self._vip_token:
            params["vip_token"] = self._vip_token
        if self._vip_type:
            params["vip"] = self._vip_type

        data = await self._lite_request(
            "/v5/url",
            params=params,
            x_router="tracker.kugou.com",
            sign=True,
            encrypt_key=True,
        )

        url = ""
        if isinstance(data, dict):
            raw_url = data.get("url", "") or ""
            if isinstance(raw_url, list):
                url = raw_url[0] if raw_url else ""
            else:
                url = raw_url
            if not url:
                inner = data.get("data")
                if isinstance(inner, dict):
                    raw_inner = inner.get("url", "") or inner.get("play_url", "") or ""
                    if isinstance(raw_inner, list):
                        url = raw_inner[0] if raw_inner else ""
                    else:
                        url = raw_inner
            if not url:
                backup = data.get("backup_url") or data.get("backupUrl", [])
                if isinstance(backup, list) and backup:
                    url = backup[0]
                elif isinstance(backup, str):
                    url = backup
        return url

    async def _get_url_fallback(self, song_hash: str) -> str:
        client = httpx.AsyncClient(follow_redirects=True, timeout=15)
        try:
            resp = await client.get(
                "https://m.kugou.com/app/i/getSongInfo.php",
                params={"cmd": "playInfo", "hash": song_hash},
                headers={"User-Agent": "Android511-AndroidPhone-8983-18-0-NetMusic-wifi"},
            )
            data = resp.json()
        except Exception:
            return ""
        finally:
            await client.aclose()

        url = data.get("url", "")
        if not url:
            backup = data.get("backup_url", "")
            if isinstance(backup, list) and backup:
                url = backup[0]
            elif isinstance(backup, str):
                url = backup
        return url

    @staticmethod
    def _valid_hash(h: str) -> bool:
        if not h:
            return False
        if set(h) <= {"0"}:
            return False
        if len(h) < 8:
            return False
        return True

    def _select_hash(self, song: Song, quality: str) -> tuple[str, int]:
        hq = (song.extra.get("hq_hash", "") or "").lower()
        sq = (song.extra.get("sq_hash", "") or "").lower()
        default = (song.extra.get("hash", "") or song.id).lower()
        if quality == "lossless" and self._valid_hash(sq):
            return sq, 4
        if quality == "lossless" and self._valid_hash(hq):
            return hq, 320
        if quality == "320" and self._valid_hash(hq):
            return hq, 320
        return default, 128

    def get_available_qualities(self, song: Song) -> list[dict]:
        qualities = [{"value": "128", "label": "标准 128k"}]
        if self._valid_hash((song.extra.get("hq_hash", "") or "").lower()):
            qualities.append({"value": "320", "label": "高品质 320k"})
        if self._valid_hash((song.extra.get("sq_hash", "") or "").lower()):
            qualities.append({"value": "lossless", "label": "无损 FLAC"})
        return qualities

    async def get_download_url(self, song: Song, quality: str = "320") -> str:
        await self._register_device()
        album_id = int(song.extra.get("album_id", 0) or 0)

        attempts = []
        h, q = self._select_hash(song, quality)
        attempts.append((h, q))
        if quality == "lossless":
            hq = (song.extra.get("hq_hash", "") or "").lower()
            if self._valid_hash(hq) and (hq, 320) not in attempts:
                attempts.append((hq, 320))
            default = (song.extra.get("hash", "") or song.id).lower()
            if self._valid_hash(default) and (default, 128) not in attempts:
                attempts.append((default, 128))

        for h, q in attempts:
            try:
                url = await self._get_url_lite(h, album_id, quality_value=q)
                if url:
                    return url
            except Exception:
                pass

        last_hash = attempts[0][0] if attempts else (song.extra.get("hash", "") or song.id).lower()
        return await self._get_url_fallback(last_hash)

    async def get_song_detail(self, song_id: str) -> Song:
        song_hash = song_id.lower()
        client = httpx.AsyncClient(follow_redirects=True, timeout=15)
        try:
            resp = await client.get(
                "https://m.kugou.com/app/i/getSongInfo.php",
                params={"cmd": "playInfo", "hash": song_hash},
                headers={"User-Agent": "Android511-AndroidPhone-8983-18-0-NetMusic-wifi"},
            )
            data = resp.json()
            if not (data.get("songName") or data.get("songname")):
                return None
            album_img = data.get("album_img", "") or ""
            cover = _https_url(album_img.replace("{size}", "240") if "{size}" in album_img else album_img)
            ext = data.get("extra", {}) or {}
            duration_ms = ext.get("128timelength", 0) or ext.get("320timelength", 0) or 0
            return Song(
                id=song_hash,
                name=data.get("songName", "") or data.get("songname", ""),
                artist=data.get("singerName", "") or data.get("singername", ""),
                album=data.get("albumName", "") or data.get("albumname", ""),
                cover=cover,
                platform="kugou",
                duration=int(duration_ms) // 1000 if duration_ms else 0,
                extra={
                    "hash": song_hash,
                    "album_id": str(data.get("albumid", "") or data.get("req_albumid", "")),
                    "sq_hash": (ext.get("sqhash", "") or "").lower(),
                    "hq_hash": (ext.get("320hash", "") or "").lower(),
                },
            )
        except Exception:
            return None
        finally:
            await client.aclose()

    # ── 歌单导入（概念版 API，参照 MakcRe/KuGouMusicApi）──

    @staticmethod
    def _parse_playlist_id(ref: str) -> str:
        """从酷狗歌单链接/ID 中提取歌单 ID（global_collection_id 或老版纯数字 ID）。"""
        ref = (ref or "").strip()
        if not ref:
            return ""
        # 纯 ID：collection_xxx 或纯数字
        if ref.startswith("collection_") or ref.isdigit():
            return ref
        # URL 参数：global_collection_id / global_specialid
        for key in ("global_collection_id", "global_specialid", "collection_id"):
            m = re.search(rf"[?&#]{key}=([A-Za-z0-9_]+)", ref)
            if m:
                return m.group(1)
        # PC 老歌单：/special/single/{id}.html
        m = re.search(r"/special/single/(\d+)\.html", ref)
        if m:
            return m.group(1)
        # 移动端歌单：m.kugou.com/songlist/gcid_xxx（gcid 后跟的 xxx 即歌单 ID）
        m = re.search(r"/songlist/gcid_([A-Za-z0-9_]+)", ref)
        if m:
            return m.group(1)
        return ""

    async def import_playlist(self, ref: str, page: int = 1, page_size: int = 30) -> dict:
        """导入酷狗歌单（分页），返回 {name, cover, creator, total, songs}。

        歌曲端点：GET /pubsongs/v2/get_other_list_file_nofilt（public 歌单无需登录）。
        短链（t1.kugou.com 分享链接）跟随重定向后从最终 URL 提取歌单 ID。
        """
        gid = self._parse_playlist_id(ref)
        if not gid and re.match(r"^(?:https?://|[\w-]+\.)", ref or ""):
            # 短链（t1.kugou.com 分享链接）跟随重定向后从最终 URL 提取歌单 ID；
            # 粘贴时可能省略协议头，自动补全
            url = ref if re.match(r"^https?://", ref) else "https://" + ref
            client = httpx.AsyncClient(follow_redirects=True, timeout=15)
            try:
                resp = await client.get(url, headers={"User-Agent": ANDROID_UA})
                gid = self._parse_playlist_id(str(resp.url))
            except Exception:
                pass
            finally:
                await client.aclose()
        if not gid:
            raise ValueError("未能识别酷狗歌单链接/ID")

        begin_idx = (page - 1) * page_size
        resp = await self._lite_request(
            "/pubsongs/v2/get_other_list_file_nofilt",
            params={
                "area_code": 1,
                "begin_idx": begin_idx,
                "plat": 1,
                "type": 1,
                "mode": 1,
                "personal_switch": 1,
                "extend_fields": "abtags,hot_cmt,popularization",
                "pagesize": page_size,
                "global_collection_id": gid,
            },
        )
        data = resp.get("data") or {}
        list_info = data.get("list_info") or {}
        total = int(list_info.get("count") or data.get("count") or 0)

        songs = []
        for f in data.get("songs") or []:
            if not isinstance(f, dict):
                continue
            song_hash = str(f.get("hash") or "").lower()
            if not song_hash:
                continue
            raw_name = str(f.get("name") or "")
            singer_name = str(f.get("remark") or "")
            singerinfo = f.get("singerinfo") or []
            if singerinfo and isinstance(singerinfo[0], dict):
                singer_name = singerinfo[0].get("name") or singer_name
            # 歌名常为 "歌手 - 歌名" 前缀格式（多歌手用顿号连接），去掉避免与歌手字段重复
            song_name = raw_name
            if " - " in raw_name:
                head, _, tail = raw_name.partition(" - ")
                if singer_name and singer_name in head:
                    song_name = tail
            # relate_goods 含各音质 hash：level 4=320k，level 5=无损
            hq_hash = sq_hash = ""
            for g in f.get("relate_goods") or []:
                if not isinstance(g, dict):
                    continue
                level = int(g.get("level") or 0)
                h = str(g.get("hash") or "").lower()
                if h and h != song_hash:
                    if level == 4 and not hq_hash:
                        hq_hash = h
                    elif level == 5 and not sq_hash:
                        sq_hash = h
            cover = str(f.get("cover") or "")
            songs.append(Song(
                id=song_hash,
                name=song_name,
                artist=singer_name,
                album=(f.get("albuminfo") or {}).get("name", "") if isinstance(f.get("albuminfo"), dict) else "",
                cover=_https_url(cover.replace("{size}", "240") if "{size}" in cover else cover),
                platform="kugou",
                duration=int(f.get("timelen") or 0) // 1000,
                extra={
                    "hash": song_hash,
                    "album_id": str(f.get("album_id") or ""),
                    "hq_hash": hq_hash,
                    "sq_hash": sq_hash,
                },
            ))

        pic = str(list_info.get("pic") or "")
        return {
            "name": str(list_info.get("name") or "") or f"酷狗歌单 {gid}",
            "cover": _https_url(pic.replace("{size}", "240") if "{size}" in pic else pic),
            "creator": str(list_info.get("list_create_username") or ""),
            "total": total,
            "songs": songs,
        }

    async def get_lyrics(self, song: Song) -> str:
        song_hash = (song.extra.get("hash", "") or song.id).lower()
        duration_ms = int((song.duration or 0) * 1000)
        keywords = [song.name]
        if song.artist and song.artist not in song.name:
            keywords.insert(0, f"{song.name} {song.artist}")

        for keyword in keywords:
            for attempt in range(2):
                try:
                    lrc = await self._fetch_kugou_lyrics(keyword, duration_ms, song_hash)
                    if lrc:
                        return lrc
                except Exception:
                    if attempt == 1:
                        break
        return ""

    async def _fetch_kugou_lyrics(self, keyword: str, duration_ms: int, song_hash: str) -> str:
        search_params = {
            "ver": 1,
            "man": "yes",
            "client": "pc",
            "keyword": keyword,
            "duration": str(duration_ms),
            "hash": song_hash,
        }
        client = httpx.AsyncClient(follow_redirects=True, timeout=15)
        try:
            resp = await client.get(
                "https://lyrics.kugou.com/search",
                params=search_params,
            )
            data = self._parse_kugou_json(resp.text)
        finally:
            await client.aclose()

        candidates = data.get("candidates") or []
        if isinstance(data.get("data"), dict):
            candidates = candidates or data["data"].get("candidates", [])
        if not candidates:
            return ""

        name_part = keyword.split()[0] if keyword else ""
        for candidate in candidates:
            if not self._candidate_matches(candidate, name_part, duration_ms):
                continue

            lyric_id = str(candidate.get("id", "") or candidate.get("download_id", "") or "")
            accesskey = candidate.get("accesskey", "")
            if not lyric_id or not accesskey:
                continue

            dl_client = httpx.AsyncClient(follow_redirects=True, timeout=15)
            try:
                resp2 = await dl_client.get(
                    "https://lyrics.kugou.com/download",
                    params={
                        "ver": 1,
                        "client": "pc",
                        "id": lyric_id,
                        "accesskey": accesskey,
                        "fmt": "lrc",
                        "charset": "utf8",
                    },
                )
                dl_data = self._parse_kugou_json(resp2.text)
            finally:
                await dl_client.aclose()

            content_b64 = dl_data.get("content", "")
            if not content_b64:
                continue
            try:
                return base64.b64decode(content_b64).decode("utf-8", errors="replace")
            except Exception:
                continue
        return ""

    @staticmethod
    def _candidate_matches(candidate: dict, song_name: str, duration_ms: int) -> bool:
        c_song = candidate.get("song", "").lower()
        name_lower = song_name.lower()

        if name_lower and c_song:
            if name_lower in c_song or c_song in name_lower:
                return True
            c_words = [w for w in re.split(r'[\s\-()（）:：·/、,，。]', c_song) if len(w) >= 2]
            if any(w in name_lower for w in c_words):
                return True
        else:
            return True

        c_dur = candidate.get("duration", 0) or 0
        if c_dur and duration_ms:
            if abs(c_dur - duration_ms) < 8000:
                return True

        return False

    @staticmethod
    def _parse_kugou_json(text: str) -> dict:
        text = text.strip()
        if not text:
            return {}
        m = re.match(r"^\w+\((.+)\);?$", text, re.S)
        if m:
            text = m.group(1)
        try:
            return json.loads(text)
        except Exception:
            return {}
