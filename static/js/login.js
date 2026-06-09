    let currentPlatform = '';
    const loggedInPlatforms = new Set();
    const userInfos = {};

    function escHtml(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    }

    const methodNames = {qrcode: '扫码登录', cookie: 'Cookie 登录', phone: '手机号登录'};

    async function initLoginStatus() {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            for (const [pid, info] of Object.entries(data)) {
                if (info.logged_in) {
                    loggedInPlatforms.add(pid);
                    if (info.user) userInfos[pid] = info.user;
                    const tab = document.querySelector(`.platform-tab[data-platform="${pid}"]`);
                    if (tab) {
                        const badge = document.createElement('span');
                        badge.className = 'badge';
                        badge.textContent = '已登录';
                        tab.appendChild(badge);
                    }
                }
            }
        } catch (e) {}
    }
    initLoginStatus();

    function selectPlatform(pid, name) {
        currentPlatform = pid;
        document.querySelectorAll('.platform-tab').forEach(t => t.classList.remove('active'));
        const btn = document.querySelector(`[data-platform="${pid}"]`);
        btn.classList.add('active');

        const loginSection = document.getElementById('loginSection');
        const logoutSection = document.getElementById('logoutSection');

        if (loggedInPlatforms.has(pid)) {
            loginSection.style.display = 'none';
            logoutSection.style.display = 'block';
            document.getElementById('logoutPlatformName').textContent = name;
            const ui = userInfos[pid];
            const el = document.getElementById('logoutUserInfo');
            if (ui && ui.name) {
                let html = '';
                if (ui.avatar) html += `<img src="${escHtml(ui.avatar)}" referrerpolicy="no-referrer" style="width:48px;height:48px;border-radius:50%;object-fit:cover;" onerror="this.style.display='none'">`;
                html += '<div style="text-align:left;">';
                html += `<div style="font-size:15px;font-weight:500;">${escHtml(ui.name)}</div>`;
                const tags = [];
                if (ui.id) tags.push(`ID: ${escHtml(String(ui.id))}`);
                if (ui.level) tags.push(`Lv.${ui.level}`);
                if (tags.length) html += `<div style="font-size:12px;color:#8e8e9b;margin-top:4px;">${tags.join(' · ')}</div>`;
                html += '</div>';
                el.innerHTML = html;
            } else {
                el.innerHTML = '';
            }
        } else {
            loginSection.style.display = 'block';
            logoutSection.style.display = 'none';

            const methods = JSON.parse(btn.getAttribute('data-methods'));
            document.querySelectorAll('.method-tab').forEach(tab => {
                const m = tab.getAttribute('data-method');
                tab.style.display = methods.includes(m) ? '' : 'none';
            });

            const firstAvailable = methods[0] || 'cookie';
            selectMethod(firstAvailable);
        }
        document.getElementById('loginResult').style.display = 'none';
    }

    async function doLogout() {
        const pid = currentPlatform;
        if (!pid) return;
        try {
            const resp = await fetch(`/api/logout/${pid}`, { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                loggedInPlatforms.delete(pid);
                delete userInfos[pid];
                const tab = document.querySelector(`.platform-tab[data-platform="${pid}"]`);
                if (tab) {
                    const badge = tab.querySelector('.badge');
                    if (badge) badge.remove();
                }
                const platformName = document.getElementById('logoutPlatformName').textContent;
                selectPlatform(pid, platformName);
                showResult(true, '已退出登录');
            }
        } catch (e) {
            showResult(false, '退出登录失败: ' + e.message);
        }
    }

    function selectMethod(method) {
        document.querySelectorAll('.method-tab').forEach(t => t.classList.remove('active'));
        const target = document.querySelector(`.method-tab[data-method="${method}"]`);
        if (target) target.classList.add('active');
        document.querySelectorAll('.method-content').forEach(el => {
            el.style.display = 'none';
            el.style.animation = 'none';
        });
        const active = document.getElementById(`method-${method}`);
        active.style.animation = '';
        active.style.display = 'block';
    }

    let qrPollTimer = null;

    async function loadQRCode() {
        const img = document.getElementById('qrImage');
        const status = document.getElementById('qrStatus');
        img.innerHTML = '<div class="loading"></div>';
        status.textContent = '正在获取二维码...';

        try {
            const resp = await fetch(`/api/login/qrcode/${currentPlatform}`);
            const data = await resp.json();
            if (data.qr_image) {
                img.innerHTML = `<img src="data:image/png;base64,${data.qr_image}" alt="QR Code">`;
                status.textContent = '请使用对应 APP 扫描二维码';
                startQRPolling();
            } else {
                status.textContent = '获取二维码失败';
            }
        } catch (e) {
            status.textContent = '获取二维码失败: ' + e.message;
        }
    }

    function startQRPolling() {
        if (qrPollTimer) clearInterval(qrPollTimer);
        qrPollTimer = setInterval(async () => {
            try {
                const resp = await fetch(`/api/login/qrcode/${currentPlatform}/check`);
                const data = await resp.json();
                const status = document.getElementById('qrStatus');
                status.textContent = data.msg;

                if (data.status === 'success') {
                    clearInterval(qrPollTimer);
                    loggedInPlatforms.add(currentPlatform);
                    if (data.user) userInfos[currentPlatform] = data.user;
                    const tab = document.querySelector(`.platform-tab[data-platform="${currentPlatform}"]`);
                    if (tab && !tab.querySelector('.badge')) {
                        const badge = document.createElement('span');
                        badge.className = 'badge';
                        badge.textContent = '已登录';
                        tab.appendChild(badge);
                    }
                    showResult(true, '登录成功！正在跳转...');
                    setTimeout(() => window.location.href = '/', 1500);
                } else if (data.status === 'expired') {
                    clearInterval(qrPollTimer);
                    document.getElementById('qrImage').innerHTML = '<p>二维码已过期</p>';
                }
            } catch (e) {}
        }, 2000);
    }

    async function loginWithCookie() {
        const cookie = document.getElementById('cookieInput').value.trim();
        if (!cookie) { alert('请输入 Cookie'); return; }

        try {
            const resp = await fetch(`/api/login/cookie/${currentPlatform}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({cookie}),
            });
            const data = await resp.json();
            showResult(data.success, data.msg);
            if (data.success) {
                loggedInPlatforms.add(currentPlatform);
                if (data.user) userInfos[currentPlatform] = data.user;
                const tab = document.querySelector(`.platform-tab[data-platform="${currentPlatform}"]`);
                if (tab && !tab.querySelector('.badge')) {
                    const badge = document.createElement('span');
                    badge.className = 'badge';
                    badge.textContent = '已登录';
                    tab.appendChild(badge);
                }
                setTimeout(() => window.location.href = '/', 1500);
            }
        } catch (e) {
            showResult(false, '登录失败: ' + e.message);
        }
    }

    async function sendPhoneCode() {
        const phone = document.getElementById('phoneInput').value.trim();
        if (!phone) { alert('请输入手机号'); return; }

        try {
            const resp = await fetch(`/api/login/phone/${currentPlatform}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone}),
            });
            const data = await resp.json();
            if (data.success || data.need_code) {
                document.getElementById('codeGroup').style.display = 'block';
                document.getElementById('sendCodeBtn').style.display = 'none';
                document.getElementById('phoneLoginBtn').style.display = 'inline-block';
                showResult(true, '验证码已发送');
            } else {
                showResult(false, data.msg);
            }
        } catch (e) {
            showResult(false, '发送失败: ' + e.message);
        }
    }

    async function loginWithPhone() {
        const phone = document.getElementById('phoneInput').value.trim();
        const code = document.getElementById('codeInput').value.trim();
        if (!phone || !code) { alert('请输入手机号和验证码'); return; }

        try {
            const resp = await fetch(`/api/login/phone/${currentPlatform}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone, code}),
            });
            const data = await resp.json();
            showResult(data.success, data.msg);
            if (data.success) {
                loggedInPlatforms.add(currentPlatform);
                if (data.user) userInfos[currentPlatform] = data.user;
                const tab = document.querySelector(`.platform-tab[data-platform="${currentPlatform}"]`);
                if (tab && !tab.querySelector('.badge')) {
                    const badge = document.createElement('span');
                    badge.className = 'badge';
                    badge.textContent = '已登录';
                    tab.appendChild(badge);
                }
                setTimeout(() => window.location.href = '/', 1500);
            }
        } catch (e) {
            showResult(false, '登录失败: ' + e.message);
        }
    }

    function showResult(success, msg) {
        const el = document.getElementById('loginResult');
        el.className = 'login-result ' + (success ? 'success' : 'error');
        el.textContent = msg;
        el.style.display = 'block';
    }
