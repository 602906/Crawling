<div align="center">

# Music Catch

**多平台音乐搜索 · 在线播放 · 批量下载**

<sub>网易云音乐 · 酷狗音乐 · Bilibili · QQ 音乐</sub>

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![httpx](https://img.shields.io/badge/httpx-async-2C5BB4?style=flat-square)](https://www.python-httpx.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)](./LICENSE)

</div>

---

### 核心能力

| | |
|---|---|
| **四平台聚合** | 一次搜索覆盖网易云 / 酷狗 / B 站 / QQ 音乐 |
| **多音质下载** | 128k · 320k · 无损 FLAC（B 站支持视频 / 音频） |
| **歌单导入** | 链接或 ID 一键导入，长歌单渐进补全 |
| **歌词翻译** | 网易云 / QQ 官方翻译，其余平台本地引擎回退 |
| **一起听歌** | 10 个常驻房间，HTTP 长轮询 / WebSocket 双传输 |
| **均衡器** | 10 段 Web Audio，8 种预设 + 自定义持久化 |

### 快速开始

```bash
pip install -r requirements.txt
python main.py
```

访问 `http://localhost:8000` &nbsp;·&nbsp; 默认密码 `musiccatch`

<details>
<summary><b>依赖清单</b></summary>

| 依赖 | 用途 |
|---|---|
| `fastapi` / `uvicorn` / `jinja2` | Web 框架与模板 |
| `httpx` | 异步 HTTP 客户端 |
| `segno` | 二维码生成 |
| `pycryptodome` | 平台加密（酷狗 / 网易云） |
| `translators` | 本地翻译引擎 |
| `qqmusic-api-python` | 可选，启用 QQ 音乐时需装 |

</details>

### 配置

**优先级：`命令行` > `config.ini` > `config.py`**

```bash
python main.py --port 9000                       # 改端口
python main.py --password abc123                 # 改密码
python main.py --https                           # 反代 HTTPS
python main.py --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem
python main.py --lt-transport ws                 # 一起听歌用 WebSocket
```

<details>
<summary><b>主要配置项</b></summary>

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `HOST` / `PORT` | 监听地址 / 端口 | `0.0.0.0` / `8000` |
| `PASSWORD` | 访问密码，支持 `$sha256$<salt>$<hash>` | `musiccatch` |
| `DEBUG` | 调试日志 | `False` |
| `HTTPS` / `SSL` | 反代 / 本地证书 HTTPS | `False` |
| `VIDEO_PLAYBACK_ENABLED` | B 站视频播放开关 | `False` |
| `ANTI_F12_ENABLED` | 反 F12 总开关 | `False` |
| `LT_TRANSPORT` | 一起听歌传输：`http` / `ws` | `http` |
| `LT_ROOM_COUNT` | 常驻房间数 | `10` |
| `LYRICS_TRANSLATION_ENABLED` | 歌词翻译开关 | `True` |
| `ALLOWED_PROXY_DOMAINS` | 代理域名白名单 | 各平台官方 |

运行 `python main.py --help` 查看全部参数。

</details>

> **部署注意**
> 单进程设计 — 限速 / 门禁 token 为内存态，`--workers N` 会破坏安全机制
> 反代模式 — `HTTPS = True` 且 Nginx 不同机时，必须改 `FORWARDED_ALLOW_IPS`

### 项目结构

```
MusicCatch/
├── main.py                  FastAPI 入口、路由、安全中间件
├── config.py                配置常量 + 参数解析
├── anti_devtools.py         门禁 + 反 F12 JS 生成
├── lyric_translator.py      歌词翻译
├── listen_together.py       一起听歌
├── playlist_download.py     歌单流式下载
│
├── platforms/               平台接入
│   ├── base.py              抽象基类
│   ├── netease.py
│   ├── kugou.py
│   ├── bilibili.py
│   └── qqmusic.py
│
├── templates/               Jinja2 模板
└── static/                  css / js
```

### API 速览

<details>
<summary><b>门禁与认证</b></summary>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/gate/register` | 注册门禁 token |
| `POST` | `/api/gate/heartbeat` | 心跳续期 |
| `POST` | `/api/auth/verify` | 访问密码验证 |

</details>

<details>
<summary><b>音乐</b></summary>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/search` | 聚合搜索 |
| `GET` | `/api/play/{platform}/{id}` | 获取播放地址 |
| `GET` | `/api/download/{platform}/{id}` | 下载 |
| `GET` | `/api/proxy` | 音频 / 视频代理 |
| `GET` | `/api/lyrics/{platform}/{id}` | 歌词 + 翻译 |
| `GET` | `/api/info/{platform}/{id}` | 歌曲信息 |

</details>

<details>
<summary><b>登录</b></summary>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/login/qrcode/{platform}` | 二维码 |
| `GET` | `/api/login/qrcode/{platform}/check` | 扫码状态 |
| `POST` | `/api/login/cookie/{platform}` | Cookie 登录 |
| `POST` | `/api/login/phone/{platform}` | 手机登录 |
| `POST` | `/api/logout/{platform}` | 退出 |

</details>

<details>
<summary><b>歌单与一起听歌</b></summary>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/playlist/import` | 平台歌单导入 |
| `POST` | `/api/playlist/download` | 歌单流式下载 |
| `POST` | `/api/resolve-songs-stream` | 批量解析（SSE） |
| `GET` | `/api/listen-together/rooms` | 房间列表 |
| `GET` | `/api/listen-together/poll` | 长轮询状态 |
| `POST` | `/api/listen-together/action` | 房间动作 |
| `WS` | `/api/listen-together/ws` | WebSocket |

</details>

---

<div align="center">
<sub>请遵守各音乐平台服务条款 · 仅用于个人合法用途</sub>
</div>