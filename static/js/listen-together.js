/* 一起听歌：房间列表 + 房间内实时同步播放（双传输：HTTP 长轮询或 WebSocket，由 config.LT_TRANSPORT 统一决定）。
   身份：用户名存 localStorage（听客户端模型：服务端不绑定 IP、不做全局唯一、改名无次数限制），
   进房时服务端下发会话 Cookie（HttpOnly），刷新页面凭 Cookie 恢复本人身份；
   门禁 token 仅用于接口访问校验（cookie 自动携带），失效时自动重新注册并重连，不打断播放。 */
(function () {
    'use strict';

    // 播放器控件图标（内联 SVG，currentColor 继承颜色，跨设备渲染一致）
    const ICON_PLAY = '<svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>';
    const ICON_PAUSE = '<svg viewBox="0 0 24 24" width="28" height="28" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>';
    const SYNC_INTERVAL = 5000;  // 播放位置上报间隔（毫秒），与 config.LT_SYNC_INTERVAL 一致

    const $ = (id) => document.getElementById(id);
    const audio = $('ltAudio');

    let meName = '';
    let roomId = null;       // 当前房间 id（1-10）或 null
    let roomData = null;     // 最近一次服务端 state
    let localPlaying = false;
    let localManual = false;   // 非房主本地手动控制：播放/暂停不同步房间，且不被房间状态强制覆盖
    let pendingIndex = -1;   // 正在加载的歌曲序号（防切歌竞态）
    let seekLock = false;    // 本地拖动进度时防同步回跳
    let syncTimer = null;
    let pollVersion = -1;    // 最近收到的房间 version（轮询增量条件）
    let pollAbort = null;    // 当前轮询请求的 AbortController（离开时中断）
    let pollTimer = null;    // 断线重连定时器
    let reconnectCount = 0;  // 连续断开次数，超过 3 次停止自动重连
    let nameMaxLen = 20;     // 名称长度上限（启动时从 /config 拉取，跟随 config.py，拉取失败用默认值）
    let ltTransport = 'http';  // 传输方式：'http'（长轮询）或 'ws'（WebSocket，config.LT_TRANSPORT）
    let wsUrl = '';          // WebSocket 连接地址覆盖（config.LT_WS_URL，空=当前域名）
    let ws = null;            // 当前 WebSocket（ws 模式：列表页即建立的全局连接，进房/离开走消息）
    let wsHeartbeat = null;   // WS 心跳定时器（30s，续期成员在线）
    let pendingEnter = null;  // 待进房房间 id（连接就绪后发送 enter：分享链接/断线重连恢复）

    // ── 工具 ──
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[c]));
    }

    function toast(msg) {
        if (typeof showToast === 'function') showToast(msg);
        else alert(msg);
    }

    function fmtTime(s) {
        s = Math.max(0, Math.floor(s || 0));
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }

    async function postJSON(url, body) {
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
            const err = new Error(data.detail || '请求失败');
            err.status = resp.status;
            throw err;
        }
        return data;
    }

    // ── 昵称 ──
    function showNameModal(title, hint, onConfirm) {
        $('ltNameModalTitle').textContent = title;
        $('ltNameModalHint').textContent = hint;
        $('ltNameInput').value = '';
        $('ltNameInput').maxLength = nameMaxLen;  // 输入框上限跟随 config.py
        $('ltNameModal').classList.remove('hidden');
        $('ltNameConfirm').onclick = () => {
            const name = $('ltNameInput').value.trim();
            if (!name) return;
            // 码点计数与后端 len() 一致（emoji 等算 1 个字符；maxlength 数的是 UTF-16 码元）
            if ([...name].length > nameMaxLen) {
                toast('昵称过长（最多 ' + nameMaxLen + ' 个字符）');
                return;
            }
            $('ltNameModal').classList.add('hidden');
            onConfirm(name);
        };
        setTimeout(() => $('ltNameInput').focus(), 50);
    }

    function applyName(name) {
        meName = name;
        try { localStorage.setItem('mc_lt_name', meName); } catch (e) {}
        $('ltMyName').textContent = meName;
    }

    async function ensureName() {
        let saved = '';
        try { saved = (localStorage.getItem('mc_lt_name') || '').trim(); } catch (e) {}
        try {
            const data = await postJSON('/api/listen-together/join', { name: saved });
            if (!data.need_input) {
                applyName(data.name);
                return;
            }
        } catch (e) { /* 名字被占用等：走输入框 */ }
        showNameModal('设置你的昵称', '进入一起听歌需要先设置昵称，昵称保存在本机浏览器', (name) => submitName(name));
    }

    async function submitName(name) {
        try {
            const data = await postJSON('/api/listen-together/join', { name });
            applyName(data.name);
            loadRooms();
        } catch (e) {
            // 重名等一律只提示，不弹窗（服务端 join 目前不做占用检查，此分支为兜底）
            toast(e.status === 403 ? e.message : '设置失败，请重试');
        }
    }

    async function renameUser(name) {
        try {
            const data = await postJSON('/api/listen-together/rename', { name });
            applyName(data.name);
            toast('昵称已修改');
        } catch (e) {
            if (e.status === 403) toast(e.message);
            else if (e.status === 401) ensureName();
            else toast('修改失败，请重试');
        }
    }
    $('ltRenameBtn').onclick = () => {
        showNameModal('修改昵称', '昵称保存在本机浏览器', (name) => renameUser(name));
    };

    // ── 房间列表 ──
    async function loadRooms() {
        try {
            const resp = await fetch('/api/listen-together/rooms?name=' + encodeURIComponent(meName));
            const data = await resp.json();
            renderRooms(data.rooms || []);
        } catch (e) { /* 断网/门禁失效时不打扰 */ }
    }

    function renderRooms(rooms) {
        const grid = $('ltRoomGrid');
        grid.innerHTML = rooms.map((r) => `
            <div class="lt-room-card">
                <div class="lt-room-name">${esc(r.name)}</div>
                <div class="lt-room-meta">在线 <b>${r.online}</b> 人 · 房主 <b>${esc(r.owner_name || '-')}</b></div>
                <div class="lt-room-song">${esc(r.current_song || '暂无播放')}</div>
                <button class="lt-room-enter" data-id="${r.id}">进入房间</button>
            </div>`).join('');
        grid.querySelectorAll('.lt-room-enter').forEach((btn) => {
            btn.onclick = () => enterRoom(parseInt(btn.dataset.id, 10));
        });
    }

    // ── 进入/离开房间 ──
    // 进房前先预检重名（零副作用）：重名只提示、不进房，避免进房请求清理房主导致其播放被重置
    async function enterRoom(id, retried) {
        if (ltTransport === 'ws') {
            // ws 模式：进房走 WS 消息（服务端校验重名/房间，enter_ok/enter_fail 决定界面切换）
            pendingEnter = id;
            if (ws && ws.readyState === 1) wsSend({ t: 'enter', room: id });
            else connectWs();  // 连接未就绪：onopen 时补发
            return;
        }
        try {
            const resp = await fetch('/api/listen-together/precheck?room_id=' + id +
                '&name=' + encodeURIComponent(meName));
            const data = await resp.json().catch(() => ({}));
            if (resp.status === 403) {
                // 403 两种含义：真重名（固定文案）→ 只提示不进房；门禁失效等其他 403 → 恢复门禁后重试一次
                if (data.detail === DUPLICATE_MSG) {
                    toast(data.detail);
                    return;
                }
                if (!retried) {
                    await recoverGate();
                    return enterRoom(id, true);
                }
                toast('进入失败，请重试');
                return;
            }
            if (!resp.ok) { toast('进入失败，请重试'); return; }
        } catch (e) { toast('进入失败，请重试'); return; }
        roomId = id;
        roomData = null;
        localManual = false;
        pollVersion = -1;
        reconnectCount = 0;
        $('ltLobby').classList.add('hidden');
        $('ltRoom').classList.remove('hidden');
        $('ltSearchPanel').classList.add('hidden');
        schedulePoll();
    }

    function leaveRoom() {
        const rid = roomId;
        roomId = null;
        pendingEnter = null;
        roomData = null;
        localManual = false;
        pendingIndex = -1;
        if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
        if (pollAbort) { try { pollAbort.abort(); } catch (e) {} pollAbort = null; }
        stopSyncTimer();
        audio.pause();
        audio.removeAttribute('src');
        localPlaying = false;
        updatePlayIcon();
        resetLyrics();
        hideLyricsPanel();
        $('ltRoom').classList.add('hidden');
        $('ltLobby').classList.remove('hidden');
        if (ltTransport === 'ws') {
            // ws 模式：连接保持（回列表模式），列表由服务端推送刷新；显式离开经 WS 消息
            wsSend({ t: 'leave' });
        } else {
            loadRooms();
            // 显式离开（失败无妨，服务端 TTL 兜底清理）
            fetch('/api/listen-together/leave?room_id=' + rid + '&name=' + encodeURIComponent(meName), { method: 'POST' }).catch(() => {});
        }
    }
    $('ltBackBtn').onclick = leaveRoom;

    // ── 长轮询 / WebSocket：连续拉取房间状态（轮询即心跳，无活动时服务端挂起后超时返回）──
    function schedulePoll(delay) {
        if (pollTimer) clearTimeout(pollTimer);
        pollTimer = setTimeout(ltTransport === 'ws' ? connectWs : pollLoop, delay || 0);
    }

    // ws 模式消息发送（连接未就绪返回 false，由调用方提示；重连由 onclose → schedulePoll 负责）
    function wsSend(obj) {
        if (ws && ws.readyState === 1) {
            ws.send(JSON.stringify(obj));
            return true;
        }
        return false;
    }

    // ── WebSocket 实时通道（config.LT_TRANSPORT="ws"）：列表页即建立的全局连接 ──
    // 连接建立即订阅房间列表（服务端推 rooms，替代 10s HTTP 轮询）；进房走 enter 消息
    // （enter_ok/enter_fail 决定界面切换），离开走 leave 消息（连接保持回列表模式）；
    // 进度按需：新成员进房时服务端询问房主（ask_sync），房主应答一次（t=sync），不再周期上报。
    // 连接地址：config.LT_WS_URL 配置完整 WS 地址时从该地址连接，空=当前域名默认端点
    function connectWs() {
        if (!meName) return;
        if (ws) return;  // 已有连接（建立中/已建立/关闭中）不重复创建；onclose 置空后才允许重建
        let url = wsUrl;
        if (!url) {
            const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
            url = proto + location.host + '/api/listen-together/ws';
        }
        ws = new WebSocket(url + (url.includes('?') ? '&' : '?') + 'name=' + encodeURIComponent(meName));
        ws.onopen = () => {
            // 心跳 30s：服务端任何消息都续期成员在线（TTL 90s），并清理其他断线成员
            wsHeartbeat = setInterval(() => {
                if (ws && ws.readyState === 1) ws.send(JSON.stringify({ t: 'ping' }));
            }, 30000);
            if (pendingEnter) wsSend({ t: 'enter', room: pendingEnter });  // 补发进房（重连恢复/分享链接）
        };
        ws.onmessage = (ev) => {
            try {
                const msg = JSON.parse(ev.data);
                if (msg.type === 'rooms') {
                    if (!roomId) renderRooms(msg.rooms || []);  // 列表模式：实时刷新房间列表
                } else if (msg.type === 'state') {
                    if (!roomId) return;
                    reconnectCount = 0;  // 收到状态即连接健康，清零断线计数
                    applyState(msg.room);
                } else if (msg.type === 'ask_sync') {
                    // 服务端询问当前进度（新成员进房时）：房主本地应答一次（按需，替代周期上报）
                    if (roomData && roomData.owner === meName && audio.duration && !audio.paused) {
                        wsSend({ t: 'sync', pos: audio.currentTime });
                    }
                } else if (msg.type === 'enter_ok') {
                    pendingEnter = null;
                    reconnectCount = 0;
                    roomId = msg.room.id;
                    roomData = null;
                    localManual = false;
                    $('ltLobby').classList.add('hidden');
                    $('ltRoom').classList.remove('hidden');
                    $('ltSearchPanel').classList.add('hidden');
                    applyState(msg.room);
                } else if (msg.type === 'enter_fail') {
                    pendingEnter = null;
                    toast(msg.reason || '进入失败');
                }
            } catch (e) {}
        };
        ws.onclose = (ev) => {
            clearInterval(wsHeartbeat);
            wsHeartbeat = null;
            ws = null;
            if (roomId) pendingEnter = roomId;  // 房间内断线：重连后自动恢复进房（凭会话 cookie 识别本人）
            // 握手阶段门禁失效（token 过期/服务重启）表现为 1006 或 1008 Forbidden：
            // 先重新注册门禁再重连，避免带着失效 token 无限重连（房主播放不受影响）；
            // 重名等进房拒绝走 enter_fail 消息（连接保持），此处不再区分
            reconnectCount++;
            if (reconnectCount > 3) {
                toast('连接失败，请刷新页面重试');
                return;
            }
            toast('连接已断开，正在重连...');
            recoverGate().then(() => schedulePoll(3000));
        };
    }

    // 403 的两种含义：重名进房被拒（detail 固定文案）→ 回列表页；
    // 门禁失效等其他 403（detail=Forbidden）→ 重新注册门禁并重连，绝不离开房间
    const DUPLICATE_MSG = '该用户名已在房间中，进入失败';
    async function recoverGate() {
        try { await fetch('/api/gate/register', { credentials: 'same-origin' }); } catch (e) {}
    }

    async function pollLoop() {
        if (!roomId) return;
        const ctrl = new AbortController();
        pollAbort = ctrl;
        try {
            const resp = await fetch('/api/listen-together/poll?room_id=' + roomId +
                '&version=' + pollVersion + '&name=' + encodeURIComponent(meName), { signal: ctrl.signal });
            const data = await resp.json().catch(() => ({}));
            if (!roomId) return;  // 等待期间已离开
            if (!resp.ok) {
                if (resp.status === 401) { leaveRoom(); ensureName(); return; }  // 未设置用户名
                if (resp.status === 404) { toast('房间不存在'); leaveRoom(); return; }
                if (resp.status === 403 && data.detail === DUPLICATE_MSG) {  // 真重名：仅提示并回列表页
                    toast(data.detail);
                    leaveRoom();
                    return;
                }
                if (resp.status === 403 || resp.status === 429) {
                    // 门禁失效/限速：重新注册门禁后重连（房主播放/暂停均不因门禁过期被踢回列表）
                    await recoverGate();
                    throw new Error('gate');
                }
                throw new Error(data.detail || '同步失败');
            }
            reconnectCount = 0;  // 重连成功后清零，避免累计超限后永久停摆
            pollVersion = data.room ? data.room.version : -1;
            applyState(data.room);
            schedulePoll();  // 立即续接下一轮
        } catch (e) {
            if (!roomId || e.name === 'AbortError') return;
            reconnectCount++;
            if (reconnectCount > 3) {
                toast('连接失败，请刷新页面重试');
                return;
            }
            toast('连接已断开，正在重连...');
            schedulePoll(3000);
        }
    }

    // 发送房间动作并应用返回的最新状态（ws 模式走通道，状态由服务端推送）
    async function sendAction(type, data) {
        if (!roomId) return;
        if (ltTransport === 'ws') {
            if (!wsSend({ t: 'action', a: Object.assign({ type: type }, data || {}) })) {
                toast('连接已断开，正在重连...');  // 断线期间操作被丢弃：提示并等重连（连接恢复后状态自动同步）
            }
            return;
        }
        try {
            const resp = await postJSON('/api/listen-together/action?room_id=' + roomId +
                '&name=' + encodeURIComponent(meName),
                Object.assign({ type: type }, data || {}));
            if (roomId && resp.room) {
                pollVersion = resp.room.version;
                applyState(resp.room);
            }
        } catch (e) {
            if (e.status === 401) { leaveRoom(); ensureName(); return; }
            if (e.status === 403 && e.message === DUPLICATE_MSG) { toast(e.message); return; }
            if (e.status === 403 || e.status === 429) { recoverGate(); toast('连接已断开，正在重连...'); return; }
            toast(e.message || '操作失败');
        }
    }

    // 房主位置上报（仅 http 模式周期调用；ws 模式改为按需应答 ask_sync，见 connectWs）
    function reportSync() {
        if (!roomId) return;
        fetch('/api/listen-together/action?room_id=' + roomId + '&name=' + encodeURIComponent(meName), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ type: 'sync', position: audio.currentTime }),
        }).catch(() => {});
    }

    function applyState(room) {
        const prev = roomData;
        roomData = room;
        $('ltRoomName').textContent = room.name;
        $('ltOnline').textContent = '在线 ' + room.members.length + ' 人';
        // 播放控制：暂停/切歌（同步房间）仅房主；播放/暂停按钮所有人可见，
        // 非房主点击为本地控制（不同步房间）
        const isOwner = room.owner === meName;
        $('ltRenameRoomBtn').classList.toggle('hidden', !isOwner);
        $('ltPrevBtn').classList.toggle('hidden', !isOwner);
        $('ltPlayBtn').classList.toggle('hidden', false);
        $('ltNextBtn').classList.toggle('hidden', !isOwner);
        $('ltProgress').disabled = !isOwner;
        renderMembers(room);
        renderQueue(room);
        const song = room.queue[room.current_index];
        if (song) {
            $('ltNowPlaying').innerHTML = esc(song.name) + '<span class="lt-now-sub">' +
                esc(song.artist || '未知艺人') + ' · ' + esc(song.platform) + '</span>';
        } else {
            $('ltNowPlaying').textContent = '暂无播放';
        }
        // 切歌检测：序号变化或歌曲对象变化（同一序号被删除替换）
        const prevSong = prev ? prev.queue[prev.current_index] : null;
        const curSong = room.queue[room.current_index];
        const changed = (prev ? prev.current_index : -2) !== room.current_index ||
            (prevSong && curSong && prevSong.id !== curSong.id) ||
            Boolean(curSong) !== Boolean(prevSong);
        if (changed) {
            localManual = false;  // 切歌后恢复跟随房间
            if (curSong) loadSong(room.current_index, room.playing);
            else stopLocal();
        } else if (localManual) {
            // 本地手动模式：不操作播放（恢复播放的对齐在播放按钮里处理），
            // roomData 已整体更新，进度以轮询到的房主进度为准
        } else if (isOwner) {
            // 房主：本地播放即为权威，不校验/校准任何进度（服务端以房主上报进度为准）
        } else if (room.playing) {
            if (audio.paused && !seekLock) audio.play().catch(() => {});
            // 位置校准：偏差超过 1.5s 才跳，避免频繁打断
            const target = room.position + (Date.now() / 1000 - (room.ts || Date.now() / 1000));
            if (!seekLock && audio.duration && Math.abs(audio.currentTime - target) > 1.5) {
                audio.currentTime = target;
            }
        } else if (!room.playing && !audio.paused) {
            audio.pause();
        }
    }

    // ── 歌词（复用主播放器 lyrics.js 侧栏面板：加载/高亮/导出/PiP 悬浮窗）──
    // 字段归一后调全局 fetchLyrics，面板、导出、悬浮窗与主页完全一致
    function loadLyrics(song) {
        if (typeof fetchLyrics !== 'function') return;  // lyrics.js 未加载时静默降级
        fetchLyrics({
            platform: song.platform,
            id: song.id,
            name: song.name,
            artist: song.artist || '',
            duration: song.duration || 0,
            extra: song.extra || null,
        });
    }

    function resetLyrics() {
        // 清空全局歌词状态（lyrics.js 顶层变量），防切歌/离开后残留
        lyricsData = [];
        lyricsRaw = '';
        lyricsSong = null;
        currentLyricIndex = -1;
        const title = $('lyricsTitle');
        if (title) title.textContent = '歌词';
        const exportBtn = $('lyricsExport');
        if (exportBtn) exportBtn.style.display = 'none';
        if (typeof pipRenderLyrics === 'function') pipRenderLyrics([]);
        if (typeof pipSetTitle === 'function') pipSetTitle('歌词');
    }

    function hideLyricsPanel() {
        const panel = $('lyricsPanel');
        if (panel && !panel.classList.contains('hidden')) panel.classList.add('hidden');
    }

    // ── 播放 ──
    function updatePlayIcon() {
        $('ltPlayBtn').innerHTML = localPlaying ? ICON_PAUSE : ICON_PLAY;
    }

    function stopLocal() {
        audio.pause();
        audio.removeAttribute('src');
        localPlaying = false;
        updatePlayIcon();
        $('ltProgress').value = 0;
        $('ltTime').textContent = '0:00 / 0:00';
        $('ltNowPlaying').textContent = '暂无播放';
        resetLyrics();
    }

    async function loadSong(index, autoplay) {
        const song = roomData.queue[index];
        if (!song) return;
        pendingIndex = index;
        try {
            const extra = song.extra ? encodeURIComponent(JSON.stringify(song.extra)) : '';
            const resp = await fetch('/api/play/' + encodeURIComponent(song.platform) + '/' +
                encodeURIComponent(song.id) + '?extra=' + extra + '&room_id=' + roomId);
            const data = await resp.json();
            if (pendingIndex !== index || !roomData) return;  // 已切歌/已离开
            audio.src = '/api/proxy?url=' + encodeURIComponent(data.url);
            loadLyrics(song);  // 歌词与播放并行加载（复用主播放器侧栏面板）
            // 首次加载对齐进度：播放中按服务端 position + 已流逝时间推算，暂停则停在原位置
            const target = roomData.playing
                ? roomData.position + (Date.now() / 1000 - (roomData.ts || Date.now() / 1000))
                : roomData.position;
            audio.addEventListener('loadedmetadata', () => {
                audio.currentTime = Math.max(0, target);
            }, { once: true });
            if (autoplay) audio.play().catch(() => {});
        } catch (e) {
            if (pendingIndex === index) toast('加载歌曲失败');
        }
    }

    function startSyncTimer() {
        stopSyncTimer();
        if (ltTransport === 'ws') return;  // ws 模式：进度按需应答（ask_sync），不周期上报
        syncTimer = setInterval(() => {
            // 位置上报仅房主发起，全员对齐房主进度
            if (!audio.paused && roomData && !localManual && roomData.owner === meName) {
                reportSync();
            }
        }, SYNC_INTERVAL);
    }

    function stopSyncTimer() {
        if (syncTimer) { clearInterval(syncTimer); syncTimer = null; }
    }

    audio.addEventListener('timeupdate', () => {
        if (seekLock || !roomData) return;
        const dur = audio.duration || 0;
        $('ltProgress').value = dur ? (audio.currentTime / dur) * 100 : 0;
        $('ltTime').textContent = fmtTime(audio.currentTime) + ' / ' + fmtTime(dur);
        if (typeof updateLyricsHighlight === 'function') updateLyricsHighlight(audio.currentTime);
    });
    audio.addEventListener('play', () => { localPlaying = true; updatePlayIcon(); startSyncTimer(); });
    audio.addEventListener('pause', () => { localPlaying = false; updatePlayIcon(); stopSyncTimer(); });
    audio.addEventListener('ended', () => {
        if (roomData && roomData.owner !== meName) return;  // 切歌仅房主触发
        sendAction('next');
    });

    // 播放控制（状态以服务端广播为准；非房主为本地控制，不同步房间）
    $('ltPlayBtn').onclick = () => {
        if (!roomData || roomData.current_index < 0) return;
        if (roomData.owner !== meName) {
            localManual = true;
            if (audio.paused) {
                // 恢复播放前对齐到房间当前进度（position + 已流逝时间）
                const target = roomData.position + (Date.now() / 1000 - (roomData.ts || Date.now() / 1000));
                if (audio.duration && Math.abs(audio.currentTime - target) > 1.5) {
                    audio.currentTime = target;
                }
                audio.play().catch(() => {});
            } else {
                audio.pause();
            }
            return;
        }
        const willPlay = !roomData.playing;
        sendAction(willPlay ? 'play' : 'pause',
            willPlay ? { index: roomData.current_index } : {});
        // 房主本地直接执行（进度权威在本地，不依赖状态回写强制播放/暂停）
        if (willPlay) audio.play().catch(() => {});
        else audio.pause();
    };
    $('ltPrevBtn').onclick = () => sendAction('prev');
    $('ltNextBtn').onclick = () => sendAction('next');

    // 进度条拖动
    $('ltProgress').addEventListener('input', () => {
        if (!audio.duration) return;
        seekLock = true;
        const pos = ($('ltProgress').value / 100) * audio.duration;
        audio.currentTime = pos;
        $('ltTime').textContent = fmtTime(pos) + ' / ' + fmtTime(audio.duration);
    });
    $('ltProgress').addEventListener('change', () => {
        seekLock = false;
        sendAction('seek', { position: audio.currentTime || 0 });
    });

    // ── 音量（本地独立：不参与房间同步；与主页共用 mc_volume/mc_muted，跨标签页实时联动）──
    const VOL_SVG = {
        high: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>',
        low: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M5 9v6h4l5 5V4L9 9H5zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>',
        muted: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>',
    };
    let _vol = 1;
    let _muted = false;
    function ltApplyVolume() {
        audio.volume = _vol;
        audio.muted = _muted;
        const btn = $('ltVolumeBtn');
        btn.innerHTML = (_muted || _vol === 0) ? VOL_SVG.muted : (_vol < 0.5 ? VOL_SVG.low : VOL_SVG.high);
        btn.title = _muted ? '取消静音' : '静音';
        $('ltVolumeSlider').value = Math.round(_vol * 100);
    }
    function ltSaveVolume() {
        try {
            localStorage.setItem('mc_volume', String(_vol));
            localStorage.setItem('mc_muted', _muted ? '1' : '0');
        } catch (e) {}
    }
    (function ltLoadVolume() {
        try {
            const v = parseFloat(localStorage.getItem('mc_volume'));
            if (!isNaN(v)) _vol = Math.min(1, Math.max(0, v));
            _muted = localStorage.getItem('mc_muted') === '1';
        } catch (e) {}
        ltApplyVolume();
    })();
    $('ltVolumeSlider').addEventListener('input', () => {
        _vol = parseInt($('ltVolumeSlider').value, 10) / 100;
        if (_vol > 0 && _muted) _muted = false;  // 拖动滑条自动解除静音
        ltApplyVolume();
        ltSaveVolume();
    });
    $('ltVolumeBtn').onclick = () => {
        // 触屏设备无 hover：点按钮改为展开/收起音量面板，静音靠拖到 0
        if (window.matchMedia && window.matchMedia('(hover: none)').matches) {
            $('ltVolumePopup').classList.toggle('open');
            return;
        }
        _muted = !_muted;
        ltApplyVolume();
        ltSaveVolume();
    };
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.volume-control')) $('ltVolumePopup').classList.remove('open');
    });
    // 主页等其他标签页调整音量时实时联动
    window.addEventListener('storage', (e) => {
        if (e.key === 'mc_volume' && e.newValue !== null) {
            const v = parseFloat(e.newValue);
            if (!isNaN(v)) { _vol = Math.min(1, Math.max(0, v)); ltApplyVolume(); }
        } else if (e.key === 'mc_muted') {
            _muted = e.newValue === '1';
            ltApplyVolume();
        }
    });

    // ── 成员 / 队列渲染 ──
    function renderMembers(room) {
        const box = $('ltMembers');
        if (!room.members.length) {
            box.innerHTML = '<div class="lt-member-empty">暂无成员</div>';
            return;
        }
        const isOwner = room.owner === meName;
        box.innerHTML = room.members.map((m) => {
            const isMe = m.name === meName;
            const tag = room.owner === m.name
                ? '<span class="lt-member-tag">房主</span>'
                : (isOwner ? '<button class="lt-transfer-btn" data-transfer="' + esc(m.name) + '">转让</button>' : '');
            return '<div class="lt-member-item"><span class="lt-member-name">' + esc(m.name) +
                (isMe ? '（我）' : '') + '</span>' + tag + '</div>';
        }).join('');
        box.querySelectorAll('.lt-transfer-btn').forEach((btn) => {
            btn.onclick = () => sendAction('transfer', { target: btn.dataset.transfer });
        });
    }

    function renderQueue(room) {
        const list = $('ltQueueList');
        if (!room.queue.length) {
            list.innerHTML = '<div class="lt-queue-empty">队列为空，点击右上角"添加歌曲"</div>';
            return;
        }
        const isOwner = room.owner === meName;
        list.innerHTML = room.queue.map((s, i) => {
            const cur = i === room.current_index ? ' current' : '';
            const remove = isOwner ? '<button class="lt-remove-btn" data-index="' + i + '">删除</button>' : '';
            return '<div class="lt-queue-item' + cur + '" data-index="' + i + '">' +
                '<div class="lt-queue-info"><div class="lt-queue-title">' + esc(s.name) + '</div>' +
                '<div class="lt-queue-sub">' + esc(s.artist || '未知艺人') + ' · ' + esc(s.platform) +
                ' · ' + esc(s.added_by_name) + ' 添加</div></div>' + remove + '</div>';
        }).join('');
        list.querySelectorAll('.lt-queue-item').forEach((item) => {
            item.addEventListener('click', (e) => {
                if (!isOwner || e.target.closest('.lt-remove-btn')) return;  // 点歌=播放，仅房主
                sendAction('play', { index: parseInt(item.dataset.index, 10) });
            });
        });
        list.querySelectorAll('.lt-remove-btn').forEach((btn) => {
            btn.onclick = () => sendAction('remove', { index: parseInt(btn.dataset.index, 10) });
        });
    }

    // ── 搜索添加歌曲 ──
    $('ltAddBtn').onclick = () => {
        const panel = $('ltSearchPanel');
        const willShow = panel.classList.contains('hidden');
        panel.classList.toggle('hidden', !willShow);
        if (willShow) setTimeout(() => $('ltSearchInput').focus(), 50);
    };
    $('ltSearchClose').onclick = () => $('ltSearchPanel').classList.add('hidden');
    $('ltSearchGo').onclick = doSearch;
    $('ltSearchInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });

    async function doSearch() {
        const kw = $('ltSearchInput').value.trim();
        if (!kw) return;
        $('ltSearchResults').innerHTML = '<div class="lt-search-empty">搜索中...</div>';
        try {
            const resp = await fetch('/api/search?keyword=' + encodeURIComponent(kw));
            const data = await resp.json();
            const songs = data.songs || [];
            if (!songs.length) {
                $('ltSearchResults').innerHTML = '<div class="lt-search-empty">没有找到相关歌曲</div>';
                return;
            }
            $('ltSearchResults').innerHTML = songs.map((s, i) => {
                const cover = s.cover
                    ? '<img class="lt-search-cover" src="' + esc(s.cover) + '" referrerpolicy="no-referrer" alt="" onerror="this.style.display=\'none\'">'
                    : '<div class="lt-search-cover lt-search-cover-empty"></div>';
                return '<div class="lt-search-item">' + cover +
                    '<div class="lt-search-info">' +
                    '<div class="lt-search-title">' + esc(s.name) + '</div>' +
                    '<div class="lt-search-sub">' + esc(s.artist || '未知艺人') +
                    '<span class="platform-badge badge-' + esc(s.platform) + '">' + esc(platformName(s.platform)) + '</span>' +
                    (s.duration ? '<span class="lt-search-duration">' + formatTime(s.duration) + '</span>' : '') +
                    '</div></div>' +
                    '<button class="lt-add-btn" data-i="' + i + '" title="添加到队列">+</button></div>';
            }).join('');
            $('ltSearchResults').querySelectorAll('.lt-add-btn').forEach((btn) => {
                btn.onclick = () => {
                    const s = songs[parseInt(btn.dataset.i, 10)];
                    if (!s) return;
                    sendAction('add', { song: {
                        id: s.id, name: s.name, artist: s.artist, album: s.album,
                        cover: s.cover, platform: s.platform, duration: s.duration, extra: s.extra,
                    } });
                    btn.disabled = true;
                };
            });
        } catch (e) {
            $('ltSearchResults').innerHTML = '<div class="lt-search-empty">搜索失败，请重试</div>';
        }
    }

    // ── 分享房间：复制链接，好友打开过验证后自动加入 ──
    $('ltShareBtn').onclick = () => {
        if (!roomId) return;
        const url = location.origin + location.pathname + '?room=' + roomId;
        const done = () => toast('房间链接已复制，好友打开即可加入');
        if (navigator.clipboard && window.isSecureContext) {
            navigator.clipboard.writeText(url).then(done).catch(() => copyFallback(url, done));
        } else {
            copyFallback(url, done);
        }
    };

    function copyFallback(text, done) {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand('copy'); done(); }
        catch (e) { toast('复制失败，请手动复制链接：' + text); }
        document.body.removeChild(ta);
    }

    // ── 房主：改房间名 ──
    $('ltRenameRoomBtn').onclick = () => {
        const name = prompt('输入新的房间名（不超过 ' + nameMaxLen + ' 个字符）', roomData ? roomData.name : '');
        if (name && name.trim()) sendAction('rename_room', { name: name.trim() });
    };

    // ── 初始化 ──
    (async function init() {
        // 拉取前端配置（名称长度上限、传输方式等）：提示/输入框限制与 config.py 保持一致
        try {
            const cfg = await (await fetch('/api/listen-together/config')).json();
            nameMaxLen = cfg.nameMaxLen || 20;
            ltTransport = cfg.transport === 'ws' ? 'ws' : 'http';
            wsUrl = cfg.wsUrl || '';  // 配置了 WS 地址覆盖则从该地址连接（空=当前域名默认端点）
        } catch (e) {}
        await ensureName();
        if (!meName) return;
        $('ltMyName').textContent = meName;
        // 分享链接：?room=N → 过门禁验证后自动加入该房间（进入后清除参数，刷新回列表）
        const roomParam = parseInt(new URLSearchParams(location.search).get('room') || '', 10);
        const autoEnter = roomParam >= 1 && roomParam <= 10;
        if (autoEnter) history.replaceState(null, '', location.pathname);
        if (ltTransport === 'ws') {
            // ws 模式：列表页即建立全局连接（房间列表/状态/进度全部走 WS，无 HTTP 轮询）
            connectWs();
            if (autoEnter) enterRoom(roomParam);
            return;
        }
        // http 模式：列表轮询 + 长轮询房间状态
        if (autoEnter) enterRoom(roomParam);
        else loadRooms();
        // 房间列表轮询：刷新人数/当前播放，同时维持用户名占用
        setInterval(() => { if (!roomId) loadRooms(); }, 10000);
    })();

    // ── 适配主播放器全局接口（本页无 player.js，lyrics.js / pip.js 引用）──
    // 歌词行点击：仅房主可跳转，且必须经房间同步（非房主点击被直接忽略；服务端也不接受非房主 seek）
    window.seekToLyric = (time) => {
        if (!roomData || roomData.owner !== meName) return;
        // 房主本地立即跳转（进度权威在本地，无需等服务端回写）
        if (audio.duration) audio.currentTime = time;
        sendAction('seek', { position: time });
    };
    // PiP 悬浮窗控制按钮：上一首/下一首为房间动作（服务端校验房主）；播放/暂停复用主按钮逻辑
    window.prevTrack = () => sendAction('prev');
    window.nextTrack = () => sendAction('next');
    window.togglePlay = () => {
        const btn = $('ltPlayBtn');
        if (btn) btn.click();
    };
    // PiP 播放状态图标：pip.js 监听主页 audioPlayer，本页用 ltAudio 自行同步
    const pipState = () => {
        if (window.pipWindow && !window.pipWindow.closed) {
            window.pipWindow.postMessage({ type: 'pip-state', playing: !audio.paused }, '*');
        }
    };
    audio.addEventListener('play', pipState);
    audio.addEventListener('pause', pipState);
})();
