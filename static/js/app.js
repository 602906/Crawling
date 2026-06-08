// app.js - shared utilities for Music Catch

document.addEventListener('DOMContentLoaded', () => {
    checkLoginStatus();
});

async function checkLoginStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        for (const [platform, info] of Object.entries(data)) {
            const badge = document.querySelector(`.filter-btn[data-filter="${platform}"] .badge`);
            if (info.logged_in && !badge) {
                const btn = document.querySelector(`.filter-btn[data-filter="${platform}"]`);
                if (btn) {
                    const span = document.createElement('span');
                    span.className = 'badge';
                    span.textContent = '已登录';
                    btn.appendChild(span);
                }
            }
        }
    } catch (e) {
        // ignore
    }
}

function _openAudioCache() {
    return new Promise((resolve, reject) => {
        const req = indexedDB.open('mc_audio_cache', 1);
        req.onupgradeneeded = () => req.result.createObjectStore('audio');
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
        alert('音频缓存已清除');
    } catch (e) {
        alert('清除失败: ' + e.message);
    }
}

let _favSet = null;

function _loadFavSet() {
    if (_favSet) return;
    try {
        const arr = JSON.parse(localStorage.getItem('mc_favorites') || '[]');
        _favSet = new Set(arr.map(s => s.platform + ':' + s.id));
    } catch (e) {
        _favSet = new Set();
    }
}

function getFavorites() {
    try {
        return JSON.parse(localStorage.getItem('mc_favorites') || '[]');
    } catch (e) {
        return [];
    }
}

function isFavorite(song) {
    _loadFavSet();
    return _favSet.has(song.platform + ':' + song.id);
}

function toggleFavorite(song) {
    _loadFavSet();
    const key = song.platform + ':' + song.id;
    let favs = getFavorites();
    if (_favSet.has(key)) {
        _favSet.delete(key);
        favs = favs.filter(s => !(s.platform === song.platform && s.id === song.id));
    } else {
        _favSet.add(key);
        favs.push(song);
    }
    localStorage.setItem('mc_favorites', JSON.stringify(favs));
    return _favSet.has(key);
}
