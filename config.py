import os
import sys
import argparse
import configparser

IS_FROZEN = getattr(sys, 'frozen', False)

BASE_DIR = sys._MEIPASS if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))
PERSIST_DIR = os.path.dirname(sys.executable) if IS_FROZEN else os.path.dirname(os.path.abspath(__file__))

# ── 基础配置 ──（改配置直接改这里，不修改即默认值；命令行参数可覆盖 host/port/password/https/ssl）
CONFIG_INI = "config.ini"            # 可选配置文件（位于程序目录，需手动创建，程序不会自动生成）：
                                    # 优先级 命令行参数 > config.ini > config.py；键名 = 下方常量名（不区分大小写）
DEBUG = False                        # 调试日志开关：开启后输出 INFO+/DEBUG+ 调试日志（关闭时仅 WARNING+）
HOST = "0.0.0.0"                    # 监听地址
PORT = 8000                         # 监听端口
PASSWORD = "musiccatch"             # 访问密码（保护登录等敏感接口），空字符串表示不启用；
                                    # 支持 $sha256$<salt>$<hexdigest> 哈希格式（密码不以明文落盘）
HTTPS = False                       # 以 HTTPS 对外提供服务（TLS 在反向代理层终止时设为 true）：
                                    # 影响鉴权 cookie 的 Secure 标记，并信任代理转发头（X-Forwarded-Proto 等）
SSL = False                         # 由本程序直接加载证书提供 HTTPS（不经反向代理时使用）
SSL_CERTFILE = "cert.pem"           # SSL 证书文件路径
SSL_KEYFILE = "key.pem"             # SSL 私钥文件路径
FORWARDED_ALLOW_IPS = "127.0.0.1"   # https 模式下可信代理 IP 白名单（逗号分隔）：
                                    # 仅信任这些 IP 提供的 X-Forwarded-For/Proto，防止伪造 IP 绕过限速；
                                    # 默认 127.0.0.1（Nginx 与后端同机），不同机请改为 Nginx 服务器 IP
VIDEO_PLAYBACK_ENABLED = False      # 是否支持视频播放（B 站）：关闭后 B 站仅播放/下载音频


def _finalize_password(value: str) -> tuple[str, str | None]:
    """解析密码配置：支持明文或 $sha256$<salt>$<hexdigest> 哈希格式（避免明文落盘）。

    返回 (原始值, 哈希元组)；哈希模式下原始值保留为哨兵（非空，密码保护照常启用）。
    """
    if isinstance(value, str) and value.startswith("$sha256$"):
        parts = value.split("$")
        if len(parts) == 4 and parts[1] == "sha256":
            return value, (parts[2], parts[3])
    return value, None


# 密码哈希派生（PASSWORD 支持明文或哈希格式；parse_args 按命令行参数重新派生）
PASSWORD_HASH = _finalize_password(PASSWORD)[1]


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

# ── 一起听歌 ──（改配置直接改这里，不修改即默认值）
LT_TRANSPORT = "http"              # 传输方式："http"（长轮询，兼容不支持 WebSocket 的 CDN）或 "ws"（低延迟推送），全局统一
LT_WS_URL = ""                     # WebSocket 连接地址覆盖（默认空=从当前域名连接）：
                                   # 配置为完整 WS 地址（如 wss://ws.example.com/api/listen-together/ws）
                                   # 时，前端 WS 改从该地址连接（WS 与 HTTP 走不同入口/CDN 的场景）
LT_ROOM_COUNT = 10                 # 常驻房间数（房间始终存在，空房恢复默认名"x号房"）
LT_QUEUE_MAX = 100                 # 单房间播放队列上限（防内存滥用）
LT_NAME_MAX_LEN = 20               # 用户名 / 自定义房间名最大长度（前端提示/输入框上限统一跟随此值）
LT_NAME_TTL = 600                  # 用户名活动记录宽限（秒）：停止活动超时清除（名字不占用，可随时再次使用）
LT_RENAME_DAILY_LIMIT = 1          # 已废弃（改名无次数限制，保留仅为兼容）
LT_ROOMS_REFRESH = 10000           # 房间列表自动刷新间隔（毫秒）
LT_SYNC_INTERVAL = 5000            # 房主播放位置同步上报间隔（毫秒）
LT_POLL_TIMEOUT = 20               # 长轮询最长挂起（秒）：状态无变化时超时返回，客户端立即续接
LT_MEMBER_TTL = 90                 # 成员离线判定（秒）：停止轮询超时视为离开（离开接口+此兜底）
LT_CACHE_MARGIN = 300              # 房间播放缓存余量（秒）：同房间多人听同一首歌复用播放地址；
                                   # 播放中每次状态变更续期，切歌/停止后超过此时长自动删除（默认 5 分钟）
LT_ACTION_RATE_MAX = 60            # 已废弃（动作已无限速，保留仅为兼容）


# 请求体（JSON 等）大小上限：防超大包内存耗尽（DoS），超过直接 413
MAX_BODY_SIZE = 1048576

def _split_csv(value: str) -> tuple[str, ...]:
    """逗号分隔字符串 → 元组（去空白、忽略空项），用于域名/端口白名单等。"""
    return tuple(x.strip() for x in value.split(",") if x.strip())


def _split_csv_int(value: str) -> tuple[int, ...]:
    """逗号分隔数字字符串 → int 元组。"""
    return tuple(int(x.strip()) for x in value.split(",") if x.strip())


def _parse_referer_map(value: str) -> tuple[tuple[str, str], ...]:
    """解析防盗链 Referer 映射："域名=Referer" 逗号分隔 → ((域名, Referer), ...)。"""
    out = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise argparse.ArgumentTypeError(f"无效的 Referer 映射项 {part!r}（应为 域名=Referer）")
        suffix, referer = part.split("=", 1)
        out.append((suffix.strip(), referer.strip()))
    return tuple(out)


# 字符串类型的转换器（int/float/str/bool 直接用内建类型）
_CONVERSIONS = {
    "csv": _split_csv,
    "csv_int": _split_csv_int,
    "referer": _parse_referer_map,
}

# (命令行参数名, config 常量名, 类型, 帮助文本)
# 类型：str/int/float/bool（bool 自动生成 --xxx / --no-xxx 对）、csv / csv_int / referer
_ARG_SPECS = (
    # ── 基础配置 ──
    ("debug", "DEBUG", bool, f"调试日志开关（开启输出 INFO+ 调试日志，关闭仅 WARNING+）(默认: {DEBUG})"),
    ("host", "HOST", str, f"监听地址 (默认: {HOST})"),
    ("port", "PORT", int, f"监听端口 (默认: {PORT})"),
    ("password", "PASSWORD", str, f"访问密码，保护登录等敏感接口，空字符串表示不启用 (默认: {PASSWORD})"),
    ("https", "HTTPS", bool, "以 HTTPS 对外提供服务（TLS 在反向代理层终止时使用）"),
    ("ssl", "SSL", bool, "由本程序直接加载证书提供 HTTPS"),
    ("ssl-certfile", "SSL_CERTFILE", str, f"SSL 证书文件路径 (默认: {SSL_CERTFILE})"),
    ("ssl-keyfile", "SSL_KEYFILE", str, f"SSL 私钥文件路径 (默认: {SSL_KEYFILE})"),
    ("forwarded-allow-ips", "FORWARDED_ALLOW_IPS", str, f"https 模式下可信代理 IP 白名单（逗号分隔）(默认: {FORWARDED_ALLOW_IPS})"),
    ("video-playback", "VIDEO_PLAYBACK_ENABLED", bool, "是否支持视频播放（B 站）"),
    # ── 速率限制 ──
    ("rate-max", "RATE_MAX", int, f"每 IP 每分钟最多请求数（gate 注册）(默认: {RATE_MAX})"),
    ("rate-window", "RATE_WINDOW", int, f"速率限制窗口（秒）(默认: {RATE_WINDOW})"),
    ("api-rate-max", "API_RATE_MAX", int, f"普通 API 每 IP 每分钟上限 (默认: {API_RATE_MAX})"),
    ("stream-rate-max", "STREAM_RATE_MAX", int, f"流式端点（proxy/download）限速上限 (默认: {STREAM_RATE_MAX})"),
    ("heartbeat-rate-max", "HEARTBEAT_RATE_MAX", int, f"gate 心跳限速 (默认: {HEARTBEAT_RATE_MAX})"),
    ("auth-verify-rate-max", "AUTH_VERIFY_RATE_MAX", int, f"密码验证限速（防爆破）(默认: {AUTH_VERIFY_RATE_MAX})"),
    # ── 代理 URL 白名单（防 SSRF）──
    ("allowed-proxy-domains", "ALLOWED_PROXY_DOMAINS", "csv", "代理允许的域名后缀（逗号分隔）"),
    ("allowed-proxy-ports", "ALLOWED_PROXY_PORTS", "csv_int", "代理允许的端口（逗号分隔）"),
    ("proxy-max-redirects", "PROXY_MAX_REDIRECTS", int, f"代理最大重定向跳数 (默认: {PROXY_MAX_REDIRECTS})"),
    ("proxy-referer-map", "PROXY_REFERER_MAP", "referer", '防盗链 Referer 映射："域名=Referer" 逗号分隔（覆盖默认表）'),
    # ── 认证 Cookie ──
    ("auth-cookie-name", "AUTH_COOKIE_NAME", str, f"认证 Cookie 名称 (默认: {AUTH_COOKIE_NAME})"),
    ("auth-cookie-max-age", "AUTH_COOKIE_MAX_AGE", int, f"认证 Cookie 有效期（秒）(默认: {AUTH_COOKIE_MAX_AGE})"),
    # ── 打包模式 ──
    ("frozen-browser-open-delay", "FROZEN_BROWSER_OPEN_DELAY", float, f"打包启动后延迟打开浏览器（秒）(默认: {FROZEN_BROWSER_OPEN_DELAY})"),
    # ── 浏览器门禁 Token ──
    ("gate-token-ttl", "GATE_TOKEN_TTL", int, f"门禁验证通过后有效时长（秒），滑动续期 (默认: {GATE_TOKEN_TTL})"),
    ("gate-pending-ttl", "GATE_PENDING_TTL", int, f"门禁注册后待验证时长（秒）(默认: {GATE_PENDING_TTL})"),
    ("gate-script-ttl", "GATE_SCRIPT_TTL", int, f"挑战页脚本 token 有效期（秒）(默认: {GATE_SCRIPT_TTL})"),
    ("gate-cookie-name", "GATE_COOKIE_NAME", str, f"门禁 Cookie 名称 (默认: {GATE_COOKIE_NAME})"),
    ("gate-cookie-max-age", "GATE_COOKIE_MAX_AGE", int, f"门禁 Cookie 有效期（秒）(默认: {GATE_COOKIE_MAX_AGE})"),
    ("gate-heartbeat-interval", "GATE_HEARTBEAT_INTERVAL", int, f"门禁心跳间隔（毫秒）(默认: {GATE_HEARTBEAT_INTERVAL})"),
    ("gate-reload-timeout", "GATE_RELOAD_TIMEOUT", int, f"门禁注册失败重试延迟（毫秒）(默认: {GATE_RELOAD_TIMEOUT})"),
    ("gate-reload-delay", "GATE_RELOAD_DELAY", int, f"门禁注册成功后刷新前等待（毫秒）(默认: {GATE_RELOAD_DELAY})"),
    # ── 反 F12 检测阈值 ──
    ("af12-threshold-min", "AF12_THRESHOLD_MIN", int, f"窗口尺寸差异阈值下限（px）(默认: {AF12_THRESHOLD_MIN})"),
    ("af12-threshold-max", "AF12_THRESHOLD_MAX", int, f"窗口尺寸差异阈值上限（px）(默认: {AF12_THRESHOLD_MAX})"),
    ("af12-interval-min", "AF12_INTERVAL_MIN", int, f"尺寸检测间隔下限（毫秒）(默认: {AF12_INTERVAL_MIN})"),
    ("af12-interval-max", "AF12_INTERVAL_MAX", int, f"尺寸检测间隔上限（毫秒）(默认: {AF12_INTERVAL_MAX})"),
    ("af12-debug-interval-min", "AF12_DEBUG_INTERVAL_MIN", int, f"debugger 检测间隔下限（毫秒）(默认: {AF12_DEBUG_INTERVAL_MIN})"),
    ("af12-debug-interval-max", "AF12_DEBUG_INTERVAL_MAX", int, f"debugger 检测间隔上限（毫秒）(默认: {AF12_DEBUG_INTERVAL_MAX})"),
    ("af12-debug-delay-threshold", "AF12_DEBUG_DELAY_THRESHOLD", int, f"debugger 断点判定阈值（毫秒）(默认: {AF12_DEBUG_DELAY_THRESHOLD})"),
    ("af12-debug-mode", "AF12_DEBUG_MODE", bool, "反 F12 调试模式（销毁动作改为 debugger + 日志）"),
    ("af12-resize-debounce", "AF12_RESIZE_DEBOUNCE", int, f"resize 防抖延迟（毫秒）(默认: {AF12_RESIZE_DEBOUNCE})"),
    # ── 下载/代理 HTTP 客户端 ──
    ("http-user-agent", "HTTP_USER_AGENT", str, "HTTP 客户端 User-Agent"),
    ("download-timeout-connect", "DOWNLOAD_TIMEOUT_CONNECT", int, f"建立连接超时（秒）(默认: {DOWNLOAD_TIMEOUT_CONNECT})"),
    ("download-timeout-read", "DOWNLOAD_TIMEOUT_READ", int, f"流式读取超时（秒）(默认: {DOWNLOAD_TIMEOUT_READ})"),
    ("head-timeout-read", "HEAD_TIMEOUT_READ", int, f"HEAD 请求读取超时（秒）(默认: {HEAD_TIMEOUT_READ})"),
    ("proxy-chunk-size", "PROXY_CHUNK_SIZE", int, f"代理流式传输块大小（字节）(默认: {PROXY_CHUNK_SIZE})"),
    # ── 一起听歌 ──
    ("lt-transport", "LT_TRANSPORT", str, f'传输方式："http"（长轮询）或 "ws"（WebSocket）(默认: {LT_TRANSPORT})'),
    ("lt-ws-url", "LT_WS_URL", str, f"WebSocket 连接地址覆盖（完整 WS 地址，空=当前域名）(默认: {LT_WS_URL or '空'})"),
    ("lt-room-count", "LT_ROOM_COUNT", int, f"常驻房间数 (默认: {LT_ROOM_COUNT})"),
    ("lt-queue-max", "LT_QUEUE_MAX", int, f"单房间播放队列上限（防内存滥用）(默认: {LT_QUEUE_MAX})"),
    ("lt-name-max-len", "LT_NAME_MAX_LEN", int, f"用户名 / 自定义房间名最大长度 (默认: {LT_NAME_MAX_LEN})"),
    ("lt-name-ttl", "LT_NAME_TTL", int, f"用户名活动记录宽限（秒）(默认: {LT_NAME_TTL})"),
    ("lt-rooms-refresh", "LT_ROOMS_REFRESH", int, f"房间列表自动刷新间隔（毫秒）(默认: {LT_ROOMS_REFRESH})"),
    ("lt-sync-interval", "LT_SYNC_INTERVAL", int, f"房主播放位置同步上报间隔（毫秒）(默认: {LT_SYNC_INTERVAL})"),
    ("lt-poll-timeout", "LT_POLL_TIMEOUT", int, f"长轮询最长挂起（秒）(默认: {LT_POLL_TIMEOUT})"),
    ("lt-member-ttl", "LT_MEMBER_TTL", int, f"成员离线判定（秒）(默认: {LT_MEMBER_TTL})"),
    ("lt-cache-margin", "LT_CACHE_MARGIN", int, f"房间播放缓存余量（秒），切歌/停止后自动删除 (默认: {LT_CACHE_MARGIN})"),
    # ── 请求体 ──
    ("max-body-size", "MAX_BODY_SIZE", int, f"请求体（JSON 等）大小上限（字节）(默认: {MAX_BODY_SIZE})"),
)


def _ini_get(cp: configparser.ConfigParser, key: str, typ) -> object:
    """从 config.ini 读取键值（不区分大小写，任意 section 均可，优先 [DEFAULT]）。

    类型与 _ARG_SPECS 一致：bool 支持 true/false/yes/no/on/off/1/0（configparser 语法），
    csv / referer 与命令行格式相同。值无效时打印警告并忽略该项（保持默认）。
    """
    for section in ("DEFAULT", *cp.sections()):
        if not cp.has_option(section, key):
            continue
        raw = cp.get(section, key)
        try:
            if typ is bool:
                return cp.getboolean(section, key)
            if typ is int:
                return int(raw)
            if typ is float:
                return float(raw)
            if typ is str:
                return raw
            conv = _CONVERSIONS.get(typ)
            if conv is not None:
                return conv(raw)
            return raw  # 未知类型原样返回
        except (ValueError, argparse.ArgumentTypeError) as e:
            print(f"[警告] config.ini 中 {key} 的值无效（{raw!r}）：{e}，已忽略该项")
            return None
    return None


def _apply_ini(namespace: dict) -> None:
    """读取 config.ini 覆盖 config.py 默认值（文件需手动创建，不存在时静默跳过）。

    优先级：命令行参数 > config.ini > config.py。
    键名 = 下方常量名（不区分大小写，如 port / PORT / lt_transport 均可），
    未列出的配置项保持 config.py 默认值。幂等，可重复调用。
    """
    path = os.path.join(BASE_DIR, CONFIG_INI)
    if not os.path.isfile(path):
        return
    cp = configparser.ConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except Exception as e:
        print(f"[警告] config.ini 读取失败（{e}），已忽略该文件")
        return
    loaded = []
    for _arg_name, var_name, typ, _help in _ARG_SPECS:
        value = _ini_get(cp, var_name, typ)
        if value is not None:
            namespace[var_name] = value
            loaded.append(var_name)
    if loaded:
        print(f"[配置] 已从 config.ini 加载 {len(loaded)} 项：{', '.join(loaded)}")


# config.ini 覆盖 config.py 默认值（模块加载即生效，uvicorn main:app 导入方式同样支持）；
# 命令行优先级更高，parse_args 里会在命令行覆盖前再次应用（幂等）
_apply_ini(globals())
# ini 可能改了 PASSWORD：重新派生密码哈希（命令行覆盖后 parse_args 也会再派生一次）
globals()["PASSWORD_HASH"] = _finalize_password(globals()["PASSWORD"])[1]


def parse_args():
    """解析命令行参数并覆盖 config.py 顶部常量（未指定的保持默认值）。

    每个可配置常量都有对应 --xxx 参数（bool 另有 --no-xxx 关闭），完整列表见 --help。
    配置优先级：命令行参数 > config.ini > config.py。
    """
    help_text = f"""\
Music Catch - 多平台音乐搜索、播放与下载工具

配置方式（优先级从高到低）:
  1. 命令行参数（--xxx / --no-xxx，完整列表见下方参数说明）
  2. config.ini（程序目录下手动创建，键名 = config.py 常量名，不区分大小写）
  3. config.py 顶部常量（不修改即默认值）
全部可配置常量均有对应 --xxx 参数（bool 常量可用 --no-xxx 关闭）。

常用示例:
  MusicCatch                          使用默认配置启动
  MusicCatch --port 9000              命令行指定端口
  MusicCatch --host 127.0.0.1 --port 3000  命令行指定地址和端口
  MusicCatch --password abc123        启用访问密码
  MusicCatch --https                  反向代理 HTTPS 模式
  MusicCatch --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem  本地证书 HTTPS
  MusicCatch --lt-transport ws        一起听歌切换 WebSocket 低延迟推送
"""
    parser = argparse.ArgumentParser(
        description=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    for arg_name, var_name, typ, help_str in _ARG_SPECS:
        dest = arg_name.replace("-", "_")
        if typ is bool:
            parser.add_argument(f"--{arg_name}", dest=dest, action="store_true",
                                default=None, help=help_str)
            parser.add_argument(f"--no-{arg_name}", dest=dest, action="store_false",
                                help=f"关闭 {var_name}（覆盖 config.py 中的 True 值）")
        else:
            conv = _CONVERSIONS.get(typ, typ)
            parser.add_argument(f"--{arg_name}", dest=dest, type=conv,
                                default=None, help=help_str)
    cli = parser.parse_args()

    _apply_ini(globals())  # config.ini 覆盖 config.py 默认值（模块加载时已应用，幂等）
    # 命令行参数覆盖 config 常量（未指定的保持 ini/config.py 的值）
    for arg_name, var_name, _typ, _help in _ARG_SPECS:
        value = getattr(cli, arg_name.replace("-", "_"))
        if value is not None:
            globals()[var_name] = value
    # PASSWORD_HASH 是 PASSWORD 的派生值：始终随 PASSWORD 重新派生（含命令行覆盖后）
    globals()["PASSWORD_HASH"] = _finalize_password(globals()["PASSWORD"])[1]
    # 返回的 Namespace 同步为最终生效值（未指定参数的取 config 默认，供 main.py 直接使用）
    for arg_name, var_name, _typ, _help in _ARG_SPECS:
        setattr(cli, arg_name.replace("-", "_"), globals()[var_name])
    return cli
