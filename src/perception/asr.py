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
from typing import Optional

_MODEL = None
_MODEL_SIZE = os.getenv("ASR_MODEL_SIZE", "small")   # tiny / base / small / medium


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
        segments, _info = model.transcribe(
            audio,
            language=language,
            beam_size=1,            # 演示优先速度
            vad_filter=True,        # 掐掉静音，减少幻觉
            condition_on_previous_text=False,
        )
        text = "".join(seg.text for seg in segments).strip()
        if not text:
            raise RuntimeError("没听清，再说一次试试？")
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
