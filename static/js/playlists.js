    // === 歌单（localStorage 存储 + 平台导入 + 分享链接）===
    // 分享链接格式：?list=kugou:hash1,hash2;netease:123,456
    // （仅平台代码 + ID 列表，分号分隔平台组、冒号分隔平台与 ID、逗号分隔 ID）
    const PL_STORAGE_KEY = 'mc_playlists';
    const PL_IMPORT_PAGE_SIZE = 100;
    let _myPlaylists = [];
    let _activePlaylistId = null;   // 当前在主页打开的本地歌单

    function _plLoad() {
        try {
            const raw = localStorage.getItem(PL_STORAGE_KEY);
            _myPlaylists = raw ? JSON.parse(raw) : [];
        } catch (e) {
            _myPlaylists = [];
        }
    }

    function _plSave() {
        try {
            localStorage.setItem(PL_STORAGE_KEY, JSON.stringify(_myPlaylists));
        } catch (e) {}
    }

    function _plGenId() {
        return 'pl_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
    }

    function getMyPlaylists() {
        return _myPlaylists;
    }

    // ── 侧栏渲染 ──
    function renderPlaylistSidebar() {
        const list = document.getElementById('playlistSidebarList');
        if (!_myPlaylists.length) {
            list.innerHTML = '<div class="playlist-sidebar-empty">还没有歌单<br>点 ＋ 新建，或导入平台歌单</div>';
            return;
        }
        list.innerHTML = _myPlaylists.map(pl => `
            <div class="playlist-sidebar-item${pl.id === _activePlaylistId ? ' active' : ''}" onclick="openMyPlaylist('${pl.id}')">
                ${pl.cover ? `<img class="playlist-sidebar-item-cover" src="${pl.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : '<div class="playlist-sidebar-item-cover playlist-sidebar-item-cover-ph"></div>'}
                <div class="playlist-sidebar-item-info">
                    <div class="playlist-sidebar-item-name">${escHtml(pl.name)}</div>
                    <div class="playlist-sidebar-item-meta">${pl.songs.length} 首</div>
                </div>
                <div class="playlist-sidebar-ops">
                    <button class="playlist-sidebar-op" onclick="event.stopPropagation();playMyPlaylistById('${pl.id}')" title="播放全部"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></button>
                    <button class="playlist-sidebar-op" onclick="event.stopPropagation();shareMyPlaylistById('${pl.id}')" title="分享"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M14 3v2h3.59l-9.83 9.83 1.41 1.41L19 6.41V10h2V3h-7zM19 19H5V5h7V3H5c-1.11 0-2 .9-2 2v14c0 1.1.89 2 2 2h14c1.1 0 2-.9 2-2v-7h-2v7z"/></svg></button>
                    <button class="playlist-sidebar-op playlist-sidebar-op-rename" onclick="event.stopPropagation();renameMyPlaylistById('${pl.id}')" title="重命名"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34a.9959.9959 0 0 0-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/></svg></button>
                    <button class="playlist-sidebar-op playlist-sidebar-op-del" onclick="event.stopPropagation();deleteMyPlaylistById('${pl.id}')" title="删除歌单"><svg viewBox="0 0 24 24" fill="currentColor"><path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg></button>
                </div>
            </div>
        `).join('');
    }

    // ── 新建 / 打开 / 隐藏 / 播放 / 删除 ──
    function createEmptyPlaylist() {
        const name = prompt('输入歌单名称', '我的歌单');
        if (name === null) return;
        const trimmed = name.trim();
        if (!trimmed) { showToast('名称不能为空'); return; }
        _myPlaylists.unshift({
            id: _plGenId(),
            name: trimmed.slice(0, 50),
            cover: '',
            created: Date.now(),
            songs: [],
        });
        _plSave();
        renderPlaylistSidebar();
        openMyPlaylist(_myPlaylists[0].id);
        showToast('已创建歌单');
    }

    function openMyPlaylist(id) {
        const pl = _myPlaylists.find(p => p.id === id);
        if (!pl) return;
        _activePlaylistId = id;
        _showingFavorites = false;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('searchLoading').style.display = 'none';
        document.getElementById('pagination').style.display = 'none';

        currentSongs = [...pl.songs];
        currentPage = 1;
        if (!pl.songs.length) {
            document.getElementById('songList').innerHTML = '<p class="empty-text">歌单还是空的，右键任意歌曲可添加到歌单</p>';
        } else {
            renderSongs(pl.songs);
        }
        renderPlaylistSidebar();
    }

    function hideMyPlaylistView() {
        _activePlaylistId = null;
        renderPlaylistSidebar();
    }

    function playMyPlaylistById(id) {
        const pl = _myPlaylists.find(p => p.id === id);
        if (!pl || !pl.songs.length) { showToast('歌单为空'); return; }
        playlist = [...pl.songs];
        playIndex = 0;
        savePlaylist();
        renderPlaylist();
        loadAndPlay(pl.songs[0]);
    }

    function renameMyPlaylistById(id) {
        const pl = _myPlaylists.find(p => p.id === id);
        if (!pl) return;
        const name = prompt('输入新的歌单名称', pl.name);
        if (name === null) return;
        const trimmed = name.trim();
        if (!trimmed) { showToast('名称不能为空'); return; }
        pl.name = trimmed.slice(0, 50);
        _plSave();
        renderPlaylistSidebar();
        showToast('已重命名');
    }

    function deleteMyPlaylistById(id) {
        const pl = _myPlaylists.find(p => p.id === id);
        if (!pl) return;
        if (!confirm(`确定删除歌单「${pl.name}」？`)) return;
        _myPlaylists = _myPlaylists.filter(p => p.id !== id);
        _plSave();
        if (_activePlaylistId === id) hideMyPlaylistView();
        renderPlaylistSidebar();
        showToast('已删除歌单');
    }

    // ── 分享（仅平台 + ID，按平台分组）──
    function _copyShareText(text) {
        return new Promise(resolve => {
            const silentCopy = () => {
                const ta = document.createElement('textarea');
                ta.value = text;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.select();
                try { document.execCommand('copy'); } catch (e) {}
                document.body.removeChild(ta);
                resolve();
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(resolve).catch(silentCopy);
            } else {
                silentCopy();
            }
        });
    }

    function shareMyPlaylistById(id) {
        const pl = _myPlaylists.find(p => p.id === id);
        if (!pl || !pl.songs.length) { showToast('歌单为空'); return; }
        // 按平台分组收集 ID：kugou:hash1,hash2;netease:123,456
        const groups = new Map();
        for (const s of pl.songs) {
            if (!s || !s.platform || !s.id) continue;
            if (!groups.has(s.platform)) groups.set(s.platform, []);
            groups.get(s.platform).push(s.id);
        }
        if (!groups.size) { showToast('歌单没有可分享的歌曲'); return; }
        const listParam = [...groups.entries()].map(([p, ids]) => `${p}:${ids.join(',')}`).join(';');
        // 平台代码与 ID 均为 URL 安全字符（hex/数字/BV），直接拼接保持链接最短
        const url = `${location.origin}/?list=${listParam}`;
        const text = `${pl.name} (${pl.songs.length} 首)\n${url}`;
        _copyShareText(text).then(() => showToast('已复制分享链接'));
    }

    // ── 导入平台歌单 ──
    let _importState = null;    // 预览成功后：{platform, ref, name, cover, creator, total, songs}

    function openImportModal() {
        _importState = null;
        document.getElementById('plImportPreview').style.display = 'none';
        document.getElementById('plImportError').style.display = 'none';
        const btn = document.getElementById('plImportBtn');
        btn.textContent = '导入';
        btn.disabled = false;
        document.getElementById('plImportRef').value = '';
        document.getElementById('plImportOverlay').style.display = 'flex';
        setTimeout(() => document.getElementById('plImportRef').focus(), 50);
    }

    function closeImportModal() {
        document.getElementById('plImportOverlay').style.display = 'none';
    }

    async function startImport() {
        const platform = document.getElementById('plImportPlatform').value;
        const ref = document.getElementById('plImportRef').value.trim();
        const errEl = document.getElementById('plImportError');
        const btn = document.getElementById('plImportBtn');
        errEl.style.display = 'none';
        if (!ref) {
            errEl.textContent = '请输入歌单链接或 ID';
            errEl.style.display = 'block';
            return;
        }

        // 已有预览：循环分页拉取全部并保存
        if (_importState) {
            btn.disabled = true;
            btn.textContent = '导入中...';
            try {
                const allSongs = [..._importState.songs];
                const pages = Math.ceil(_importState.total / PL_IMPORT_PAGE_SIZE);
                for (let p = 2; p <= pages; p++) {
                    const r = await fetch(`/api/playlist/import?platform=${encodeURIComponent(_importState.platform)}&ref=${encodeURIComponent(_importState.ref)}&page=${p}&page_size=${PL_IMPORT_PAGE_SIZE}`);
                    const d = await r.json().catch(() => ({}));
                    if (!r.ok) throw new Error(d.detail || `导入失败 (HTTP ${r.status})`);
                    allSongs.push(...d.songs);
                }
                const st = _importState;
                _myPlaylists.unshift({
                    id: _plGenId(),
                    name: st.name,
                    cover: st.cover,
                    created: Date.now(),
                    songs: allSongs,
                });
                _plSave();
                renderPlaylistSidebar();
                closeImportModal();
                openMyPlaylist(_myPlaylists[0].id);
                showToast(`已导入歌单「${st.name}」（${allSongs.length} 首）`);
            } catch (e) {
                errEl.textContent = e.message;
                errEl.style.display = 'block';
                btn.disabled = false;
                btn.textContent = `导入全部 ${_importState.total} 首`;
            }
            return;
        }

        // 第一步：拉第一页预览
        btn.disabled = true;
        btn.textContent = '加载中...';
        try {
            const r = await fetch(`/api/playlist/import?platform=${encodeURIComponent(platform)}&ref=${encodeURIComponent(ref)}&page=1&page_size=${PL_IMPORT_PAGE_SIZE}`);
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.detail || `导入失败 (HTTP ${r.status})`);
            if (!d.songs || !d.songs.length) throw new Error('歌单为空');
            _importState = { platform, ref, name: d.name, cover: d.cover, creator: d.creator, total: d.total, songs: d.songs };
            const preview = document.getElementById('plImportPreview');
            preview.style.display = 'flex';
            preview.innerHTML = `
                ${d.cover ? `<img src="${d.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : ''}
                <div class="pl-import-preview-info">
                    <div class="pl-import-preview-name">${escHtml(d.name)}</div>
                    <div class="pl-import-preview-meta">${escHtml(d.creator || '')}${d.creator ? ' · ' : ''}共 ${d.total} 首</div>
                </div>
            `;
            btn.textContent = d.total > d.songs.length ? `导入全部 ${d.total} 首` : '确认导入';
            btn.disabled = false;
        } catch (e) {
            errEl.textContent = e.message;
            errEl.style.display = 'block';
            btn.disabled = false;
            btn.textContent = '重试';
        }
    }

    // ── 添加到歌单（供右键菜单调用）──
    function addSongToMyPlaylistById(plId, song) {
        const pl = _myPlaylists.find(p => p.id === plId);
        if (!pl) { showToast('歌单不存在'); return; }
        if (!song) return;
        if (pl.songs.some(s => s.platform === song.platform && s.id === song.id)) {
            showToast('该歌曲已在歌单中');
            return;
        }
        pl.songs.push(song);
        _plSave();
        // 正在打开该歌单时，同步刷新中间歌曲列表
        if (_activePlaylistId === plId) {
            currentSongs = [...pl.songs];
            renderSongs(pl.songs);
        }
        renderPlaylistSidebar();
        showToast(`已添加到「${pl.name}」`);
    }

    // ── 解析分享链接：?list=kugou:hash1,hash2;netease:123,456 ──
    async function checkShareList() {
        const params = new URLSearchParams(location.search);
        const listParam = params.get('list');
        if (!listParam) return;

        const items = [];
        for (const group of listParam.split(';')) {
            if (!group) continue;
            const idx = group.indexOf(':');
            if (idx <= 0) continue;
            const platform = group.slice(0, idx).trim().toLowerCase();
            for (const id of group.slice(idx + 1).split(',')) {
                const tid = id.trim();
                if (tid) items.push({ platform, id: tid });
            }
        }
        if (!items.length) return;

        // 先保存歌曲 ID 骨架，立即打开歌单；详情在后台分批补全（见 _enrichSharePlaylist），
        // 避免长歌单一次性解析导致导入长时间等待
        const pl = {
            id: _plGenId(),
            name: `分享歌单（${items.length} 首）`,
            cover: '',
            created: Date.now(),
            songs: items.map(i => ({
                id: i.id,
                name: '获取中…',
                artist: '',
                album: '',
                cover: '',
                platform: i.platform,
                duration: 0,
                extra: null,
                _pending: true,
            })),
        };
        _myPlaylists.unshift(pl);
        _plSave();
        renderPlaylistSidebar();
        openMyPlaylist(pl.id);
        showToast('歌单已保存，正在获取歌曲详情');
        _enrichSharePlaylist(pl.id, items);
        if (params.get('autoplay') === '1') {
            await playSong(0);   // 占位歌曲由 playSong 内解析兜底后播放
        }
        history.replaceState({}, '', location.pathname);
    }

    // 分享歌单后台补全：SSE 流式消费 /api/resolve-songs-stream，服务端按配置每批解析
    // 并分批传回，客户端每收到一批就写回，正在打开时同步刷新列表。
    // 幂等可恢复：每次请求前只取仍 _pending 的歌曲，页面刷新/流中断后重新调用即可续传；
    // 流中断自动重试（最多 3 次），全部完成才结束。
    const _enrichRunning = new Set();   // 正在补全的歌单 id（防并发双跑）

    async function _enrichSharePlaylist(plId, items) {
        if (_enrichRunning.has(plId)) return;
        _enrichRunning.add(plId);
        try {
            await _enrichSharePlaylistInner(plId, items);
        } finally {
            _enrichRunning.delete(plId);
        }
    }

    async function _enrichSharePlaylistInner(plId, items) {
        let failed = 0;
        let attempt = 0;
        for (;;) {
            const pl = _myPlaylists.find(p => p.id === plId);
            if (!pl) return;                          // 歌单已被删除，停止补全
            const pending = pl.songs.filter(s => s._pending);
            if (!pending.length) break;               // 全部完成
            const toResolve = items.filter(i => pl.songs.some(
                s => s._pending && s.platform === i.platform && s.id === i.id));
            if (!toResolve.length) break;
            attempt++;
            try {
                const resp = await fetch('/api/resolve-songs-stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ songs: toResolve }),
                });
                if (!resp.ok || !resp.body) throw new Error('resolve failed');
                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buf = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buf += decoder.decode(value, { stream: true });
                    let sep;
                    while ((sep = buf.indexOf('\n\n')) !== -1) {
                        const event = buf.slice(0, sep);
                        buf = buf.slice(sep + 2);
                        if (!event.startsWith('data:')) continue;
                        const data = event.slice(5).trim();
                        if (!data || data === '[DONE]') continue;
                        let batch;
                        try { batch = JSON.parse(data); } catch (e) { continue; }
                        const songs = batch.songs || [];
                        if (!songs.length) continue;
                        const pl2 = _myPlaylists.find(p => p.id === plId);
                        if (!pl2) { reader.cancel(); return; }   // 歌单已被删除，停止补全
                        const map = new Map(songs.map(s => [s.platform + ':' + s.id, s]));
                        let changed = false;
                        for (const s of pl2.songs) {
                            if (!s._pending) continue;
                            const r = map.get(s.platform + ':' + s.id);
                            if (!r) continue;
                            if (r.name) {
                                Object.assign(s, r);
                                s._pending = false;
                            } else {
                                failed++;             // 解析失败（兜底空歌）：保留占位
                                s._pending = false;
                                s._failed = true;
                            }
                            changed = true;
                        }
                        if (changed) {
                            _plSave();
                            if (_activePlaylistId === plId) {
                                currentSongs = [...pl2.songs];
                                renderSongs(pl2.songs);
                            }
                        }
                    }
                }
                break;                                // 流正常读完
            } catch (e) {
                if (attempt >= 3) {                   // 连续失败：保留占位，等下次页面加载续传
                    showToast('歌曲详情获取失败，刷新页面后可重试');
                    return;
                }
                await new Promise(res => setTimeout(res, 2000));
            }
        }
        showToast(failed ? `歌单详情已更新（${items.length - failed} 首）` : '歌单详情已更新');
    }

    // 页面加载时恢复未完成的补全（刷新/中断后自动续传剩余占位歌曲）
    function _resumePendingEnrich() {
        for (const pl of _myPlaylists) {
            const pending = pl.songs.filter(s => s._pending);
            if (!pending.length) continue;
            _enrichSharePlaylist(pl.id, pending.map(s => ({ platform: s.platform, id: s.id })));
        }
    }

    // ── 侧栏开关（镜像歌词面板：左侧固定悬浮 + tab 滑出）──
    function togglePlaylistSidebar() {
        const panel = document.getElementById('playlistSidebar');
        const tab = document.getElementById('playlistTab');
        const hidden = panel.classList.toggle('hidden');
        tab.classList.toggle('collapsed', hidden);
        tab.innerHTML = hidden
            ? '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6z"/></svg>'
            : '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>';
        // 移动端互斥：展开歌单时收起歌词面板（两个全宽面板不能同时显示，避免互相盖住）
        if (!hidden && window.innerWidth <= 640) {
            const lp = document.getElementById('lyricsPanel');
            if (lp && !lp.classList.contains('hidden') && typeof toggleLyrics === 'function') {
                toggleLyrics();
            }
        }
    }

    _plLoad();
    renderPlaylistSidebar();
    checkShareList();
    _resumePendingEnrich();
