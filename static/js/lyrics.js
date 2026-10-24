let lyricsData = [];
let lyricsTranslated = [];  // 翻译后的歌词数据
let currentLyricIndex = -1;
let lyricsVisible = false;
let lyricsRaw = '';        // 原始 LRC 文本，供复制/下载导出
let lyricsTranslatedRaw = ''; // 翻译后的 LRC 文本
let lyricsSong = null;     // 当前歌词对应的歌曲，用于生成文件名

    function parseLRC(text) {
        if (!text) return [];
        const lines = text.split('\n');
        const parsed = [];
        const tagRegex = /\[(\d{1,2}):(\d{2})(?:[.:](\d{1,3}))?\]/g;
        for (const line of lines) {
            if (/^\[([a-zA-Z]+):/.test(line)) continue;
            const timestamps = [];
            const stripped = line.replace(tagRegex, (m, min, sec, ms) => {
                const total = parseInt(min) * 60 + parseInt(sec) + (parseInt(ms || '0') / (ms && ms.length === 3 ? 1000 : 100));
                timestamps.push(total);
                return '';
            }).trim();
            for (const ts of timestamps) {
                parsed.push({ time: ts, text: stripped || '...' });
            }
        }
        parsed.sort((a, b) => a.time - b.time);
        return parsed;
    }

    // 播放一首歌时自动拉歌词（带本地 Blob 缓存，无歌词也缓存）
    async function fetchLyrics(song) {
        lyricsData = [];
        lyricsTranslated = [];
        currentLyricIndex = -1;
        lyricsRaw = '';
        lyricsTranslatedRaw = '';
        lyricsSong = null;
        const content = document.getElementById('lyricsContent');
        const exportBtn = document.getElementById('lyricsExport');
        if (exportBtn) exportBtn.style.display = 'none';
        if (content) content.innerHTML = '<p class="lyrics-empty">加载中...</p>';
        document.getElementById('lyricsTitle').textContent = song.name;

        // 先设置 PiP 标题（即使歌词还没加载完也要更新）
        if (typeof pipSetTitle === 'function') pipSetTitle(song.name + ' - ' + song.artist);

        const key = song.platform + ':' + song.id;

        // ── 优先：使用本地缓存的歌词 Blob ──
        if (typeof getCachedLyricsBlob === 'function') {
            try {
                const cached = await getCachedLyricsBlob(key);
                if (cached && cached.blob instanceof Blob) {
                    const text = await cached.blob.text();
                    // 兼容旧格式（纯文本）和新格式（JSON: {lrc, translated}）
                    let parsed;
                    try { parsed = JSON.parse(text); } catch (_) { parsed = null; }
                    if (parsed && parsed.lrc != null) {
                        lyricsRaw = parsed.lrc;
                        lyricsTranslatedRaw = parsed.translated || '';
                    } else {
                        // 旧格式：纯文本歌词，无翻译
                        lyricsRaw = text;
                        lyricsTranslatedRaw = '';
                    }
                    lyricsSong = song;
                    lyricsData = parseLRC(lyricsRaw);
                    lyricsTranslated = parseLRC(lyricsTranslatedRaw);
                    if (exportBtn) exportBtn.style.display = lyricsData.length ? '' : 'none';
                    _syncExportTranslatedVis();
                    renderLyrics();
                    return;
                }
            } catch (e) {}
        }

        // ── 回源：请求服务端，无论有无歌词都写入缓存 Blob ──
        const extra = encodeURIComponent(JSON.stringify(song.extra));
        const params = `extra=${extra}&name=${encodeURIComponent(song.name)}&artist=${encodeURIComponent(song.artist)}&duration=${song.duration || 0}`;
        try {
            const resp = await fetch(`/api/lyrics/${song.platform}/${song.id}?${params}`);
            const data = await resp.json();
            // 即使歌词为空也缓存，用空 blob 标记"已确认无歌词"
            const rawText = (data && data.lyrics) ? data.lyrics : '';
            const transText = (data && data.translated) ? data.translated : '';
            if (typeof putCachedLyricsBlob === 'function') {
                // 新格式：存 JSON {lrc, translated}，兼容旧纯文本解析
                const cacheData = { lrc: rawText, translated: transText || undefined };
                putCachedLyricsBlob(key, new Blob([JSON.stringify(cacheData)], { type: 'text/plain;charset=utf-8' }), song);
            }
            lyricsRaw = rawText;
            lyricsTranslatedRaw = transText;
            lyricsSong = song;
            lyricsData = parseLRC(rawText);
            if (transText) {
                lyricsTranslated = parseLRC(transText);
            }
            if (exportBtn) exportBtn.style.display = lyricsData.length ? '' : 'none';
            _syncExportTranslatedVis();
            renderLyrics();
        } catch (e) {
            if (content) content.innerHTML = '<p class="lyrics-empty">歌词加载失败</p>';
        }
    }

    // 仅当有翻译时，才显示"下载 LRC 歌词(翻译)"选项
    function _syncExportTranslatedVis() {
        const el = document.getElementById('lyricsExportTranslated');
        if (el) el.style.display = lyricsTranslatedRaw ? '' : 'none';
    }

    // === 歌词导出：复制纯文本 / 下载 LRC 文件 ===
    function toggleLyricsExportMenu(e) {
        e.stopPropagation();
        document.getElementById('lyricsExportMenu').classList.toggle('open');
    }

    // 点击菜单外部时收起
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.lyrics-export')) {
            document.getElementById('lyricsExportMenu').classList.remove('open');
        }
    });

    function _closeLyricsExportMenu() {
        document.getElementById('lyricsExportMenu').classList.remove('open');
    }

    function copyLyricsText() {
        _closeLyricsExportMenu();
        if (!lyricsRaw) return;
        // 去掉时间标签和元信息行，只保留歌词文本
        const text = lyricsRaw.split('\n')
            .filter(l => !/^\[([a-zA-Z]+):/.test(l))
            .map(l => l.replace(/\[[^\]]*\]/g, '').trim())
            .filter(Boolean)
            .join('\n');
        if (!text) { showToast('没有可复制的歌词'); return; }
        const silentCopy = () => {
            const ta = document.createElement('textarea');
            ta.value = text;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand('copy'); } catch (e) {}
            document.body.removeChild(ta);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(() => {
                showToast('歌词已复制到剪贴板');
            }).catch(() => {
                silentCopy();
                showToast('歌词已复制到剪贴板');
            });
        } else {
            silentCopy();
            showToast('歌词已复制到剪贴板');
        }
    }

    function downloadLrcFile() {
        _closeLyricsExportMenu();
        if (!lyricsRaw) return;
        // 与音频下载保持一致：歌手 - 歌名.lrc
        const name = lyricsSong ? `${lyricsSong.artist} - ${lyricsSong.name}` : '歌词';
        // 去掉文件名非法字符
        const safeName = name.replace(/[\\/:*?"<>|]/g, '_');
        const blob = new Blob([lyricsRaw], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${safeName}.lrc`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('LRC 歌词已下载');
    }

    function downloadLrcTranslated() {
        _closeLyricsExportMenu();
        if (!lyricsTranslatedRaw) return;
        // 与音频下载保持一致：歌手 - 歌名(翻译).lrc
        const name = lyricsSong ? `${lyricsSong.artist} - ${lyricsSong.name}` : '歌词';
        // 去掉文件名非法字符
        const safeName = name.replace(/[\\/:*?"<>|]/g, '_');
        const blob = new Blob([lyricsTranslatedRaw], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${safeName}（翻译）.lrc`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showToast('LRC 歌词(翻译)已下载');
    }

    function renderLyrics() {
        const content = document.getElementById('lyricsContent');
        if (!lyricsData.length) {
            content.innerHTML = '<p class="lyrics-empty">暂无歌词</p>';
            if (typeof pipRenderLyrics === 'function') pipRenderLyrics([]);
            return;
        }
        // translated 是服务端合并版（原文+译文交替），直接用它渲染；无翻译时用原歌词
        const displayData = lyricsTranslated.length > 0 ? lyricsTranslated : lyricsData;
        content.innerHTML = displayData.map((line, i) =>
            `<div class="lyric-line" data-index="${i}" onclick="seekToLyric(${line.time})">${escHtml(line.text)}</div>`
        ).join('');
        if (typeof pipRenderLyrics === 'function') pipRenderLyrics(displayData);
    }

    let _lastDisplayData = [];
    function updateLyricsHighlight(currentTime) {
        if (!lyricsData.length) return;
        let idx = -1;
        for (let i = lyricsData.length - 1; i >= 0; i--) {
            if (currentTime >= lyricsData[i].time) {
                idx = i;
                break;
            }
        }
        if (idx === currentLyricIndex) return;
        currentLyricIndex = idx;

        // 同步更新画中画悬浮窗歌词
        if (typeof pipHighlight === 'function') pipHighlight(currentLyricIndex);

        const content = document.getElementById('lyricsContent');
        const prev = content.querySelector('.lyric-line.active');
        if (prev) prev.classList.remove('active');

        if (idx >= 0) {
            // displayData 是原文+译文交替的合并版，每首曲原文在原数组的 idx*2 位置
            const pairedIdx = lyricsTranslated.length > 0 ? idx * 2 : idx;
            const activeLine = content.querySelector(`.lyric-line[data-index="${pairedIdx}"]`);
            if (activeLine) {
                activeLine.classList.add('active');
                const containerHeight = content.clientHeight;
                const lineTop = activeLine.offsetTop;
                const lineHeight = activeLine.offsetHeight;
                content.scrollTo({
                    top: lineTop - containerHeight / 2 + lineHeight / 2,
                    behavior: 'smooth'
                });
            }
        }
    }

    function toggleLyrics() {
        const panel = document.getElementById('lyricsPanel');
        const tab = document.getElementById('lyricsTab');
        lyricsVisible = !lyricsVisible;
        if (lyricsVisible) {
            panel.classList.remove('hidden');
            tab.classList.remove('collapsed');
            tab.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8.59 16.59L13.17 12 8.59 7.41 10 6l6 6-6 6z"/></svg>';
            // 移动端互斥：展开歌词时收起歌单侧栏（两个全宽面板不能同时显示，避免互相盖住）
            if (window.innerWidth <= 640 && typeof togglePlaylistSidebar === 'function') {
                const ps = document.getElementById('playlistSidebar');
                if (ps && !ps.classList.contains('hidden')) {
                    togglePlaylistSidebar();
                }
            }
        } else {
            panel.classList.add('hidden');
            tab.classList.add('collapsed');
            tab.innerHTML = '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z"/></svg>';
        }
    }

    function seekToLyric(time) {
        if (currentPlayer.duration) {
            currentPlayer.currentTime = time;
        }
    }
