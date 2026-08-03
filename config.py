import os
import sys
import argparse
import configparser

IS_FROZEN = getattr(sys, 'frozen', False)

BASE_DIR = sys._MEIPASS if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))
PERSIST_DIR = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))

_DEFAULTS = {
    "host": "0.0.0.0",
    "port": 8000,
    "password": "musiccatch",
    "https": False,
    "ssl": False,
    "ssl_certfile": "cert.pem",
    "ssl_keyfile": "key.pem",
    "forwarded_allow_ips": "127.0.0.1",  # https 模式可信代理 IP 白名单（逗号分隔）
    "video_playback": False,              # 是否支持视频播放（B 站），关闭后仅播放音频
}

# ── 速率限制 ──
RATE_MAX = 5             # 每 IP 每分钟最多请求数（gate 注册）
RATE_WINDOW = 60         # 速率限制窗口（秒）
API_RATE_MAX = 60        # 普通 API 每 IP 每分钟上限（token 校验通过后仍限速）
STREAM_RATE_MAX = 600    # 流式端点（proxy/download）放宽，避免误伤视频播放
HEARTBEAT_RATE_MAX = 60  # gate 心跳限速（正常浏览器约 6 次/分钟，多标签页留余量）
AUTH_VERIFY_RATE_MAX = 10  # 密码验证限速（防爆破，正常用户每次输入只提交 1 次）

# ── 代理 URL 白名单（防 SSRF）──
# 仅允许音乐平台官方域名；IP 直连 / 仿冒域名 / 内网地址一律拒绝
ALLOWED_PROXY_DOMAINS = (
    "163.com",      # 网易云音乐主站
    "126.net",      # 网易云音乐 CDN（m*.music.126.net）
    "kugou.com",    # 酷狗主站/CDN
    "bilibili.com", # B 站主站/接口
    "bilivideo.com",# B 站视频 CDN
    "hdslb.com",    # B 站静态资源/CDN
    "akamaized.net",# B 站 Akamai 镜像源
)
ALLOWED_PROXY_PORTS = (80, 443)      # 代理允许的端口
PROXY_MAX_REDIRECTS = 3              # 代理最大重定向跳数（每跳重新校验）
# 域名后缀 → 防盗链 Referer 映射（顺序匹配）
PROXY_REFERER_MAP = (
    ("163.com", "https://music.163.com/"),
    ("126.net", "https://music.163.com/"),
    ("kugou.com", "https://www.kugou.com/"),
    ("bilibili.com", "https://www.bilibili.com/"),
    ("bilivideo.com", "https://www.bilibili.com/"),
    ("hdslb.com", "https://www.bilibili.com/"),
    ("akamaized.net", "https://www.bilibili.com/"),
)

# ── 认证 Cookie ──
AUTH_COOKIE_NAME = "mc_auth"
AUTH_COOKIE_MAX_AGE = 7 * 86400  # 7 天

# ── 打包模式 ──
FROZEN_BROWSER_OPEN_DELAY = 1.5  # 启动后延迟打开浏览器（秒）

# ── 浏览器门禁 Token ──
GATE_TOKEN_TTL = 15                # 验证通过后有效时长（秒）；滑动续期：每次请求/心跳都会重置
GATE_PENDING_TTL = 3               # 注册后待验证时长（秒）
GATE_SCRIPT_TTL = 3                # 挑战页脚本 token 有效期（秒）
GATE_COOKIE_NAME = "mc_gate"       # 门禁 Cookie 名称
GATE_COOKIE_MAX_AGE = 86400        # 门禁 Cookie 有效期（秒）
GATE_HEARTBEAT_INTERVAL = 10000    # 心跳间隔（毫秒）
GATE_RELOAD_TIMEOUT = 500          # 注册失败重试延迟（毫秒）
GATE_RELOAD_DELAY = 1000           # 注册成功后刷新前等待（毫秒）

# ── 反 F12 检测阈值 ──
AF12_THRESHOLD_MIN = 140           # 窗口尺寸差异阈值下限（px）
AF12_THRESHOLD_MAX = 180           # 窗口尺寸差异阈值上限（px）
AF12_INTERVAL_MIN = 800            # 尺寸检测间隔下限（毫秒）
AF12_INTERVAL_MAX = 1200           # 尺寸检测间隔上限（毫秒）
AF12_DEBUG_INTERVAL_MIN = 1800     # debugger 检测间隔下限（毫秒）
AF12_DEBUG_INTERVAL_MAX = 3200     # debugger 检测间隔上限（毫秒）
AF12_DEBUG_DELAY_THRESHOLD = 100   # debugger 断点判定阈值（毫秒）
AF12_DEBUG_MODE = False            # 调试模式：销毁动作改为 debugger + 日志（定位误杀用），定位后置 False 恢复硬销毁
AF12_RESIZE_DEBOUNCE = 300         # resize 防抖延迟（毫秒）

# ── 下载/代理 HTTP 客户端 ──
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
DOWNLOAD_TIMEOUT_CONNECT = 30   # 建立连接超时（秒）
DOWNLOAD_TIMEOUT_READ = 300     # 流式读取超时（秒）
HEAD_TIMEOUT_READ = 30          # HEAD 请求读取超时（秒）
PROXY_CHUNK_SIZE = 65536        # 代理流式传输块大小（字节）


def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "on")


def _read_ini_section() -> dict:
    ini = configparser.ConfigParser()
    ini_path = os.path.join(PERSIST_DIR, "config.ini")
    if os.path.exists(ini_path):
        try:
            ini.read(ini_path, encoding="utf-8")
            if ini.has_section("server"):
                return dict(ini["server"])
        except Exception:
            pass
    return {}


# 模块加载时从 config.ini 读取初始值，parse_args() 可被命令行参数覆盖
def _finalize_password(value: str) -> tuple[str, str | None]:
    """解析密码配置：支持明文或 $sha256$<salt>$<hexdigest> 哈希格式（避免明文落盘）。

    返回 (原始值, 哈希元组)；哈希模式下原始值保留为哨兵（非空，密码保护照常启用）。
    """
    if isinstance(value, str) and value.startswith("$sha256$"):
        parts = value.split("$")
        if len(parts) == 4 and parts[1] == "sha256":
            return value, (parts[2], parts[3])
    return value, None


_ini = _read_ini_section()

# 访问密码（保护登录等敏感接口），空字符串表示不启用。
# 支持两种格式：明文（如 1145）或 $sha256$<salt>$<hexdigest>（密码不以明文落盘）。
PASSWORD, PASSWORD_HASH = _finalize_password(_ini.get("password", _DEFAULTS["password"]))
# 是否以 HTTPS 对外提供服务（TLS 在反向代理层终止时设为 true）：
# 影响鉴权 cookie 的 Secure 标记，并信任代理转发头（X-Forwarded-Proto 等）
HTTPS = _to_bool(_ini.get("https", _DEFAULTS["https"]))
# 是否由本程序直接加载证书提供 HTTPS（不经反向代理时使用）
SSL = _to_bool(_ini.get("ssl", _DEFAULTS["ssl"]))
SSL_CERTFILE = _ini.get("ssl_certfile", _DEFAULTS["ssl_certfile"])
SSL_KEYFILE = _ini.get("ssl_keyfile", _DEFAULTS["ssl_keyfile"])
# https 模式下信任转发头的代理 IP 白名单：仅信任这些 IP 提供的 X-Forwarded-For/Proto，
# 防止攻击者伪造 IP 绕过速率限制与 token 指纹绑定（若 Nginx 与后端不同机，请改为 Nginx 服务器 IP）
FORWARDED_ALLOW_IPS = _ini.get("forwarded_allow_ips", _DEFAULTS["forwarded_allow_ips"])

# 请求体（JSON 等）大小上限：防超大包内存耗尽（DoS），超过直接 413
MAX_BODY_SIZE = 1048576

# ── 视频播放 ──
# 是否支持视频播放（B 站）：关闭后 B 站仅播放/下载音频，视频流接口停用
VIDEO_PLAYBACK_ENABLED = _to_bool(_ini.get("video_playback", _DEFAULTS["video_playback"]))

def parse_args():
    ini = configparser.ConfigParser()
    ini_path = os.path.join(PERSIST_DIR, "config.ini")
    if os.path.exists(ini_path):
        ini.read(ini_path, encoding="utf-8")

    section = ini["server"] if ini.has_section("server") else {}

    help_text = f"""\
Music Catch - 多平台音乐搜索、播放与下载工具

配置优先级: 命令行参数 > config.ini > 默认值

配置文件: 在程序同级目录下创建 config.ini，格式如下:

  [server]
  host = 0.0.0.0
  port = 8000
  password = 你的访问密码
  https = false
  ssl = false
  ssl_certfile = cert.pem
  ssl_keyfile = key.pem
  forwarded_allow_ips = 127.0.0.1
  video_playback = true

password 用于保护登录等敏感接口，不配置则不启用密码验证。
https    以 HTTPS 对外提供服务（TLS 在反向代理层终止时设为 true，
         本程序仍监听 HTTP，但会信任代理转发头并为 cookie 加 Secure 标记）
ssl      由本程序直接加载证书提供 HTTPS（不经反向代理时使用，
         需配合 ssl_certfile / ssl_keyfile 指定证书和私钥路径）
forwarded_allow_ips  https 模式下可信代理 IP 白名单（逗号分隔），
         仅信任这些 IP 提供的 X-Forwarded-For/Proto，防止伪造 IP 绕过限速；
         默认 127.0.0.1（Nginx 与后端同机），不同机请改为 Nginx 服务器 IP
video_playback  是否支持视频播放（默认 true）：设为 false 后 B 站只播放
         音频，视频播放/下载接口停用

示例:
  MusicCatch                          使用默认配置启动
  MusicCatch --port 9000              命令行指定端口
  MusicCatch --host 127.0.0.1 --port 3000  命令行指定地址和端口
  MusicCatch --password abc123        启用访问密码
  MusicCatch --https                  反向代理 HTTPS 模式
  MusicCatch --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem  本地证书 HTTPS
"""

    parser = argparse.ArgumentParser(
        description=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=None, help=f"监听地址 (默认: {_DEFAULTS['host']})")
    parser.add_argument("--port", type=int, default=None, help=f"监听端口 (默认: {_DEFAULTS['port']})")
    parser.add_argument("--password", default=None, help="访问密码，保护登录等敏感接口 (默认不启用)")
    parser.add_argument("--https", action="store_true", default=None, help="以 HTTPS 对外提供服务（反向代理终止 TLS 模式）")
    parser.add_argument("--ssl", action="store_true", default=None, help="由本程序直接加载证书提供 HTTPS")
    parser.add_argument("--ssl-certfile", default=None, help=f"SSL 证书文件路径 (默认: {_DEFAULTS['ssl_certfile']})")
    parser.add_argument("--ssl-keyfile", default=None, help=f"SSL 私钥文件路径 (默认: {_DEFAULTS['ssl_keyfile']})")
    cli = parser.parse_args()

    host = cli.host or section.get("host", _DEFAULTS["host"])
    port = cli.port if cli.port is not None else int(section.get("port", _DEFAULTS["port"]))
    password = cli.password if cli.password is not None else section.get("password", _DEFAULTS["password"])
    https = cli.https if cli.https is not None else _to_bool(section.get("https", _DEFAULTS["https"]))
    ssl = cli.ssl if cli.ssl is not None else _to_bool(section.get("ssl", _DEFAULTS["ssl"]))
    ssl_certfile = cli.ssl_certfile or section.get("ssl_certfile", _DEFAULTS["ssl_certfile"])
    ssl_keyfile = cli.ssl_keyfile or section.get("ssl_keyfile", _DEFAULTS["ssl_keyfile"])

    global PASSWORD, PASSWORD_HASH, HTTPS, SSL, SSL_CERTFILE, SSL_KEYFILE
    PASSWORD, PASSWORD_HASH = _finalize_password(password)
    HTTPS = https
    SSL = ssl
    SSL_CERTFILE = ssl_certfile
    SSL_KEYFILE = ssl_keyfile

    return argparse.Namespace(
        host=host, port=port, password=password,
        https=https, ssl=ssl, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
    )
