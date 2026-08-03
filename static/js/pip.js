// === Settings Panel ===
function toggleSettings() {
    var panel = document.getElementById('settingsPanel');
    panel.classList.toggle('open');
}

// 点击设置面板外部时关闭
document.addEventListener('click', function(e) {
    if (!e.target.closest('.nav-brand')) {
        var panel = document.getElementById('settingsPanel');
        if (panel) panel.classList.remove('open');
    }
});

// === Picture-in-Picture Floating Lyrics ===
var pipWindow = null;
var pipEnabled = false;

function _pipSupported() {
    return 'documentPictureInPicture' in window;
}

function togglePipLyrics(enabled) {
    pipEnabled = enabled;
    try { localStorage.setItem('mc_pip_lyrics', enabled ? '1' : '0'); } catch (e) {}
    var hint = document.getElementById('pipHint');
    if (enabled) {
        if (!_pipSupported()) {
            hint.textContent = '当前浏览器不支持画中画 API，请使用 Chrome/Edge 116+';
            return;
        }
        hint.textContent = '悬浮窗已开启，播放时将自动显示歌词';
        _openPipWindow();
    } else {
        _closePipWindow();
        hint.textContent = '';
    }
}

function _openPipWindow() {
    if (pipWindow && !pipWindow.closed) {
        _rebuildPipLyrics();
        return;
    }
    if (!_pipSupported()) return;
    window.documentPictureInPicture.requestWindow({ width: 420, height: 520 })
        .then(function(win) {
            pipWindow = win;
            _stylePipWindow(win);
            _rebuildPipLyrics();
            _setupPipMessaging(win);
            win.addEventListener('pagehide', function() {
                pipWindow = null;
                pipEnabled = false;
                try { localStorage.setItem('mc_pip_lyrics', '0'); } catch (e) {}
                var toggle = document.getElementById('pipLyricsToggle');
                if (toggle) toggle.checked = false;
                var hint = document.getElementById('pipHint');
                if (hint) hint.textContent = '悬浮窗已关闭';
            });
        })
        .catch(function(err) {
            showToast('打开悬浮窗失败: ' + err.message);
            pipEnabled = false;
            var toggle = document.getElementById('pipLyricsToggle');
            if (toggle) toggle.checked = false;
        });
}

function _closePipWindow() {
    if (pipWindow && !pipWindow.closed) {
        pipWindow.close();
    }
    pipWindow = null;
}

function _stylePipWindow(win) {
    var doc = win.document;
    doc.documentElement.style.cssText = 'margin:0;padding:0;background:transparent;height:100%;';
    doc.body.style.cssText = 'margin:0;padding:0;background:transparent;height:100%;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans SC",sans-serif;overflow:hidden;';

    // 加载 PiP 窗口样式（与主页共用 pip.css）
    var link = doc.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/css/pip.css';
    doc.head.appendChild(link);

    // 滚动条颜色（由 _applyPipTheme 动态更新覆盖 pip.css 默认值）
    var sbStyle = doc.createElement('style');
    sbStyle.id = 'pipScrollbar';
    doc.head.appendChild(sbStyle);

    doc.body.innerHTML = '<div id="pipContainer" style="display:flex;flex-direction:column;height:100%;box-sizing:border-box;transition:background 0.3s;">' +
        '<div id="pipLyricsList" style="flex:1;overflow-y:auto;padding:12px 0;"></div>' +
        '<div id="pipBottomBar">' +
            '<div id="pipControls">' +
                '<div id="pipSeparator"></div>' +
                '<div id="pipBtnRow">' +
                '<button class="pip-ctrl-btn" id="pipPrevBtn" title="上一首">&#9198;</button>' +
                '<button class="pip-ctrl-btn" id="pipPlayBtn" title="播放/暂停">&#9654;</button>' +
                '<button class="pip-ctrl-btn" id="pipNextBtn" title="下一首">&#9197;</button>' +
                '</div>' +
            '</div>' +
        '</div>' +
        '</div>';

    // PiP 窗口内部的脚本：检测宽高比 + 控件交互
    var pipScript = doc.createElement('script');
    pipScript.textContent = [
        '(function() {',
        '  var controls = document.getElementById("pipControls");',
        '  var bottomBar = document.getElementById("pipBottomBar");',
        '  var playBtn = document.getElementById("pipPlayBtn");',
        '',
        '  // 按钮点击 → 通知主页',
        '  function sendAction(act) {',
        '    window.opener && window.opener.postMessage({ type: "pip-action", action: act }, "*");',
        '  }',
        '  document.getElementById("pipPrevBtn").onclick = function() { sendAction("prev"); };',
        '  document.getElementById("pipNextBtn").onclick = function() { sendAction("next"); };',
        '  playBtn.onclick = function() { sendAction("playpause"); };',
        '',
        '  // 接收主页发来的播放状态',
        '  window.addEventListener("message", function(e) {',
        '    if (e.data && e.data.type === "pip-state") {',
        '      playBtn.innerHTML = e.data.playing ? "&#9646;&#9646;" : "&#9654;";',
        '    }',
        '  });',
        '',
        '  // 检测宽高比：宽度 < 高度 * 0.75 时显示控件',
        '  function checkAspect() {',
        '    var narrow = window.innerWidth < window.innerHeight * 0.75;',
        '    if (narrow) {',
        '      bottomBar.classList.add("open");',
        '      controls.classList.add("visible");',
        '    } else {',
        '      bottomBar.classList.remove("open");',
        '      controls.classList.remove("visible");',
        '    }',
        '  }',
        '  checkAspect();',
        '  window.addEventListener("resize", checkAspect);',
        '})();'
    ].join('\n');
    doc.body.appendChild(pipScript);

    _applyPipTheme(doc);
}

// === 主页面 ↔ PiP 窗口消息通信 ===
var _pipMsgSetup = false;

function _setupPipMessaging(win) {
    if (_pipMsgSetup) return;
    _pipMsgSetup = true;

    // 接收 PiP 窗口的按钮操作
    window.addEventListener('message', function(e) {
        if (!e.data || e.data.type !== 'pip-action') return;
        if (!pipWindow || pipWindow.closed) return;
        var act = e.data.action;
        if (act === 'prev') { if (typeof prevTrack === 'function') prevTrack(); }
        else if (act === 'next') { if (typeof nextTrack === 'function') nextTrack(); }
        else if (act === 'playpause') { if (typeof togglePlay === 'function') togglePlay(); }
    });

    // 监听主页音频播放/暂停 → 同步到 PiP
    function _sendPipState() {
        if (!pipWindow || pipWindow.closed) return;
        var audio = document.getElementById('audioPlayer');
        if (!audio) return;
        pipWindow.postMessage({ type: 'pip-state', playing: !audio.paused }, '*');
    }
    var audio = document.getElementById('audioPlayer');
    if (audio) {
        audio.addEventListener('play', _sendPipState);
        audio.addEventListener('pause', _sendPipState);
        // 初始状态
        _sendPipState();
    }
}

// === 主题色应用 ===

// hex 转 rgb 通道字符串
function _hexToRgb(hex) {
    var m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    return m ? parseInt(m[1],16)+','+parseInt(m[2],16)+','+parseInt(m[3],16) : '15,15,19';
}

// 从主页读取当前主题色并应用到 PiP 窗口
function _applyPipTheme(doc) {
    var cs = getComputedStyle(document.documentElement);
    var isLight = document.documentElement.getAttribute('data-theme') === 'light';
    var bg = cs.getPropertyValue('--bg-primary').trim() || (isLight ? '#f4f5f9' : '#0f0f13');
    var text2 = cs.getPropertyValue('--text-secondary').trim() || (isLight ? '#6d6d7c' : '#8e8e9b');
    var accent = cs.getPropertyValue('--accent').trim() || '#6366f1';

    var bgRgb = _hexToRgb(bg);

    var container = doc.getElementById('pipContainer');
    if (container) {
        container.style.background = 'rgba(' + bgRgb + ',' + (isLight ? '0.82' : '0.85') + ')';
        container.style.backdropFilter = 'blur(12px)';
    }

    // 分隔线 + 控件按钮颜色
    var separator = doc.getElementById('pipSeparator');
    if (separator) separator.style.borderTopColor = text2;
    var controls = doc.getElementById('pipControls');
    if (controls) controls.style.color = text2;

    // 滚动条颜色
    var sbRgb = _hexToRgb(text2);
    var sbStyle = doc.getElementById('pipScrollbar');
    if (sbStyle) {
        sbStyle.textContent = [
            '::-webkit-scrollbar-thumb { background: rgba(' + sbRgb + ',0.3); }',
            '::-webkit-scrollbar-thumb:hover { background: rgba(' + sbRgb + ',0.5); }'
        ].join('\n');
    }

    // 动态更新歌词行颜色
    var listEl = doc.getElementById('pipLyricsList');
    if (listEl) {
        var lines = listEl.querySelectorAll('.pip-lyric-line');
        for (var i = 0; i < lines.length; i++) {
            lines[i].style.color = lines[i].classList.contains('active') ? accent : text2;
        }
    }
}

function _refreshPipTheme() {
    if (!pipWindow || pipWindow.closed) return;
    _applyPipTheme(pipWindow.document);
    _rebuildPipLyrics();
}

// === 由 lyrics.js 调用的公开接口 ===

// 设置 PiP 悬浮窗标题
function pipSetTitle(name) {
    if (!pipWindow || pipWindow.closed) return;
    pipWindow.document.title = name + ' - Music Catch';
}

// 渲染全部歌词到 PiP 窗口
function pipRenderLyrics(data) {
    if (!pipWindow || pipWindow.closed) return;
    var doc = pipWindow.document;
    var listEl = doc.getElementById('pipLyricsList');
    if (!listEl) return;

    var cs = getComputedStyle(document.documentElement);
    var text2 = cs.getPropertyValue('--text-secondary').trim() || '#8e8e9b';

    if (!data || !data.length) {
        listEl.innerHTML = '<div class="pip-lyric-line" style="color:' + text2 + ';">暂无歌词</div>';
        return;
    }

    var html = '';
    for (var i = 0; i < data.length; i++) {
        html += '<div class="pip-lyric-line" data-index="' + i + '" style="color:' + text2 + ';">' + _escHtml(data[i].text) + '</div>';
    }
    listEl.innerHTML = html;
}

// 高亮指定行并滚动到可见位置
function pipHighlight(index) {
    if (!pipWindow || pipWindow.closed) return;
    var doc = pipWindow.document;
    var listEl = doc.getElementById('pipLyricsList');
    if (!listEl) return;

    var cs = getComputedStyle(document.documentElement);
    var accent = cs.getPropertyValue('--accent').trim() || '#6366f1';
    var text2 = cs.getPropertyValue('--text-secondary').trim() || '#8e8e9b';

    var prev = listEl.querySelector('.pip-lyric-line.active');
    if (prev) {
        prev.classList.remove('active');
        prev.style.color = text2;
    }

    if (index >= 0) {
        var line = listEl.querySelector('.pip-lyric-line[data-index="' + index + '"]');
        if (line) {
            line.classList.add('active');
            line.style.color = accent;
            var containerH = listEl.clientHeight;
            var lineTop = line.offsetTop;
            var lineH = line.offsetHeight;
            listEl.scrollTo({
                top: lineTop - containerH / 2 + lineH / 2,
                behavior: 'smooth'
            });
        }
    }
}

// 用当前歌词数据重建 PiP 内容
function _rebuildPipLyrics() {
    if (typeof lyricsData !== 'undefined' && lyricsData.length) {
        pipRenderLyrics(lyricsData);
        if (typeof currentLyricIndex !== 'undefined' && currentLyricIndex >= 0) {
            pipHighlight(currentLyricIndex);
        }
    }
    if (typeof lyricsSong !== 'undefined' && lyricsSong) {
        pipSetTitle(lyricsSong.name + ' - ' + (lyricsSong.artist || ''));
    }
}

function _escHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// 页面关闭时清理悬浮窗
window.addEventListener('beforeunload', function() {
    if (pipWindow && !pipWindow.closed) pipWindow.close();
});

// 初始化设置状态
document.addEventListener('DOMContentLoaded', function() {
    var toggle = document.getElementById('pipLyricsToggle');
    if (!toggle) return;
    try {
        var saved = localStorage.getItem('mc_pip_lyrics');
        if (saved === '1') {
            toggle.checked = true;
            pipEnabled = true;
            var hint = document.getElementById('pipHint');
            if (hint) hint.textContent = _pipSupported()
                ? '悬浮窗已开启，播放时将自动显示歌词'
                : '当前浏览器不支持画中画 API，请使用 Chrome/Edge 116+';
        }
    } catch (e) {}
});
