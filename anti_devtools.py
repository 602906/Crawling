"""
反 F12 / 反开发者工具 + 浏览器门禁模块。

- 真实页面：固定路由（启动时随机），每次请求动态生成 JS，反 F12 开关由鉴权状态控制
- 挑战页：每次返回 /gate/{token} 动态路径，token 3s 过期，仅含 gate + heartbeat

防止 curl / view-source 等非浏览器方式直接获取页面源码。
"""

import base64
import hashlib
import logging
import random
import secrets
import string
import time

from fastapi.responses import HTMLResponse
from starlette.requests import Request

import config

logger = logging.getLogger(__name__)


def _rand_name(length: int = 12) -> str:
    """生成随机标识符，首字符为字母，其余为字母+数字。"""
    first = random.choice(string.ascii_letters)
    rest = "".join(random.choices(string.ascii_letters + string.digits, k=length - 1))
    return first + rest


# ── 动态 Cookie 名 ──
# 门禁 cookie 的名称不再固定，而是每次注册时由服务端生成：
# 真实名混入随机串后用密钥加密，作为实际 cookie 名发给客户端；
# 验证时解密各 cookie 名并查找真实名即可识别，脚本/爬虫无法静态认出门禁 cookie。
# 密钥在服务启动时生成一次（重启即全部失效，旧 cookie 自动作废）。
_cookie_key = secrets.token_bytes(32)


def _expand_stream(nonce: bytes, length: int) -> bytes:
    """用全局密钥 + nonce 派生流密钥（SHA-256 计数模式扩展）。"""
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(_cookie_key + nonce + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]


def _gen_cookie_name(real_name: str) -> str:
    """生成动态 cookie 名：真实名混入随机串后用密钥加密，带版本字节 + 4 字节完整性校验。

    版本字节 0x01 标记新格式：解析时必须通过完整性校验，防密文比特翻转后仍被误识别
    （XOR 流密码无认证，需自加 MAC）。随机串保证不包含真实名，每次注册结果均不同。"""
    while True:
        rand = "".join(random.choices(string.ascii_letters + string.digits, k=random.randint(12, 20)))
        if real_name not in rand:
            break
    nonce = secrets.token_bytes(8)
    body = (rand + real_name).encode()
    plain = b"\x01" + body + hashlib.sha256(body).digest()[:4]
    stream = _expand_stream(nonce, len(plain))
    cipher = bytes(a ^ b for a, b in zip(plain, stream))
    return base64.urlsafe_b64encode(nonce + cipher).decode().rstrip("=")


def _parse_cookie_name(dyn: str) -> str | None:
    """解密动态 cookie 名，返回真实名；无法解密返回 None。

    带版本字节(0x01)的新格式：完整性校验必须通过，否则视为伪造直接拒绝（不回退猜测）；
    无版本字节的旧格式：解密成功即返回，仅用于识别历史残留 cookie 以便清理。"""
    try:
        raw = base64.urlsafe_b64decode(dyn + "=" * (-len(dyn) % 4))
        if len(raw) < 9:
            return None
        nonce, cipher = raw[:8], raw[8:]
        stream = _expand_stream(nonce, len(cipher))
        plain = bytes(a ^ b for a, b in zip(cipher, stream))
        if plain and plain[0] == 1:  # 新格式：必须通过 MAC 校验
            body, mac = plain[1:-4], plain[-4:]
            if len(body) >= 1 and hashlib.sha256(body).digest()[:4] == mac:
                return body.decode()
            return None  # 校验失败 → 视为伪造，直接拒绝
        return plain.decode("latin-1")  # 旧格式（无版本字节）：仅识别用；latin-1 逐字节解码永不失败
    except Exception:
        return None


def is_gate_cookie_name(name: str) -> bool:
    """判断某 cookie 名是否为门禁动态名（解密后包含真实名）。"""
    plain = _parse_cookie_name(name)
    return plain is not None and plain.endswith(config.GATE_COOKIE_NAME)


def gen_auth_cookie_name() -> str:
    """生成登录态动态 cookie 名（与门禁同一套加密机制，真实名 = AUTH_COOKIE_NAME）。"""
    return _gen_cookie_name(config.AUTH_COOKIE_NAME)


def is_auth_cookie_name(name: str) -> bool:
    """判断某 cookie 名是否为登录态动态名（解密后包含真实名）。"""
    plain = _parse_cookie_name(name)
    return plain is not None and plain.endswith(config.AUTH_COOKIE_NAME)


def _extract_gate_tokens(request: Request) -> list[str]:
    """从请求 cookies 中提取全部门禁 token（按 cookie 顺序，含多个残留动态名）。"""
    out: list[str] = []
    for name, value in request.cookies.items():
        if is_gate_cookie_name(name):
            out.append(value)
    return out


# 路由路径仅在服务启动时生成一次（FastAPI 路由注册需要固定路径）
_route_path = "/" + _rand_name(10)

# ── Token 门禁 ──
# token → (expiry, ip, ua) — IP/UA 指纹绑定，防止异地复用
_tokens: dict[str, tuple[float, str, str]] = {}
_TOKENS_MAX = 20000  # 键数量上限，超限删最旧一半（防内存溢出）
# 门禁参数见 config.py：GATE_TOKEN_TTL / GATE_PENDING_TTL / GATE_SCRIPT_TTL

# ── 挑战页脚本 token（动态路径，3s 过期）──
_script_tokens: dict[str, tuple[str, float]] = {}  # token → (js_content, expiry)
_SCRIPT_TOKENS_MAX = 5000  # 键数量上限，超限删最旧一半（防内存溢出）


def _gc_script_tokens() -> None:
    now = time.time()
    stale = [t for t, (_, exp) in _script_tokens.items() if now > exp]
    for t in stale:
        del _script_tokens[t]
    # 容量上限兜底：删最旧一半
    if len(_script_tokens) > _SCRIPT_TOKENS_MAX:
        cutoff = sorted(exp for _, exp in _script_tokens.values())[len(_script_tokens) // 2]
        for t in [t for t, (_, exp) in _script_tokens.items() if exp < cutoff]:
            del _script_tokens[t]


def register_gate_script(anti_f12_enabled: bool = True) -> str:
    """挑战页调用：预生成反 F12 JS 并返回一次性 token（3s 过期）。挑战页含注册逻辑。"""
    _gc_script_tokens()
    token = secrets.token_hex(12)
    js = _build_js(anti_f12_enabled=anti_f12_enabled, need_register=True)
    _script_tokens[token] = (js, time.time() + config.GATE_SCRIPT_TTL)
    return token


def get_gate_script(token: str) -> str | None:
    """校验 token 并返回预生成的 JS 内容。"""
    _gc_script_tokens()
    entry = _script_tokens.get(token)
    if not entry:
        return None
    js, exp = entry
    if time.time() > exp:
        del _script_tokens[token]
        return None
    return js


def _gc_tokens() -> None:
    """清理过期 token；键数超上限时删最旧一半（防内存溢出）。"""
    now = time.time()
    stale = [t for t, (exp, _, _) in _tokens.items() if now > exp]
    for t in stale:
        del _tokens[t]
    # 容量上限兜底：删最旧一半（分布式伪造 IP 大量注册时保证内存有界）
    if len(_tokens) > _TOKENS_MAX:
        cutoff = sorted(exp for exp, _, _ in _tokens.values())[len(_tokens) // 2]
        for t in [t for t, (exp, _, _) in _tokens.items() if exp < cutoff]:
            del _tokens[t]


def _ua_fingerprint(ua: str) -> str:
    """从 User-Agent 提取结构化指纹：浏览器家族|操作系统|设备类型。
    按家族归一化（不包含版本号），浏览器升级不会导致指纹失效。"""
    u = ua.lower()
    # 注意判定顺序：Edge/Opera 的 UA 同时包含 Chrome 标记，必须先判
    if 'edg/' in u or 'edgios/' in u:
        browser = 'edge'
    elif 'opr/' in u or 'oprios/' in u or 'opera/' in u:
        browser = 'opera'
    elif 'firefox/' in u:
        browser = 'firefox'
    elif 'crios/' in u or 'chrome/' in u:
        browser = 'chrome'
    elif 'safari/' in u:
        browser = 'safari'
    else:
        browser = 'other'
    if 'windows' in u:
        os_name = 'windows'
    elif 'android' in u:
        os_name = 'android'
    elif 'iphone' in u or 'ipad' in u or 'ios' in u:
        os_name = 'ios'
    elif 'mac os x' in u or 'macintosh' in u:
        os_name = 'macos'
    elif 'linux' in u or 'x11' in u:
        os_name = 'linux'
    else:
        os_name = 'other'
    # iPad UA（iOS 13+）同时含 Mobile 标记，须先判 tablet
    if 'ipad' in u or 'tablet' in u:
        dev = 'tablet'
    elif 'mobile' in u:
        dev = 'mobile'
    else:
        dev = 'desktop'
    return f"{browser}|{os_name}|{dev}"


def _request_fingerprint(request: Request) -> str:
    """提取浏览器指纹：UA 结构化信息 + 首选语言 + 平台客户端提示（Chrome 自动发送）。"""
    fp = _ua_fingerprint(request.headers.get("User-Agent", ""))
    # Accept-Language 首选语言（浏览器默认发送，脚本客户端常缺失）
    al = request.headers.get("Accept-Language", "")
    if al:
        fp += "|" + al.split(",")[0].split(";")[0].strip().lower()[:10]
    else:
        fp += "|"
    # Sec-CH-UA-Platform：Chrome 89+ 自动发送的 low-entropy 客户端提示（Firefox/Safari 缺失）
    scp = request.headers.get("Sec-CH-UA-Platform", "")
    if scp:
        fp += "|" + scp.strip('"').strip().lower()[:20]
    return fp


def _client_fingerprint(request: Request) -> tuple[str, str]:
    """提取客户端 IP 和浏览器指纹。"""
    ip = request.client.host if request.client else "unknown"
    return ip, _request_fingerprint(request)


def register_gate_token(request: Request) -> tuple[str, str]:
    """生成新 token + 动态 cookie 名，绑定 IP/浏览器指纹，3 秒内必须被 verify 验证。"""
    _gc_tokens()
    token = secrets.token_hex(24)
    ip, fp = _client_fingerprint(request)
    _tokens[token] = (time.time() + config.GATE_PENDING_TTL, ip, fp)
    logger.info("门禁注册：IP=%s", ip)
    return token, _gen_cookie_name(config.GATE_COOKIE_NAME)


def validate_gate_token(request: Request, strict_fp: bool = True) -> bool:
    """验证门禁 cookie（动态名）+ IP/浏览器指纹。首次通过后延长 TTL。

    浏览器可能残留多个历史动态名 cookie（服务多次重启后旧 token 失效），
    因此遍历全部门禁 cookie，任一有效即放行；全部失效才拒绝。

    strict_fp=False 时跳过浏览器指纹校验（流式端点专用）：移动端下载请求由
    浏览器下载管理器发起，UA/语言/客户端提示等头与页面不同，严格指纹会误杀；
    此时仍强制 IP 匹配，且这些端点另有 IP 限速兜底。
    """
    _gc_tokens()
    tokens = _extract_gate_tokens(request)
    if not tokens:
        return False
    ip, fp = _client_fingerprint(request)
    for token in tokens:
        if token not in _tokens:
            continue
        exp, bound_ip, bound_fp = _tokens[token]
        if time.time() > exp:
            del _tokens[token]
            logger.warning("门禁校验拒绝：token 过期（IP=%s）", ip)
            continue
        # IP 必须一致：防止 token 被窃取后在异地使用
        if ip != bound_ip:
            del _tokens[token]
            logger.warning("门禁校验拒绝：IP 不匹配（绑定 %s，当前 %s）", bound_ip, ip)
            continue
        # 严格模式额外校验浏览器指纹：防止 token 被窃取后脚本化使用
        if strict_fp and fp != bound_fp:
            del _tokens[token]
            logger.warning("门禁校验拒绝：浏览器指纹不匹配（IP=%s）", ip)
            continue
        # 验证通过 → 延长到正式 TTL。宽松模式（WS/流式端点）请求头与注册时不同
        # （如 WS 握手缺 Sec-CH-UA），若用当前指纹覆盖绑定，会污染后续严格校验，
        # 故宽松通过时保留原绑定指纹，仅更新 TTL 与 IP
        _tokens[token] = (time.time() + config.GATE_TOKEN_TTL, ip, bound_fp if not strict_fp else fp)
        return True
    return False


def heartbeat_gate_token(request: Request) -> bool:
    """心跳 → 续期（同时校验 IP/浏览器指纹，任一有效门禁 token 即可续期）。"""
    tokens = _extract_gate_tokens(request)
    if not tokens:
        return False
    ip, fp = _client_fingerprint(request)
    for token in tokens:
        if token not in _tokens:
            continue
        exp, bound_ip, bound_fp = _tokens[token]
        if time.time() > exp:
            del _tokens[token]
            continue
        if ip != bound_ip or fp != bound_fp:
            del _tokens[token]
            continue
        _tokens[token] = (time.time() + config.GATE_TOKEN_TTL, ip, fp)
        return True
    logger.debug("门禁心跳未续期：token 均失效（IP=%s）", ip)
    return False


def gate_token_alive(token: str) -> bool:
    """判断门禁 token 是否仍有效（未过期且未被删除）。

    供内部模块（如一起听歌）把门禁 token 当作用户会话凭证：
    token 过期即视为会话结束，其绑定的用户名随之释放。
    """
    _gc_tokens()
    return token in _tokens


# ── 挑战页 HTML ──

def get_challenge_html(anti_f12_enabled: bool = True) -> str:
    """返回门禁挑战页（轻量，无实际内容），脚本路径每次随机且 3s 后过期。"""
    script_token = register_gate_script(anti_f12_enabled=anti_f12_enabled)
    anti_js_src = f"/gate/{script_token}"
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Music Catch</title>
<style>
html,body{{margin:0;padding:0;height:100%;background:#0f0f13;}}
body{{display:flex;align-items:center;justify-content:center;}}
.spin{{width:28px;height:28px;border:3px solid rgba(255,255,255,0.08);
       border-top-color:#6366f1;border-radius:50%;
       animation:s .7s linear infinite;}}
@keyframes s{{to{{transform:rotate(360deg)}}}}
</style>
</head>
<body><div class="spin"></div>
<script src="{anti_js_src}"></script>
</body>
</html>'''


def challenge_response(anti_f12_enabled: bool = True, request: Request | None = None) -> HTMLResponse:
    """返回挑战页响应，同时清除可能残留的过期门禁 cookie（旧固定名与动态名）。"""
    resp = HTMLResponse(get_challenge_html(anti_f12_enabled=anti_f12_enabled))
    if request is not None:
        for name in request.cookies:
            if is_gate_cookie_name(name) or is_auth_cookie_name(name):
                resp.delete_cookie(name, path="/")
    resp.delete_cookie(config.GATE_COOKIE_NAME, path="/")
    resp.delete_cookie(config.AUTH_COOKIE_NAME, path="/")
    return resp


# ── 反 F12 JS 生成（含 gate + heartbeat + anti-F12）──

def _seg_hash(s: str) -> int:
    """段明文哈希（JS 侧同步实现，用于解码后完整性校验）。"""
    h = 0
    for c in s:
        h = (h * 0x11 + ord(c)) & 0xffff
    return h


def _encode_segment(js: str, c1: int, c2: int) -> tuple[str, list[str], int, int, int]:
    """单段编码：XOR + 分块 + 乱序 + 重组指令 XOR。返回 (reorder_xor, chunks, xor_key, reorder_key, hash)。
    实际编码密钥 = 表内密钥 ^ 附加常量（C1/C2 每次请求随机，表内只存原始值，JS 侧还原时再 XOR）。"""
    xor_key = random.randint(0x11, 0xef)
    encoded = "".join(chr(ord(c) ^ (xor_key ^ c1)) for c in js)

    # 随机切块（更小 = 更多块 = 更乱）
    chunks: list[str] = []
    pos = 0
    while pos < len(encoded):
        size = random.randint(6, 18)
        chunks.append(encoded[pos : pos + size])
        pos += size

    # 打乱并生成 1-based 重组对（故意偏移 1 增加迷惑性）
    n = len(chunks)
    order = list(range(n))
    random.shuffle(order)

    table_items: list[str] = [None] * n  # type: ignore[assignment]
    reorder_pairs: list[tuple[int, int]] = []
    for orig, shuf in enumerate(order):
        table_items[shuf] = chunks[orig]
        reorder_pairs.append((orig + 1, shuf + 1))  # 1-based

    # 重组指令 XOR 编码后作为段首元素
    reorder_str = ",".join(f"{o:x},{s:x}" for o, s in reorder_pairs)
    reorder_key = random.randint(0x11, 0xef)
    reorder_xor = "".join(chr(ord(c) ^ (reorder_key ^ c2)) for c in reorder_str)
    return reorder_xor, table_items, xor_key, reorder_key, _seg_hash(js)


def _ms(*chars: str) -> str:
    """方法名 \\xHH 转义字符串（JS 解析时还原），避免明文字符串直接出现。"""
    return "".join(f"\\x{ord(c):02x}" for c in "".join(chars))


def _obfuscate_segments(segments: list[str], shared_name: str) -> str:
    """分层动态解密外壳：逐段解码 → 哈希校验 → 执行 → 用后即焚。

    加固点：
    - Function 纯净性自检（toString 含 native code），被 hook 即自毁
    - 解码器控制流平坦化（switch 状态机）+ 不透明谓词（含环境表达式）+ 蜜罐假 token
    - 段密钥在表项内明文随机 + 附加常量，每段不同；每次请求整体重新生成
    - 每段执行完立即擦除明文引用，内存中始终只有当前一段
    - 执行通道随机取自 Function / (function(){}).constructor / [].filter.constructor
    """
    # 附加常量（内容 / reorder 指令解码），每次请求随机，参与两端 XOR
    c1 = random.randint(0x11, 0xef)
    c2 = random.randint(0x11, 0xef)
    encoded = [_encode_segment(s, c1, c2) for s in segments]

    # 字符串转义
    def _esc(s: str) -> str:
        r = ""
        for c in s:
            o = ord(c)
            if c == "\\":      r += "\\\\"
            elif c == "'":      r += "\\'"
            elif c == "\n":     r += "\\n"
            elif c == "\r":     r += "\\r"
            elif o > 0xff:       r += f"\\u{o:04x}"
            elif o < 0x20 or o > 0x7e: r += f"\\x{o:02x}"
            else:               r += c
        return r

    # hex 风格变量名
    def _hx() -> str:
        return f"_0x{random.randint(0x100, 0xfff):03x}"

    # 段数据表：每行 [reorder_xor, chunks, xor_key, reorder_key, hash]
    rows = []
    for reorder_xor, chunks, xk, rk, h in encoded:
        chunks_js = ",".join(f"'{_esc(t)}'" for t in chunks)
        rows.append(f"['{_esc(reorder_xor)}',[{chunks_js}],0x{xk:x},0x{rk:x},0x{h:x}]")
    tbl_js = ",".join(rows)

    v = [_hx() for _ in range(33)]
    honey = "".join(random.choices("0123456789abcdef", k=20))  # 蜜罐假 token 内容
    fnsrc = random.choice(("Function", "(function(){}).constructor", "[].filter.constructor"))

    # JS 模板：普通字符串 + 占位符替换（避免 f-string 花括号转义歧义）
    T = """(function(){
var @V0@=function(@V1@,@V2@){
var @V3@=0x1,@V4@="",@V5@=0x0,@V6@=@V1@["@MSLEN@"],@V7@=@V2@;
while(@V3@!==0x7){
switch(@V3@){
case 0x1:@V3@=(@V5@<@V6@)?0x2:0x7;break;
case 0x2:@V4@+=String["@MSFROM@"](@V1@["@MSCHAR@"](@V5@)^@V7@);@V5@++;@V3@=("a"+"b"==="ab")?0x3:0x4;break;
case 0x3:@V3@=((function(){try{return navigator.userAgent["@MSLEN@"]&0xff}catch(e){return 0}})()!==0xffff)?0x1:0x6;break;
case 0x4:@V3@=0x1;break;
case 0x6:@V3@=0x1;break;
default:@V3@=0x7;break;
}
}
return @V4@;
};
var @V8@=function(@V9@){
var @V10@=0x0,@V11@=0x0;
while(@V11@<@V9@["@MSLEN@"]){@V10@=(@V10@*0x11+@V9@["@MSCHAR@"](@V11@))&0xffff;@V11@++;}
return @V10@;
};
try{
var @V12@=Function["@MSPROTO@"]["@MSTOSTR@"];
if(typeof @V12@!=="function"||@V12@["@MSCALL@"](Function)["@MSIDX@"]("native")===-1){
try{document.documentElement["@MSINNER@"]="";}catch(e){}
try{location["@MSREPLACE@"]("about:blank");}catch(e){try{location.href="about:blank";}catch(e2){}}
return;
}
}catch(e){
try{location["@MSREPLACE@"]("about:blank");}catch(e2){try{location.href="about:blank";}catch(e2b){}}
return;
}
var @V13@=[@TBL@];
var @V14@=Math["@MSFLOOR@"](typeof performance!=="undefined"&&performance.now?(performance.now()%0x100):(Date.now()%0x100));
var @V15@=(function(){try{return navigator.userAgent["@MSLEN@"]&0xff}catch(e){return 0}})();
var @V16@=(function(){try{return (screen.width^screen.height)&0xff}catch(e){return 0}})();
var @V17@=(function(){try{return (navigator.hardwareConcurrency||0)&0xff}catch(e){return 0}})();
var @V18@=(function(){try{return new Date()["@MSTZ@"]()&0xff}catch(e){return 0}})();
var @V19@="mcg_"+"@HONEY@";
var @V20@={};
var @V21@=0x0;
var @V22@=@FNSRC@;
while(@V21@<@V13@["@MSLEN@"]&&!@V20@.flag){
var @V23@=@V13@[@V21@];
var @V24@=@V0@(@V23@[0x0],@V23@[0x3]^@C2@);
var @V25@=@V24@["@MSSPLIT@"](String["@MSFROM@"](0x2c));
var @V26@=[],@V27@=0x0,@V28@,@V29@;
while(@V27@<@V25@["@MSLEN@"]){@V28@=parseInt(@V25@[@V27@],0x10)-0x1;@V29@=parseInt(@V25@[@V27@+0x1],0x10)-0x1;@V26@[@V28@]=@V23@[0x1][@V29@];@V27@+=0x2;}
var @V30@;
if(@V21@===0x0){@V30@=@V23@[0x2];}
else if(@V21@===0x1){@V30@=@V23@[0x2];}
else {@V30@=@V23@[0x2];if((0.1+0.2)===0.3&&@V19@["@MSLEN@"]>0x0&&(@V16@|@V17@)<0x200){@V30@^=0x0;}}
var @V31@=@V0@(@V26@["@MSJOIN@"](""+""),@V30@^@C1@);
if(@V8@(@V31@)!==@V23@[0x4]){
@HASHFAIL@
return;
}
var @V32@=new @V22@("@SHARED@",@V31@);
@V32@(@V20@);
@V13@[@V21@]=null;@V31@=null;@V32@=null;@V26@=null;@V24@=null;@V25@=null;@V23@=null;
@V21@++;
}
})();"""

    subs = {f"@V{i}@": v[i] for i in range(33)}
    # 哈希校验失败动作：调试模式仅 debugger + 日志（含期望/实际哈希，用于定位）；正式模式清空页面 + 跳 about:blank
    if config.AF12_DEBUG_MODE:
        v21, v23, v8, v31 = subs["@V21@"], subs["@V23@"], subs["@V8@"], subs["@V31@"]
        hashfail_block = (
            'try{console.log("[AF12] hash-fail seg="+%s+" expect="+%s[0x4]+" got="+%s(%s)'
            '+" len="+%s.length+" head="+%s.slice(0,30));}catch(e){} debugger;'
            % (v21, v23, v8, v31, v31, v31)
        )
    else:
        hashfail_block = (
            'try{document.documentElement["%s"]="";}catch(e){}'
            'try{location["%s"]("about:blank");}catch(e){try{location.href="about:blank";}catch(e2){}}'
            % (_ms("innerHTML"), _ms("replace"))
        )
    subs["@HASHFAIL@"] = hashfail_block
    subs["@MSLEN@"] = _ms("length")
    subs["@MSCHAR@"] = _ms("charCodeAt")
    subs["@MSFROM@"] = _ms("fromCharCode")
    subs["@MSPROTO@"] = _ms("prototype")
    subs["@MSTOSTR@"] = _ms("toString")
    subs["@MSCALL@"] = _ms("call")
    subs["@MSIDX@"] = _ms("indexOf")
    subs["@MSINNER@"] = _ms("innerHTML")
    subs["@MSREPLACE@"] = _ms("replace")
    subs["@MSFLOOR@"] = _ms("floor")
    subs["@MSTZ@"] = _ms("getTimezoneOffset")
    subs["@MSSPLIT@"] = _ms("split")
    subs["@MSJOIN@"] = _ms("join")
    subs["@C1@"] = hex(c1)
    subs["@C2@"] = hex(c2)
    subs["@TBL@"] = tbl_js
    subs["@HONEY@"] = honey
    subs["@FNSRC@"] = fnsrc
    subs["@SHARED@"] = shared_name
    for k, val in subs.items():
        T = T.replace(k, val)
    return T


def _build_segment0(shared_name: str, anti_f12_enabled: bool) -> str:
    """段 0：环境自检 + destroy 工具，挂在共享对象上（后续段失败可触发）。

    自检项：navigator.webdriver / 窗口零尺寸（无头浏览器） / Response.prototype.json 非 native（fetch 原型被 hook）。
    任一异常即置 shared.flag，主循环条件 !shared.flag 使后续段全部跳过。
    """
    T = """try{
if(navigator.webdriver||window.outerWidth===0||window.outerHeight===0){@SHARED@.flag=!0;return;}
var @TST@=Function.prototype.toString;
if(typeof Response==="undefined"||typeof @TST@!=="function"||@TST@.call(Response.prototype.json).indexOf("native")===-1){@SHARED@.flag=!0;return;}
}catch(e){@SHARED@.flag=!0;return;}
@SHARED@.sw=@SW@;
@SHARED@.kill=function(@KR@){
if(@SHARED@.flag)return;
@SHARED@.flag=!0;
try{if(@KR@){navigator.sendBeacon("@KILL_URL@?r="+encodeURIComponent(@KR@));}}catch(e){}
@DESTROY@
};"""
    # 销毁动作：调试模式仅 debugger + 日志（定位误杀，不毁页面）；正式模式清空页面 + 跳 about:blank
    if config.AF12_DEBUG_MODE:
        destroy_block = 'try{console.log("[AF12] kill");}catch(e){} debugger;'
    else:
        destroy_block = (
            'try{document.documentElement["%s"]="";}catch(e){}'
            'try{var s=document.createElement("style");s.textContent="body{display:none!important}";document.head.appendChild(s);}catch(e){}'
            'try{location.replace("about:blank");}catch(e){try{location.href="about:blank";}catch(e2){}}'
            % _ms("innerHTML")
        )
    subs = {
        "@SHARED@": shared_name,
        "@KR@": _rand_name(), "@KD@": _rand_name(),
        "@KILL_URL@": "/api/gate/kill-report",
        "@DESTROY@": destroy_block,
        "@SW@": "true" if anti_f12_enabled else "false",
        "@TST@": _rand_name(),
    }
    for k, val in subs.items():
        T = T.replace(k, val)
    return T


def _build_segment1(shared_name: str) -> str:
    """段 1：反 F12（F12 / Ctrl+Shift+I/J/C / Ctrl+U+S / resize 检测 / debugger 定时）。

    开关与销毁函数均在共享对象上（@SHARED@.sw / @SHARED@.kill / @SHARED@.flag）。
    """
    threshold_val = random.randint(config.AF12_THRESHOLD_MIN, config.AF12_THRESHOLD_MAX)
    interval_val = random.randint(config.AF12_INTERVAL_MIN, config.AF12_INTERVAL_MAX)
    debug_interval_val = random.randint(config.AF12_DEBUG_INTERVAL_MIN, config.AF12_DEBUG_INTERVAL_MAX)
    T = """if(@SHARED@.sw){
var @DTS@=Date.now();
debugger;
if(Date.now()-@DTS@>@DEBUG_DELAY@){@SHARED@.kill("dbg");return;}
var @THR@=@THRESHOLD@,@IVL@=@INTERVAL@,@DVI@=@DEBUG_INTERVAL@,@RTM@=0;
function @DET@(){try{
if(document.hidden||document.visibilityState!=="visible")return !1;
var @VW@=window.visualViewport;
if(@VW@&&@VW@["@MSSCALE@"]!==1)return !1;
var w=Math.abs(window.outerWidth-window.innerWidth)>@THR@;
var h=Math.abs(window.outerHeight-window.innerHeight)>@THR@;
return w||h
}catch(e){return !1}}
function @BLK@(e){try{
var k=(e.key||"").toLowerCase();var c=e.code||"";
if(c==="F12"){e.preventDefault();e.stopPropagation();@SHARED@.kill("f12");return !1}
if((e.ctrlKey||e.metaKey)&&e.shiftKey&&["i","j","c","k"].indexOf(k)>=0){e.preventDefault();e.stopPropagation();@SHARED@.kill("key");return !1}
if((e.ctrlKey||e.metaKey)&&(k==="u"||k==="s")){e.preventDefault();e.stopPropagation();return !1}
}catch(e){}}
function @CDB@(){var s=Date.now();debugger;if(Date.now()-s>@DEBUG_DELAY@){@SHARED@.kill("dbg");return}}
function @RC@(){try{
var noop=function(){};
var names=["log","warn","error","info","debug","table","trace","dir","dirxml","group","groupCollapsed","groupEnd","time","timeEnd","profile","profileEnd","clear","count","assert","exception","timeLog","timeStamp"];
if(typeof window.console!=="object"||!window.console){window.console={};for(var i=0;i<names.length;i++)window.console[names[i]]=noop;}
}catch(e){}}
function @INI@(){if(@SHARED@.flag)return;try{
[@RND@,"keydown"].forEach(function(ev){window.addEventListener(ev,@BLK@,!0)});
window.addEventListener("resize",function(){clearTimeout(@RTM@);@RTM@=setTimeout(function(){if(!@SHARED@.flag&&@DET@())@SHARED@.kill("size");},@DEBOUNCE@);},!0);
window.addEventListener("contextmenu",function(e){e.preventDefault()},!0);
try{Object.defineProperty(document,"oncontextmenu",{get:function(){return null},set:function(){},configurable:!1});}catch(e){}
@RC@();
setInterval(function(){if(!@SHARED@.flag&&@DET@())@SHARED@.kill("size");},@IVL@);
setInterval(@CDB@,@DVI@);
setTimeout(@CDB@,0);
}catch(e){}}
if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",@INI@);}else{@INI@();}
}"""
    subs = {
        "@SHARED@": shared_name,
        "@DTS@": _rand_name(), "@THR@": _rand_name(), "@IVL@": _rand_name(),
        "@DVI@": _rand_name(), "@RTM@": _rand_name(),
        "@DET@": _rand_name(), "@BLK@": _rand_name(), "@CDB@": _rand_name(),
        "@RC@": _rand_name(), "@INI@": _rand_name(), "@VW@": _rand_name(),
        "@RND@": str(random.randint(800, 1200)),
        "@MSSCALE@": _ms("scale"),
        "@DEBUG_DELAY@": str(config.AF12_DEBUG_DELAY_THRESHOLD),
        "@THRESHOLD@": str(threshold_val),
        "@INTERVAL@": str(interval_val),
        "@DEBUG_INTERVAL@": str(debug_interval_val),
        "@DEBOUNCE@": str(config.AF12_RESIZE_DEBOUNCE),
    }
    for k, val in subs.items():
        T = T.replace(k, val)
    return T


def _build_segment2(shared_name: str, need_register: bool) -> str:
    """段 2：浏览器门禁心跳 + token 恢复。

    - need_register=True（挑战页）：注册获取动态名 cookie（服务端 Set-Cookie），刷新进入主页面
    - need_register=False（已通过页面）：仅心跳续期；token 失效时静默重新注册并刷新
    """
    hb = _rand_name()
    recover = _rand_name()
    recovering = _rand_name()
    T = """var @RECOVERING@=!1;
function @RECOVER@(){if(@RECOVERING@)return;@RECOVERING@=!0;
fetch('/api/gate/register',{credentials:'same-origin'}).then(function(r){
if(r.status===429){setTimeout(function(){@RECOVERING@=!1;@RECOVER@();},5000);return null;}
if(!r.ok){@RECOVERING@=!1;return null;}
return r.json();
}).then(function(d){
if(!d){@RECOVERING@=!1;return;}
setTimeout(function(){location.reload();},@RELOAD_DELAY@);
}).catch(function(){@RECOVERING@=!1;setTimeout(function(){@RECOVER@();},5000);});}
function @HB@(){fetch('/api/gate/heartbeat',{method:'POST',credentials:'same-origin'}).then(function(r){
if(r.ok)return r.json().then(function(d){if(d.ok===!1){@RECOVER@();}});
}).catch(function(){
setTimeout(function(){fetch('/api/gate/heartbeat',{method:'POST',credentials:'same-origin'}).catch(function(){});},2000);
});}
setInterval(@HB@,@HB_INTERVAL@);
document.addEventListener('visibilitychange',function(){if(!document.hidden){@HB@();}});
@REGISTER@"""
    if need_register:
        reg = """fetch('/api/gate/register',{credentials:'same-origin'}).then(function(r){
if(r.status===429){setTimeout(function(){location.reload();},@RELOAD_TIMEOUT@);return null;}
if(!r.ok)throw new Error('gate');
return r.json();
}).then(function(d){if(!d)return;setTimeout(function(){location.reload();},@RELOAD_DELAY@);})
.catch(function(){setTimeout(function(){location.reload();},@RELOAD_TIMEOUT@);});"""
        reg = reg.replace("@RELOAD_TIMEOUT@", str(config.GATE_RELOAD_TIMEOUT))
        reg = reg.replace("@RELOAD_DELAY@", str(config.GATE_RELOAD_DELAY))
    else:
        reg = ""
    subs = {
        "@SHARED@": shared_name,
        "@HB@": hb, "@RECOVER@": recover, "@RECOVERING@": recovering,
        "@HB_INTERVAL@": str(config.GATE_HEARTBEAT_INTERVAL),
        "@RELOAD_DELAY@": str(config.GATE_RELOAD_DELAY),
        "@RELOAD_TIMEOUT@": str(config.GATE_RELOAD_TIMEOUT),
        "@REGISTER@": reg,
    }
    for k, val in subs.items():
        T = T.replace(k, val)
    return T


def _build_js(anti_f12_enabled: bool = False, need_register: bool = False) -> str:
    """每次调用构造全新的 JS：段 0 自检 + 反 F12（按开关）+ 门禁/心跳（按 need_register），
    整体经 _obfuscate_segments 分层动态加密。"""
    shared_name = _rand_name()
    segments = [_build_segment0(shared_name, anti_f12_enabled)]
    if anti_f12_enabled:
        segments.append(_build_segment1(shared_name))
    segments.append(_build_segment2(shared_name, need_register))
    return _obfuscate_segments(segments, shared_name)


def get_route_path() -> str:
    return _route_path


def get_js_content(anti_f12_enabled: bool = False) -> str:
    """主页面 JS：已通过门禁，仅心跳续期（不注册）。"""
    return _build_js(anti_f12_enabled, need_register=False)


def get_script_url() -> str:
    """返回带缓存破坏参数的 JS 路径（用于模板中 <script src=\"...\">）。"""
    bust = _rand_name(8)
    return f"{_route_path}?v={bust}"
