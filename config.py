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
    "password": "1145",
    "https": False,
    "ssl": False,
    "ssl_certfile": "cert.pem",
    "ssl_keyfile": "key.pem",
}


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
_ini = _read_ini_section()

# 访问密码（保护登录等敏感接口），空字符串表示不启用
PASSWORD = _ini.get("password", _DEFAULTS["password"])
# 是否以 HTTPS 对外提供服务（TLS 在反向代理层终止时设为 true）：
# 影响鉴权 cookie 的 Secure 标记，并信任代理转发头（X-Forwarded-Proto 等）
HTTPS = _to_bool(_ini.get("https", _DEFAULTS["https"]))
# 是否由本程序直接加载证书提供 HTTPS（不经反向代理时使用）
SSL = _to_bool(_ini.get("ssl", _DEFAULTS["ssl"]))
SSL_CERTFILE = _ini.get("ssl_certfile", _DEFAULTS["ssl_certfile"])
SSL_KEYFILE = _ini.get("ssl_keyfile", _DEFAULTS["ssl_keyfile"])


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

password 用于保护登录等敏感接口，不配置则不启用密码验证。
https    以 HTTPS 对外提供服务（TLS 在反向代理层终止时设为 true，
         本程序仍监听 HTTP，但会信任代理转发头并为 cookie 加 Secure 标记）
ssl      由本程序直接加载证书提供 HTTPS（不经反向代理时使用，
         需配合 ssl_certfile / ssl_keyfile 指定证书和私钥路径）

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

    global PASSWORD, HTTPS, SSL, SSL_CERTFILE, SSL_KEYFILE
    PASSWORD = password
    HTTPS = https
    SSL = ssl
    SSL_CERTFILE = ssl_certfile
    SSL_KEYFILE = ssl_keyfile

    return argparse.Namespace(
        host=host, port=port, password=password,
        https=https, ssl=ssl, ssl_certfile=ssl_certfile, ssl_keyfile=ssl_keyfile,
    )
