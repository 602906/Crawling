# Music Catch

基于 FastAPI 的多平台音乐搜索、在线播放与下载工具，支持酷狗音乐、网易云音乐和 Bilibili。

## 功能特性

### 搜索与播放
- **多平台聚合搜索** -- 同时搜索酷狗、网易云、B站三个平台的歌曲
- **在线播放** -- 音频/视频播放器，支持 B站视频播放、倍速播放、长按加速
- **音量控制** -- 悬停/点按弹出竖向音量滑条，支持静音，音量状态本地持久化
- **歌词同步显示** -- 支持 LRC 格式歌词，播放时自动滚动高亮，点击歌词跳转播放
- **歌词导出** -- 歌词栏一键复制完整歌词纯文本，或下载 LRC 歌词文件
- **播放列表** -- 顺序播放、列表循环、随机播放、单曲循环
- **收藏功能** -- 本地收藏歌曲，localStorage 持久化
- **音频缓存** -- IndexedDB 缓存已播放音频（最大 200MB，LRU 淘汰），写入前校验数据
  有效性，损坏缓存自动删除并回退在线播放
- **自动播放解锁** -- 自动播放被浏览器拦截时降级为静音播放，首次交互自动恢复声音

### 分享
- **分享链接** -- 右键菜单生成歌曲分享链接，打开即自动播放
- **从当前播放处分享** -- 播放中的歌曲可生成带时间点的链接（`t` 参数），打开后自动跳转到对应进度

### 下载
- **多音质下载** -- 标准 128k、高品质 320k、无损 FLAC（酷狗/网易云）
- **B站视频下载** -- 支持下载视频或仅下载音频

### 登录与安全
- **多种登录方式** -- 扫码登录、Cookie 登录、手机号验证码登录
- **登录状态持久化** -- 服务端保存 Cookie，重启后自动恢复登录
- **访问密码保护** -- 可配置密码保护登录等敏感接口，验证后发放 7 天有效期的
  HttpOnly Cookie 令牌（服务重启后失效）
- **HTTPS 支持** -- 反向代理终止 TLS 模式与本地证书直连模式两种开关，
  自动处理 Secure Cookie 与混合内容升级

### 界面
- **明暗双主题** -- 按客户端本地时间自动选择（6:00–20:00 亮色，其余暗色），
  可手动切换；页面关闭超过 1 分钟后重置为按时间判定
- **响应式 UI** -- 适配桌面端和移动端（触屏交互、地址栏颜色同步）
- **项目底栏** -- 未搜索的初始页面在播放条上方展示项目地址与联系方式链接

## 快速开始

### 从源码运行

```bash
pip install -r requirements.txt
python main.py
```

浏览器访问 `http://localhost:8000`。

### 从 exe 运行

双击 `MusicCatch.exe`，浏览器会自动打开。

## 配置

配置优先级: **命令行参数 > config.ini > 默认值**

### 命令行参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--host` | 监听地址 | `0.0.0.0` |
| `--port` | 监听端口 | `8000` |
| `--password` | 访问密码，保护登录等敏感接口 | 见 config.py |
| `--https` | 以 HTTPS 对外提供服务（反向代理终止 TLS 模式） | 关闭 |
| `--ssl` | 由本程序直接加载证书提供 HTTPS | 关闭 |
| `--ssl-certfile` | SSL 证书文件路径 | `cert.pem` |
| `--ssl-keyfile` | SSL 私钥文件路径 | `key.pem` |

```bash
python main.py --port 9000
python main.py --password abc123
python main.py --https                # 反向代理 HTTPS 模式
python main.py --ssl --ssl-certfile cert.pem --ssl-keyfile key.pem
```

### 配置文件

在程序同级目录创建 `config.ini`：

```ini
[server]
host = 0.0.0.0
port = 8000
password = 你的访问密码
https = false
ssl = false
ssl_certfile = cert.pem
ssl_keyfile = key.pem
```

- `password`：保护登录等敏感接口，留空则不启用密码验证
- `https`：TLS 在反向代理层终止时设为 `true`。本程序仍监听 HTTP，
  但会信任代理转发头（`X-Forwarded-Proto` 等）、为鉴权 Cookie 加 Secure 标记，
  并通过 `upgrade-insecure-requests` 响应头消除混合内容告警。
  反代需转发协议头，Nginx 示例：`proxy_set_header X-Forwarded-Proto $scheme;`
- `ssl`：不经反向代理、由本程序直接加载证书提供 HTTPS，
  需配合 `ssl_certfile` / `ssl_keyfile`

查看完整帮助：`python main.py --help`

## 项目结构

```
.
+-- main.py                     # FastAPI 主应用，路由与 API、密码鉴权、HTTPS 中间件
+-- config.py                   # 配置（命令行 / config.ini / 默认值）
+-- requirements.txt            # Python 依赖
+-- platforms/
|   +-- __init__.py             # 平台注册表
|   +-- base.py                 # 平台抽象基类
|   +-- kugou.py                # 酷狗音乐
|   +-- netease.py              # 网易云音乐
|   +-- bilibili.py             # Bilibili
+-- static/
|   +-- css/
|   |   +-- base.css            # 全局样式（明暗主题变量、导航、按钮、表单）
|   |   +-- search.css          # 搜索页
|   |   +-- player.css          # 播放器栏 + 视频播放器 + 音量控件
|   |   +-- lyrics.css          # 歌词面板 + 导出菜单
|   |   +-- playlist.css        # 播放列表面板
|   |   +-- favorites.css       # 收藏面板
|   |   +-- context-menu.css    # 右键菜单 + 信息弹窗 + Toast
|   |   +-- login.css           # 登录页
|   |   +-- responsive.css      # 移动端适配
|   +-- js/
|       +-- app.js              # 公共工具（缓存、收藏数据、格式化、主题切换）
|       +-- player.js           # 播放器（播放/暂停、倍速、进度、音量、自动播放解锁）
|       +-- search.js           # 搜索（过滤、分页、歌曲渲染）
|       +-- lyrics.js           # 歌词（LRC 解析、高亮同步、复制/下载导出）
|       +-- playlist.js         # 播放列表（管理、模式、持久化）
|       +-- favorites.js        # 收藏（面板、切换、播放）
|       +-- context-menu.js     # 右键菜单（下载、分享/时间点分享、歌曲信息）
|       +-- login.js            # 登录页逻辑
+-- templates/
    +-- base.html               # 基础模板（主题判定内联脚本）
    +-- index.html              # 搜索/播放主页
    +-- login.html              # 平台登录页
    +-- verify.html             # 访问密码验证页
```

## API 接口

| 方法 | 路径 | 说明 | 密码保护 |
|------|------|------|:---:|
| GET | `/` | 搜索/播放主页 | |
| GET | `/login` | 登录页（未验证时显示密码验证页） | Y |
| POST | `/api/auth/verify` | 验证访问密码，发放令牌 Cookie | |
| GET | `/api/search` | 搜索歌曲（keyword, platform, page） | |
| GET | `/api/play/{platform}/{song_id}` | 获取播放地址 | |
| GET | `/api/lyrics/{platform}/{song_id}` | 获取歌词（LRC） | |
| GET/HEAD | `/api/download/{platform}/{song_id}` | 下载歌曲（支持音质选择） | |
| GET | `/api/info/{platform}/{song_id}` | 歌曲详细信息和可用音质 | |
| GET | `/api/resolve-song/{platform}/{song_id}` | 解析歌曲元数据（分享链接用） | |
| GET | `/api/status` | 各平台登录状态 | Y |
| GET | `/api/login/qrcode/{platform}` | 获取扫码登录二维码 | Y |
| GET | `/api/login/qrcode/{platform}/check` | 轮询扫码状态 | Y |
| POST | `/api/login/cookie/{platform}` | Cookie 登录 | Y |
| POST | `/api/login/phone/{platform}` | 手机号登录 | Y |
| POST | `/api/login/phone/{platform}/send_code` | 发送验证码 | Y |
| POST | `/api/logout/{platform}` | 退出登录 | Y |
| GET | `/api/proxy` | 音视频代理（透传 Range/Referer，解决跨域） | |

分享链接格式：`/?autoplay=1&platform={平台}&id={歌曲id}[&t={秒数}]`，
带 `t` 参数时打开后自动跳转到对应播放进度。

## 各平台登录方式

| 平台 | 扫码登录 | Cookie 登录 | 手机号登录 |
|------|---------|------------|-----------|
| 酷狗音乐 | - | Y | Y |
| 网易云音乐 | Y | Y | Y |
| Bilibili | Y | Y | - |

## 依赖

- **FastAPI** -- Web 框架
- **Uvicorn** -- ASGI 服务器
- **httpx** -- 异步 HTTP 客户端
- **Jinja2** -- 模板引擎
- **segno** -- 二维码生成
- **PyCryptodome** -- 加密解密（网易云、酷狗签名）

## 技术栈

- **后端**: Python 3.10+, FastAPI, httpx (async)
- **前端**: 原生 HTML/CSS/JS, Jinja2 模板, CSS 变量明暗双主题
- **存储**: 文件系统（登录态）, IndexedDB（音频缓存）, localStorage（播放列表/收藏/主题/音量）
