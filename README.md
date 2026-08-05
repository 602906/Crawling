# Music Catch 🎵

多平台音乐搜索、播放与下载工具。基于 FastAPI 构建，支持 **网易云音乐、酷狗音乐、Bilibili** 三大平台聚合搜索，提供在线播放、歌词展示、多音质下载、播放列表、收藏等完整功能。

内置浏览器门禁（Token 挑战）与反 F12 防护，防止非浏览器方式直接抓取页面源码与接口。

---

## ✨ 功能特性

### 搜索与播放
- **三平台聚合搜索**：一次输入关键词，同时检索网易云音乐、酷狗音乐、Bilibili（并行请求，互不阻塞）
- **在线播放**：音频/视频在线播放，支持 B 站视频播放（可通过配置开关）
- **多音质**：标准 128k / 高品质 320k / 无损（各平台按实际可用档位展示）
- **音频缓存**：IndexedDB 本地缓存（上限 200MB），支持后台预缓存、缓存失败自动回退在线播放、断流自动重连
- **媒体代理**：服务端代理转发（规避跨域与防盗链），支持 Range 请求（拖动进度条）

### 歌词
- 歌词同步滚动与高亮
- 导出：复制完整歌词 / 下载 LRC 文件
- **歌词悬浮窗**（画中画）：播放时自动弹出独立悬浮窗显示歌词（需 Chrome/Edge 116+）

### 下载
- 按平台可用音质下载（128k / 320k / 无损 FLAC / B 站视频或音频）
- 流式传输（边下边存），自动根据文件头魔数识别真实格式（mp3/flac/m4a/ogg/mp4）并修正扩展名
- HEAD 预检：先返回文件大小与类型，供前端展示

### 播放管理
- 播放列表：顺序 / 随机播放，切歌、上一首/下一首
- 收藏夹：快速收藏与管理常用歌曲
- 右键菜单：播放、加入列表、收藏、下载、歌曲信息、分享（支持"从当前播放位置分享"，带时间戳跳转）
- 倍速播放、音量/静音、播放进度记忆

### 平台登录
| 平台 | 扫码 | Cookie | 手机号 |
| ---- | ---- | ------ | ------ |
| 网易云音乐 | ✅ | ✅ | ✅ |
| 酷狗音乐 | ❌ | ✅ | ✅ |
| Bilibili | ✅ | ✅ | ❌ |

- 会话持久化到本地 `.sessions/` 目录，重启后自动恢复登录态

### 界面
- 明暗双主题：按客户端时间自动切换（6:00–20:00 亮色），支持手动切换并记忆
- 全响应式布局，移动端适配
- 自定义加载动画、SVG 图标

---

## 🛡️ 安全设计

- **浏览器门禁（Gate）**：访问页面先通过 Token 挑战（动态脚本路径、3 秒过期）；门禁 Cookie 采用**动态加密名**（真实名混入随机串 + XOR 流加密 + 完整性校验），客户端 JS 完全无感；Token 绑定 **IP + 浏览器指纹**（UA 家族/语言/客户端提示），滑动续期
- **反 F12**：动态生成混淆 JS（XOR 分段编码、分块乱序、控制流平坦化、不透明谓词、蜜罐假 token、用后即焚）；检测 F12 快捷键、窗口尺寸变化、debugger 断点、webdriver、fetch 原型 hook，触发即销毁页面并上报原因
- **访问密码**：保护登录等敏感接口；支持明文或 `$sha256$<salt>$<hexdigest>` 哈希存储（明文不落盘）；登录 Cookie 动态名 + 恒定时间比较 + 限速防爆破
- **IP 速率限制**：按限速档位分桶（注册/心跳/普通 API/流式/密码验证），内存有界（空闲清理 + 容量上限兜底）
- **SSRF 防护**：代理 URL 仅允许平台官方域名白名单，解析全部 A/AAAA 记录拒绝内网/保留地址，端口白名单，手动逐跳校验重定向
- **安全响应头**：CSP（限制 connect-src 防数据外泄）、X-Frame-Options、X-Content-Type-Options；生产环境禁用 Swagger/OpenAPI
- **请求体大小限制**（1MB，超限 413），防超大包 DoS
- **单进程内存态设计**：限速与 Token 均存内存，多进程部署会破坏安全防线（详见部署注意事项）

---

## 🧰 技术栈

| 层 | 技术 |
| -- | ---- |
| 后端 | Python 3.8+ · FastAPI · Uvicorn |
| HTTP 客户端 | httpx（异步） |
| 前端 | 原生 HTML / CSS / JavaScript（无框架）· Jinja2 模板 |
| 加密 | PyCryptodome（AES/RSA）、hashlib |
| 二维码 | segno |
| 存储 | IndexedDB（前端缓存）· JSON 文件（会话持久化） |

---

## 📁 目录结构

```
MusicCatch/
├── main.py                  # FastAPI 应用入口：路由、中间件、安全防护、代理/下载
├── config.py                # 配置加载（config.ini + 命令行参数）与默认值
├── anti_devtools.py         # 反 F12 + 浏览器门禁（动态 Cookie 名、Token 挑战、JS 混淆）
├── requirements.txt         # Python 依赖
├── platforms/
│   ├── __init__.py          # 平台注册表 PLATFORMS
│   ├── base.py              # 抽象基类 MusicPlatform、Song、SearchResult
│   ├── netease.py           # 网易云音乐（weapi 加密、扫码/手机号/Cookie 登录）
│   ├── kugou.py             # 酷狗音乐（Android Lite 网关签名、设备注册、AES/RSA）
│   └── bilibili.py          # Bilibili（WBI 签名、扫码/Cookie 登录、DASH 音视频流）
├── templates/               # Jinja2 页面模板
│   ├── base.html            # 布局骨架：主题、导航、加载动画、反 F12 脚本注入
│   ├── index.html           # 主页：搜索 + 播放器 + 歌词 + 列表 + 收藏
│   ├── login.html           # 平台登录页
│   └── verify.html          # 访问密码验证页
├── static/
│   ├── css/                 # 样式（base / player / search / lyrics / playlist /
│   │                        #  favorites / context-menu / login / pip / responsive）
│   └── js/                  # 前端逻辑（app / player / search / lyrics / playlist /
│                            #  favorites / context-menu / login / pip / verify）
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

> 提示：首次访问会经过浏览器门禁挑战页（自动验证，无需操作）。

### 命令行参数

```bash
python main.py                        # 默认配置启动
python main.py --port 9000            # 指定端口
python main.py --host 127.0.0.1 --port 3000   # 指定地址和端口
python main.py --password abc123      # 启用访问密码
python main.py --https                # 反向代理 HTTPS 模式
python main.py --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem   # 本地证书 HTTPS
```

配置优先级：**命令行参数 > config.ini > 默认值**

---

## ⚙️ 配置说明

在程序同级目录下创建 `config.ini`：

```ini
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
```

| 配置项 | 默认值 | 说明 |
| ------ | ------ | ---- |
| `host` | `0.0.0.0` | 监听地址 |
| `port` | `8000` | 监听端口 |
| `password` | `musiccatch` | 访问密码（保护登录等敏感接口）；支持 `$sha256$<salt>$<hexdigest>` 哈希格式，明文不落盘；空字符串表示不启用 |
| `https` | `false` | 以 HTTPS 对外提供服务（TLS 由反向代理终止时设为 `true`）：信任代理转发头，并为 Cookie 加 Secure 标记 |
| `ssl` | `false` | 由本程序直接加载证书提供 HTTPS（不经反向代理时使用） |
| `ssl_certfile` / `ssl_keyfile` | `cert.pem` / `key.pem` | `ssl=true` 时使用的证书与私钥路径 |
| `forwarded_allow_ips` | `127.0.0.1` | `https` 模式下可信代理 IP 白名单（逗号分隔），防止伪造 X-Forwarded-For 绕过限速与 Token 指纹绑定；仅当 Nginx 与后端同机时保持默认值 |
| `video_playback` | `false` | 是否支持 B 站视频播放：`false` 时 B 站仅播放/下载音频，视频接口停用 |

> ⚠️ 默认密码 `musiccatch` 仅为开箱即用，部署到公网前务必修改。

---

## 📖 使用指南

1. **登录**（可选）：进入"登录"页，选择平台与登录方式（扫码 / Cookie / 手机号）。登录后搜索可获取更高音质。
2. **搜索**：输入关键词回车，可按平台筛选结果，支持分页。
3. **播放**：点击歌曲即可播放；B 站视频自动切换视频播放器。
4. **下载**：右键歌曲 → 下载 → 选择音质；或打开"歌曲信息"查看可用音质。
5. **歌词**：播放时右侧滑出歌词面板，可复制或下载 LRC；设置中可开启歌词悬浮窗（画中画）。
6. **收藏/列表**：播放条按钮或右键菜单管理。

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
| GET | `/api/lyrics/{platform}/{song_id}` | 获取 LRC 歌词 |
| GET/HEAD | `/api/download/{platform}/{song_id}` | 下载（`quality`: 128/320/lossless；B 站: video/audio） |
| GET | `/api/resolve-song/{platform}/{song_id}` | 歌曲完整元数据 |
| GET | `/api/info/{platform}/{song_id}` | 歌曲信息 + 可用音质列表 |
| GET | `/api/status` | 各平台登录状态 |
| POST | `/api/logout/{platform}` | 退出登录 |
| GET | `/api/proxy?url=...` | 媒体流代理（白名单 + Range 支持） |

> 除门禁注册/心跳外，所有 `/api/` 接口均需有效门禁 Token；敏感接口（登录、状态）另需密码验证。流式端点（proxy/download）限速放宽以避免误伤正常播放。

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

对应后端配置：`config.ini` 中 `https = true`，`forwarded_allow_ips` 保持 `127.0.0.1`（Nginx 与后端同机）或改为 Nginx 服务器实际 IP。

### ⚠️ 注意事项

- **保持单进程运行**：限速与门禁 Token 均为内存态，请勿使用 `uvicorn main:app --workers N` 多进程部署，否则限速阈值按 Worker 数放大、Token 不共享，安全防线失效
- **反向代理 IP 信任**：`https=true` 时若 `forwarded_allow_ips` 配置不当，所有客户端将共享代理 IP，导致限速变全局限流、Token 指纹绑定失效
- 80 端口出站受限的环境无需担心：代理层会自动将 `http://` 源站升级为 `https://` 重试

---

## 📜 免责声明

本项目仅用于技术学习与个人研究，请遵守各音乐平台的服务条款与相关法律法规。请勿将本项目用于任何商业用途或侵犯版权的内容传播。因使用本项目产生的一切法律后果由使用者自行承担。

---

## 📄 License

MIT License
