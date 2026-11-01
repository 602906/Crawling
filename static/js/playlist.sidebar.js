    // === 歌单（localStorage 存储 + 平台导入 + 分享链接）===
    // 分享链接格式：?list=kugou:hash1,hash2;netease:123,456
    // （仅平台代码 + ID 列表，分号分隔平台组、冒号分隔平台与 ID、逗号分隔 ID）
    const PL_STORAGE_KEY = 'mc_playlists';
    const PL_IMPORT_PAGE_SIZE = 100;
    // 各平台歌单链接格式提示
    const PLATFORM_IMPORT_HINTS = {
        netease: '粘贴网易云歌单链接或输入歌单 ID',
        kugou: '粘贴酷狗歌单链接或输入歌单 ID',
        qqmusic: '粘贴 QQ 音乐歌单链接或输入歌单 ID（暂不支持专辑/歌手链接）',
    };
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

    function getMyPlaylist(id) {
        return _myPlaylists.find(p => p.id === id);
    }

    // ── 歌单下载（进度条显示） ──
    // ── 歌单下载（进度条显示），剔除已存入 IndexedDB 的缓存歌曲 ──
    function downloadProgressUI() {
        const overlay = document.getElementById('plDownloadOverlay');
        if (!overlay) {
            const el = document.createElement('div');
            el.id = 'plDownloadOverlay';
            el.className = 'pl-download-overlay';
            el.innerHTML = `
                <div class="pl-download-box">
                    <div class="pl-download-header">
                        <span class="pl-download-title">歌单下载</span>
                        <span class="pl-download-status">准备中...</span>
                    </div>
                    <div class="pl-download-bar"><div class="pl-download-bar-fill"></div></div>
                    <div class="pl-download-info">已下载 0 KB / 0 KB</div>
                    <div class="pl-download-step">从服务器接收音频中...</div>
                </div>`;
            document.body.appendChild(el);
            return el;
        }
        return overlay;
    }

    // 已缓存（IndexedDB）的 [platform:id] 集合
    async function getCachedKeys() {
        const out = [];
        if (typeof _openAudioCache !== 'function') return out;
        try {
            const db = await _openAudioCache();
            const tx = db.transaction('audio', 'readonly');
            const store = tx.objectStore('audio');
            return new Promise((resolve) => {
                const req = store.openCursor();
                req.onsuccess = function () {
                    const cur = req.result;
                    if (!cur) {
                        resolve(out);
                        return;
                    }
                    out.push(String(cur.key));
                    cur.continue();
                };
                req.onerror = function () {
                    resolve(out); // 出错也返回已收集的列表
                };
            });
        } catch (e) {
            return out;
        }
    }

    // 为所有歌曲添加 _cached 标记（用于服务端跳过下载，前端从 IndexedDB 导出）
    async function markCachedSongs(songs) {
        const cacheKeys = await getCachedKeys();
        const cacheSet = new Set(cacheKeys.map(k => k.toLowerCase())); // 统一小写
        return songs.map(s => {
            const kl = `${(s.platform || '').toLowerCase()}:${(s.id || '')}`;
            return { ...s, _cached: cacheSet.has(kl) };
        });
    }

    async function downloadPlaylistSkipCached(songs) {
        // 不再过滤，只返回带标记的歌曲
        return songs;
    }

    function downloadProgressUpdate(el, pct, status, info) {
        el.querySelector('.pl-download-bar-fill').style.width = pct + '%';
        el.querySelector('.pl-download-status').textContent = status;
        if (info) el.querySelector('.pl-download-info').textContent = info;
    }

    function downloadProgressDone(el, info) {
        downloadProgressUpdate(el, 100, '已完成', info);
        setTimeout(() => { el.style.display = 'none'; el.remove(); }, 2500);
    }

    function bytesFmt(b) {
        if (b < 1024) return b + ' B';
        if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
        return (b / 1024 / 1024).toFixed(2) + ' MB';
    }

    function saveAsBlob(blob, name) {
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = name;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 60000);
    }

    // 每首 [4 字节长度][音频]
    async function downloadPlaylistStreams(el, body, total) {
        const reader = body.getReader();
        let received = 0;
        // 流式缓冲区：read() 的 chunk 边界与协议边界无关，必须自行缓存余量
        let pendingChunks = [];
        let pendingLen = 0;

        const fill = async (n) => {
            // 保证缓冲区至少有 n 字节
            while (pendingLen < n) {
                const { done, value } = await reader.read();
                if (done) throw new Error('连接中断，未收到完整数据');
                if (value && value.length) {
                    pendingChunks.push(value);
                    pendingLen += value.length;
                    received += value.length;
                }
            }
        };

        const take = async (n) => {
            // 精确取出 n 字节（不越界），剩余留在缓冲区
            await fill(n);
            const out = new Uint8Array(n);
            let pos = 0;
            while (pos < n) {
                const head = pendingChunks[0];
                const need = n - pos;
                if (head.length <= need) {
                    out.set(head, pos);
                    pos += head.length;
                    pendingChunks.shift();
                    pendingLen -= head.length;
                } else {
                    out.set(head.subarray(0, need), pos);
                    pendingChunks[0] = head.subarray(need);
                    pendingLen -= need;
                    pos += need;
                }
            }
            return out;
        };

        // manifest
        const mLenBuf = await take(4);
        const mLenVal = new DataView(mLenBuf.buffer, mLenBuf.byteOffset, 4).getUint32(0);
        const mBuf = await take(mLenVal);
        const manifest = JSON.parse(new TextDecoder().decode(mBuf));
        console.debug('[playlist-download] manifest:', manifest);

        // 按 manifest 中的歌曲，每首读出 [4 字节长度][音频]，同时显示下载进度
        // lenVal === 0 表示这首歌已由前端缓存，从 IndexedDB 读取导出
        const blobs = [];
        const totalSongs = manifest.songs.length;
        let doneCount = 0;
        let skipped = 0;
        for (const song of manifest.songs) {
            const lenBuf = await take(4);
            const lenVal = new DataView(lenBuf.buffer, lenBuf.byteOffset, 4).getUint32(0);
            if (lenVal === 0) {
                // 已缓存或不可用：从 IndexedDB 读取缓存
                const cacheKey = `${song.platform}:${song.id}`;
                try {
                    const cached = await getCachedAudio(cacheKey);
                    if (cached && cached.blob) {
                        blobs.push({ name: song.name, artist: song.artist, blob: cached.blob, len: cached.blob.size });
                        console.debug('[playlist-download] 本地缓存导出:', song.name, cached.blob.size, '字节');
                    } else {
                        skipped++;
                        console.warn('[playlist-download] 无缓存且不可用，跳过:', song.name);
                    }
                } catch (e) {
                    skipped++;
                    console.warn('[playlist-download] 读取本地缓存失败，跳过:', song.name, e);
                }
            } else {
                const audioBuf = await take(lenVal);
                const blob = new Blob([audioBuf]);
                blobs.push({ name: song.name, artist: song.artist, blob: blob, len: lenVal });
            }
            doneCount++;
            downloadProgressUpdate(el, Math.round(doneCount / totalSongs * 100), '下载中',
                `${doneCount} / ${totalSongs} 首  (${song.name})`);
        }
        downloadProgressDone(el, `已下载 ${blobs.length} 首${skipped ? `，跳过 ${skipped} 首（无缓存且不可用）` : ''}`);
        if (!blobs.length) { showToast('没有可导出的歌曲'); return; }
        // 打包成一个 ZIP 下载：浏览器会拦截同一时刻的批量自动下载（超过 ~10 个会被静默丢弃），
        // 因此不能逐首 saveAsBlob，必须合并为单次下载。
        const zip = await buildZip(blobs);
        const zipName = `${(manifest.name || '歌单').replace(/[\\/:*?"<>|]/g, '_')}.zip`;
        saveAsBlob(zip, zipName);
        showToast(`已导出 ${blobs.length} 首到 ${zipName}`);
    }

    // ── 极简 ZIP 打包（STORE 不压缩：音频本身已压缩，省 CPU）──
    // 支持 UTF-8 文件名（通用标志位 bit 11），>4GB 不做（歌单不可能这么大）
    const _CRC_TABLE = (() => {
        const t = new Uint32Array(256);
        for (let i = 0; i < 256; i++) {
            let c = i;
            for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
            t[i] = c >>> 0;
        }
        return t;
    })();

    function crc32(u8) {
        let c = 0xFFFFFFFF;
        for (let i = 0; i < u8.length; i++) c = _CRC_TABLE[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
        return (c ^ 0xFFFFFFFF) >>> 0;
    }

    async function buildZip(items) {
        const enc = new TextEncoder();
        const parts = [];      // 依次收集所有字节块
        const central = [];    // 中央目录记录
        let offset = 0;

        const used = new Set();
        for (const it of items) {
            const raw = new Uint8Array(await it.blob.arrayBuffer());
            // 文件名去重：同名追加 (2)、(3)…
            let base = `${it.name || 'track'} - ${it.artist || '未知'}`.replace(/[\\/:*?"<>|]/g, '_').slice(0, 120);
            let fname = base + '.mp3';
            let n = 2;
            while (used.has(fname)) fname = `${base} (${n++}).mp3`;
            used.add(fname);

            const nameBytes = enc.encode(fname);
            const crc = crc32(raw);
            const size = raw.length;

            // 本地文件头（30 字节固定 + 文件名）
            const lh = new Uint8Array(30 + nameBytes.length);
            const lv = new DataView(lh.buffer);
            lv.setUint32(0, 0x04034b50, true);   // 签名 PK\x03\x04
            lv.setUint16(4, 20, true);           // 解压所需版本
            lv.setUint16(6, 0x0800, true);       // 标志：UTF-8 文件名
            lv.setUint16(8, 0, true);            // 压缩方法 0 = STORE
            lv.setUint16(10, 0, true);           // 修改时间
            lv.setUint16(12, 0, true);           // 修改日期
            lv.setUint32(14, crc, true);
            lv.setUint32(18, size, true);        // 压缩后大小
            lv.setUint32(22, size, true);        // 原始大小
            lv.setUint16(26, nameBytes.length, true);
            lv.setUint16(28, 0, true);           // 扩展字段长度
            lh.set(nameBytes, 30);
            parts.push(lh, raw);

            // 中央目录项（46 字节固定 + 文件名）
            const ch = new Uint8Array(46 + nameBytes.length);
            const cv = new DataView(ch.buffer);
            cv.setUint32(0, 0x02014b50, true);   // 签名 PK\x01\x02
            cv.setUint16(4, 20, true);           // 创建版本
            cv.setUint16(6, 20, true);           // 解压所需版本
            cv.setUint16(8, 0x0800, true);       // 标志：UTF-8
            cv.setUint16(10, 0, true);           // STORE
            cv.setUint16(12, 0, true);
            cv.setUint16(14, 0, true);
            cv.setUint32(16, crc, true);
            cv.setUint32(20, size, true);
            cv.setUint32(24, size, true);
            cv.setUint16(28, nameBytes.length, true);
            cv.setUint16(30, 0, true);           // 扩展字段
            cv.setUint16(32, 0, true);           // 注释
            cv.setUint16(34, 0, true);           // 磁盘号
            cv.setUint16(36, 0, true);           // 内部属性
            cv.setUint32(38, 0, true);           // 外部属性
            cv.setUint32(42, offset, true);      // 本地头偏移
            ch.set(nameBytes, 46);
            central.push(ch);

            offset += lh.length + raw.length;
        }

        const cdSize = central.reduce((s, c) => s + c.length, 0);
        // 中央目录结束记录（22 字节）
        const eocd = new Uint8Array(22);
        const ev = new DataView(eocd.buffer);
        ev.setUint32(0, 0x06054b50, true);       // 签名 PK\x05\x06
        ev.setUint16(4, 0, true);
        ev.setUint16(6, 0, true);
        ev.setUint16(8, items.length, true);     // 本磁盘条目数
        ev.setUint16(10, items.length, true);    // 总条目数
        ev.setUint32(12, cdSize, true);
        ev.setUint32(16, offset, true);          // 中央目录偏移
        ev.setUint16(20, 0, true);               // 注释长度

        return new Blob([...parts, ...central, eocd], { type: 'application/zip' });
    }

    async function startDownloadPlaylist(plId) {
        const pl = getMyPlaylist(plId);
        if (!pl || !pl.songs.length) { showToast('歌单为空'); return; }

        // 给每首歌打上 _cached 标记：已缓存的由前端从 IndexedDB 导出，未缓存的走服务端下载
        const marked = await markCachedSongs(pl.songs);
        const cachedCount = marked.filter(s => s._cached).length;
        const remoteCount = marked.length - cachedCount;

        const tip = cachedCount > 0
            ? `确定下载歌单「${pl.name}」？共 ${marked.length} 首：本地缓存 ${cachedCount} 首（直接导出）、服务器下载 ${remoteCount} 首。`
            : `确定下载歌单「${pl.name}」中的 ${marked.length} 首歌曲？`;
        if (!confirm(tip)) return;

        const el = downloadProgressUI();
        el.style.display = 'flex';
        downloadProgressUpdate(el, 0, '准备中', '0 KB / 0 KB');

        try {
            const resp = await fetch('/api/playlist/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json; charset=utf-8' },
                body: JSON.stringify({ name: pl.name, songs: marked }),
            });
            if (!resp.ok) {
                const d = await resp.json().catch(() => ({}));
                throw new Error(d.detail || `下载失败 (HTTP ${resp.status})`);
            }
            // 手动按协议读：4 字节的 manifest 长度 + manifest + 每首 [4 字节长度][音频]
            const total = Number(resp.headers.get('content-length') || 0);
            await downloadPlaylistStreams(el, resp.body, total);
        } catch (e) {
            downloadProgressUpdate(el, 0, '失败', '0 KB / 0 KB');
            alert('下载失败: ' + e.message);
            el.style.display = 'none'; el.remove();
        }
    }

    // ── 侧栏渲染 ──
    function renderPlaylistSidebar() {
        const list = document.getElementById('playlistSidebarList');
        if (!_myPlaylists.length) {
            list.innerHTML = '<div class="playlist-sidebar-empty">还没有歌单<br>点 ＋ 新建，或导入平台歌单</div>';
            return;
        }
        list.innerHTML = _myPlaylists.map(pl => `
            <div class="playlist-sidebar-item${pl.id === _activePlaylistId ? ' active' : ''}"
                 onclick="openMyPlaylist('${pl.id}')"
                 oncontextmenu="return openPlaylistCtxMenu(event, '${pl.id}')">
                ${pl.cover ? `<img class="playlist-sidebar-item-cover" src="${pl.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : '<div class="playlist-sidebar-item-cover playlist-sidebar-item-cover-ph"></div>'}
                <div class="playlist-sidebar-item-info">
                    <div class="playlist-sidebar-item-name">${escHtml(pl.name)}</div>
                    <div class="playlist-sidebar-item-meta">${pl.songs.length} 首</div>
                </div>
                <div class="playlist-sidebar-ops">
                    <button class="playlist-sidebar-op playlist-sidebar-op-more"
                            onclick="event.stopPropagation();openPlaylistCtxMenuByBtn(event, '${pl.id}')"
                            title="更多">&#8943;</button>
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
        // 参数值整体 URL 编码（: → %3A、, → %2C、; → %3B），避免分享到聊天软件被截断/误解析
        const url = `${location.origin}/?list=${encodeURIComponent(listParam)}`;
        const text = `${pl.name} (${pl.songs.length} 首)\n${url}`;
        _copyShareText(text).then(() => showToast('已复制分享链接'));
    }

    // ── 导入平台歌单 ──
    let _importState = null;    // 预览成功后：{platform, ref, name, cover, creator, total, songs}

    function openImportModal() {
        _importState = null;
        document.getElementById('playlistSidebarImportPreview').style.display = 'none';
        document.getElementById('playlistSidebarImportError').style.display = 'none';
        const btn = document.getElementById('playlistSidebarImportBtn');
        btn.textContent = '导入';
        btn.disabled = false;
        const refInput = document.getElementById('playlistSidebarImportRef');
        refInput.value = '';
        // 不同平台的链接格式提示不同
        const platform = document.getElementById('playlistSidebarImportPlatform').value;
        refInput.placeholder = PLATFORM_IMPORT_HINTS[platform] || '粘贴歌单链接或直接输入 ID';
        document.getElementById('playlistSidebarImportOverlay').style.display = 'flex';
        setTimeout(() => refInput.focus(), 50);
    }

    function closeImportModal() {
        document.getElementById('playlistSidebarImportOverlay').style.display = 'none';
    }

    async function startImport() {
        const platform = document.getElementById('playlistSidebarImportPlatform').value;
        const ref = document.getElementById('playlistSidebarImportRef').value.trim();
        const errEl = document.getElementById('playlistSidebarImportError');
        const btn = document.getElementById('playlistSidebarImportBtn');
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
            const preview = document.getElementById('playlistSidebarImportPreview');
            preview.style.display = 'flex';
            preview.innerHTML = `
                ${d.cover ? `<img src="${d.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : ''}
                <div class="playlist-sidebar-import-preview-info">
                    <div class="playlist-sidebar-import-preview-name">${escHtml(d.name)}</div>
                    <div class="playlist-sidebar-import-preview-meta">${escHtml(d.creator || '')}${d.creator ? ' · ' : ''}共 ${d.total} 首</div>
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
        const tab = document.getElementById('playlistSidebarTab');
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
