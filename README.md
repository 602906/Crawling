<div align="center">

# Music Catch

<a href="https://git.io/typing-svg"><img src="https://readme-typing-svg.demolab.com?font=Fira+Code&weight=500&size=20&duration=3200&pause=1200&color=6366F1&center=true&vCenter=true&width=600&lines=多平台音乐搜索+·+在线播放+·+批量下载;网易云+·+酷狗+·+Bilibili+·+QQ+音乐" alt="Music Catch" /></a>

<p>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-0.100%2B-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI"></a>
  <a href="https://www.python-httpx.org/"><img src="https://img.shields.io/badge/httpx-async-2C5BB4?style=flat-square" alt="httpx"></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License"></a>
</p>

<p><sub>一个自托管的多平台音乐聚合工具 · 支持搜索 / 播放 / 下载 / 歌单 / 歌词翻译 / 一起听歌</sub></p>

</div>

---

## 目录

- [核心能力](#核心能力)
- [快速开始](#快速开始)
- [配置](#配置)
- [使用指南](#使用指南)
- [项目结构](#项目结构)
- [API 参考](#api-参考)
- [常见问题](#常见问题)
- [License](#license)

---

## 核心能力

| 分类 | 能力 |
|:---|:---|
| **搜索播放** | 四平台聚合搜索（网易云 / 酷狗 / B 站 / QQ 音乐），后端代理音频流，规避跨域 |
| **下载** | 128k / 320k / 无损 FLAC 多音质；B 站支持视频 / 音频（可开关），文件名统一为 `歌手 - 歌名.ext` |
| **歌单** | 本地歌单新建 / 重命名 / 分享 / 打包下载；平台歌单链接或 ID 一键导入，长歌单渐进补全 |
| **歌词** | 多平台歌词拉取；网易云 / QQ 音乐官方翻译，其余平台本地引擎回退（bing / 阿里 / 百度 / 有道） |
| **播放器** | 播放列表、收藏、四种播放模式、倍速、音量、PiP 歌词悬浮窗（主题联动） |
| **均衡器** | 10 段 Web Audio BiquadFilter，8 种预设 + 自定义，localStorage 持久化 |
| **音频缓存** | IndexedDB 本地缓存（默认 200MB），命中免请求、断网可用，文件头魔数校验 |
| **一起听歌** | 10 个常驻房间，HTTP 长轮询 / WebSocket 双传输，房主控场，成员加歌 |
| **安全** | 访问密码（SHA256 落盘）· 动态 Cookie 门禁 + IP/UA 指纹 · 反 F12 · SSRF 防护 · IP 限速 |

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 启动
python main.py
```

访问 **`http://localhost:8000`** &nbsp;·&nbsp; 默认密码 `musiccatch`

<details>
<summary><b>依赖清单</b></summary>

<br>

| 依赖 | 用途 |
|---|---|
| `fastapi` / `uvicorn` / `jinja2` | Web 框架与模板渲染 |
| `httpx` | 异步 HTTP 客户端（平台请求 / 代理 / 下载） |
| `segno` | 二维码生成 |
| `pycryptodome` | 平台加密算法（酷狗 / 网易云） |
| `translators` | 歌词本地翻译引擎 |
| `qqmusic-api-python` | 可选，启用 QQ 音乐时需安装 |

</details>

<details>
<summary><b>PyInstaller 打包模式</b></summary>

<br>

打包后（`sys.frozen = True`）行为变化：

- 静态资源从 `sys._MEIPASS` 读取
- 会话与持久化文件写入**可执行文件所在目录**
- 启动后延迟 `FROZEN_BROWSER_OPEN_DELAY` 秒自动打开浏览器

</details>

---

## 配置

**优先级：`命令行参数` > `config.ini` > `config.py`**

<details>
<summary><b>三种配置入口</b></summary>

<br>

| 方式 | 位置 | 说明 |
|---|---|---|
| **`config.py`** | 项目根目录，文件顶部常量 | 直接修改代码，不修改则使用默认值 |
| **`config.ini`** | 程序目录（需手动创建，程序不自动生成） | 键名 = 常量名，不区分大小写，任意 section 均可 |
| **命令行** | `--xxx` / `--no-xxx` | 所有常量都有对应参数，bool 可用 `--no-xxx` 关闭 |

</details>

<details>
<summary><b>常用命令行示例</b></summary>

<br>

```bash
python main.py --port 9000                                    # 改端口
python main.py --host 127.0.0.1 --password abc123             # 改地址 + 密码
python main.py --https                                        # 反代 HTTPS 模式
python main.py --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem   # 本地证书 HTTPS
python main.py --lt-transport ws                              # 一起听歌切 WebSocket
```

运行 `python main.py --help` 查看全部参数。

</details>

<details>
<summary><b>主要配置项</b></summary>

<br>

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `HOST` / `PORT` | 监听地址 / 端口 | `0.0.0.0` / `8000` |
| `PASSWORD` | 访问密码，支持 `$sha256$<salt>$<hash>` 哈希格式 | `musiccatch` |
| `DEBUG` | 调试日志开关（INFO+ 级别） | `False` |
| `HTTPS` / `SSL` | 反代 HTTPS / 本地证书 HTTPS | `False` |
| `VIDEO_PLAYBACK_ENABLED` | B 站视频播放开关（关闭后仅音频） | `False` |
| `ANTI_F12_ENABLED` | 反 F12 功能总开关 | `False` |
| `LT_TRANSPORT` | 一起听歌传输方式：`http` / `ws` | `http` |
| `LT_ROOM_COUNT` | 常驻房间数 | `10` |
| `LT_NAME_MAX_LEN` | 用户名 / 房间名最大长度 | `20` |
| `PLAYLIST_ENRICH_BATCH` | 分享歌单每批解析数 | `5` |
| `PLAYLIST_DOWNLOAD_BANDWIDTH` | 歌单下载限速（字节/秒） | `524288` |
| `LYRICS_TRANSLATION_ENABLED` | 歌词翻译总开关 | `True` |
| `LYRICS_TRANSLATION_NON_CHINESE_RATIO` | 触发翻译的非中文占比阈值 | `0.7` |
| `ALLOWED_PROXY_DOMAINS` | 代理域名白名单 | 各平台官方域名 |
| `RATE_MAX` / `API_RATE_MAX` / `STREAM_RATE_MAX` | 各类端点 IP 限速 | 见 `config.py` |

</details>

<details>
<summary><b>部署注意事项</b></summary>

<br>

> **单进程设计** — 限速计数器、门禁 token、一起听歌房间状态均为进程内内存态。使用 `uvicorn main:app --workers N` 会导致：限速阈值按 worker 数放大、门禁 token 各 worker 不共享导致频繁 403、房间状态各自独立。如需多进程，必须自行接入 Redis 改造。

> **反向代理** — `HTTPS = True` 且 Nginx 与后端**不同机**时，必须将 `FORWARDED_ALLOW_IPS` 改为 Nginx 实际 IP，否则所有客户端共享同一 IP（限速变全局限流，token 的 IP 指纹绑定失效）。

> **门禁 Cookie 时长** — `GATE_COOKIE_MAX_AGE` 需 **大于** `GATE_HEARTBEAT_INTERVAL / 1000`，否则浏览器会提前停止携带 cookie，导致心跳失败 → 无限重注册循环。

</details>

---

## 使用指南

<details>
<summary><b>平台登录</b></summary>

<br>

访问 `/login` 选择平台。各平台支持方式：

| 平台 | 扫码 | Cookie | 手机号 |
|---|:---:|:---:|:---:|
| 网易云音乐 | ✓ | ✓ | ✓ |
| 酷狗音乐 | — | ✓ | ✓ |
| Bilibili | ✓ | ✓ | — |
| QQ 音乐 | ✓ | ✓ | ✓ |

**Cookie 登录步骤** — 浏览器登录对应平台 → 按 `F12` 打开开发者工具 → `Network` 面板 → 复制请求的 Cookie → 粘贴到输入框。

登录状态通过 `.sessions/` 目录持久化，重启后自动恢复。

</details>

<details>
<summary><b>歌单导入（支持的链接格式）</b></summary>

<br>

| 平台 | 支持的输入 |
|---|---|
| **网易云** | `music.163.com` 歌单链接 · `163cn.tv` 短链 · 纯歌单 ID |
| **酷狗** | `kugou.com` 歌单链接 · `t1.kugou.com` 短链 · `gcid_xxx` / `collection_xxx` / 纯数字 ID |
| **QQ 音乐** | `y.qq.com/n/ryqq/playlist/{id}` · `c6.y.qq.com` / `t.qq.com` 短链 · 纯歌单 ID |

> QQ 音乐暂不支持专辑 / 歌手链接，粘贴时会给出明确提示。

</details>

<details>
<summary><b>一起听歌</b></summary>

<br>

访问 `/listen-together`：

1. **设置昵称** — 保存在本机浏览器 localStorage
2. **进入房间** — 从 10 个常驻房间选择，或通过分享链接 `?room=N` 自动进入
3. **房主权限** — 播放 / 暂停 / 切歌 / 拖动进度、删除队列歌曲、转让房主、修改房间名
4. **成员权限** — 添加歌曲到队列；播放 / 暂停按钮为本地控制（不同步到房间）

**传输方式**（`LT_TRANSPORT` 全局统一切换）：

| 方式 | 说明 |
|---|---|
| `http` | 长轮询（`LT_POLL_TIMEOUT` 秒挂起），兼容性最好 |
| `ws` | WebSocket 推送，延迟更低，需 `uvicorn[standard]` |

</details>

<details>
<summary><b>均衡器</b></summary>

<br>

- **入口** — 导航栏设置（齿轮）→ 均衡器，或播放条 EQ 按钮
- **频段** — 32Hz ~ 16kHz 共 10 段 BiquadFilter 串联
- **预设** — 平直 / 流行 / 摇滚 / 爵士 / 古典 / 重低音 / 人声 / 电子
- **注意** — 首次启用需在用户手势（点击）后创建 AudioContext
- **持久化** — 设置存 localStorage，音频与视频播放器共用同一滤波链

</details>

<details>
<summary><b>音频缓存</b></summary>

<br>

- **存储** — 浏览器 IndexedDB（`MusicCatchAudioCache`），默认上限 200MB
- **行为** — 命中缓存直接本地播放，后台不再请求
- **校验** — 缓存内容做文件头魔数校验，错误页 / 截断数据自动拒绝
- **清理** — 导航栏"清缓存"按钮清空音频 + 歌词缓存

</details>

---

## 项目结构

```
MusicCatch/
├── main.py                  FastAPI 入口、路由、安全中间件
├── config.py                配置常量 + 参数解析
├── requirements.txt         依赖清单
├── LICENSE                  MIT License
├── README.md                说明文档
│
├── function/                核心功能模块
│   ├── anti_devtools.py     门禁 + 反 F12 JS 生成与校验
│   ├── listen_together.py   一起听歌房间状态与 API
│   ├── lyric_translator.py  歌词翻译（平台原生 + 本地引擎）
│   └── playlist_download.py 歌单流式下载（服务端不落盘）
│
├── platforms/               平台接入
│   ├── __init__.py          PLATFORMS 注册表
│   ├── base.py              MusicPlatform 抽象基类 / Song / SearchResult
│   ├── netease.py           网易云音乐
│   ├── kugou.py             酷狗音乐
│   ├── bilibili.py          Bilibili
│   └── qqmusic.py           QQ 音乐
│
├── templates/               Jinja2 模板
│   ├── base.html            通用骨架 + 导航栏 + 设置
│   ├── index.html           主页（搜索 / 播放器 / 歌单侧栏 / 均衡器）
│   ├── login.html           平台登录页
│   ├── verify.html          访问密码验证页
│   └── listen_together.html 一起听歌页
│
└── static/                  前端资源
    ├── css/                 全局 / 播放器 / 歌单 / 歌词 / 均衡器等样式
    └── js/                  播放器 / 搜索 / 歌词 / 均衡器 / 一起听歌等脚本
```

<details>
<summary><b>模块职责说明</b></summary>

<br>

| 模块 | 职责 |
|---|---|
| `main.py` | 应用入口、HTTP 路由、安全中间件（限速 / 门禁 / CSP）、各类端点 |
| `config.py` | 全部可配置常量，命令行 / config.ini / 默认值三级覆盖 |
| `function/anti_devtools.py` | 动态 Cookie 名、token 绑定与续期、分层动态加密的反 F12 JS |
| `function/lyric_translator.py` | 平台原生翻译注册表、本地翻译三级策略（整段→分批→逐行）、LRU 缓存 |
| `function/listen_together.py` | 房间模型、成员管理、HTTP / WS 双传输、播放缓存、消息处理 |
| `function/playlist_download.py` | 歌单流式协议：4B 长度前缀拼接，服务端不落盘 |
| `platforms/base.py` | 平台抽象接口：登录 / 搜索 / 播放 / 下载 / 歌词 / 歌单导入 |

</details>

---

## API 参考

> 所有 `/api/*` 与 `/static/*` 请求均需通过**浏览器门禁**校验（`/api/gate/register`、`/api/gate/heartbeat` 除外）。登录态敏感接口还需**访问密码**验证。

<details>
<summary><b>门禁与认证</b></summary>

<br>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/gate/register` | 注册门禁 token（动态 Cookie 名，IP + 指纹绑定） |
| `POST` | `/api/gate/heartbeat` | 心跳续期（滑动 TTL） |
| `POST` | `/api/auth/verify` | 访问密码验证，成功下发登录 Cookie |

</details>

<details>
<summary><b>音乐搜索与播放</b></summary>

<br>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/search` | 聚合搜索（`keyword` / `platform` / `page` / `page_size`） |
| `GET` | `/api/play/{platform}/{id}` | 获取播放地址（`room_id` 非 0 走房间缓存） |
| `GET` / `HEAD` | `/api/download/{platform}/{id}` | 下载（GET 流式 / HEAD 仅元信息） |
| `GET` | `/api/proxy` | 音频 / 视频代理（白名单 + 逐跳校验防 SSRF） |
| `GET` | `/api/lyrics/{platform}/{id}` | 歌词 + 翻译 |
| `GET` | `/api/info/{platform}/{id}` | 歌曲信息（含可用音质列表） |
| `GET` | `/api/resolve-song/{platform}/{id}` | 按 ID 解析完整歌曲元数据 |

</details>

<details>
<summary><b>登录（四平台通用）</b></summary>

<br>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/login/qrcode/{platform}` | 获取二维码（base64 图片） |
| `GET` | `/api/login/qrcode/{platform}/check` | 轮询扫码状态 |
| `POST` | `/api/login/cookie/{platform}` | Cookie 登录 |
| `POST` | `/api/login/phone/{platform}` | 手机登录（`code` 空 = 发码，非空 = 校验登录） |
| `POST` | `/api/logout/{platform}` | 退出登录 |

</details>

<details>
<summary><b>歌单</b></summary>

<br>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/playlist/import` | 平台歌单导入（分页） |
| `POST` | `/api/playlist/download` | 歌单下载（流式协议见 `function/playlist_download.py`） |
| `POST` | `/api/resolve-songs` | 分享歌单批量解析（并发 8） |
| `POST` | `/api/resolve-songs-stream` | 分享歌单批量解析（SSE 分批流式） |

</details>

<details>
<summary><b>一起听歌</b></summary>

<br>

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/listen-together/config` | 前端配置（名称长度 / 传输方式） |
| `POST` | `/api/listen-together/join` | 设置昵称 |
| `POST` | `/api/listen-together/rename` | 修改昵称 |
| `GET` | `/api/listen-together/rooms` | 房间列表 |
| `GET` | `/api/listen-together/precheck` | 进房前重名预检（零副作用） |
| `GET` | `/api/listen-together/poll` | 长轮询房间状态（轮询即心跳） |
| `POST` | `/api/listen-together/action` | 房间动作（add / play / pause / next / prev / seek / remove / transfer / rename_room / sync） |
| `POST` | `/api/listen-together/leave` | 离开房间 |
| `WS` | `/api/listen-together/ws` | WebSocket 通道（`LT_TRANSPORT=ws` 时使用） |

</details>

---

## 常见问题

<details>
<summary><b>QQ 音乐为什么无法播放 / 下载？</b></summary>

<br>

QQ 音乐的播放 / 下载 URL 需要登录凭证（`musicid` + `musickey`）才能获取带 vkey 的完整地址，未登录时接口返回空串。请先通过扫码或 Cookie 登录。

</details>

<details>
<summary><b>B 站视频 / 音频加载失败？</b></summary>

<br>

部分部署环境**禁止 80 端口出站**，CDN 返回 http 直链时会连接失败。本程序已内置自动升级到 https 重试一次的逻辑，但若 CDN 本身不支持 https 仍会失败。可在服务器安全组放行 80 出站。

</details>

<details>
<summary><b>每次重启都要重新验证门禁？</b></summary>

<br>

正常现象。门禁密钥在**服务启动时随机生成**，重启即全部失效，旧 cookie 自动作废。这是设计上的安全隔离，避免 token 长期有效被复用。（登录状态不受影响，仍会从 `.sessions/` 恢复。）

</details>

<details>
<summary><b>为什么不能多 worker 部署？</b></summary>

<br>

限速计数器（`_RATE_LIMITS`）、门禁 token（`_tokens`）、一起听歌房间状态（`_ROOMS`）**均为单进程内存态**。多 worker 下：

- 限速阈值按 worker 数线性放大
- 门禁 token 各 worker 不共享 → 请求随机命中 worker 导致频繁 403
- 房间状态各自独立 → 多人加入不同房间

如需多进程，需自行接入 Redis 改造。

</details>

<details>
<summary><b>歌词翻译没有触发？</b></summary>

<br>

本地翻译仅对**非中文占比 ≥ 70%** 的歌词触发（可通过 `LYRICS_TRANSLATION_NON_CHINESE_RATIO` 调整）。另外需确保 `translators` 库已安装且能联网，可用引擎在启动时自动探测。

</details>

<details>
<summary><b>能不能自定义主题？</b></summary>

<br>

支持。前端通过 `data-theme="light|dark"` 属性切换，颜色变量集中在 `static/css/base.css` 的 `:root` 与 `[data-theme="light"]` 中，修改 CSS 变量即可换肤。主题选择会写入 localStorage 并在多标签页同步。

</details>

---

## License

本项目采用 **MIT License** 开源，详见 [LICENSE](./LICENSE) 文件。

---

<div align="center">
<sub>请遵守各音乐平台服务条款 · 仅用于个人合法用途</sub>
</div>