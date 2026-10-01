// === 均衡器（Web Audio API） ===
// 10 段 BiquadFilter 串联，作用于主播放器（音频/视频），预设 + 自定义 + localStorage 持久化。
// 依赖 player.js：audio、video、currentPlayer 全局对象。

(function () {
    'use strict';

    // ── 频段定义 ──
    const BANDS = [
        { freq: 32,   label: '32' },
        { freq: 64,   label: '64' },
        { freq: 125,  label: '125' },
        { freq: 250,  label: '250' },
        { freq: 500,  label: '500' },
        { freq: 1000, label: '1k' },
        { freq: 2000, label: '2k' },
        { freq: 4000, label: '4k' },
        { freq: 8000, label: '8k' },
        { freq: 16000,label: '16k' },
    ];
    const GAIN_MIN = -12;
    const GAIN_MAX = 12;

    // ── 预设 ──
    const PRESETS = {
        flat:        { name: '平直',     gains: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
        pop:         { name: '流行',     gains: [-1, 1, 2, 3, 2, 0, -1, -1, 1, 3] },
        rock:        { name: '摇滚',     gains: [4, 3, 1, -1, -2, 1, 3, 5, 5, 4] },
        jazz:        { name: '爵士',     gains: [3, 2, 1, 2, -1, -1, 0, 1, 2, 3] },
        classical:   { name: '古典',     gains: [3, 2, 1, 0, 0, 1, 2, 3, 3, 3] },
        bass:        { name: '重低音',   gains: [7, 6, 5, 3, 1, 0, 0, 0, 0, 0] },
        vocal:       { name: '人声',     gains: [-2, -1, 0, 2, 4, 5, 4, 2, 0, -1] },
        electronic:  { name: '电子',     gains: [4, 3, 1, 0, -1, 1, 2, 3, 5, 6] },
    };

    // ── 状态 ──
    let audioCtx = null;
    const sourceNodes = {};    // { 'audio': node, 'video': node } —— 已创建的媒体源（每个元素只能建一次）
    let filters = [];
    let eqEnabled = false;
    let currentGains = PRESETS.flat.gains.slice();
    let currentPreset = 'flat';
    let chainReady = false;    // 滤波链是否已建成（首次启用时一次性搭建）

    // ── 持久化 ──
    const STORAGE_KEY = 'mc_equalizer';
    function _save() {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({
                preset: currentPreset,
                gains: currentGains,
                enabled: eqEnabled,
            }));
        } catch (e) {}
    }
    function _load() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return;
            const data = JSON.parse(raw);
            if (data.preset && PRESETS[data.preset]) currentPreset = data.preset;
            if (Array.isArray(data.gains) && data.gains.length === BANDS.length) {
                currentGains = data.gains.map(g => Math.min(GAIN_MAX, Math.max(GAIN_MIN, g)));
            }
            if (typeof data.enabled === 'boolean') eqEnabled = data.enabled;
        } catch (e) {}
    }

    // ── Audio 节点链 ──
    // 首次启用时搭建一次：为 audio 和 video 各建一个媒体源，都汇入同一滤波链 → destination。
    // 因为 createMediaElementSource 每个元素只能调用一次，且建源后该元素音频恒走 AudioContext，
    // 所以链一旦建成永久保留；之后无论播放器切音频还是视频，声音都自动过均衡器。
    async function _buildChain() {
        _teardownChain();

        if (!audioCtx) {
            audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        }
        if (audioCtx.state === 'suspended') {
            try { await audioCtx.resume(); } catch (e) {}
        }

        // 为两个播放器建滤波链
        filters = BANDS.map((b, i) => {
            const f = audioCtx.createBiquadFilter();
            f.type = 'peaking';
            f.frequency.value = b.freq;
            f.Q.value = 1.0;
            f.gain.value = eqEnabled ? currentGains[i] : 0;
            return f;
        });

        // 串联内部：filter0 → filter1 → ... → destination
        let node = filters[0];
        for (let i = 1; i < filters.length; i++) {
            node.connect(filters[i]);
            node = filters[i];
        }
        node.connect(audioCtx.destination);

        // 把已存在的媒体源接入滤波链头部；尚未创建的等播放器就绪时再补
        for (const key of Object.keys(sourceNodes)) {
            const src = sourceNodes[key];
            try { src.connect(filters[0]); } catch (e) {}
        }

        chainReady = true;
    }

    // 为指定元素建媒体源（每个元素一次）并接入已建成的滤波链
    function _ensureSource(element, key) {
        if (!element || !audioCtx) return null;
        if (sourceNodes[key]) return sourceNodes[key];
        const src = audioCtx.createMediaElementSource(element);
        sourceNodes[key] = src;
        if (chainReady && filters.length) {
            try { src.connect(filters[0]); } catch (e) {}
        }
        return src;
    }

    function _teardownChain() {
        for (const key of Object.keys(sourceNodes)) {
            const src = sourceNodes[key];
            try { src.disconnect(); } catch (e) {}
        }
        for (const f of filters) {
            try { f.disconnect(); } catch (e) {}
        }
        filters = [];
        chainReady = false;
    }

    function _applyGains() {
        for (let i = 0; i < filters.length; i++) {
            filters[i].gain.value = eqEnabled ? currentGains[i] : 0;
        }
    }

    // player.js 调用：某播放器元素（audio/video）即将就绪，确保已建源并入链
    function ensurePlayer(player) {
        if (!player || !audioCtx || !chainReady) return;
        const key = (player === document.getElementById('audioPlayer')) ? 'audio'
            : (player === document.getElementById('videoPlayer')) ? 'video' : null;
        if (key) _ensureSource(player, key);
    }

    // ── 公开接口 ──

    // 面板开关
    function togglePanel() {
        const panel = document.getElementById('eqPanel');
        if (!panel) return;
        const willOpen = !panel.classList.contains('open');
        // 打开前先关闭其他侧面板（互斥：同一时刻只开一个）
        if (willOpen && typeof closeAllSidePanels === 'function') closeAllSidePanels();
        const isOpen = panel.classList.toggle('open');
        // 同步遮罩
        const backdrop = document.getElementById('eqPanelBackdrop');
        if (backdrop) backdrop.classList.toggle('active', isOpen);
        if (isOpen) _updateUI();
    }

    // 均衡器启用/禁用
    async function setEnabled(enabled) {
        eqEnabled = enabled;
        if (enabled && !chainReady) {
            // 懒初始化：首次启用时搭建滤波链，并为当前播放器建源
            await _buildChain();
            const player = (typeof currentPlayer !== 'undefined') ? currentPlayer : document.getElementById('audioPlayer');
            if (player) ensurePlayer(player);
        }
        _applyGains();
        _save();
        _updateUI();
    }

    // 切换启用/禁用
    function toggleEnabled() {
        setEnabled(!eqEnabled);
    }

    // 设置频段增益（用户拖动滑块时调用）
    function setGain(index, value) {
        if (index < 0 || index >= BANDS.length) return;
        currentGains[index] = Math.min(GAIN_MAX, Math.max(GAIN_MIN, Math.round(value)));
        currentPreset = 'custom';
        _applyGains();
        _save();
    }

    // 设置预设
    function setPreset(key) {
        if (!PRESETS[key]) return;
        currentPreset = key;
        currentGains = PRESETS[key].gains.slice();
        if (filters.length) _applyGains();
        _save();
        _updateUI();
    }

    // 重置为平直
    function reset() { setPreset('flat'); }

    // ── 检测当前增益匹配的预设 ──
    function _detectPreset() {
        const g = currentGains.join();
        for (const k in PRESETS) {
            if (PRESETS[k].gains.join() === g) return k;
        }
        return 'custom';
    }
    function getGains() { return currentGains.slice(); }

    // ── UI 同步 ──
    function _updateUI() {
        const panel = document.getElementById('eqPanel');
        if (!panel) return;

        // 启用开关
        const toggle = document.getElementById('eqToggle');
        if (toggle) toggle.checked = eqEnabled;

    // 预设按钮高亮（'custom' 时不高亮任何按钮）
    const presetBtns = document.querySelectorAll('#eqPresetBtns .eq-preset-btn');
    if (presetBtns.length) {
        const active = _detectPreset();
        presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === active));
    }

        // 频段滑块（自绘：轨道填充 + 圆点位置 = 增益百分比）
        for (let i = 0; i < BANDS.length; i++) {
            const pct = ((currentGains[i] - GAIN_MIN) / (GAIN_MAX - GAIN_MIN)) * 100;
            const valEl = document.getElementById('eqValue' + i);
            if (valEl) valEl.textContent = (currentGains[i] > 0 ? '+' : '') + currentGains[i];
            const fillEl = document.getElementById('eqFill' + i);
            if (fillEl) fillEl.style.height = pct + '%';
            const thumbEl = document.getElementById('eqThumb' + i);
            if (thumbEl) thumbEl.style.bottom = pct + '%';
        }

        // EQ 按钮高亮
        const btn = document.getElementById('eqBtn');
        if (btn) btn.classList.toggle('active', eqEnabled);
    }

    // ── player.js 调用：某播放器元素（audio/video）即将就绪，确保已建源并入链 ──

    // 点击面板外部收起（整行点击区域也忽略）
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.eq-panel') && !e.target.closest('#eqBtn') && !e.target.closest('.settings-eq')) {
            const panel = document.getElementById('eqPanel');
            if (panel && panel.classList.contains('open')) {
                panel.classList.remove('open');
                const bd = document.getElementById('eqPanelBackdrop');
                if (bd) bd.classList.remove('active');
            }
        }
    });

    // 若历史上已启用均衡器但滤波链未建（AudioContext 需用户手势才能启动），
    // 在首次用户交互时自动搭建一次，保证恢复播放即走均衡器。
    (function _autoBuildOnGesture() {
        const tryBuild = () => {
            if (!eqEnabled || chainReady) return;
            setEnabled(true);
        };
        document.addEventListener('pointerdown', () => {
            if (eqEnabled && !chainReady) setEnabled(true);
        }, { once: true });
    })();

    // 暴露全局接口
    window.equalizer = {
        togglePanel,
        toggleEnabled,
        setEnabled,
        setGain,
        setPreset,
        reset,
        ensurePlayer,
        isEnabled: () => eqEnabled,
        getGains,
        _detectPreset,
        _updateUI,
        PRESETS,
        BANDS,
        GAIN_MIN,
        GAIN_MAX,
    };

    _load();
})();

// ── DOM 初始化 ──
document.addEventListener('DOMContentLoaded', function () {
    const panel = document.getElementById('eqPanel');
    if (!panel) return;
    const eq = window.equalizer;

    // 生成预设按钮（按钮比 select UI 更好，更清晰）
    const presetWrap = document.getElementById('eqPresetBtns');
    if (presetWrap) {
        presetWrap.innerHTML = Object.keys(equalizer.PRESETS).map(
            k => `<button type="button" class="eq-preset-btn" data-preset="${k}">${equalizer.PRESETS[k].name}</button>`
        ).join('');
        presetWrap.addEventListener('click', (e) => {
            const btn = e.target.closest('.eq-preset-btn');
            if (!btn) return;
            equalizer.setPreset(btn.dataset.preset);
            // 选择预设时自动打开均衡器开关
            if (!equalizer.isEnabled()) equalizer.setEnabled(true);
        });
    }

    // 生成频段滑块（自绘轨道 + 可拖动 thumb，不依赖原生 range 的垂直渲染）
    const sliders = document.getElementById('eqSliders');
    if (sliders) {
        sliders.innerHTML = equalizer.BANDS.map((b, i) => `
            <div class="eq-band">
                <span class="eq-band-value" id="eqValue${i}">0</span>
                <div class="eq-track" id="eqTrack${i}" role="slider"
                     aria-label="${b.label} Hz 增益" aria-valuemin="-12" aria-valuemax="12">
                    <div class="eq-track-fill" id="eqFill${i}"></div>
                    <div class="eq-thumb" id="eqThumb${i}"></div>
                </div>
                <span class="eq-band-label">${b.label}</span>
            </div>
        `).join('');
    }

    // 绑定事件：自绘滑块（事件绑在轨道上，点击跳转 + 拖动，兼容鼠标和触摸）
    equalizer.BANDS.forEach((b, i) => {
        const track = document.getElementById('eqTrack' + i);
        if (!track) return;

        let dragging = false;
        const setValueFromEvent = (event) => {
            const rect = track.getBoundingClientRect();
            const ratio = 1 - (event.clientY - rect.top) / rect.height;
            const value = Math.round(equalizer.GAIN_MIN + (equalizer.GAIN_MAX - equalizer.GAIN_MIN) * Math.max(0, Math.min(1, ratio)));
            equalizer.setGain(i, value);
            equalizer._updateUI();
        };
        const endDrag = (event) => {
            if (!dragging) return;
            dragging = false;
            track.classList.remove('dragging');
            try { track.releasePointerCapture(event.pointerId); } catch (e) {}
        };
        track.addEventListener('pointerdown', (event) => {
            dragging = true;
            track.setPointerCapture(event.pointerId);
            track.classList.add('dragging');
            setValueFromEvent(event);
        });
        track.addEventListener('pointermove', (event) => {
            if (dragging) setValueFromEvent(event);
        });
        track.addEventListener('pointerup', endDrag);
        track.addEventListener('pointercancel', endDrag);
        track.addEventListener('lostpointercapture', () => {
            dragging = false;
            track.classList.remove('dragging');
        });
    });

    // 绑定事件：重置
    document.getElementById('eqReset').addEventListener('click', () => equalizer.reset());

    // 绑定事件：关闭面板
    document.getElementById('eqClose').addEventListener('click', () => {
        panel.classList.remove('open');
        var bd = document.getElementById('eqPanelBackdrop');
        if (bd) bd.classList.remove('active');
    });

    // 绑定事件：启用/禁用开关
    const toggle = document.getElementById('eqToggle');
    if (toggle) toggle.addEventListener('change', () => equalizer.setEnabled(toggle.checked));

    // 恢复 UI
    eq._updateUI();

    // 在设置面板中显示均衡器入口（仅首页有均衡器时）
    var eqItem = document.getElementById('eqSettingsItem');
    if (eqItem) eqItem.style.display = '';
});