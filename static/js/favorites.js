let _showingFavorites = false;

    function toggleFav(index) {
        const song = currentSongs[index];
        if (!song) return;
        const nowFav = toggleFavorite(song);
        const btns = document.querySelectorAll(`.song-item[data-index="${index}"] .fav-btn`);
        btns.forEach(btn => {
            btn.classList.toggle('active', nowFav);
            btn.textContent = nowFav ? '♥' : '♡';
        });
        if (_currentSong && _currentSong.platform === song.platform && _currentSong.id === song.id) {
            updatePlayerFavBtn();
        }
        if (_favoritesPanelVisible) renderFavoritesPanel();
        if (playlistVisible) renderPlaylist();
    }

    function togglePlayerFav() {
        if (!_currentSong) return;
        const nowFav = toggleFavorite(_currentSong);
        updatePlayerFavBtn();
        document.querySelectorAll('.song-item').forEach(item => {
            const idx = parseInt(item.getAttribute('data-index'));
            const s = currentSongs[idx];
            if (s && s.platform === _currentSong.platform && s.id === _currentSong.id) {
                const btn = item.querySelector('.fav-btn');
                if (btn) {
                    btn.classList.toggle('active', nowFav);
                    btn.textContent = nowFav ? '♥' : '♡';
                }
            }
        });
        if (_favoritesPanelVisible) renderFavoritesPanel();
        if (playlistVisible) renderPlaylist();
    }

    function updatePlayerFavBtn() {
        const btn = document.getElementById('playerFavBtn');
        if (!_currentSong) { btn.textContent = '♡'; btn.classList.remove('active'); return; }
        const fav = isFavorite(_currentSong);
        btn.textContent = fav ? '♥' : '♡';
        btn.classList.toggle('active', fav);
    }


    function showFavorites() {
        _showingFavorites = true;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        document.querySelector('[data-filter="favorites"]').classList.add('active');
        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('searchLoading').style.display = 'none';
        document.getElementById('pagination').style.display = 'none';

        currentSongs = getFavorites();
        currentPage = 1;
        if (!currentSongs.length) {
            document.getElementById('songList').innerHTML = '<p class="empty-text">还没有收藏歌曲</p>';
        } else {
            renderSongs(currentSongs);
        }
    }

    let _favoritesPanelVisible = false;

    function toggleFavoritesPanel() {
        _favoritesPanelVisible = !_favoritesPanelVisible;
        const panel = document.getElementById('favoritesPanel');
        panel.style.display = _favoritesPanelVisible ? 'flex' : 'none';
        if (_favoritesPanelVisible) {
            playlistVisible = false;
            document.getElementById('playlistPanel').style.display = 'none';
            renderFavoritesPanel();
        }
    }

    function renderFavoritesPanel() {
        const favs = getFavorites();
        const content = document.getElementById('favoritesContent');
        document.getElementById('favoritesCount').textContent = favs.length;
        if (!favs.length) {
            content.innerHTML = '<p class="favorites-empty">还没有收藏歌曲</p>';
            return;
        }
        content.innerHTML = favs.map((s, i) => `
            <div class="favorites-item${_currentSong && _currentSong.platform === s.platform && _currentSong.id === s.id ? ' active' : ''}" onclick="playFromFavorites(${i})" oncontextmenu="showCtxMenuFrom(event, _favoritesCache(), ${i})">
                ${s.cover ? `<img class="favorites-item-cover" src="${s.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : '<div class="favorites-item-cover favorites-item-cover-ph"></div>'}
                <div class="favorites-item-info">
                    <div class="favorites-item-name">${escHtml(s.name)}</div>
                    <div class="favorites-item-artist">${escHtml(s.artist)}</div>
                </div>
                <span class="platform-badge badge-${s.platform}">${platformName(s.platform)}</span>
                <button class="favorites-item-remove active" onclick="event.stopPropagation();removeFavoriteItem(${i})" title="取消收藏">♥</button>
            </div>
        `).join('');
    }

    function playFromFavorites(index) {
        const favs = getFavorites();
        if (!favs[index]) return;
        currentSongs = [...favs];
        playIndex = index;
        savePlaylist();
        renderPlaylist();
        loadAndPlay(favs[index]);
    }

    function removeFavoriteItem(index) {
        const favs = getFavorites();
        if (!favs[index]) return;
        const removed = favs[index];
        toggleFavorite(removed);
        renderFavoritesPanel();
        document.querySelectorAll('.song-item').forEach(item => {
            const idx = parseInt(item.getAttribute('data-index'));
            const s = currentSongs[idx];
            if (s && s.platform === removed.platform && s.id === removed.id) {
                const btn = item.querySelector('.fav-btn');
                if (btn) { btn.classList.remove('active'); btn.textContent = '♡'; }
            }
        });
        if (_currentSong && _currentSong.platform === removed.platform && _currentSong.id === removed.id) {
            updatePlayerFavBtn();
        }
        if (_showingFavorites) showFavorites();
    }

    function clearFavorites() {
        if (!confirm('确定清空所有收藏？')) return;
        const favs = getFavorites();
        for (const s of favs) toggleFavorite(s);
        renderFavoritesPanel();
        document.querySelectorAll('.fav-btn.active').forEach(btn => {
            btn.classList.remove('active');
            btn.textContent = '♡';
        });
        updatePlayerFavBtn();
        if (_showingFavorites) showFavorites();
    }
