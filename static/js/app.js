// app.js - shared utilities for Music Catch

document.addEventListener('DOMContentLoaded', () => {
    checkLoginStatus();
});

async function checkLoginStatus() {
    try {
        const resp = await fetch('/api/status');
        const data = await resp.json();
        for (const [platform, info] of Object.entries(data)) {
            const badge = document.querySelector(`.filter-btn[data-filter="${platform}"] .badge`);
            if (info.logged_in && !badge) {
                const btn = document.querySelector(`.filter-btn[data-filter="${platform}"]`);
                if (btn) {
                    const span = document.createElement('span');
                    span.className = 'badge';
                    span.textContent = '已登录';
                    btn.appendChild(span);
                }
            }
        }
    } catch (e) {
        // ignore
    }
}
