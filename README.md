# Music Catch 🎵

多平台音乐聚合搜索、在线播放与下载工具。基于 **FastAPI + 原生前端** 构建，聚合 **网易云音乐 / 酷狗音乐 / Bilibili** 三大平台，覆盖搜索、播放、歌词、下载、歌单、收藏、一起听歌等完整场景。

内置浏览器门禁（Token 挑战）、反 F12 防护、SSRF 防护、IP 限速等多层安全机制，阻止非浏览器方式抓取页面源码与接口。

---

## ✨ 功能特性

### 🔍 搜索与播放

- **三平台聚合搜索**：一次关键词同时检索网易云 / 酷狗 / B 站，并行请求、互不阻塞，支持平台筛选与分页
- **在线播放**：音频 / 视频在线播放；B 站视频播放由 `VIDEO_PLAYBACK_ENABLED` 开关控制（关闭时 B 站只播音频流）
- **多音质**：标准 128k / 高品质 320k / 无损（各平台按实际可用档位展示）
- **本地音频缓存**：IndexedDB 缓存（上限 200MB），播放时后台预缓存；缓存损坏自动删除并回退在线流；断流自动重连并恢复进度
- **媒体代理**：服务端代理转发，支持 Range 请求（拖动进度条），自动处理防盗链、302 跳转与 http→https 升级
- **10 段均衡器**：Web Audio API 实时调节，内置 8 种预设（流行 / 摇滚 / 爵士 / 古典 / 重低音 / 人声 / 电子 / 平直），自定义增益持久化
- **倍速播放**：0.5x–2x 循环切换；B 站视频长按画面临时 2x 试听

### 🎤 歌词

- LRC 解析、同步滚动与高亮
- **自动翻译**：歌词非中文内容占比 ≥ 70% 时，服务端调用多引擎（Bing / 阿里 / 百度 / 有道）自动翻译，返回原文 + 译文合并版；按歌词 SHA-256 缓存，同一首歌只翻译一次
- **导出**：复制完整歌词 / 下载 LRC / 下载翻译版 LRC
- **歌词悬浮窗（PiP）**：独立悬浮窗显示歌词（需 Chrome / Edge 116+），窗口内可控制上一首 / 播放暂停 / 下一首

### ⬇️ 下载

- 按平台可用音质下载（128k / 320k / 无损 FLAC / B 站视频或音频）
- 流式传输（边下边存），按文件头魔数自动识别真实格式（mp3 / flac / m4a / ogg / mp4）并修正扩展名
- HEAD 预检：先返回文件大小与类型；请求无损但上游只给 MP3 时自动降级并提示

### 📋 播放管理

- 播放列表：顺序 / 列表循环 / 随机 / 单曲循环
- 收藏夹：快速收藏与清空
- 右键菜单：播放、加入列表、加入歌单、收藏、下载、歌曲信息、分享（支持"从当前播放位置分享"，附带时间戳跳转）
- 音量 / 静音本地记忆，跨标签页实时联动

### 🎧 我的歌单

- **左侧歌单栏**：歌单保存在浏览器 `localStorage`，不占用服务器存储
- **平台导入**：粘贴网易云 / 酷狗歌单链接或 ID，预览确认后自动分页拉取全量（酷狗含设备注册）
- **分享**：生成仅含平台代码与歌曲 ID 的极短链接 `?list=kugou:hash1,hash2;netease:123,456`，不限歌曲数量；对方打开自动批量解析并保存为"分享歌单"
- **流式补全**：长歌单先保存 ID 骨架立即打开，服务端 SSE 分批解析、客户端边收边写回，中断自动续传
- **历史缓存**：侧栏底部展示 IndexedDB 已缓存歌曲，可搜索过滤、单曲删除或一键清空

### 🎶 一起听歌

- **常驻房间**：`LT_ROOM_COUNT`（默认 10）个房间始终存在，空房恢复默认名"x号房"
- **双传输模式**（`LT_TRANSPORT` 全局统一切换）：
  - `http`（默认）：长轮询 `/api/listen-together/poll`，兼容不支持 WebSocket 的 CDN
  - `ws`：WebSocket 低延迟推送，列表页即建立全局连接，房间列表实时推送，进房 / 离开 / 操作全走消息
- **房主权威播放**：房主本地播放即为权威，全员自动对齐；播放 / 暂停 / 切歌 / 拖动仅房主可操作，非房主播放按钮为本地控制
- **按需进度同步**：WS 模式新成员进房时服务端 `ask_sync` 询问房主，房主 `sync` 应答一次；HTTP 模式房主按 `LT_SYNC_INTERVAL` 周期上报
- **成员协作**：任何成员可添加歌曲进队列，房主删除 / 管理队列、自定义房间名、转让房主；房主离开自动转让给最早加入的成员
- **房间播放缓存**：同房间多人听同一首歌复用播放地址，播放中持续续期、切歌 / 停止后超 `LT_CACHE_MARGIN` 自动删除
- **昵称与会话**：昵称存本机浏览器（不绑定 IP、不做全局占用、不限改名次数）；进房下发 HttpOnly 会话 Cookie `mc_lt_sid`，刷新页面自动恢复身份
- **重名保护**：进房前零副作用预检 `precheck`，重名仅提示"进入失败"、不进入房间，不影响房主播放
- **断线自愈**：门禁 Token 失效时自动重新注册并重连，403 严格区分"门禁失效"与"重名"
- **独立音量**：音量 / 静音本地控制，不参与房间同步；与主页共用 `localStorage`，跨标签页联动
- **分享房间**：`?room=N` 链接直达，进入后自动清理 URL 参数
- **歌词联动**：复用全局歌词系统，房主点击歌词行即可同步跳转

### 🔐 平台登录

| 平台 | 扫码 | Cookie | 手机号 |
| ---- | ---- | ------ | ------ |
| 网易云音乐 | ✅ | ✅ | ✅ |
| 酷狗音乐 | ❌ | ✅ | ✅ |
| Bilibili | ✅ | ✅ | ❌ |

- 会话持久化到 `.sessions/` 目录，重启后自动恢复登录态
- 网易云采用 weapi 加密（AES + RSA）；酷狗采用 Android Lite 网关签名 + 设备注册（AES / RSA）；B 站采用 WBI 签名

### 🎨 界面

- 明暗双主题：按客户端时间自动切换（6:00–20:00 亮色），支持手动切换并记忆（1 分钟内优先用户选择）
- 全响应式布局，移动端适配
- 自定义加载动画、内联 SVG 图标

---

## 🛡️ 安全设计

- **浏览器门禁（Gate）**：访问页面先过 Token 挑战（动态脚本路径、3 秒过期）；门禁 Cookie 采用动态加密名（真实名混入随机串 + XOR 流加密 + 完整性校验），客户端 JS 完全无感；Token 绑定 **IP + 浏览器指纹**（UA 家族 / 语言 / 客户端提示），滑动续期
- **反 F12**：动态生成混淆 JS（XOR 分段编码、分块乱序、控制流平坦化、不透明谓词、蜜罐假 token、用后即焚）；检测 F12 快捷键、窗口尺寸变化、debugger 断点、webdriver、fetch 原型 hook，触发即销毁页面并上报原因（`AF12_DEBUG_MODE` 可切调试模式仅记录不销毁）
- **访问密码**：保护登录等敏感接口；支持明文或 `$sha256$<salt>$<hexdigest>` 哈希存储（明文不落盘）；登录 Cookie 动态名 + 恒定时间比较 + 限速防爆破
- **IP 速率限制**：按限速档位分桶（注册 / 心跳 / 普通 API / 流式 / 密码验证 / 歌单导入 / 批量解析），内存有界（空闲清理 + 容量上限兜底）
- **SSRF 防护**：代理 URL 仅允许平台官方域名白名单，解析全部 A/AAAA 记录拒绝内网 / 保留地址，端口白名单，手动逐跳校验重定向
- **安全响应头**：CSP（限制 `connect-src` 防数据外泄）、`X-Frame-Options`、`X-Content-Type-Options`；生产环境禁用 Swagger / OpenAPI 文档
- **请求体大小限制**（默认 1MB，超限 413），防超大包 DoS
- **单进程内存态设计**：限速与 Token 均存内存，多进程部署会破坏安全防线（详见部署注意事项）

---

## 🧰 技术栈

| 层 | 技术 |
| -- | ---- |
| 后端 | Python 3.8+ · FastAPI · Uvicorn |
| HTTP 客户端 | httpx（异步） |
| 前端 | 原生 HTML / CSS / JavaScript（无框架）· Jinja2 模板 |
| 加密 | PyCryptodome（AES / RSA）、hashlib |
| 二维码 | segno |
| 翻译 | translators（多引擎） |
| 存储 | IndexedDB（前端缓存）· JSON 文件（会话持久化）· localStorage（歌单 / 收藏 / 设置） |

---

## 📁 目录结构

```
MusicCatch/
├── main.py                  # FastAPI 应用入口：路由、中间件、安全防护、代理 / 下载
├── config.py                # 全部配置常量（不修改即默认值，支持命令行 / config.ini 覆盖）
├── anti_devtools.py         # 反 F12 + 浏览器门禁（动态 Cookie 名、Token 挑战、JS 混淆）
├── listen_together.py       # 一起听歌：常驻房间 + 双传输同步、房主权威播放、按需询问-应答、会话 Cookie、重名预检
├── requirements.txt         # Python 依赖
├── platforms/
│   ├── __init__.py          # 平台注册表 PLATFORMS
│   ├── base.py              # 抽象基类 MusicPlatform、Song、SearchResult
│   ├── netease.py           # 网易云音乐（weapi 加密、扫码 / 手机号 / Cookie 登录、歌单导入）
│   ├── kugou.py             # 酷狗音乐（Android Lite 网关签名、设备注册、AES / RSA、歌单导入）
│   └── bilibili.py          # Bilibili（WBI 签名、扫码 / Cookie 登录、DASH 音视频流）
├── templates/               # Jinja2 页面模板
│   ├── base.html            # 布局骨架：主题、导航、加载动画、反 F12 脚本注入
│   ├── index.html           # 主页：搜索 + 播放器 + 歌词 + 列表 + 收藏 + 歌单 + 均衡器
│   ├── listen_together.html # 一起听歌页：房间列表 + 播放器 + 成员 / 队列 + 歌词面板
│   ├── login.html           # 平台登录页
│   └── verify.html          # 访问密码验证页
├── static/
│   ├── css/                 # base / player / search / lyrics / playlist / favorites /
│   │                        # context-menu / playlist.sidebar / playlist.sidebar.history /
│   │                        # equalizer / login / pip / responsive / listen-together
│   └── js/                  # app / player / search / lyrics / playlist / favorites /
│                            # context-menu / playlist.sidebar / playlist.sidebar.history /
│                            # equalizer / login / pip / verify / listen-together
└── .sessions/               # 平台登录会话（运行时自动生成）
```

---

## 🚀 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动

```bash
python main.py
```

默认监听 `0.0.0.0:8000`，浏览器访问 `http://localhost:8000` 即可。

> 首次访问会经过浏览器门禁挑战页（自动验证，无需操作）。

### 命令行参数

**`config.py` 中每个可配置常量都有对应的命令行参数**（常量名转小写连字符：`LT_TRANSPORT` → `--lt-transport`；bool 常量可用 `--no-xxx` 关闭），完整列表见 `python main.py --help`。

```bash
python main.py                        # 默认配置启动
python main.py --debug                # 开启调试日志
python main.py --port 9000            # 指定端口
python main.py --host 127.0.0.1 --port 3000      # 指定地址和端口
python main.py --password abc123      # 启用访问密码
python main.py --https                # 反向代理 HTTPS 模式
python main.py --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem   # 本地证书 HTTPS
python main.py --lt-transport ws      # 一起听歌切换 WebSocket 低延迟推送
python main.py --lt-room-count 20     # 常驻房间数改为 20
python main.py --video-playback       # 允许 B 站视频播放
```

- 逗号分隔型常量（域名 / 端口白名单）直接传逗号字符串：`--allowed-proxy-domains "163.com,kugou.com"`
- Referer 映射传 `域名=Referer` 逗号分隔：`--proxy-referer-map "163.com=https://music.163.com/"`
- 密码支持哈希格式：`--password '$sha256$<salt>$<hexdigest>'`

### 可选 config.ini（手动创建）

程序目录下可放一个 `config.ini`（**程序不会自动创建**）。键名 = `config.py` 常量名（不区分大小写），类型与 `config.py` 一致，未列出的项保持默认值：

```ini
[basic]
port = 9000                  # 监听端口
lt_transport = ws            # 一起听歌传输方式
debug = true                 # 调试日志（bool 支持 true/false/yes/no/on/off/1/0）
```

**配置优先级：命令行参数 > config.ini > config.py**（仅命令行显式传入的参数覆盖 config.ini；两者均未设置时用 config.py 默认值）

---

## ⚙️ 配置说明

所有配置集中在 [config.py](config.py) 顶部常量（**不修改即默认值**，改后重启生效）；**每个常量均有对应命令行参数**，命令行优先级最高。

### 基础配置

| 常量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `DEBUG` | `False` | 调试日志开关：开启后输出 INFO+/DEBUG+（进房 / 动作 / 缓存命中 / 门禁 / 搜索等），关闭时仅 WARNING+ |
| `HOST` | `"0.0.0.0"` | 监听地址 |
| `PORT` | `8000` | 监听端口 |
| `PASSWORD` | `"musiccatch"` | 访问密码（保护登录等敏感接口）；支持 `$sha256$<salt>$<hexdigest>` 哈希格式；空字符串表示不启用 |
| `HTTPS` | `False` | 以 HTTPS 对外提供服务（TLS 由反向代理终止）：信任代理转发头，并为 Cookie 加 Secure 标记 |
| `SSL` | `False` | 由本程序直接加载证书提供 HTTPS（不经反向代理时使用） |
| `SSL_CERTFILE` / `SSL_KEYFILE` | `"cert.pem"` / `"key.pem"` | `SSL=True` 时使用的证书与私钥路径 |
| `FORWARDED_ALLOW_IPS` | `"127.0.0.1"` | `HTTPS=True` 模式下可信代理 IP 白名单（逗号分隔），防止伪造 X-Forwarded-For 绕过限速与 Token 指纹绑定；仅当 Nginx 与后端同机时保持默认值 |
| `VIDEO_PLAYBACK_ENABLED` | `False` | 是否支持 B 站视频播放 |
| `ANTI_F12_ENABLED` | `False` | 反 F12 功能总开关 |

> ⚠️ 默认密码 `musiccatch` 仅为开箱即用，部署到公网前务必修改。

### 限速与代理

| 常量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `RATE_MAX` / `RATE_WINDOW` | `5` / `60` | 门禁注册每 IP 速率与窗口（秒） |
| `API_RATE_MAX` | `60` | 普通 API 每 IP 每分钟上限 |
| `STREAM_RATE_MAX` | `600` | 流式端点（proxy / download）限速上限 |
| `HEARTBEAT_RATE_MAX` | `60` | 门禁心跳限速 |
| `AUTH_VERIFY_RATE_MAX` | `10` | 密码验证限速（防爆破） |
| `ALLOWED_PROXY_DOMAINS` | 平台官方域名 | 代理域名白名单（`163.com` / `126.net` / `kugou.com` / `bilibili.com` / `bilivideo.com` / `hdslb.com` / `akamaized.net`） |
| `ALLOWED_PROXY_PORTS` | `(80, 443)` | 代理允许端口 |
| `PROXY_MAX_REDIRECTS` | `3` | 代理最大重定向跳数（每跳重新校验） |
| `PROXY_REFERER_MAP` | 平台 Referer 映射 | 域名后缀 → 防盗链 Referer |
| `MAX_BODY_SIZE` | `1048576` | 请求体大小上限（字节），超限 413 |

### 门禁 Token

| 常量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `GATE_TOKEN_TTL` | `60` | 验证通过后有效时长（秒），滑动续期 |
| `GATE_PENDING_TTL` | `3` | 注册后待验证时长（秒，保留兼容） |
| `GATE_SCRIPT_TTL` | `3` | 挑战页脚本 token 有效期（秒） |
| `GATE_COOKIE_NAME` | `"mc_gate"` | 门禁 Cookie 名称（实际下发为动态加密名） |
| `GATE_COOKIE_MAX_AGE` | `15` | 门禁 Cookie 有效期（秒） |
| `GATE_HEARTBEAT_INTERVAL` | `10000` | 心跳间隔（毫秒） |
| `GATE_RELOAD_TIMEOUT` / `GATE_RELOAD_DELAY` | `500` / `1000` | 注册失败重试 / 成功后刷新前延迟（毫秒） |

### 反 F12 阈值

| 常量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `AF12_THRESHOLD_MIN` / `AF12_THRESHOLD_MAX` | `140` / `180` | 窗口尺寸差异阈值范围（px） |
| `AF12_INTERVAL_MIN` / `AF12_INTERVAL_MAX` | `800` / `1200` | 尺寸检测间隔范围（毫秒） |
| `AF12_DEBUG_INTERVAL_MIN` / `AF12_DEBUG_INTERVAL_MAX` | `1800` / `3200` | debugger 检测间隔范围（毫秒） |
| `AF12_DEBUG_DELAY_THRESHOLD` | `100` | debugger 断点判定阈值（毫秒） |
| `AF12_DEBUG_MODE` | `False` | 调试模式：销毁动作改为 debugger + 日志（定位误杀用） |
| `AF12_RESIZE_DEBOUNCE` | `300` | resize 防抖延迟（毫秒） |

### 一起听歌

| 常量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `LT_TRANSPORT` | `"http"` | 传输方式：`"http"`（长轮询，兼容不支持 WebSocket 的 CDN）或 `"ws"`（WebSocket 低延迟推送，需 `uvicorn[standard]`），全局统一 |
| `LT_WS_URL` | `""` | WebSocket 连接地址覆盖（如 `wss://ws.example.com/api/listen-together/ws`），空 = 当前域名默认端点 |
| `LT_ROOM_COUNT` | `10` | 常驻房间数 |
| `LT_QUEUE_MAX` | `100` | 单房间播放队列上限 |
| `LT_NAME_MAX_LEN` | `20` | 用户名 / 自定义房间名最大长度（**前后端提示与输入框上限统一跟随此值**） |
| `LT_NAME_TTL` | `600` | 用户名活动记录宽限（秒），停止活动超时清除 |
| `LT_ROOMS_REFRESH` | `10000` | 房间列表自动刷新间隔（毫秒，仅 http 模式生效） |
| `LT_SYNC_INTERVAL` | `5000` | 房主播放位置同步上报间隔（毫秒，仅 http 模式生效） |
| `LT_POLL_TIMEOUT` | `20` | 长轮询最长挂起（秒） |
| `LT_MEMBER_TTL` | `90` | 成员离线判定（秒） |
| `LT_CACHE_MARGIN` | `300` | 房间播放缓存余量（秒） |

> 已废弃（保留仅为兼容）：`LT_RENAME_DAILY_LIMIT`、`LT_ACTION_RATE_MAX`。

### 其他

| 常量 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `PLAYLIST_ENRICH_BATCH` | `5` | 分享歌单流式解析每批回传歌曲数 |
| `HTTP_USER_AGENT` | Chrome UA | 下载 / 代理 HTTP 客户端 UA |
| `DOWNLOAD_TIMEOUT_CONNECT` / `DOWNLOAD_TIMEOUT_READ` | `30` / `300` | 连接 / 流式读取超时（秒） |
| `HEAD_TIMEOUT_READ` | `30` | HEAD 请求读取超时（秒） |
| `PROXY_CHUNK_SIZE` | `65536` | 代理流式传输块大小（字节） |
| `AUTH_COOKIE_MAX_AGE` | `604800` | 登录态 Cookie 有效期（7 天） |

---

## 📖 使用指南

1. **登录**（可选）：进入"登录"页，选择平台与登录方式（扫码 / Cookie / 手机号）。登录后搜索可获取更高音质。
2. **搜索**：输入关键词回车，可按平台筛选结果，支持分页。
3. **播放**：点击歌曲即可播放；B 站视频自动切换视频播放器。
4. **下载**：右键歌曲 → 下载 → 选择音质；或打开"歌曲信息"查看可用音质。
5. **歌词**：播放时右侧滑出歌词面板，可复制或下载 LRC；设置中可开启歌词悬浮窗（画中画）。
6. **收藏 / 列表**：播放条按钮或右键菜单管理。
7. **歌单**：主页左侧"我的歌单"栏：＋ 新建空歌单，⇩ 导入平台歌单（粘贴链接或 ID，预览确认后全量导入）；右键任意歌曲 → "添加到歌单"；打开歌单后支持"播放全部"或逐曲播放；"分享"复制极短链接，对方打开自动解析并保存为"分享歌单"。
8. **一起听歌**：进入"一起听歌"页 → 首次设置昵称（保存在本机浏览器）→ 加入任意房间；房主负责播放控制，其余成员自动跟随；重名进入会被拦截并提示。

---

## 🔌 API 概览

| 方法 | 路径 | 说明 |
| ---- | ---- | ---- |
| GET | `/api/gate/register` | 浏览器门禁 Token 注册（下发动态 Cookie） |
| POST | `/api/gate/heartbeat` | 门禁心跳续期 |
| GET/POST | `/api/gate/kill-report` | 反 F12 销毁原因上报（仅日志） |
| POST | `/api/auth/verify` | 访问密码验证 |
| GET | `/api/login/qrcode/{platform}` | 获取登录二维码（base64 PNG） |
| GET | `/api/login/qrcode/{platform}/check` | 轮询扫码状态 |
| POST | `/api/login/cookie/{platform}` | Cookie 登录 |
| POST | `/api/login/phone/{platform}` | 手机号登录 |
| POST | `/api/login/phone/{platform}/send_code` | 发送短信验证码 |
| GET | `/api/search` | 聚合搜索（`keyword` / `platform` / `page` / `page_size`） |
| GET | `/api/play/{platform}/{song_id}` | 获取播放地址 |
| GET | `/api/playlist/import` | 导入平台歌单单页（`platform` / `ref` / `page` / `page_size`；网易云 / 酷狗） |
| POST | `/api/resolve-songs` | 批量解析分享歌单歌曲（并发 8，失败保留最小信息） |
| POST | `/api/resolve-songs-stream` | 分享歌单分批解析（SSE 流式） |
| GET | `/api/lyrics/{platform}/{song_id}` | 获取 LRC 歌词（含翻译） |
| GET/HEAD | `/api/download/{platform}/{song_id}` | 下载（`quality`: 128 / 320 / lossless；B 站: video / audio） |
| GET | `/api/resolve-song/{platform}/{song_id}` | 歌曲完整元数据 |
| GET | `/api/info/{platform}/{song_id}` | 歌曲信息 + 可用音质列表 |
| GET | `/api/status` | 各平台登录状态 |
| POST | `/api/logout/{platform}` | 退出登录 |
| GET | `/api/proxy?url=...` | 媒体流代理（白名单 + Range 支持） |
| GET | `/api/listen-together/config` | 一起听歌前端配置（名称长度上限、传输方式等） |
| POST | `/api/listen-together/join` | 设置 / 恢复昵称（body: `{name}`） |
| POST | `/api/listen-together/rename` | 修改昵称（body: `{name}`，无次数限制） |
| GET | `/api/listen-together/rooms` | 房间列表（人数 / 播放中） |
| GET | `/api/listen-together/precheck` | 进房前重名预检（零副作用，重名返回 403） |
| GET | `/api/listen-together/poll` | 房间长轮询（`room_id` / `version` / `name`；HTTP 传输模式） |
| WS | `/api/listen-together/ws` | WebSocket 实时通道（`name`；消息：`enter/leave/action/sync/ping`；服务端推 `rooms/state/ask_sync/enter_ok/enter_fail`；WS 传输模式，需 `uvicorn[standard]`） |
| POST | `/api/listen-together/action` | 房间动作（add/play/pause/next/prev/seek/remove/transfer/rename_room/sync，仅房主可播放控制） |
| POST | `/api/listen-together/leave` | 离开房间 |

> 除门禁注册 / 心跳外，所有 `/api/` 接口均需有效门禁 Token；敏感接口（登录、状态）另需密码验证。流式端点（proxy / download）限速放宽以避免误伤正常播放。
> 一起听歌接口统一带 `?name=` 用户名参数，进房成功通过 `Set-Cookie` 下发会话 Cookie（`mc_lt_sid`，HttpOnly），刷新页面凭 Cookie 恢复身份；同名成员且非本人会话一律 403 拦截。

---

## 🌐 部署说明

### 反向代理 HTTPS（Nginx 示例）

```nginx
server {
    listen 443 ssl;
    server_name music.example.com;

    ssl_certificate     /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        # 长连接 + 大文件流式传输
        proxy_buffering off;
        proxy_read_timeout 300s;
    }
}
```

对应后端配置：`config.py` 中 `HTTPS = True`，`FORWARDED_ALLOW_IPS` 保持 `"127.0.0.1"`（Nginx 与后端同机）或改为 Nginx 服务器实际 IP。

### ⚠️ 注意事项

- **保持单进程运行**：限速与门禁 Token 均为内存态，请勿使用 `uvicorn main:app --workers N` 多进程部署，否则限速阈值按 Worker 数放大、Token 不共享，安全防线失效
- **反向代理 IP 信任**：`https=true` 时若 `forwarded_allow_ips` 配置不当，所有客户端将共享代理 IP，导致限速变全局限流、Token 指纹绑定失效
- **80 端口出站受限**：代理层会自动将 `http://` 源站升级为 `https://` 重试，无需额外处理
- **编译打包模式**：`IS_FROZEN` 为真时自动打开浏览器，会话目录位于可执行文件同级目录

---

## 📜 免责声明

本项目仅用于技术学习与个人研究，请遵守各音乐平台的服务条款与相关法律法规。请勿将本项目用于任何商业用途或侵犯版权的内容传播。因使用本项目产生的一切法律后果由使用者自行承担。

---

## 📄 License

MIT License