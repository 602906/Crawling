# -*- coding: utf-8 -*-
"""临时测试：config.ini 三级优先级（测试后删除）。"""
import importlib
import os
import sys

INI_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")

assert not os.path.isfile(INI_PATH), "测试前不应存在 config.ini"

import config

# 阶段1：无 config.ini → 全部默认值
assert config.PORT == 8000
assert config.DEBUG is False
assert config.LT_TRANSPORT == "http"
assert config.PASSWORD_HASH is None
print("[1] 无 ini 默认值 OK")

# 阶段2：创建 config.ini → 覆盖默认值（含大小写键名、bool on、csv、referer、哈希密码）
INI_BODY = """\
[basic]
PORT = 9000
DEBUG = on
password = $sha256$testsalt$0123456789abcdef0123456789abcdef
LT_TRANSPORT = ws

[rate]
rate_max = 123

[proxy]
ALLOWED_PROXY_DOMAINS = 163.com, kugou.com
ALLOWED_PROXY_PORTS = 80, 443, 8080
PROXY_REFERER_MAP = 163.com=https://music.163.com/, kugou.com=https://www.kugou.com/

[listen_together]
lt_room_count = 5
lt_cache_margin = 600

[bad]
unknown_key = 999
port = not_an_int
"""
with open(INI_PATH, "w", encoding="utf-8") as f:
    f.write(INI_BODY)

importlib.reload(config)
assert config.PORT == 9000, config.PORT
assert config.DEBUG is True, config.DEBUG
assert config.LT_TRANSPORT == "ws"
assert config.RATE_MAX == 123
assert config.ALLOWED_PROXY_DOMAINS == ("163.com", "kugou.com")
assert config.ALLOWED_PROXY_PORTS == (80, 443, 8080)
assert config.PROXY_REFERER_MAP == (("163.com", "https://music.163.com/"), ("kugou.com", "https://www.kugou.com/"))
assert config.LT_ROOM_COUNT == 5
assert config.LT_CACHE_MARGIN == 600
assert config.PASSWORD_HASH is not None, "ini 中哈希格式密码应派生 PASSWORD_HASH"
print("[2] ini 覆盖默认值 OK（含大小写键/bool on/csv/referer/哈希密码）")

# 阶段3：命令行覆盖 ini（未指定的保留 ini 值）
sys.argv = ["x", "--port", "7000", "--no-debug"]
cli = config.parse_args()
assert config.PORT == 7000, config.PORT
assert config.DEBUG is False, config.DEBUG
assert config.LT_TRANSPORT == "ws", "命令行未指定应保留 ini 值"
assert config.LT_ROOM_COUNT == 5
assert cli.port == 7000
assert cli.lt_transport == "ws", "Namespace 应同步 ini 生效值"
print("[3] 命令行覆盖 ini OK（未指定保留 ini 值）")

# 阶段4：删除 config.ini → 恢复默认
os.remove(INI_PATH)
importlib.reload(config)
assert config.PORT == 8000
assert config.DEBUG is False
assert config.LT_TRANSPORT == "http"
print("[4] 删除 ini 恢复默认 OK")

print("全部通过")
