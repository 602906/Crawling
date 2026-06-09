let currentFilter = 'all';
let currentPage = 1;
let currentSongs = [];

    function setFilter(f) {
        _showingFavorites = false;
        currentFilter = f;
        document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
        document.querySelector(`[data-filter="${f}"]`).classList.add('active');
    }

    async function doSearch(page) {
        const keyword = document.getElementById('searchInput').value.trim();
        if (!keyword) return;
        _showingFavorites = false;
        currentPage = page || 1;

        document.getElementById('emptyState').style.display = 'none';
        document.getElementById('searchLoading').style.display = 'flex';
        document.getElementById('songList').innerHTML = '';
        document.getElementById('pagination').style.display = 'none';

        try {
            const resp = await fetch(`/api/search?keyword=${encodeURIComponent(keyword)}&platform=${currentFilter}&page=${currentPage}`);
            const data = await resp.json();
            currentSongs = data.songs;
            renderSongs(data.songs);
            renderPagination(data.total, currentPage);

            if (data.errors && Object.keys(data.errors).length > 0) {
                console.warn('部分平台搜索出错:', data.errors);
            }
        } catch (e) {
            document.getElementById('songList').innerHTML = `<p class="error-text">搜索出错: ${e.message}</p>`;
        } finally {
            document.getElementById('searchLoading').style.display = 'none';
        }
    }

    function renderSongs(songs) {
        const list = document.getElementById('songList');
        if (!songs.length) {
            list.innerHTML = '<p class="empty-text">没有找到相关歌曲</p>';
            return;
        }

        list.innerHTML = songs.map((s, i) => `
            <div class="song-item" data-index="${i}" oncontextmenu="showCtxMenu(event, ${i})">
                <div class="song-index">${(currentPage - 1) * 20 + i + 1}</div>
                <div class="song-cover-wrap">
                    ${s.cover ? `<img class="song-cover" src="${s.cover}" referrerpolicy="no-referrer" alt="" onerror="this.style.display='none'">` : '<div class="song-cover-placeholder"></div>'}
                </div>
                <div class="song-info">
                    <div class="song-name">${escHtml(s.name)}</div>
                    <div class="song-artist">${escHtml(s.artist)} · ${escHtml(s.album)}</div>
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
                </div>
            </div>
        `).join('');
    }

    function renderPagination(total, page) {
        const pages = Math.ceil(total / 20);
        if (pages <= 1) { document.getElementById('pagination').style.display = 'none'; return; }

        const el = document.getElementById('pagination');
        el.style.display = 'flex';
        let html = '';
        if (page > 1) html += `<button class="page-btn" onclick="doSearch(${page - 1})">上一页</button>`;
        for (let i = Math.max(1, page - 2); i <= Math.min(pages, page + 2); i++) {
            html += `<button class="page-btn ${i === page ? 'active' : ''}" onclick="doSearch(${i})">${i}</button>`;
        }
        if (page < pages) html += `<button class="page-btn" onclick="doSearch(${page + 1})">下一页</button>`;
        el.innerHTML = html;
    }

    async function playSong(index) {
        const song = currentSongs[index];
        if (!song) return;

        playlist = [...currentSongs];
        playIndex = index;
        savePlaylist();
        renderPlaylist();
        await loadAndPlay(song);
    }
