"""
歌词翻译模块
- 自动检测各平台的翻译 API 是否可用（通过是否有实现来判断）
- 优先使用平台原生翻译，失败则回退到本地翻译（translators 库）
- 只翻译非中文占比 >= 70% 的歌词
"""

import asyncio
import hashlib
import logging
import re
from collections import OrderedDict
from functools import partial
from typing import Optional

import config

logger = logging.getLogger(__name__)

# ── 服务端缓存（LRU，每次只删 10%，避免命中率周期性掉崖）──
_TRANSLATE_CACHE_MAX = config.LYRICS_TRANSLATE_CACHE_MAX
_TRANSLATE_CACHE_EVICT_RATIO = config.LYRICS_TRANSLATE_CACHE_EVICT_RATIO
_TRANSLATE_CACHE: OrderedDict[str, str] = OrderedDict()


def _cache_translation(key: str, value: str) -> None:
    if key in _TRANSLATE_CACHE:
        _TRANSLATE_CACHE.move_to_end(key)
        _TRANSLATE_CACHE[key] = value
        return
    if len(_TRANSLATE_CACHE) >= _TRANSLATE_CACHE_MAX:
        # 淘汰最旧的 10%
        n_evict = max(1, int(_TRANSLATE_CACHE_MAX * _TRANSLATE_CACHE_EVICT_RATIO))
        for _ in range(n_evict):
            _TRANSLATE_CACHE.popitem(last=False)
    _TRANSLATE_CACHE[key] = value


# ── 中文比例检测 ──
_CJK_RE = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\U00020000-\U0002A6DF]')
# CJK 符号/标点范围（进一步排除，避免把全角标点算成"非中文"）
_CJK_PUNCT = set('，。！？、：；""''（）【】《》—…·')


def count_non_chinese_ratio(lrc: str) -> float:
    """计算歌词中非中文内容的比例（0-1之间）。"""
    if not lrc:
        return 0.0
    lines = []
    for line in lrc.split('\n'):
        # 移除所有方括号标签（时间戳、元信息等）
        line = re.sub(r'\[[^\]]*\]', '', line).strip()
        if not line:
            continue
        lines.append(line)
    if not lines:
        return 0.0
    total_chars = sum(len(l) for l in lines)
    if total_chars == 0:
        return 0.0
    non_cjk = 0
    for line in lines:
        for ch in line:
            if _CJK_RE.match(ch):
                continue
            if ch in _CJK_PUNCT:
                continue
            if ch.isdigit():
                continue
            # ASCII 字母和数字是内容字符，标点空格跳过
            if '\u0020' <= ch <= '\u007e' and not ch.isalnum():
                continue
            non_cjk += 1
    return non_cjk / total_chars


# ── 平台翻译能力注册表 ──
_PLATFORM_TRANSLATE_MAP: dict[str, dict] = {}


def register_platform(platform_id: str, platform_instance=None, has_api: bool | None = None) -> None:
    """
    注册平台翻译能力。
    has_api 为 None 时自动检测（hasattr get_lyrics_with_translation）。
    建议显式传 has_api，避免基类有同名方法导致误判。
    """
    if has_api is None:
        has_api = (
            platform_instance is not None
            and hasattr(platform_instance, 'get_lyrics_with_translation')
            and callable(getattr(platform_instance, 'get_lyrics_with_translation'))
        )
    _PLATFORM_TRANSLATE_MAP[platform_id] = {
        "has_api": has_api,
        "platform_instance": platform_instance,
    }
    logger.info("翻译能力注册：%s → %s", platform_id, "有API" if has_api else "无API")


async def get_platform_translation(platform_id: str, song) -> Optional[dict]:
    """
    调用平台原生的翻译 API，返回 {"lyrics": "...", "translated": "..."} 或 None。
    只有 lyrics 和 translated 都非空时才视为成功。
    """
    info = _PLATFORM_TRANSLATE_MAP.get(platform_id)
    if not info:
        logger.debug("【翻译平台】%s 未注册，跳过", platform_id)
        return None
    if not info["has_api"]:
        logger.debug("【翻译平台】%s 无翻译 API，跳过", platform_id)
        return None
    instance = info["platform_instance"]
    if instance is None:
        logger.warning("【翻译平台】%s 已注册但实例为 None", platform_id)
        return None
    try:
        result = await instance.get_lyrics_with_translation(song)
        # 严格校验：lyrics 和 translated 都必须非空
        if result and result.get("lyrics") and result.get("translated"):
            lrc_lines = result["translated"].count('\n') + 1
            logger.info("【翻译平台】%s 原生翻译可用，歌词 %d 行，翻译 %d 行",
                        platform_id,
                        len(result["lyrics"].splitlines()),
                        lrc_lines)
            return result
        elif result and result.get("lyrics"):
            logger.warning("【翻译平台】%s 返回了歌词但 translated 为空，回退本地翻译",
                           platform_id)
        else:
            logger.debug("【翻译平台】%s 原生翻译返回 None 或空结果，回退本地翻译", platform_id)
    except Exception as e:
        logger.warning("【翻译平台】%s 翻译 API 调用失败: %s", platform_id, e)
    return None


# ── 本地翻译（fallback） ──
_SYNC_TRANSLATE_POOL = None
_SYNC_TRANSLATE_TIMEOUT = config.LYRICS_TRANSLATION_ENGINE_TIMEOUT   # 单次翻译网络请求超时（秒）
_BATCH_SIZE = config.LYRICS_TRANSLATION_BATCH_SIZE                  # 整段翻译每批最大行数
_FALLBACK_LINE_TIMEOUT = config.LYRICS_TRANSLATION_LINE_TIMEOUT     # 逐行回退时单行超时


def _get_sync_translate_pool():
    global _SYNC_TRANSLATE_POOL
    from concurrent.futures import ThreadPoolExecutor
    if _SYNC_TRANSLATE_POOL is None:
        _SYNC_TRANSLATE_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lrc-trans")
    return _SYNC_TRANSLATE_POOL


def _sync_translate(text: str, engine: str | None) -> str:
    import translators as _translators
    # from_language="auto" 让库自动检测源语言，避免日文/韩文被当英文翻
    kwargs = {"from_language": "auto", "to_language": "zh"}
    if engine:
        kwargs["translator"] = engine
    out = _translators.translate_text(text, **kwargs)
    return out if isinstance(out, str) else str(out)


def _detect_available_engines() -> list[str | None]:
    """
    启动时检测可用的翻译引擎。
    串行探测，每引擎最多 8 秒；不可用则跳过。
    """
    import translators as _translators
    _engines = ["bing", "alibaba", "baidu", "youdao", None]
    available: list[str | None] = []
    test_text = "Hello world"
    logger.info("开始检测翻译引擎可用性，测试文本：%r", test_text)
    for engine in _engines:
        name = engine or "默认引擎"
        try:
            result = _sync_translate(test_text, engine)
            stripped = result.strip() if result else ""
            ok = bool(stripped) and stripped != test_text
            logger.info("引擎 %s → 结果=%r ok=%s", name, stripped, ok)
            if ok:
                available.append(engine)
            else:
                logger.warning("引擎 %s 返回结果异常（相同或为空），跳过", name)
        except Exception as e:
            logger.debug("引擎 %s 不可用: %s", name, e)
    logger.info("歌词翻译引擎检测结果：%s", available or "无可用引擎")
    return available


# 全局可用引擎列表（由主模块启动时初始化）
_AVAILABLE_ENGINES: list[str | None] = []


def set_available_engines(engines: list[str | None]) -> None:
    global _AVAILABLE_ENGINES
    _AVAILABLE_ENGINES = engines
    logger.info("翻译引擎列表已更新：%s", _AVAILABLE_ENGINES)


async def translate_lrc_local(lrc: str) -> str:
    """
    本地翻译：当平台没有原生翻译 API 时使用。
    只翻译非中文占比 >= 70% 的歌词。
    返回原文+译文合并版本。
    """
    if not lrc:
        return ""

    # 检查是否需要翻译
    ratio = count_non_chinese_ratio(lrc)
    threshold = config.LYRICS_TRANSLATION_NON_CHINESE_RATIO
    logger.debug("【翻译本地】非中文占比 %.2f（阈值 %.2f），歌词 %d 行",
                 ratio, threshold, lrc.count('\n') + 1)
    if ratio < threshold:
        logger.debug("【翻译本地】中文占比过高，跳过翻译")
        return ""

    logger.info("【翻译本地】非中文占比 %.2f，触发本地翻译（引擎：%s）",
                ratio, _AVAILABLE_ENGINES or "无")

    # 检查引擎可用性
    if not _AVAILABLE_ENGINES:
        logger.warning("【翻译本地】没有可用的翻译引擎，跳过翻译")
        return ""

    try:
        import translators as _translators  # noqa: F401
    except Exception as e:
        logger.warning("【翻译本地】translators 导入失败: %s", e)
        return ""
    if not hasattr(_translators, "translate_text"):
        logger.warning("【翻译本地】translators 版本不支持 translate_text")
        return ""

    # 服务端缓存
    cache_key = hashlib.sha256(lrc.encode("utf-8")).hexdigest()
    cached = _TRANSLATE_CACHE.get(cache_key)
    if cached is not None:
        logger.debug("【翻译本地】缓存命中，直接返回（%d 行）", cached.count('\n') + 1)
        return cached
    else:
        logger.debug("【翻译本地】缓存未命中，开始翻译")

    # 解析 LRC 行
    entries = []
    texts = []
    for line in lrc.split('\n'):
        m = re.match(r'((?:\[\d{1,2}:\d{2}(?:[.:]\d{1,3})?\])+)(.*)', line)
        if not m or not m.group(2).strip():
            entries.append((line, None))
            continue
        entries.append((m.group(1), m.group(2).strip()))
        texts.append(m.group(2).strip())

    if not texts:
        logger.debug("【翻译本地】无可翻译的行，返回空")
        return ""

    logger.debug("【翻译本地】解析出 %d 行可翻译文本", len(texts))
    loop = asyncio.get_running_loop()
    translated: list[str] | None = None

    # ── 策略 1：整段翻译（快，但行数可能不对齐）──
    logger.debug("【翻译本地】策略1：整段翻译（%d 行）", len(texts))
    for engine in _AVAILABLE_ENGINES:
        try:
            parts = await _translate_batch(texts, engine, loop)
            if parts is not None and len(parts) == len(texts):
                translated = parts
                logger.info("【翻译本地】整段翻译成功（engine=%s，%d 行）", engine or "默认", len(parts))
                break
            if parts is not None:
                logger.warning("【翻译本地】引擎 %s 整段翻译行数不匹配（%s != %s），降级",
                               engine, len(parts), len(texts))
        except Exception as e:
            logger.debug("【翻译本地】引擎 %s 整段翻译异常: %s", engine or "默认", e)

    # ── 策略 2：分批翻译（每批 _BATCH_SIZE 行）──
    if translated is None:
        logger.info("【翻译本地】策略2：分批翻译（batch=%d，共 %d 行）", _BATCH_SIZE, len(texts))
        for engine in _AVAILABLE_ENGINES:
            parts = await _translate_in_batches(texts, engine, loop)
            if parts is not None:
                translated = parts
                logger.info("【翻译本地】分批翻译成功（engine=%s，%d 行）", engine or "默认", len(parts))
                break

    # ── 策略 3：逐行翻译兜底（最慢但最稳）──
    if translated is None:
        logger.warning("【翻译本地】策略3：逐行翻译兜底（%d 行）", len(texts))
        translated = await _translate_line_by_line(texts, loop)

    if translated is None:
        logger.warning("【翻译本地】全部翻译策略均失败")
        return ""

    # 拼回合并版本
    result = []
    ti = 0
    for head, orig in entries:
        if orig is None:
            result.append(head)
        else:
            result.append(f"{head}{orig}")
            result.append(f"{head}{translated[ti]}")
            ti += 1
    out = "\n".join(result)
    _cache_translation(cache_key, out)
    logger.debug("【翻译本地】合并完成，输出 %d 行", out.count('\n') + 1)
    return out


async def _translate_batch(
    texts: list[str], engine: str | None, loop
) -> list[str] | None:
    """一次性翻译所有文本，返回拆分后的列表；失败返回 None。"""
    try:
        res = await asyncio.wait_for(
            loop.run_in_executor(
                _get_sync_translate_pool(),
                partial(_sync_translate, "\n".join(texts), engine),
            ),
            timeout=_SYNC_TRANSLATE_TIMEOUT,
        )
        parts = res.splitlines()
        return parts
    except (asyncio.TimeoutError, Exception) as e:
        return None


async def _translate_in_batches(
    texts: list[str], engine: str | None, loop
) -> list[str] | None:
    """按 _BATCH_SIZE 分批翻译，逐批校验行数，全通过则合并返回。"""
    result: list[str] = []
    for i in range(0, len(texts), _BATCH_SIZE):
        batch = texts[i:i + _BATCH_SIZE]
        try:
            res = await asyncio.wait_for(
                loop.run_in_executor(
                    _get_sync_translate_pool(),
                    partial(_sync_translate, "\n".join(batch), engine),
                ),
                timeout=_SYNC_TRANSLATE_TIMEOUT * len(batch),
            )
            parts = res.splitlines()
            if len(parts) != len(batch):
                logger.warning("引擎 %s 分批翻译行数不匹配（%s != %s）", engine or "默认", len(parts), len(batch))
                return None
            result.extend(parts)
        except (asyncio.TimeoutError, Exception) as e:
            logger.warning("引擎 %s 分批翻译失败: %s", engine or "默认", e)
            return None
    return result


async def _translate_line_by_line(
    texts: list[str], loop
) -> list[str] | None:
    """逐行翻译兜底，每行独立超时，全部成功才返回。"""
    result: list[str] = []
    for i, text in enumerate(texts):
        found = False
        for engine in _AVAILABLE_ENGINES:
            try:
                res = await asyncio.wait_for(
                    loop.run_in_executor(
                        _get_sync_translate_pool(),
                        partial(_sync_translate, text, engine),
                    ),
                    timeout=_FALLBACK_LINE_TIMEOUT,
                )
                if res and res.strip():
                    result.append(res.strip())
                    found = True
                    logger.debug("第 %d/%d 行翻译成功（engine=%s）", i + 1, len(texts), engine or "默认")
                    break
            except (asyncio.TimeoutError, Exception):
                continue
        if not found:
            logger.warning("第 %d/%d 行翻译全部失败，保留原文", i + 1, len(texts))
            result.append(text)  # 保留原文
    return result


async def translate_lrc(lrc: str, platform_id: str, song) -> dict:
    """
    统一翻译入口：
    1. 总开关关闭时直接返回原文
    2. 优先使用平台原生翻译 API（要求 lyrics 和 translated 都非空）
    3. 失败则回退到本地翻译（三级策略：整段→分批→逐行）
    4. 返回 {"lyrics": "...", "translated": "..."}
    """
    result = {"lyrics": lrc, "translated": ""}

    if not lrc:
        logger.debug("歌词为空，跳过翻译 %s/%s", platform_id, getattr(song, 'id', '?'))
        return result

    # 总开关关闭 → 直接返回原文，不走任何翻译逻辑
    if not config.LYRICS_TRANSLATION_ENABLED:
        logger.debug("翻译总开关关闭，跳过 %s/%s", platform_id, getattr(song, 'id', '?'))
        return result

    # 步骤 1：尝试平台原生翻译
    platform_result = await get_platform_translation(platform_id, song)
    if platform_result:
        result["lyrics"] = platform_result["lyrics"]
        result["translated"] = platform_result["translated"]
        logger.info("【翻译】使用平台 %s 原生翻译 API，歌词 %d 行，翻译 %d 行",
                     platform_id,
                     result["lyrics"].count('\n') + 1,
                     result["translated"].count('\n') + 1)
        return result

    # 步骤 2：回退到本地翻译
    logger.info("【翻译】平台 %s 无原生翻译，回退本地翻译（歌词 %d 行）",
                 platform_id, lrc.count('\n') + 1)
    translated = await translate_lrc_local(lrc)
    if translated:
        result["translated"] = translated
        logger.info("【翻译】本地翻译成功，合并后 %d 行", translated.count('\n') + 1)
    else:
        logger.info("【翻译】本地翻译未触发或无结果（可能中文占比不足 70%）")
    return result
