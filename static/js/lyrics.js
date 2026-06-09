let lyricsData = [];
let currentLyricIndex = -1;
let lyricsVisible = false;

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

    async function fetchLyrics(song) {
        lyricsData = [];
        currentLyricIndex = -1;
        const content = document.getElementById('lyricsContent');
        content.innerHTML = '<p class="lyrics-empty">加载歌词中...</p>';
        document.getElementById('lyricsTitle').textContent = song.name;

        const extra = encodeURIComponent(JSON.stringify(song.extra));
        const params = `extra=${extra}&name=${encodeURIComponent(song.name)}&artist=${encodeURIComponent(song.artist)}&duration=${song.duration || 0}`;
        try {
            const resp = await fetch(`/api/lyrics/${song.platform}/${song.id}?${params}`);
            const data = await resp.json();
            if (data.lyrics) {
                lyricsData = parseLRC(data.lyrics);
                renderLyrics();
            } else {
                content.innerHTML = '<p class="lyrics-empty">暂无歌词</p>';
            }
        } catch (e) {
            content.innerHTML = '<p class="lyrics-empty">歌词加载失败</p>';
        }
    }

    function renderLyrics() {
        const content = document.getElementById('lyricsContent');
        if (!lyricsData.length) {
            content.innerHTML = '<p class="lyrics-empty">暂无歌词</p>';
            return;
        }
        content.innerHTML = lyricsData.map((line, i) =>
            `<div class="lyric-line" data-index="${i}" onclick="seekToLyric(${line.time})">${escHtml(line.text)}</div>`
        ).join('');
    }

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

        const content = document.getElementById('lyricsContent');
        const prev = content.querySelector('.lyric-line.active');
        if (prev) prev.classList.remove('active');

        if (idx >= 0) {
            const activeLine = content.querySelector(`.lyric-line[data-index="${idx}"]`);
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
            tab.innerHTML = '&#8250;';
        } else {
            panel.classList.add('hidden');
            tab.innerHTML = '&#8249;';
        }
    }

    function seekToLyric(time) {
        if (currentPlayer.duration) {
            currentPlayer.currentTime = time;
        }
    }
