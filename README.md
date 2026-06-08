# Music Catch

一个基于 FastAPI 的多平台音乐搜索、在线播放与下载工具，支持酷狗音乐、网易云音乐和 Bilibili。

## 功能特性

- **多平台聚合搜索** — 同时搜索酷狗、网易云、B站三个平台的歌曲
- **多种登录方式** — 扫码登录、Cookie 登录、手机号验证码登录
- **在线播放** — 音频/视频播放器，支持 B站视频播放、倍速播放
- **歌词同步显示** — 支持 LRC 格式歌词，播放时自动滚动高亮
- **多音质下载** — 标准 128k、高品质 320k、无损 FLAC（酷狗/网易云）
- **B站视频下载** — 支持下载视频或仅下载音频
- **播放列表** — 顺序播放、列表循环、随机播放、单曲循环
- **收藏功能** — 本地收藏歌曲，localStorage 持久化
- **音频缓存** — IndexedDB 缓存已播放音频，减少重复请求
- **分享链接** — 生成歌曲分享链接，打开即可自动播放
- **登录状态持久化** — 服务端保存 Cookie，重启后自动恢复登录
- **响应式 UI** — 暗色主题，适配桌面端和移动端

## 项目结构

```
.
├── main.py                 # FastAPI 主应用，所有路由和 API 接口
├── config.py               # 配置（监听地址、端口、下载目录）
├── requirements.txt        # Python 依赖
├── platforms/
│   ├── __init__.py         # 平台注册表
│   ├── base.py             # 平台抽象基类 (MusicPlatform, Song, SearchResult)
│   ├── kugou.py            # 酷狗音乐平台实现
│   ├── netease.py          # 网易云音乐平台实现
│   └── bilibili.py         # Bilibili 平台实现
├── static/
│   ├── css/style.css       # 全局样式（暗色主题）
│   └── js/app.js           # 前端公共工具函数
└── templates/
    ├── base.html           # 基础模板（导航栏、缓存清除）
    ├── index.html          # 搜索/播放主页
    └── login.html          # 平台登录页
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动服务

```bash
python main.py
```

服务默认监听 `http://0.0.0.0:8000`，可在 `config.py` 中修改。

### 3. 使用

1. 打开浏览器访问 `http://localhost:8000`
2. 在搜索栏输入关键词，选择平台或搜索全部
3. 点击播放按钮在线播放，右键或点击「...」可下载/查看信息
4. 进入「登录」页面，选择平台并通过扫码/Cookie/手机号登录

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search` | 搜索歌曲，支持 `keyword`、`platform`、`page` 参数 |
| GET | `/api/play/{platform}/{song_id}` | 获取播放地址 |
| GET | `/api/lyrics/{platform}/{song_id}` | 获取歌词（LRC 格式） |
| GET | `/api/download/{platform}/{song_id}` | 流式下载歌曲，支持音质选择 |
| GET | `/api/info/{platform}/{song_id}` | 获取歌曲详细信息和可用音质 |
| GET | `/api/resolve-song/{platform}/{song_id}` | 解析歌曲完整元数据 |
| GET | `/api/status` | 获取所有平台登录状态 |
| GET | `/api/login/qrcode/{platform}` | 获取扫码登录二维码 |
| GET | `/api/login/qrcode/{platform}/check` | 轮询二维码扫码状态 |
| POST | `/api/login/cookie/{platform}` | Cookie 登录 |
| POST | `/api/login/phone/{platform}` | 手机号登录 |
| POST | `/api/login/phone/{platform}/send_code` | 发送手机验证码 |
| POST | `/api/logout/{platform}` | 退出登录 |
| GET | `/api/proxy` | 音频代理（解决跨域问题） |

## 各平台支持的登录方式

| 平台 | 扫码登录 | Cookie 登录 | 手机号登录 |
|------|---------|------------|-----------|
| 酷狗音乐 | - | ✓ | ✓ |
| 网易云音乐 | ✓ | ✓ | ✓ |
| Bilibili | ✓ | ✓ | - |

## 依赖

- **FastAPI** — Web 框架
- **Uvicorn** — ASGI 服务器
- **httpx** — 异步 HTTP 客户端
- **Jinja2** — 模板引擎
- **segno** — 二维码生成
- **PyCryptodome** — 加密/解密（网易云、酷狗签名）

## 技术栈

- **后端**: Python 3.10+, FastAPI, httpx (async)
- **前端**: 原生 HTML/CSS/JS, Jinja2 模板
- **存储**: 文件系统（登录态持久化）, IndexedDB（音频缓存）, localStorage（播放列表/收藏）
