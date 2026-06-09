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
}


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

示例:
  MusicCatch                          使用默认配置启动
  MusicCatch --port 9000              命令行指定端口
  MusicCatch --host 127.0.0.1 --port 3000  命令行指定地址和端口
"""

    parser = argparse.ArgumentParser(
        description=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--host", default=None, help=f"监听地址 (默认: {_DEFAULTS['host']})")
    parser.add_argument("--port", type=int, default=None, help=f"监听端口 (默认: {_DEFAULTS['port']})")
    cli = parser.parse_args()

    host = cli.host or section.get("host", _DEFAULTS["host"])
    port = cli.port if cli.port is not None else int(section.get("port", _DEFAULTS["port"]))

    return argparse.Namespace(host=host, port=port)
