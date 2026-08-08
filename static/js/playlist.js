let playlist = [];
let playIndex = -1;
let playlistVisible = false;
let playMode = 'sequence';

    function renderPlaylist() {
        const content = document.getElementById('playlistContent');
        document.getElementById('playlistCount').textContent = playlist.length;
        if (!playlist.length) {
            content.innerHTML = '<p class="playlist-empty">播放列表为空</p>';
            return;
        }
        content.innerHTML = playlist.map((s, i) => `
            <div class="playlist-item${i === playIndex ? ' active' : ''}" onclick="playFromPlaylist(${i})" oncontextmenu="showCtxMenuFrom(event, playlist, ${i})">
                <button class="playlist-fav-indicator${isFavorite(s) ? ' active' : ''}" onclick="event.stopPropagation();togglePlaylistFav(${i})" title="收藏">${isFavorite(s) ? '♥' : '♡'}</button>
                ${s.cover ? `<img class="playlist-item-cover" src="${s.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : '<div class="playlist-item-cover playlist-item-cover-ph"></div>'}
                <div class="playlist-item-info">
                    <div class="playlist-item-name">${escHtml(s.name)}</div>
                    <div class="playlist-item-artist">${escHtml(s.artist)}</div>
                </div>
                <span class="platform-badge badge-${s.platform}">${platformName(s.platform)}</span>
                <button class="playlist-item-remove" onclick="event.stopPropagation();removePlaylistItem(${i})" title="移除">&#10005;</button>
            </div>
        `).join('');
    }

    async function playFromPlaylist(index) {
        if (!playlist[index]) return;
        playIndex = index;
        savePlaylist();
        renderPlaylist();
        await loadAndPlay(playlist[index]);
    }

    function removePlaylistItem(index) {
        playlist.splice(index, 1);
        if (playlist.length === 0) {
            playIndex = -1;
        } else if (index < playIndex) {
            playIndex--;
        } else if (index === playIndex) {
            playIndex = Math.min(playIndex, playlist.length - 1);
        }
        savePlaylist();
        renderPlaylist();
    }

    function clearPlaylist() {
        playlist = [];
        playIndex = -1;
        savePlaylist();
        renderPlaylist();
    }

    function addToPlaylist(index) {
        const song = currentSongs[index];
        if (!song) return;
        playlist.push(song);
        savePlaylist();
        renderPlaylist();
    }

    const _modes = [
        { key: 'sequence', icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M20 12l-1.41-1.41L13 16.17V4h-2v12.17l-5.58-5.59L4 12l8 8 8-8z"/></svg>', label: '顺序播放' },
        { key: 'loop',     icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/></svg>', label: '列表循环' },
        { key: 'shuffle',  icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M10.59 9.17L5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41l-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/></svg>', label: '随机播放' },
        { key: 'single',   icon: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4zm-4-2V9h-1l-2 1v1h1.5v4H13z"/></svg>', label: '单曲循环' },
    ];

    function cyclePlayMode() {
        const i = _modes.findIndex(m => m.key === playMode);
        const next = _modes[(i + 1) % _modes.length];
        playMode = next.key;
        const btn = document.getElementById('modeBtn');
        btn.innerHTML = next.icon + ' ' + next.label;
        btn.title = next.label;
        savePlaylist();
    }

    function togglePlaylist() {
        const panel = document.getElementById('playlistPanel');
        playlistVisible = !playlistVisible;
        panel.style.display = playlistVisible ? 'flex' : 'none';
        if (playlistVisible) {
            _favoritesPanelVisible = false;
            document.getElementById('favoritesPanel').style.display = 'none';
        }
    }

    function savePlaylist() {
        try {
            localStorage.setItem('mc_playlist', JSON.stringify({ songs: playlist, index: playIndex, mode: playMode }));
        } catch (e) {}
    }

    function loadPlaylist() {
        try {
            const raw = localStorage.getItem('mc_playlist');
            if (raw) {
                const data = JSON.parse(raw);
                playlist = data.songs || [];
                playIndex = data.index != null ? data.index : -1;
                if (data.mode) playMode = data.mode;
            }
        } catch (e) {}
        const m = _modes.find(x => x.key === playMode) || _modes[0];
        const btn = document.getElementById('modeBtn');
        if (btn) {
            btn.innerHTML = m.icon + ' ' + m.label;
            btn.title = m.label;
        }
    }


    function togglePlaylistFav(index) {
        if (!playlist[index]) return;
        const nowFav = toggleFavorite(playlist[index]);
        renderPlaylist();
        document.querySelectorAll('.song-item').forEach(item => {
            const idx = parseInt(item.getAttribute('data-index'));
            const s = currentSongs[idx];
            if (s && s.platform === playlist[index].platform && s.id === playlist[index].id) {
                const btn = item.querySelector('.fav-btn');
                if (btn) { btn.classList.toggle('active', nowFav); btn.textContent = nowFav ? '♥' : '♡'; }
            }
        });
        if (_currentSong && _currentSong.platform === playlist[index].platform && _currentSong.id === playlist[index].id) {
            updatePlayerFavBtn();
        }
        if (_favoritesPanelVisible) renderFavoritesPanel();
    }

    loadPlaylist();
    renderPlaylist();

