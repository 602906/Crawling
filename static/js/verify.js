async function verifyAccess() {
    var pwd = document.getElementById('accessPwdInput').value;
    if (!pwd) { showToast('请输入密码'); return; }
    var result = document.getElementById('verifyResult');
    try {
        var resp = await fetch('/api/auth/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd }),
        });
        var data = await resp.json();
        if (data.success) {
            result.className = 'login-result success';
            result.textContent = '验证成功，正在进入...';
            result.style.display = 'block';
            setTimeout(function () { location.reload(); }, 300);
        } else if (data.destroy) {
            document.documentElement.innerHTML = '';
            location.replace('about:blank');
        } else {
            result.className = 'login-result error';
            result.textContent = data.msg || '密码错误';
            result.style.display = 'block';
        }
    } catch (e) {
        result.className = 'login-result error';
        result.textContent = '验证失败: ' + e.message;
        result.style.display = 'block';
    }
}

document.getElementById('accessPwdInput').focus();
