const audio = document.getElementById('audioPlayer');
const video = document.getElementById('videoPlayer');
let currentPlayer = audio;
let isVideo = false;
let _currentSong = null;

    async function loadAndPlay(song) {
        _currentSong = song;
        document.getElementById('playerTitle').textContent = song.name;
        document.getElementById('playerArtist').textContent = song.artist;
        updatePlayerFavBtn();
        const coverEl = document.getElementById('playerCover');
        if (song.cover) {
            coverEl.src = song.cover;
            coverEl.referrerPolicy = 'no-referrer';
        } else {
            coverEl.removeAttribute('src');
        }

        currentPlayer.pause();
        isVideo = song.platform === 'bilibili';
        currentPlayer = isVideo ? video : audio;
        speedIndex = 2;
        applySpeed(1);
        document.getElementById('speedBtn').textContent = '1x';
        document.getElementById('videoContainer').style.display = isVideo ? 'block' : 'none';
        document.getElementById('videoShowBtn').style.display = 'none';

        const safePlay = async () => {
            try {
                await currentPlayer.play();
                document.getElementById('playPauseBtn').innerHTML = '&#9646;&#9646;';
            } catch (e) {
                document.getElementById('playPauseBtn').innerHTML = '&#9654;';
                showToast('自动播放被浏览器阻止，请点击播放按钮');
            }
        };

        const extra = encodeURIComponent(JSON.stringify(song.extra));
        const cacheKey = `${song.platform}:${song.id}`;
        try {
            const cached = await getCachedAudio(cacheKey);
            if (cached) {
                currentPlayer.src = URL.createObjectURL(cached.blob);
                await safePlay();
                fetchLyrics(song);
                return;
            }

            const resp = await fetch(`/api/play/${song.platform}/${song.id}?extra=${extra}`);
            const data = await resp.json();
            if (data.url) {
                const proxyUrl = `/api/proxy?url=${encodeURIComponent(data.url)}`;
                const audioResp = await fetch(proxyUrl);
                const blob = await audioResp.blob();
                putCachedAudio(cacheKey, blob);
                currentPlayer.src = URL.createObjectURL(blob);
                await safePlay();
                fetchLyrics(song);
            } else {
                showToast('无法获取播放地址');
            }
        } catch (e) {
            showToast('播放出错: ' + e.message);
        }
    }

    function closeVideo() {
        document.getElementById('videoContainer').style.display = 'none';
        document.getElementById('videoShowBtn').style.display = '';
    }

    function showVideo() {
        document.getElementById('videoContainer').style.display = 'block';
        document.getElementById('videoShowBtn').style.display = 'none';
    }

    const speeds = [0.5, 0.75, 1, 1.25, 1.5, 2];
    let speedIndex = 2;
    let _desiredRate = 1;
    let _speedTimer = null;

    let _enforcingSpeed = false;

    function applySpeed(rate) {
        _desiredRate = rate;
        _enforcingSpeed = true;
        currentPlayer.playbackRate = rate;
        if (_speedTimer) clearInterval(_speedTimer);
        _speedTimer = setInterval(() => {
            if (Math.abs(currentPlayer.playbackRate - _desiredRate) > 0.01) {
                currentPlayer.playbackRate = _desiredRate;
            }
        }, 200);
    }

    // Instant rate enforcement via ratechange event
    function onRateChange() {
        if (_enforcingSpeed && Math.abs(this.playbackRate - _desiredRate) > 0.01) {
            this.playbackRate = _desiredRate;
        }
    }
    audio.addEventListener('ratechange', onRateChange);
    video.addEventListener('ratechange', onRateChange);

    function cycleSpeed() {
        speedIndex = (speedIndex + 1) % speeds.length;
        const s = speeds[speedIndex];
        applySpeed(s);
        document.getElementById('speedBtn').textContent = s + 'x';
    }

    let _savedRate = 1;
    let _pressTime = 0;
    let _pressTimer = null;
    let _longPressActive = false;
    const speedInd = document.getElementById('speedIndicator');

    function videoPressStart(e) {
        e.preventDefault();
        _pressTime = Date.now();
        if (currentPlayer.paused) return;
        _savedRate = _desiredRate;
        if (_pressTimer) clearTimeout(_pressTimer);
        _pressTimer = setTimeout(() => {
            _pressTimer = null;
            _longPressActive = true;
            applySpeed(2);
            speedInd.textContent = '2x 倍速播放中';
            speedInd.style.display = 'block';
        }, 1000);
    }

    function videoPressEnd() {
        if (_pressTimer) { clearTimeout(_pressTimer); _pressTimer = null; }
        if (speedInd.style.display === 'block') {
            applySpeed(_savedRate);
            speedInd.style.display = 'none';
        }
        if (_longPressActive) {
            Promise.resolve().then(() => { _longPressActive = false; });
        }
        _pressTime = 0;
    }

    // Safety net: auto-resume if browser pauses video after long-press release
    document.getElementById('videoPlayer').addEventListener('pause', () => {
        if (_longPressActive) {
            document.getElementById('videoPlayer').play();
        }
    });

    function togglePlay() {
        if (currentPlayer.paused) {
            currentPlayer.play();
            document.getElementById('playPauseBtn').innerHTML = '&#9646;&#9646;';
        } else {
            currentPlayer.pause();
            document.getElementById('playPauseBtn').innerHTML = '&#9654;';
        }
    }

    function prevTrack() {
        if (playIndex > 0) { playIndex--; savePlaylist(); renderPlaylist(); loadAndPlay(playlist[playIndex]); }
    }

    function nextTrack() {
        if (!playlist.length) return;
        if (playMode === 'single') {
            renderPlaylist();
            loadAndPlay(playlist[playIndex]);
        } else if (playMode === 'shuffle') {
            playIndex = Math.floor(Math.random() * playlist.length);
            savePlaylist();
            renderPlaylist();
            loadAndPlay(playlist[playIndex]);
        } else if (playMode === 'loop') {
            playIndex = (playIndex + 1) % playlist.length;
            savePlaylist();
            renderPlaylist();
            loadAndPlay(playlist[playIndex]);
        } else {
            if (playIndex < playlist.length - 1) { playIndex++; savePlaylist(); renderPlaylist(); loadAndPlay(playlist[playIndex]); }
        }
    }

    function seekTo(val) {
        if (currentPlayer.duration) currentPlayer.currentTime = (val / 100) * currentPlayer.duration;
    }

    function onTimeUpdate() {
        if (this.duration) {
            document.getElementById('progressBar').value = (this.currentTime / this.duration) * 100;
            document.getElementById('currentTime').textContent = formatTime(Math.floor(this.currentTime));
            document.getElementById('totalTime').textContent = formatTime(Math.floor(this.duration));
            updateLyricsHighlight(this.currentTime);
        }
    }
    audio.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('ended', () => nextTrack());
    video.addEventListener('ended', () => nextTrack());

    // Video events
    (function() {
        const vc = document.getElementById('videoContainer');
        const vp = document.getElementById('videoPlayer');

        // Block browser click-to-pause on video
        vp.addEventListener('click', e => { e.preventDefault(); e.stopPropagation(); });

        vc.addEventListener('mousedown', videoPressStart);
        vc.addEventListener('touchstart', videoPressStart, {passive: false});
        vc.addEventListener('mouseup', videoPressEnd);
        vc.addEventListener('touchend', videoPressEnd);
        vc.addEventListener('mouseleave', videoPressEnd);
        vc.addEventListener('touchcancel', videoPressEnd);
        const closeBtn = document.getElementById('videoCloseBtn');
        ['mousedown', 'touchstart'].forEach(evt =>
            closeBtn.addEventListener(evt, e => e.stopPropagation(), {passive: false})
        );
        ['mouseup', 'touchend'].forEach(evt =>
            closeBtn.addEventListener(evt, e => { e.stopPropagation(); e.preventDefault(); closeVideo(); })
        );
        closeBtn.addEventListener('click', closeVideo);
    })();

