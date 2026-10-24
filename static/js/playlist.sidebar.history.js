/* 历史缓存（playlist.sidebar.history）
 * 侧栏底部「历史缓存」条目 → 点击把已正常写入 IndexedDB 的缓存歌曲展示到主列表 #songList
 * 交互约定：
 *   - 主搜索框输入文本 = 实时过滤本地缓存（不需要点搜索按钮）
 *   - 主搜索框回车 / 点「搜索」按钮 = 走服务器搜索，并退出历史缓存视图
 *   - 缓存歌曲行额外提供「删除该歌曲缓存」按钮
 */
(function () {
    'use strict';

    var _allSongs = [];       // 全部缓存歌曲（未过滤）
    var _viewSongs = [];      // 当前展示（已过滤）
    var _active = false;      // 历史缓存视图是否处于激活状态
    var _count = 0;           // 缓存总数（与视图是否打开无关，关闭后仍保留）

    // ── IndexedDB 读取 ──
    function _readAll() {
        return new Promise(function (resolve) {
            if (typeof _openAudioCache !== 'function') return resolve([]);
            _openAudioCache().then(function (db) {
                var out = [];
                try {
                    var tx = db.transaction('audio', 'readonly');
                    var req = tx.objectStore('audio').openCursor();
                    req.onsuccess = function () {
                        var cur = req.result;
                        if (!cur) return resolve(out);
                        var v = cur.value || {};
                        var m = v.meta || {};
                        var i = String(cur.key).indexOf(':');
                        var platform = i >= 0 ? cur.key.slice(0, i) : '';
                        var id = i >= 0 ? cur.key.slice(i + 1) : String(cur.key);
                        out.push({
                            _cacheKey: cur.key,
                            _cachedSize: v.size || 0,
                            _cachedTs: v.ts || 0,
                            platform: platform,
                            id: id,
                            name: m.name || id,
                            artist: m.artist || '',
                            album: m.album || '',
                            cover: m.cover || '',
                            duration: m.duration || 0,
                            extra: m.extra || null
                        });
                        cur.continue();
                    };
                    req.onerror = function () { resolve(out); };
                } catch (e) { resolve(out); }
            }).catch(function () { resolve([]); });
        });
    }

    // ── 视图开关 ──
    function openHistoryCache() {
        _active = true;
        _hidePlaylistActive();
        // 打开时清空搜索框，避免上次的关键词让缓存列表看起来是空的
        var input = document.getElementById('searchInput');
        if (input) input.value = '';
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('searchLoading').style.display = 'none';
        document.getElementById('pagination').style.display = 'none';

        return _readAll().then(function (rows) {
            // 最新缓存在最前
            rows.sort(function (a, b) { return b._cachedTs - a._cachedTs; });
            _allSongs = rows;
            _count = rows.length;
            _applyKeyword();
            _render();
            _updateEntryMeta();
            if (!_allSongs.length) {
                showToast('暂无历史缓存，先播放几首歌吧');
            }
        });
    }

    function closeHistoryCache() {
        if (!_active) return;
        _active = false;
        _allSongs = [];
        _viewSongs = [];
        // 保留 _count：退出视图后侧栏仍显示真实缓存数量
        _updateEntryMeta();
    }

    function isHistoryCacheActive() { return _active; }

    // 退出历史缓存时，取消侧栏条目的高亮态
    function _hidePlaylistActive() {
        if (typeof _activePlaylistId !== 'undefined') {
            if (typeof hideMyPlaylistView === 'function') hideMyPlaylistView();
        }
    }

    // ── 实时过滤（主搜索框输入）──
    function _applyKeyword() {
        var input = document.getElementById('searchInput');
        var kw = ((input && input.value) || '').trim().toLowerCase();
        if (!kw) { _viewSongs = _allSongs.slice(); return; }
        _viewSongs = _allSongs.filter(function (s) {
            return ((s.name || '') + ' ' + (s.artist || '') + ' ' + (s.platform || ''))
                .toLowerCase().indexOf(kw) !== -1;
        });
    }

    function filterHistoryCache() {
        if (!_active) return;
        _applyKeyword();
        _render();
    }

    // ── 渲染到主列表 ──
    function _fmtSize(bytes) {
        if (!bytes) return '';
        if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + ' KB';
        return (bytes / 1024 / 1024).toFixed(1) + ' MB';
    }

    function _render() {
        var list = document.getElementById('songList');
        if (!list) return;

        currentSongs = _viewSongs.slice();
        currentPage = 1;

        if (!_viewSongs.length) {
            list.innerHTML = '<p class="empty-text">' +
                (_allSongs.length ? '没有匹配的缓存歌曲' : '暂无历史缓存，先播放几首歌吧') + '</p>';
            return;
        }

        list.innerHTML = currentSongs.map(function (s, i) {
            var meta = [];
            if (s.artist) meta.push(s.artist);
            var size = _fmtSize(s._cachedSize);
            if (size) meta.push(size);
            return `
            <div class="song-item" data-index="${i}" ondblclick="playSong(${i})" oncontextmenu="showCtxMenu(event, ${i})">
                <div class="song-index">${i + 1}</div>
                <div class="song-cover-wrap">
                    ${s.cover ? `<img class="song-cover" src="${s.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : '<div class="song-cover-placeholder"></div>'}
                </div>
                <div class="song-info">
                    <div class="song-name">${escHtml(s.name)}</div>
                    <div class="song-artist">${escHtml(meta.join(' · '))}</div>
                </div>
                <div class="song-platform">
                    <span class="platform-badge badge-${s.platform}">${platformName(s.platform)}</span>
                </div>
                <div class="song-duration">${formatTime(s.duration)}</div>
                <div class="song-actions">
                    <button class="action-btn fav-btn${isFavorite(s) ? ' active' : ''}" onclick="toggleFav(${i})" title="收藏">${isFavorite(s) ? '♥' : '♡'}</button>
                    <button class="action-btn" onclick="playSong(${i})" title="播放">&#9654;</button>
                    <button class="action-btn" onclick="addToPlaylist(${i})" title="添加到播放列表">+</button>
                    <button class="action-btn song-menu-btn" onclick="openSongMenuBtn(event, ${i})" title="更多">&#8943;</button>
                    <button class="action-btn history-del-btn" onclick="deleteHistoryCacheOf(${i})" title="删除该歌曲缓存">
                        <svg viewBox="0 0 24 24" fill="currentColor" style="width:15px;height:15px"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                    </button>
                </div>
            </div>`;
        }).join('');
    }

    // ── 删除 ──
    function deleteHistoryCacheOf(index) {
        var s = _viewSongs[index];
        if (!s) return;
        if (typeof deleteCachedAudio !== 'function') return;
        deleteCachedAudio(s._cacheKey).then(function () {
            showToast('已删除「' + s.name + '」的缓存');
            return openHistoryCache();
        });
    }

    function deleteAllHistoryCache() {
        if (!_allSongs.length && !_active) {
            // 未打开视图时也要能清空：先读一次
            _readAll().then(function (rows) {
                if (!rows.length) { showToast('暂无历史缓存'); return; }
                if (!confirm('确定清空全部历史缓存？')) return;
                if (typeof clearAudioCache === 'function') {
                    clearAudioCache();
                    openHistoryCache();
                }
            });
            return;
        }
        if (!confirm('确定清空全部历史缓存？')) return;
        if (typeof clearAudioCache === 'function') {
            clearAudioCache();
            openHistoryCache();
        }
    }

    // ── 侧栏条目数量 ──
    function _updateEntryMeta() {
        var entry = document.getElementById('playlistSidebarHistoryEntry');
        if (!entry) return;
        var meta = entry.querySelector('.playlist-sidebar-item-meta');
        if (meta) meta.textContent = _count
            ? _count + ' 首 · 点击显示缓存歌曲'
            : '0 首 · 点击显示缓存歌曲';
    }

    // 只刷新数量，不打开视图（缓存写入/删除后调用）
    function refreshHistoryCount() {
        return _readAll().then(function (rows) {
            _count = rows.length;
            _updateEntryMeta();
        });
    }

    // ── 暴露接口 ──
    window.historyCacheView = {
        open: openHistoryCache,
        close: closeHistoryCache,
        filter: filterHistoryCache,
        isActive: isHistoryCacheActive,
        refresh: function () { return _active ? openHistoryCache() : refreshHistoryCount(); },
        deleteOf: deleteHistoryCacheOf
    };
    window.openHistoryCache = openHistoryCache;
    window.closeHistoryCache = closeHistoryCache;
    window.deleteHistoryCacheOf = deleteHistoryCacheOf;
    window.filterHistoryCache = filterHistoryCache;
    window.isHistoryCacheActive = isHistoryCacheActive;
    window.refreshHistoryCache = refreshHistoryCount;

    // ── 初始化 ──
    function _init() {
        var entry = document.getElementById('playlistSidebarHistoryEntry');
        if (entry) {
            // 每次点击都重新读取缓存并渲染（可重复点击，不做锁定）
            entry.addEventListener('click', function () {
                openHistoryCache();
            });
        }
        // 主搜索框：输入 = 实时过滤本地缓存；回车 = 走服务器搜索并退出
        var input = document.getElementById('searchInput');
        if (input) {
            input.addEventListener('input', function () {
                if (_active) filterHistoryCache();
            });
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && _active) {
                    e.preventDefault();
                    closeHistoryCache();          // 回车 = 服务器搜索
                    doSearch();
                }
            });
        }
        // 点「搜索」按钮 = 服务器搜索并退出历史缓存
        var btn = document.querySelector('.search-btn');
        if (btn) {
            btn.addEventListener('click', function () {
                if (_active) closeHistoryCache();
            });
        }
        // 启动时先刷一次数量（避免初始一直显示 0）
        refreshHistoryCount();
        _updateEntryMeta();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', _init);
    } else {
        _init();
    }
})();
