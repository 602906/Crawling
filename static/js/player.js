const audio = document.getElementById('audioPlayer');
const video = document.getElementById('videoPlayer');
let currentPlayer = audio;
let isVideo = false;
let _currentSong = null;

// 播放器控件图标统一用内联 SVG（currentColor 继承按钮文字色），
// 字符/emoji 在不同设备上渲染不一（手机可能显示彩色/缺字形）
const _ICONS = {
    play: '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
    fav: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>',
    favBorder: '<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor"><path d="M16.5 3c-1.74 0-3.41.81-4.5 2.09C10.91 3.81 9.24 3 7.5 3 4.42 3 2 5.42 2 8.5c0 3.78 3.4 6.86 8.55 11.54L12 21.35l1.45-1.32C18.6 15.36 22 12.28 22 8.5 22 5.42 19.58 3 16.5 3zm-4.4 15.55l-.1.1-.1-.1C7.14 14.24 4 11.39 4 8.5 4 6.5 5.5 5 7.5 5c1.54 0 3.04.99 3.57 2.36h1.87C13.46 5.99 14.96 5 16.5 5c2 0 3.5 1.5 3.5 3.5 0 2.89-3.14 5.74-7.9 10.05z"/></svg>',
};

// 加载令牌：快速切歌时丢弃过期的异步结果，防止竞态
let _loadToken = 0;
// 当前使用的 blob URL，切歌时释放，避免内存泄漏
let _activeBlobUrl = null;
// 正在进行的后台缓存请求，切歌时中止，避免缓存不完整数据
let _bgCacheAbort = null;
// 缓存播放失败时的回退信息 { key, proxyUrl, token }
let _cacheFallback = null;
// 当前在线流的代理 URL（中断自动重连用）
let _onlineUrl = null;
// 重连次数（限次防止死循环）、卡住计时器、待恢复播放位置
let _retryCount = 0;
let _stallTimer = null;
let _pendingSeek = 0;

    function _setSrc(player, url, isBlob) {
        if (_activeBlobUrl) {
            URL.revokeObjectURL(_activeBlobUrl);
            _activeBlobUrl = null;
        }
        if (isBlob) _activeBlobUrl = url;
        player.src = url;
    }

    function _resetPlayer(player) {
        player.pause();
        if (player.getAttribute('src')) {
            player.removeAttribute('src');
            player.load();
        }
    }

    // 同步视频容器位置：底部紧贴播放条（移动端播放条高度可变）
    function _syncVideoPosition() {
        const bar = document.getElementById('playerBar');
        const h = bar ? bar.offsetHeight : 72;
        document.documentElement.style.setProperty('--player-bar-h', h + 'px');
    }
    window.addEventListener('resize', _syncVideoPosition);
    _syncVideoPosition();

    async function loadAndPlay(song) {
        const token = ++_loadToken;
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

        // 中止上一首的后台缓存
        if (_bgCacheAbort) { _bgCacheAbort.abort(); _bgCacheAbort = null; }
        _cacheFallback = null;
        _onlineUrl = null;
        _retryCount = 0;

        // 播放器类型由 /api/play 响应决定：video:true 才启用视频播放器；
        // 视频开关关闭时接口返回音频流，全程走音频（不闪现视频窗口）
        isVideo = false;
        const player = audio;
        const other = video;
        _resetPlayer(currentPlayer);
        _resetPlayer(other);
        currentPlayer = player;
        speedIndex = 2;
        applySpeed(1);
        document.getElementById('speedBtn').textContent = '1x';
        document.getElementById('videoContainer').style.display = 'none';
        document.getElementById('videoShowBtn').style.display = 'none';

        const extra = encodeURIComponent(JSON.stringify(song.extra));
        const cacheKey = `${song.platform}:${song.id}`;
        try {
            const resp = await fetch(`/api/play/${song.platform}/${song.id}?extra=${extra}`);
            const data = await resp.json();
            if (token !== _loadToken) return;
            if (!data.url) { showToast('无法获取播放地址'); return; }

            // 接口明确返回视频流时才切换视频播放器
            if (data.video) {
                isVideo = true;
                const vp = video;
                const vo = audio;
                _resetPlayer(currentPlayer);
                _resetPlayer(vo);
                currentPlayer = vp;
                document.getElementById('videoContainer').style.display = 'block';
                _syncVideoPosition();
            }

            const proxyUrl = `/api/proxy?url=${encodeURIComponent(data.url)}`;
            _onlineUrl = proxyUrl;

            // 仅音频走 IndexedDB 缓存（视频流不缓存）
            let cached = null;
            if (!isVideo) {
                cached = await getCachedAudio(cacheKey);
                if (token !== _loadToken) return;
                if (cached && !(await isValidMediaBlob(cached.blob))) {
                    // 旧版本可能缓存了错误页/损坏数据，清掉后走在线播放
                    deleteCachedAudio(cacheKey);
                    cached = null;
                }
                if (cached && cached.total && cached.blob.size < cached.total) {
                    // 下载中断写入的截断缓存：播放必然中断，清掉后走在线播放
                    deleteCachedAudio(cacheKey);
                    cached = null;
                }
            }

            if (cached) {
                // 记录回退信息：若 blob 解码失败则删缓存改用在线流
                _cacheFallback = { key: cacheKey, proxyUrl, token };
                _setSrc(currentPlayer, URL.createObjectURL(cached.blob), true);
            } else {
                _setSrc(currentPlayer, proxyUrl, false);
            }

            await _safePlay(currentPlayer, token);
            fetchLyrics(song);

            if (!cached && !isVideo) {
                _bgCacheAbort = new AbortController();
                _bgCacheAudio(cacheKey, proxyUrl, _bgCacheAbort.signal);
            }
        } catch (e) {
            if (token === _loadToken) showToast('播放出错: ' + e.message);
        }
    }

    // === 自动播放被拦截时的解锁机制 ===
    // 策略：先降级为静音自动播放（浏览器普遍允许），首次交互时恢复声音；
    // 若静音播放也被拒，则首次交互时直接补播
    let _unlockHandler = null;

    function _clearUnlock() {
        if (_unlockHandler) {
            document.removeEventListener('pointerdown', _unlockHandler, true);
            document.removeEventListener('keydown', _unlockHandler, true);
            _unlockHandler = null;
        }
    }

    function _armUnlock(fn) {
        _clearUnlock();
        _unlockHandler = () => { _clearUnlock(); fn(); };
        document.addEventListener('pointerdown', _unlockHandler, true);
        document.addEventListener('keydown', _unlockHandler, true);
    }

    async function _safePlay(player, token) {
        try {
            await player.play();
            if (token === _loadToken) {
                document.getElementById('playPauseBtn').innerHTML = _ICONS.pause;
            }
        } catch (e) {
            if (token !== _loadToken) return;
            if (e.name === 'NotAllowedError') {
                try {
                    // 降级：静音自动播放
                    player.muted = true;
                    await player.play();
                    if (token !== _loadToken) { player.muted = _muted; return; }
                    document.getElementById('playPauseBtn').innerHTML = _ICONS.pause;
                    showToast('已静音自动播放，点击页面任意处恢复声音');
                    _armUnlock(() => {
                        if (token === _loadToken) player.muted = _muted;
                    });
                } catch (e2) {
                    if (token !== _loadToken) return;
                    player.muted = _muted;
                    document.getElementById('playPauseBtn').innerHTML = _ICONS.play;
                    showToast('自动播放被浏览器阻止，点击任意处开始播放');
                    _armUnlock(() => {
                        if (token === _loadToken) _safePlay(player, token);
                    });
                }
            } else if (e.name !== 'AbortError') {
                // 解码/格式错误，交由 error 事件统一处理缓存回退
                _handleMediaError(player);
            }
        }
    }

    // 缓存 blob 播放失败 -> 删除坏缓存并回退到在线流
    function _handleMediaError(player) {
        const fb = _cacheFallback;
        if (!fb || fb.token !== _loadToken || player !== currentPlayer) return;
        _cacheFallback = null;
        deleteCachedAudio(fb.key);
        showToast('缓存已损坏，改用在线播放');
        _setSrc(player, fb.proxyUrl + '&retry=' + Date.now(), false);
        _safePlay(player, fb.token);
    }
    audio.addEventListener('error', function () { _handleMediaError(this); });
    video.addEventListener('error', function () { _handleMediaError(this); });

    // === 播放中断检测 ===
    // 缓存播放卡住 -> 强制回退在线流；在线流卡住 -> 自动重连并恢复进度
    // 先确保门禁 token 有效：心跳失败（服务重启/过期）时重新注册并刷新页面
    // （动态 cookie 名由服务端 Set-Cookie 下发，JS 无法预知 → 刷新让新 cookie 生效）
    function _ensureGate() {
        return fetch('/api/gate/heartbeat', { method: 'POST', credentials: 'same-origin' })
            .then(r => r.json())
            .then(d => {
                if (d && d.ok) return true;
                return fetch('/api/gate/register', { credentials: 'same-origin' })
                    .then(r => (r.status === 429 ? null : r.json()))
                    .then(d2 => {
                        if (!d2 || !d2.token) return false;
                        location.reload();
                        return new Promise(function () {});
                    });
            })
            .catch(() => false);
    }

    function _onStalled() {
        const player = currentPlayer;
        if (!player || player.paused || player.ended || _stallTimer) return;
        // 正在播缓存且卡住（截断缓存数据耗尽/解码停滞）→ 回退在线流
        if (_cacheFallback && _cacheFallback.token === _loadToken) {
            _handleMediaError(player);
            return;
        }
        if (!_onlineUrl) return;
        _stallTimer = setTimeout(() => {
            _stallTimer = null;
            if (player.paused || player.ended || player !== currentPlayer) return;
            if (_retryCount >= 2) {
                _retryCount = 0;
                showToast('网络中断，播放已停止，请重试');
                return;
            }
            _retryCount++;
            const pos = player.currentTime || 0;
            // 先确保门禁 token 有效再重连（失效则自动重新注册激活，播放不中断）
            _ensureGate().then(ok => {
                if (!ok) { showToast('连接已断开，请刷新页面'); return; }
                if (player.paused || player.ended || player !== currentPlayer) return;
                _pendingSeek = pos;
                _setSrc(player, _onlineUrl + '&retry=' + Date.now(), false);
                player.play().catch(() => {});
            });
        }, 3000);
    }

    function _clearStall() {
        clearTimeout(_stallTimer);
        _stallTimer = null;
    }

    function _onLoadedMeta() {
        if (_pendingSeek > 0 && this === currentPlayer) {
            const pos = _pendingSeek;
            _pendingSeek = 0;
            try { this.currentTime = pos; } catch (e) {}
        }
    }

    ['stalled', 'waiting'].forEach(ev => {
        audio.addEventListener(ev, _onStalled);
        video.addEventListener(ev, _onStalled);
    });
    ['playing', 'canplay', 'seeked'].forEach(ev => {
        audio.addEventListener(ev, _clearStall);
        video.addEventListener(ev, _clearStall);
    });
    audio.addEventListener('loadedmetadata', _onLoadedMeta);
    video.addEventListener('loadedmetadata', _onLoadedMeta);
    audio.addEventListener('playing', () => { _retryCount = 0; });
    video.addEventListener('playing', () => { _retryCount = 0; });

    const _cachingKeys = new Set();
    async function _bgCacheAudio(key, proxyUrl, signal) {
        if (_cachingKeys.has(key)) return;
        _cachingKeys.add(key);
        try {
            const resp = await fetch(proxyUrl, { signal });
            const ct = (resp.headers.get('content-type') || '').toLowerCase();
            // 代理出错时会返回 JSON/HTML，绝不能写进缓存
            if (!resp.ok || ct.includes('json') || ct.includes('html') || ct.startsWith('text/')) return;
            const len = resp.headers.get('content-length');
            const blob = await resp.blob();
            // Content-Length 声明与实收不符 = 下载中断，绝不写缓存，防止截断音频下次播放中断
            if (len && blob.size !== Number(len)) return;
            if (!(await isValidMediaBlob(blob))) return;
            await putCachedAudio(key, blob, len ? Number(len) : blob.size);
        } catch (e) {
        } finally {
            _cachingKeys.delete(key);
        }
    }

    function closeVideo() {
        document.getElementById('videoContainer').style.display = 'none';
        document.getElementById('videoShowBtn').style.display = '';
    }

    function showVideo() {
        document.getElementById('videoContainer').style.display = 'block';
        document.getElementById('videoShowBtn').style.display = 'none';
        _syncVideoPosition();
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
    video.addEventListener('pause', () => {
        if (_longPressActive) {
            video.play();
        }
    });

    function togglePlay() {
        if (currentPlayer.paused) {
            currentPlayer.play();
            document.getElementById('playPauseBtn').innerHTML = _ICONS.pause;
        } else {
            currentPlayer.pause();
            document.getElementById('playPauseBtn').innerHTML = _ICONS.play;
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

    // === 音量控制：同时作用于音频/视频元素，选择持久化到 localStorage ===
    let _volume = 1;
    let _muted = false;

    // 音量图标用内联 SVG（currentColor 继承按钮文字色），
    // emoji 在手机上会忽略 &#xFE0E; 渲染成彩色，风格不统一
    const _VOL_SVG = {
        high: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>',
        low: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M5 9v6h4l5 5V4L9 9H5zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/></svg>',
        muted: '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>'
    };

    function _applyVolume() {
        audio.volume = _volume;
        video.volume = _volume;
        audio.muted = _muted;
        video.muted = _muted;
        const btn = document.getElementById('volumeBtn');
        btn.innerHTML = (_muted || _volume === 0) ? _VOL_SVG.muted : (_volume < 0.5 ? _VOL_SVG.low : _VOL_SVG.high);
        btn.title = _muted ? '取消静音' : '静音';
    }

    function _saveVolume() {
        try {
            localStorage.setItem('mc_volume', String(_volume));
            localStorage.setItem('mc_muted', _muted ? '1' : '0');
        } catch (e) {}
    }

    function setVolume(val) {
        _volume = Math.min(100, Math.max(0, parseInt(val, 10) || 0)) / 100;
        if (_volume > 0 && _muted) _muted = false; // 拖动滑条自动解除静音
        _applyVolume();
        _saveVolume();
    }

    // 触屏设备无 hover：点按钮改为展开/收起音量面板，静音靠拖到 0
    const _touchVolume = window.matchMedia && window.matchMedia('(hover: none)').matches;

    function toggleMute() {
        if (_touchVolume) {
            document.querySelector('.volume-popup').classList.toggle('open');
            return;
        }
        _muted = !_muted;
        _applyVolume();
        _saveVolume();
    }

    // 点击控件外部时收起音量面板
    document.addEventListener('click', (e) => {
        if (_touchVolume && !e.target.closest('.volume-control')) {
            document.querySelector('.volume-popup').classList.remove('open');
        }
    });

    (function _initVolume() {
        try {
            const v = parseFloat(localStorage.getItem('mc_volume'));
            if (!isNaN(v) && v >= 0 && v <= 1) _volume = v;
            _muted = localStorage.getItem('mc_muted') === '1';
        } catch (e) {}
        document.getElementById('volumeSlider').value = Math.round(_volume * 100);
        _applyVolume();
    })();

    function onTimeUpdate() {
        if (this !== currentPlayer) return;
        if (this.duration) {
            document.getElementById('progressBar').value = (this.currentTime / this.duration) * 100;
            document.getElementById('currentTime').textContent = formatTime(Math.floor(this.currentTime));
            document.getElementById('totalTime').textContent = formatTime(Math.floor(this.duration));
            updateLyricsHighlight(this.currentTime);
        }
    }
    audio.addEventListener('timeupdate', onTimeUpdate);
    video.addEventListener('timeupdate', onTimeUpdate);
    audio.addEventListener('ended', function () { if (this === currentPlayer) nextTrack(); });
    video.addEventListener('ended', function () { if (this === currentPlayer) nextTrack(); });

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
