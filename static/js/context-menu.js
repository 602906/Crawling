    // === Context Menu ===
    let _ctxSong = null;
    let _ctxSource = null;
    let _ctxIndex = -1;
    function _favoritesCache() { return getFavorites(); }

    // 视频播放开关状态：关闭时隐藏“下载视频”入口（后端仍会 403 兜底）
    window._videoPlayback = true;
    fetch('/api/status').then(r => r.json()).then(d => {
        if (typeof d.video_playback === 'boolean') window._videoPlayback = d.video_playback;
    }).catch(() => {});

    function showCtxMenu(event, index) {
        showCtxMenuFrom(event, currentSongs, index);
    }

    function openSongMenuBtn(event, index) {
        event.preventDefault();
        event.stopPropagation();
        _ctxSong = currentSongs[index];
        _ctxSource = currentSongs;
        _ctxIndex = index;
        if (!_ctxSong) return;
        _populateCtxMenu();
        const menu = document.getElementById('ctxMenu');
        menu.style.display = 'block';
        const rect = event.currentTarget.getBoundingClientRect();
        const vw = window.innerWidth, vh = window.innerHeight;
        let x = rect.right - menu.offsetWidth;
        let y = rect.bottom + 4;
        if (x < 8) x = 8;
        if (y + menu.offsetHeight > vh) y = rect.top - menu.offsetHeight - 4;
        if (x + menu.offsetWidth > vw) x = vw - menu.offsetWidth - 8;
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';
        const sub = document.getElementById('ctxDownloadSub');
        if (x + menu.offsetWidth + 160 > vw) sub.classList.add('flip-left');
    }

    function _populateCtxMenu() {
        const favText = document.getElementById('ctxFavText');
        favText.textContent = isFavorite(_ctxSong) ? '♡ 取消收藏' : '♥ 收藏';

        // 仅当右键的正是当前播放歌曲且已有进度时，显示“从当前播放处分享”
        const shareAtItem = document.getElementById('ctxShareAtItem');
        const isPlayingSong = _currentSong && _ctxSong &&
            _currentSong.platform === _ctxSong.platform && _currentSong.id === _ctxSong.id;
        shareAtItem.style.display = (isPlayingSong && currentPlayer.currentTime > 1) ? 'block' : 'none';

        const sub = document.getElementById('ctxDownloadSub');
        const platform = _ctxSong.platform;
        let items = '';
        if (platform === 'kugou') {
            const q = [];
            q.push({v: '128', l: '标准 128k'});
            if (_ctxSong.extra && _ctxSong.extra.hq_hash) q.push({v: '320', l: '高品质 320k'});
            if (_ctxSong.extra && _ctxSong.extra.sq_hash) q.push({v: 'lossless', l: '无损 FLAC'});
            items = q.map(x => `<div class="ctx-item" onclick="event.stopPropagation();ctxDownload('${x.v}')">${x.l}</div>`).join('');
        } else if (platform === 'netease') {
            items = [
                {v: '128', l: '标准 128k'}, {v: '320', l: '高品质 320k'}, {v: 'lossless', l: '无损'}
            ].map(x => `<div class="ctx-item" onclick="event.stopPropagation();ctxDownload('${x.v}')">${x.l}</div>`).join('');
        } else if (platform === 'bilibili') {
            const v = [{v: 'video', l: '下载视频'}];
            if (window._videoPlayback === false) v.length = 0;  // 开关关闭时仅保留音频下载
            items = [
                ...v,
                {v: 'audio', l: '下载音频'}
            ].map(x => `<div class="ctx-item" onclick="event.stopPropagation();ctxDownload('${x.v}')">${x.l}</div>`).join('');
        }
        sub.innerHTML = items;

        const dlParent = document.getElementById('ctxDownloadItem');
        dlParent.classList.remove('sub-open');
        sub.classList.remove('flip-left');
    }

    function showCtxMenuFrom(event, source, index) {
        event.preventDefault();
        event.stopPropagation();
        _ctxSong = source[index];
        _ctxSource = source;
        _ctxIndex = index;
        if (!_ctxSong) return;

        _populateCtxMenu();
        const menu = document.getElementById('ctxMenu');
        menu.style.display = 'block';
        const vw = window.innerWidth, vh = window.innerHeight;
        let x = event.clientX, y = event.clientY;
        const mw = menu.offsetWidth, mh = menu.offsetHeight;
        if (x + mw > vw) x = vw - mw - 8;
        if (y + mh > vh) y = vh - mh - 8;
        menu.style.left = x + 'px';
        menu.style.top = y + 'px';

        const sub = document.getElementById('ctxDownloadSub');
        if (x + mw + 160 > vw) sub.classList.add('flip-left');
    }

    function hideContextMenu() {
        const menu = document.getElementById('ctxMenu');
        menu.style.display = 'none';
        document.getElementById('ctxDownloadItem').classList.remove('sub-open');
    }

    document.addEventListener('click', (e) => {
        if (!e.target.closest('.ctx-menu')) hideContextMenu();
    });
    document.addEventListener('contextmenu', (e) => {
        if (!e.target.closest('.song-item') && !e.target.closest('.playlist-item') && !e.target.closest('.favorites-item') && !e.target.closest('.ctx-menu')) {
            hideContextMenu();
        }
    });

    document.getElementById('ctxDownloadItem').addEventListener('click', function(e) {
        e.stopPropagation();
        this.classList.toggle('sub-open');
    });

    function ctxPlay() { hideContextMenu(); if (_ctxSong) { const idx = currentSongs.indexOf(_ctxSong); if (idx >= 0) playSong(idx); else { currentSongs = [_ctxSong, ...currentSongs]; playSong(0); } } }
    function ctxAddToPlaylist() { hideContextMenu(); if (_ctxSong) { playlist.push(_ctxSong); savePlaylist(); renderPlaylist(); } }
    function ctxToggleFav() {
        hideContextMenu();
        if (!_ctxSong) return;
        toggleFavorite(_ctxSong);
        if (_favoritesPanelVisible) renderFavoritesPanel();
        if (playlistVisible) renderPlaylist();
        document.querySelectorAll('.song-item').forEach(item => {
            const idx = parseInt(item.getAttribute('data-index'));
            const s = currentSongs[idx];
            if (s && s.platform === _ctxSong.platform && s.id === _ctxSong.id) {
                const btn = item.querySelector('.fav-btn');
                if (btn) { const f = isFavorite(_ctxSong); btn.classList.toggle('active', f); btn.textContent = f ? '♥' : '♡'; }
            }
        });
        if (_currentSong && _currentSong.platform === _ctxSong.platform && _currentSong.id === _ctxSong.id) updatePlayerFavBtn();
        if (_showingFavorites) showFavorites();
    }

    function ctxDownload(quality) {
        hideContextMenu();
        if (!_ctxSong) return;
        const s = _ctxSong;
        const extra = encodeURIComponent(JSON.stringify(s.extra));
        let params = `extra=${extra}&name=${encodeURIComponent(s.name)}&artist=${encodeURIComponent(s.artist)}&quality=${quality}`;
        const url = `/api/download/${s.platform}/${s.id}?${params}`;
        const doDownload = () => {
            const a = document.createElement('a');
            a.href = url;
            document.body.appendChild(a);
            a.click();
            a.remove();
        };
        if (quality === 'lossless') {
            fetch(url, { method: 'HEAD' })
                .then(r => {
                    const cd = r.headers.get('content-disposition') || '';
                    const m = cd.match(/filename\*?=(?:UTF-8''|")?([^";]+)/i);
                    const fn = m ? decodeURIComponent(m[1].replace(/"/g, '')) : '';
                    if (fn && fn.toLowerCase().endsWith('.mp3')) {
                        showToast('该歌曲暂无无损资源，将下载 320k MP3');
                    }
                    doDownload();
                })
                .catch(() => doDownload());
        } else {
            doDownload();
        }
    }

    async function ctxAnalyze() {
        hideContextMenu();
        if (!_ctxSong) return;
        const s = _ctxSong;
        const extra = encodeURIComponent(JSON.stringify(s.extra));
        const params = `extra=${extra}&name=${encodeURIComponent(s.name)}&artist=${encodeURIComponent(s.artist)}&album=${encodeURIComponent(s.album)}&duration=${s.duration || 0}`;
        try {
            const resp = await fetch(`/api/info/${s.platform}/${s.id}?${params}`);
            const data = await resp.json();
            const dur = s.duration ? `${Math.floor(s.duration / 60)}:${String(s.duration % 60).padStart(2, '0')}` : '-';
            const qualities = (data.qualities || []).map(q => q.label).join('、') || '-';
            let extraInfo = '';
            if (s.platform === 'kugou' && s.extra) {
                if (s.extra.hash) extraInfo += `<div class="info-row"><span class="info-key">Hash (128k)</span><span class="info-val">${s.extra.hash}</span></div>`;
                if (s.extra.hq_hash) extraInfo += `<div class="info-row"><span class="info-key">HQ Hash (320k)</span><span class="info-val">${s.extra.hq_hash}</span></div>`;
                if (s.extra.sq_hash) extraInfo += `<div class="info-row"><span class="info-key">SQ Hash (无损)</span><span class="info-val">${s.extra.sq_hash}</span></div>`;
                if (s.extra.album_id) extraInfo += `<div class="info-row"><span class="info-key">Album ID</span><span class="info-val">${s.extra.album_id}</span></div>`;
            } else if (s.platform === 'netease') {
                extraInfo += `<div class="info-row"><span class="info-key">Song ID</span><span class="info-val">${s.id}</span></div>`;
                if (s.extra && s.extra.fee !== undefined) extraInfo += `<div class="info-row"><span class="info-key">Fee</span><span class="info-val">${s.extra.fee}</span></div>`;
            } else if (s.platform === 'bilibili') {
                extraInfo += `<div class="info-row"><span class="info-key">BVID</span><span class="info-val">${s.extra && s.extra.bvid ? s.extra.bvid : s.id}</span></div>`;
            }
            const html = `
                <div class="info-row"><span class="info-key">歌曲</span><span class="info-val">${escHtml(data.name)}</span></div>
                <div class="info-row"><span class="info-key">歌手</span><span class="info-val">${escHtml(data.artist)}</span></div>
                <div class="info-row"><span class="info-key">专辑</span><span class="info-val">${escHtml(data.album) || '-'}</span></div>
                <div class="info-row"><span class="info-key">平台</span><span class="info-val">${escHtml(data.platform_name)}</span></div>
                <div class="info-row"><span class="info-key">时长</span><span class="info-val">${dur}</span></div>
                <div class="info-row"><span class="info-key">可用音质</span><span class="info-val">${qualities}</span></div>
                ${extraInfo}
            `;
            document.getElementById('infoModalBody').innerHTML = html;
            document.getElementById('infoOverlay').style.display = 'flex';
        } catch (e) {
            alert('获取歌曲信息失败: ' + e.message);
        }
    }

    function closeInfoModal() {
        document.getElementById('infoOverlay').style.display = 'none';
    }

    function ctxShare() {
        hideContextMenu();
        if (!_ctxSong) return;
        _copyShareLink(_ctxSong, 0);
    }

    // 从当前播放进度处分享：链接附带 t 秒数，打开后自动跳转
    function ctxShareAt() {
        hideContextMenu();
        if (!_ctxSong) return;
        _copyShareLink(_ctxSong, Math.floor(currentPlayer.currentTime || 0));
    }

    function _copyShareLink(s, seconds) {
        let text = `${s.name} - ${s.artist} (${platformName(s.platform)})`;
        let url = `${location.origin}/?autoplay=1&platform=${encodeURIComponent(s.platform)}&id=${encodeURIComponent(s.id)}`;
        if (seconds > 0) {
            url += `&t=${seconds}`;
            text += ` [${formatTime(seconds)} 处]`;
        }
        const shareText = `${text}\n${url}`;
        const doneMsg = seconds > 0 ? `已复制分享链接（从 ${formatTime(seconds)} 处播放）` : '已复制分享链接';
        const silentCopy = () => {
            const ta = document.createElement('textarea');
            ta.value = shareText;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); } catch (e) {}
            document.body.removeChild(ta);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(shareText).then(() => {
                showToast(doneMsg);
            }).catch(() => {
                silentCopy();
                showToast(doneMsg);
            });
        } else {
            silentCopy();
            showToast(doneMsg);
        }
    }

    async function checkShareAutoplay() {
        const params = new URLSearchParams(location.search);
        if (params.get('autoplay') !== '1') return;
        const platform = params.get('platform');
        const id = params.get('id');
        if (!platform || !id) return;
        const startAt = parseInt(params.get('t') || '0', 10) || 0;

        showToast('正在加载歌曲...');
        let song;
        try {
            const resp = await fetch(`/api/resolve-song/${encodeURIComponent(platform)}/${encodeURIComponent(id)}`);
            if (!resp.ok) throw new Error('resolve failed');
            song = await resp.json();
        } catch (e) {
            showToast('歌曲加载失败');
            history.replaceState({}, '', location.pathname);
            return;
        }

        if (!playlist.some(p => p.platform === song.platform && p.id === song.id)) {
            playlist.push(song);
            savePlaylist();
            renderPlaylist();
        }
        playIndex = playlist.findIndex(p => p.platform === song.platform && p.id === song.id);
        savePlaylist();
        renderPlaylist();
        await loadAndPlay(song);
        if (startAt > 0) _seekWhenReady(startAt);
        if (!lyricsVisible) toggleLyrics();
        history.replaceState({}, '', location.pathname);
    }

    // 媒体元数据就绪后跳转到指定秒数（超出时长则不跳）
    function _seekWhenReady(seconds) {
        const player = currentPlayer;
        const doSeek = () => {
            if (player !== currentPlayer) return; // 已切歌，放弃
            if (player.duration && seconds < player.duration) {
                player.currentTime = seconds;
            }
        };
        if (player.readyState >= 1 && player.duration) {
            doSeek();
        } else {
            player.addEventListener('loadedmetadata', doSeek, { once: true });
        }
    }
    checkShareAutoplay();

