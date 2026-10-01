const AUDIO_CACHE_MAX = 200 * 1024 * 1024;

// === Theme ===
function _applyThemeIcon() {
    const btn = document.getElementById('themeToggleBtn');
    if (!btn) return;
    const theme = document.documentElement.getAttribute('data-theme');
    // 暗色显太阳（点击切亮色），亮色显月亮（点击切暗色）
    btn.textContent = theme === 'light' ? '\u263E' : '\u2600';
    btn.title = theme === 'light' ? '切换到暗色主题' : '切换到亮色主题';
}

function toggleTheme() {
    const cur = document.documentElement.getAttribute('data-theme');
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    const meta = document.getElementById('metaThemeColor');
    if (meta) meta.content = next === 'light' ? '#ffffff' : '#1a1a24';
    try {
        localStorage.setItem('mc_theme', next);
        localStorage.setItem('mc_theme_ts', String(Date.now()));
    } catch (e) {}
    _applyThemeIcon();
    // 同步更新 PiP 悬浮窗主题（函数定义在 pip.js）
    if (typeof _refreshPipTheme === 'function') _refreshPipTheme();
}

// 页面存活期间刷新时间戳，关闭/切后台时也记录一次；
// 这样"关闭超过 1 分钟"可由 base.html 加载时的时间戳差值判定
function _touchThemeTs() {
    try {
        if (localStorage.getItem('mc_theme')) {
            localStorage.setItem('mc_theme_ts', String(Date.now()));
        }
    } catch (e) {}
}
setInterval(_touchThemeTs, 20000);
window.addEventListener('pagehide', _touchThemeTs);
document.addEventListener('visibilitychange', _touchThemeTs);

document.addEventListener('DOMContentLoaded', _applyThemeIcon);

// === 侧面板互斥（播放列表 / 收藏列表 / 均衡器）===
// 同一时刻只允许打开一个：打开任意一个前先关闭其他；
// 点击面板之外的空白区域时全部关闭（面板自身/开关按钮/右键菜单/模态/歌词面板不触发）。
function closeAllSidePanels() {
    // 播放列表（style 驱动显隐）
    if (typeof playlistVisible !== 'undefined') playlistVisible = false;
    var pl = document.getElementById('playlistPanel');
    if (pl) pl.style.display = 'none';
    // 收藏列表（style 驱动显隐）
    if (typeof _favoritesPanelVisible !== 'undefined') _favoritesPanelVisible = false;
    var fv = document.getElementById('favoritesPanel');
    if (fv) fv.style.display = 'none';
    // 均衡器（class 驱动显隐）
    var eq = document.getElementById('eqPanel');
    if (eq) eq.classList.remove('open');
    var backdrop = document.getElementById('eqPanelBackdrop');
    if (backdrop) backdrop.classList.remove('active');
}

document.addEventListener('click', function (e) {
    var keep = e.target.closest(
        '#playlistPanel, #favoritesPanel, .eq-panel, ' +
        '#playlistToggleBtn, #favoritesToggleBtn, #eqBtn, .settings-eq, ' +
        '.ctx-menu, #infoOverlay, #plImportOverlay, .lyrics-panel'
    );
    if (keep) return;
    closeAllSidePanels();
});

function _openAudioCache() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('MusicCatchAudioCache', 1);
        req.onupgradeneeded = () => { req.result.createObjectStore('audio'); };
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
    });
}

async function clearAudioCache() {
    try {
        const db = await _openAudioCache();
        const tx = db.transaction('audio', 'readwrite');
        tx.objectStore('audio').clear();
        await new Promise((resolve) => { tx.oncomplete = resolve; tx.onerror = resolve; });
        if (typeof showToast === 'function') showToast('音频缓存已清除');
        else alert('音频缓存已清除');
    } catch (e) {
        if (typeof showToast === 'function') showToast('清除缓存失败: ' + e.message);
        else alert('清除缓存失败: ' + e.message);
    }
}

// === Audio Cache ===
    // 校验缓存 blob 是否为合法音频：先验文件头魔数，排除错误 JSON/HTML/截断数据
    async function _isAudioSignature(blob) {
        try {
            const buf = new Uint8Array(await blob.slice(0, 16).arrayBuffer());
            if (buf.length < 4) return false;
            // ID3v2 (mp3)
            if (buf[0] === 0x49 && buf[1] === 0x44 && buf[2] === 0x33) return true;
            // fLaC
            if (buf[0] === 0x66 && buf[1] === 0x4c && buf[2] === 0x61 && buf[3] === 0x43) return true;
            // MP3 同步字 0xFF Ex/Fx（无 ID3 头的裸 MP3）
            if (buf[0] === 0xff && (buf[1] & 0xe0) === 0xe0) return true;
            // OggS (ogg)
            if (buf[0] === 0x4f && buf[1] === 0x67 && buf[2] === 0x67 && buf[3] === 0x53) return true;
            // ftyp (mp4/m4a，偏移 4)
            if (buf[4] === 0x66 && buf[5] === 0x74 && buf[6] === 0x79 && buf[7] === 0x70) return true;
            // RIFF (wav)
            if (buf[0] === 0x52 && buf[1] === 0x49 && buf[2] === 0x46 && buf[3] === 0x46) return true;
            return false;
        } catch (e) { return false; }
    }

    async function isValidMediaBlob(blob) {
        if (!blob || !(blob instanceof Blob) || blob.size < 1024) return false;
        const type = (blob.type || '').toLowerCase();
        if (type.includes('json') || type.includes('html') || type.startsWith('text/')) return false;
        return _isAudioSignature(blob);
    }

    async function getCachedAudio(key) {
        try {
            const db = await _openAudioCache();
            return new Promise((resolve) => {
                const tx = db.transaction('audio', 'readonly');
                const req = tx.objectStore('audio').get(key);
                req.onsuccess = () => resolve(req.result || null);
                req.onerror = () => resolve(null);
            });
        } catch (e) {
            return null;
        }
    }

    async function putCachedAudio(key, blob, totalLen) {
        try {
            const db = await _openAudioCache();
            const tx = db.transaction('audio', 'readwrite');
            const store = tx.objectStore('audio');
            await new Promise((resolve) => {
                let totalSize = 0;
                const cursorReq = store.openCursor();
                const entries = [];
                cursorReq.onsuccess = () => {
                    const cursor = cursorReq.result;
                    if (cursor) {
                        totalSize += cursor.value.size || 0;
                        entries.push({ key: cursor.key, ts: cursor.value.ts || 0, size: cursor.value.size || 0 });
                        cursor.continue();
                    } else {
                        entries.sort((a, b) => a.ts - b.ts);
                        while (totalSize + blob.size > AUDIO_CACHE_MAX && entries.length) {
                            const old = entries.shift();
                            store.delete(old.key);
                            totalSize -= old.size;
                        }
                        resolve();
                    }
                };
                cursorReq.onerror = () => resolve();
            });
            store.put({ blob, ts: Date.now(), size: blob.size, total: totalLen || 0 }, key);
            await new Promise((resolve) => { tx.oncomplete = resolve; tx.onerror = resolve; });
        } catch (e) {}
    }

    async function deleteCachedAudio(key) {
        try {
            const db = await _openAudioCache();
            const tx = db.transaction('audio', 'readwrite');
            tx.objectStore('audio').delete(key);
            await new Promise((resolve) => { tx.oncomplete = resolve; tx.onerror = resolve; });
        } catch (e) {}
    }

// === Favorites (data) ===
    function getFavorites() {
        try {
            const raw = localStorage.getItem('mc_favorites');
            return raw ? (JSON.parse(raw) || []) : [];
        } catch (e) { return []; }
    }

    function saveFavorites(list) {
        try { localStorage.setItem('mc_favorites', JSON.stringify(list)); } catch (e) {}
    }

    function isFavorite(song) {
        if (!song) return false;
        return getFavorites().some(s => s.platform === song.platform && s.id === song.id);
    }

    function toggleFavorite(song) {
        if (!song) return false;
        const list = getFavorites();
        const idx = list.findIndex(s => s.platform === song.platform && s.id === song.id);
        if (idx >= 0) { list.splice(idx, 1); saveFavorites(list); return false; }
        list.push(song); saveFavorites(list); return true;
    }

// === Utilities ===
    function platformName(p) {
        return {kugou: '酷狗', netease: '网易云', bilibili: 'B站'}[p] || p;
    }

    function formatTime(s) {
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`;
        return `${m}:${sec.toString().padStart(2, '0')}`;
    }

    function escHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function showToast(msg) {
        let t = document.getElementById('toast');
        if (!t) {
            t = document.createElement('div');
            t.id = 'toast';
            t.className = 'toast';
            document.body.appendChild(t);
        }
        t.textContent = msg;
        t.style.display = 'block';
        setTimeout(() => { t.style.display = 'none'; }, 2000);
    }
