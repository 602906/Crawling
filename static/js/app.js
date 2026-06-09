const AUDIO_CACHE_MAX = 200 * 1024 * 1024;

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

    async function putCachedAudio(key, blob) {
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
            store.put({ blob, ts: Date.now(), size: blob.size }, key);
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

