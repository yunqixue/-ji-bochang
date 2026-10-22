"""
感知层：语音识别（ASR）。  Owner: B

设计要点（三天冲刺）：
  1. faster-whisper 本地跑，演示现场断网也能用
  2. 懒加载：第一次调用才下载/加载模型，服务启动不被拖慢
  3. 没装依赖时**不要崩**，抛一个带人话说明的异常，让上层降级到打字输入

用法：
    from src.perception.asr import transcribe, available
    text = transcribe(webm_bytes)
"""
from __future__ import annotations

import io
import os
import tempfile
import time
from typing import Optional

_MODEL = None
_MODEL_SIZE = os.getenv("ASR_MODEL_SIZE", "small")   # tiny / base / small / medium

# 中文识别的关键技巧：给一个 initial_prompt，whisper 会输出更自然的书面/口语表达，
# 标点更准、少出现"嗯嗯啊啊"的重复。改这句能明显提升中文效果。
ZH_INITIAL_PROMPT = os.getenv(
    "ASR_INITIAL_PROMPT",
    "以下是普通话的日常对话，说话人情绪比较低落，语气比较随意。",
)


def available() -> bool:
    """依赖装了没（没装就让前端提示用打字）。"""
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception:
        return False


def _get_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        # 首次运行会自动下载模型（small 约 500MB），演示前务必先跑一次！
        _MODEL = WhisperModel(_MODEL_SIZE, device="cpu", compute_type="int8")
    return _MODEL


def transcribe(audio_bytes: bytes, language: str = "zh") -> str:
    """把录音（webm/opus/wav 都行）转成文字。

    失败时抛 RuntimeError，message 是可以直接给用户看的中文。
    """
    if not audio_bytes:
        raise RuntimeError("录音是空的，再说一次试试？")
    if not available():
        raise RuntimeError("语音识别没装好（缺 faster-whisper），先用打字吧")

    try:
        model = _get_model()
        audio = io.BytesIO(audio_bytes)          # faster-whisper 用 av 解码，不需要 ffmpeg
        started = time.perf_counter()
        segments, info = model.transcribe(
            audio,
            language=language,
            beam_size=1,                 # 演示优先速度；要准可改 5
            vad_filter=True,             # 掐掉静音，减少"幻觉出话"
            condition_on_previous_text=False,
            initial_prompt=ZH_INITIAL_PROMPT if language == "zh" else None,
        )
        text = "".join(seg.text for seg in segments).strip()
        elapsed = time.perf_counter() - started
        if not text:
            raise RuntimeError("没听清，再说一次试试？")
        # 耗时日志：B 调 ASR 时就看这一行（音频几秒、识别几秒）
        try:
            print(f"[ASR] 音频 {info.duration:.1f}s → 识别 {elapsed:.1f}s "
                  f"(语言 {info.language} 置信度 {info.language_probability:.2f})")
        except Exception:
            pass
        return text
    except RuntimeError:
        raise
    except Exception as exc:                    # noqa: BLE001
        raise RuntimeError(f"语音识别出错：{exc}") from exc


def transcribe_file(path: str, language: str = "zh") -> str:
    """调试用：直接转一个本地音频文件。"""
    with open(path, "rb") as fh:
        return transcribe(fh.read(), language=language)


if __name__ == "__main__":
    # 自测：python -m src.perception.asr <某个音频文件>
    import sys
    if len(sys.argv) > 1:
        print(transcribe_file(sys.argv[1]))
    else:
        print("可用:", available(), "| 模型:", _MODEL_SIZE)
