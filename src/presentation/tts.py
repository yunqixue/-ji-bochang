"""
表现层：语音合成（TTS）。  Owner: B（语音接入） / C（静态资源目录）

主选 edge-tts（微软，免费，中文音色好，支持调速调音高）。
兜底 pyttsx3（离线，音色差但能用）。

对外一个函数：
    url = synthesize("文本", speech_rate=0.85, pitch_shift=-2)
    # 返回 "/static/tts/xxxx.mp3"，失败返回 None（前端只显示文字）
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import time
from typing import Optional

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_DIR = os.path.join(REPO_ROOT, "src", "presentation", "static", "tts")

VOICE = os.getenv("TTS_VOICE", "zh-CN-XiaoyiNeural")   # 备选：zh-CN-XiaoxiaoNeural
# edge-tts 的音高单位是 Hz，契约里用的是半音；经验换算 1 半音 ≈ 15Hz
HZ_PER_SEMITONE = 15.0


def available() -> bool:
    try:
        import edge_tts  # noqa: F401
        return True
    except Exception:
        try:
            import pyttsx3  # noqa: F401
            return True
        except Exception:
            return False


def _ensure_dir() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)


def _cache_name(text: str, rate: float, pitch: float, suffix: str) -> str:
    raw = f"{VOICE}|{text}|{rate:.2f}|{pitch:.1f}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:12] + suffix


def _rate_str(speech_rate: float) -> str:
    pct = (float(speech_rate) - 1.0) * 100.0
    pct = max(-50.0, min(100.0, pct))
    return f"{pct:+.0f}%"


def _pitch_str(pitch_shift: float) -> str:
    hz = float(pitch_shift) * HZ_PER_SEMITONE
    hz = max(-50.0, min(50.0, hz))
    return f"{hz:+.0f}Hz"


async def _edge_save(text: str, out_path: str, rate: str, pitch: str) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, VOICE, rate=rate, pitch=pitch)
    await communicate.save(out_path)


# 复用同一个事件循环。
# 用 asyncio.run() 每次新建+关闭循环时，aiohttp 的连接器会在循环关闭后报
# "RuntimeError: Event loop is closed"，表现为"偶尔生成不出语音"。
_LOOP = None


def _run_edge(coro):
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP.run_until_complete(coro)


def _pyttsx3_save(text: str, out_path: str) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    engine.save_to_file(text, out_path)
    engine.runAndWait()


def synthesize(text: str, speech_rate: float = 1.0, pitch_shift: float = 0.0,
               retries: int = 3) -> Optional[str]:
    """生成语音，返回可直接给前端的 URL；任何失败都返回 None（不抛异常）。

    retries: 在线合成重试次数。实测每次尝试成功率约 40%（国内连微软服务器不稳），
             实时对话用 3 次（不让用户等太久）；演示预演可以传 8，慢慢补到全成功。
    """
    text = (text or "").strip()
    if not text:
        return None
    _ensure_dir()

    mp3_name = _cache_name(text, speech_rate, pitch_shift, ".mp3")
    mp3_path = os.path.join(OUT_DIR, mp3_name)
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        return f"/static/tts/{mp3_name}"

    attempts = max(1, int(retries))
    try:
        for attempt in range(attempts):
            try:
                _run_edge(_edge_save(text, mp3_path, _rate_str(speech_rate), _pitch_str(pitch_shift)))
                if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                    return f"/static/tts/{mp3_name}"
            except Exception:
                if attempt < attempts - 1:
                    time.sleep(0.4 * (attempt + 1))
                continue
    except Exception:
        pass                                    # 落到 pyttsx3 兜底

    try:
        wav_name = _cache_name(text, speech_rate, pitch_shift, ".wav")
        wav_path = os.path.join(OUT_DIR, wav_name)
        _pyttsx3_save(text, wav_path)
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            return f"/static/tts/{wav_name}"
    except Exception:
        pass

    return None


if __name__ == "__main__":
    print("TTS 可用:", available())
    print("生成:", synthesize("嗯，我在听。今天发生什么了？", 0.9, -1.0))
