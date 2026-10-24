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


def _sapi_save(text: str, out_path: str, rate: int = 0) -> None:
    """用 Windows 自带 SAPI 离线合成（不需要联网，不需要任何 pip 包）。

    实测本机装了 Microsoft Huihui Desktop (zh-CN)，所以离线兜底可行。
    注意：在某些受限账户/沙箱下 SAPI 会报"当前安全设置下没有可用语音"，
    此时抛异常，由上层继续兜底。
    """
    import subprocess
    import tempfile

    tmp = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    txt_path = tmp.name
    tmp.write(text)
    tmp.close()

    script = (
        "Add-Type -AssemblyName System.Speech;"
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
        f"$s.Rate={int(rate)};"
        "$zh=$s.GetInstalledVoices() | Where-Object {$_.VoiceInfo.Culture.Name -like 'zh*'} "
        "| Where-Object {$_.Enabled} | Select-Object -First 1;"
        "if($zh){$s.SelectVoice($zh.VoiceInfo.Name)};"
        f"$s.SetOutputToWaveFile('{out_path}');"
        f"$t=[System.IO.File]::ReadAllText('{txt_path}',[System.Text.Encoding]::UTF8);"
        "$s.Speak($t);"
        "$s.Dispose()"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, timeout=90,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", "ignore")[:200])
        if not os.path.exists(out_path) or os.path.getsize(out_path) < 1000:
            raise RuntimeError("SAPI 没有生成有效音频（可能是缺少中文语音包）")
    finally:
        try:
            os.remove(txt_path)
        except OSError:
            pass


def _pyttsx3_save(text: str, out_path: str) -> None:
    import pyttsx3
    engine = pyttsx3.init()
    engine.save_to_file(text, out_path)
    engine.runAndWait()


_LAST_ERROR = ""      # 最近一次合成失败的原因（给 /api/health 和日志看）
_LAST_BACKEND = ""    # 最近一次成功用的是哪个后端：edge / sapi / pyttsx3


def _explain(engine: str, exc_text: str) -> str:
    """把英文异常翻成"人能看懂 + 知道该干什么"的一句话。"""
    low = (exc_text or "").lower()
    if engine == "edge":
        if "cannot connect" in low or "connectorerror" in low or "timeout" in low:
            return "连不上微软服务器（网络问题，重试几次通常能好）"
        if "ssl" in low or "certificate" in low:
            return "加密连接被拦了（网络/代理问题）"
        return f"报错：{exc_text[:60]}"
    if engine == "sapi":
        if "有效音频" in exc_text:
            return "本机没有可用的中文语音包（装一个中文语音包就能出声）"
        if "安全设置" in exc_text or "未安装语音" in exc_text:
            return "这台机器没有可用的语音包，或系统不让程序调用语音"
        return f"报错：{exc_text[:60]}"
    if "pywintypes" in low:
        return "pyttsx3 缺依赖（这台机器上这条兜底用不了，可忽略）"
    return f"pyttsx3 报错：{exc_text[:60]}"


def last_error() -> str:
    """最近一次没出声的原因（中文，能直接看懂）。空字符串＝没失败过。"""
    return _LAST_ERROR


def last_backend() -> str:
    """最近一次成功用的是哪个后端。"""
    return _LAST_BACKEND


def synthesize(text: str, speech_rate: float = 1.0, pitch_shift: float = 0.0,
               retries: int = 3) -> Optional[str]:
    """生成语音，返回可直接给前端的 URL；任何失败都返回 None（不抛异常）。

    retries: 在线合成尝试次数。
      实测：连不上微软服务器时是**快速失败**（每次约 0.4 秒就抛 ClientConnectorError），
      不是死死等超时。所以多重试几次的代价很小，但能把"偶发连不上"救回来一大半。
      默认 3 次；演示现场完全连不上时最坏多花约 2.5 秒，之后就落到 SAPI 离线兜底。
      演示预演请传 8 —— 那时不赶时间，可以慢慢补到全部成功。

    ★ 为什么"有的时候没声音"必须能查：这条链有三种后端，任一环出问题，
      用户只看到"没声音"，不知道原因。所以每一环失败都记下原因，
      全挂时打印一行并写进 _LAST_ERROR（/api/health 里能看到）。
    """
    global _LAST_ERROR, _LAST_BACKEND

    text = (text or "").strip()
    if not text:
        _LAST_ERROR = "文本为空"
        return None
    _ensure_dir()

    mp3_name = _cache_name(text, speech_rate, pitch_shift, ".mp3")
    mp3_path = os.path.join(OUT_DIR, mp3_name)
    if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
        _LAST_ERROR = ""
        _LAST_BACKEND = "cache"
        return f"/static/tts/{mp3_name}"

    reasons: list[str] = []

    # 主选：edge-tts（在线，音色好）
    attempts = max(1, int(retries))
    edge_err = ""
    for attempt in range(attempts):
        try:
            _run_edge(_edge_save(text, mp3_path, _rate_str(speech_rate), _pitch_str(pitch_shift)))
            if os.path.exists(mp3_path) and os.path.getsize(mp3_path) > 0:
                _LAST_ERROR = ""
                _LAST_BACKEND = "edge"
                return f"/static/tts/{mp3_name}"
            edge_err = "生成了空文件"
        except Exception as exc:                       # noqa: BLE001
            edge_err = f"{type(exc).__name__}: {str(exc)[:60]}"
            if attempt < attempts - 1:
                time.sleep(0.4 * (attempt + 1))
    reasons.append("在线语音：" + _explain("edge", edge_err))

    # 兜底 1：Windows 自带 SAPI（离线）
    try:
        wav_name = _cache_name(text, speech_rate, pitch_shift, "_sapi.wav")
        wav_path = os.path.join(OUT_DIR, wav_name)
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 1000:
            _LAST_ERROR = ""
            _LAST_BACKEND = "sapi"
            return f"/static/tts/{wav_name}"
        # 契约里的 speech_rate 是倍率，SAPI 的 Rate 是 -10~10 的档位，粗略换算
        sapi_rate = int(round((float(speech_rate) - 1.0) * 10))
        _sapi_save(text, wav_path, rate=max(-10, min(10, sapi_rate)))
        _LAST_ERROR = ""
        _LAST_BACKEND = "sapi"
        return f"/static/tts/{wav_name}"
    except Exception as exc:                           # noqa: BLE001
        reasons.append("离线兜底：" + _explain("sapi", str(exc)))

    # 兜底 2：pyttsx3（某些机器上可用）
    try:
        wav_name = _cache_name(text, speech_rate, pitch_shift, ".wav")
        wav_path = os.path.join(OUT_DIR, wav_name)
        _pyttsx3_save(text, wav_path)
        if os.path.exists(wav_path) and os.path.getsize(wav_path) > 0:
            _LAST_ERROR = ""
            _LAST_BACKEND = "pyttsx3"
            return f"/static/tts/{wav_name}"
        reasons.append("pyttsx3：生成了空文件")
    except Exception as exc:                           # noqa: BLE001
        reasons.append(_explain("pyttsx3", str(exc)))

    _LAST_ERROR = " ｜ ".join(reasons)
    _LAST_BACKEND = ""
    print(f"[TTS] 这次没出声，三个后端都失败了 → {_LAST_ERROR}")
    return None


if __name__ == "__main__":
    print("TTS 可用:", available())
    print("生成:", synthesize("嗯，我在听。今天发生什么了？", 0.9, -1.0))
