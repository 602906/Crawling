# Music Catch

基于 FastAPI 的多平台音乐搜索、在线播放与下载工具，支持酷狗音乐、网易云音乐和 Bilibili。

## 功能特性

- **多平台聚合搜索** -- 同时搜索酷狗、网易云、B站三个平台的歌曲
- **多种登录方式** -- 扫码登录、Cookie 登录、手机号验证码登录
- **在线播放** -- 音频/视频播放器，支持 B站视频播放、倍速播放、长按加速
- **歌词同步显示** -- 支持 LRC 格式歌词，播放时自动滚动高亮，点击歌词跳转播放
- **多音质下载** -- 标准 128k、高品质 320k、无损 FLAC（酷狗/网易云）
- **B站视频下载** -- 支持下载视频或仅下载音频
- **播放列表** -- 顺序播放、列表循环、随机播放、单曲循环
- **收藏功能** -- 本地收藏歌曲，localStorage 持久化
- **音频缓存** -- IndexedDB 缓存已播放音频（最大 200MB），减少重复请求
- **分享链接** -- 生成歌曲分享链接，打开即可自动播放
- **登录状态持久化** -- 服务端保存 Cookie，重启后自动恢复登录
- **响应式 UI** -- 暗色主题，适配桌面端和移动端

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

```bash
python main.py --port 9000
python main.py --host 127.0.0.1 --port 3000
```

### 配置文件

在程序同级目录创建 `config.ini`：

```ini
[server]
host = 0.0.0.0
port = 8000
```

查看完整帮助：`python main.py --help`

## 项目结构

```
.
+-- main.py                     # FastAPI 主应用，路由与 API
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
|   |   +-- base.css            # 全局样式（变量、导航、按钮、表单）
|   |   +-- search.css          # 搜索页
|   |   +-- player.css          # 播放器栏 + 视频播放器
|   |   +-- lyrics.css          # 歌词面板
|   |   +-- playlist.css        # 播放列表面板
|   |   +-- favorites.css       # 收藏面板
|   |   +-- context-menu.css    # 右键菜单 + 信息弹窗 + Toast
|   |   +-- login.css           # 登录页
|   |   +-- responsive.css      # 移动端适配
|   +-- js/
|       +-- app.js              # 公共工具（缓存、收藏数据、格式化）
|       +-- player.js           # 播放器（播放/暂停、倍速、进度条）
|       +-- search.js           # 搜索（过滤、分页、歌曲渲染）
|       +-- lyrics.js           # 歌词（LRC 解析、高亮同步）
|       +-- playlist.js         # 播放列表（管理、模式、持久化）
|       +-- favorites.js        # 收藏（面板、切换、播放）
|       +-- context-menu.js     # 右键菜单（下载、分享、歌曲信息）
|       +-- login.js            # 登录页逻辑
+-- templates/
    +-- base.html               # 基础模板
    +-- index.html              # 搜索/播放主页
    +-- login.html              # 平台登录页
```

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 搜索/播放主页 |
| GET | `/login` | 登录页 |
| GET | `/api/search` | 搜索歌曲（keyword, platform, page） |
| GET | `/api/play/{platform}/{song_id}` | 获取播放地址 |
| GET | `/api/lyrics/{platform}/{song_id}` | 获取歌词（LRC） |
| GET | `/api/download/{platform}/{song_id}` | 下载歌曲（支持音质选择） |
| GET | `/api/info/{platform}/{song_id}` | 歌曲详细信息和可用音质 |
| GET | `/api/resolve-song/{platform}/{song_id}` | 解析歌曲元数据 |
| GET | `/api/status` | 各平台登录状态 |
| GET | `/api/login/qrcode/{platform}` | 获取扫码登录二维码 |
| GET | `/api/login/qrcode/{platform}/check` | 轮询扫码状态 |
| POST | `/api/login/cookie/{platform}` | Cookie 登录 |
| POST | `/api/login/phone/{platform}` | 手机号登录 |
| POST | `/api/login/phone/{platform}/send_code` | 发送验证码 |
| POST | `/api/logout/{platform}` | 退出登录 |
| GET | `/api/proxy` | 音频代理（解决跨域） |

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
- **前端**: 原生 HTML/CSS/JS, Jinja2 模板
- **存储**: 文件系统（登录态）, IndexedDB（音频缓存）, localStorage（播放列表/收藏）
