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
import time
from typing import Optional

# 必须在 import faster_whisper / huggingface_hub 之前设好缓存与镜像：
#   1) HF_HOME 默认落在 C:\Users\<你>\.cache\huggingface，某些受限环境写不进去（实测 WinError 5），
#      而且模型 150~500MB 放在用户目录也不方便共享排查。统一放到项目 data/models/hf（已 gitignore）。
#   2) HF_ENDPOINT 走国内镜像，否则 huggingface.co 经常连不上，模型下不下来。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("HF_HOME", os.path.join(_REPO_ROOT, "data", "models", "hf"))
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

_MODEL = None
# 默认 base：和 experiments/download_asr_model.py 的默认值保持一致（约 150MB，演示够用）。
# 原来这里写的是 small，但下载脚本默认下 base —— 结果本地有模型也判成"没下载"，
# 真到演示现场会去联网拉 500MB。两边必须对齐，改这里记得同时改下载脚本。
_MODEL_SIZE = os.getenv("ASR_MODEL_SIZE", "base")   # tiny / base / small / medium
_MODEL_FILES = ["model.bin", "vocabulary.txt", "tokenizer.json", "config.json"]

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


def _dir_ready(d: str) -> bool:
    """这个目录里的模型文件齐了没（model.bin + vocabulary.txt + tokenizer.json + config.json）。"""
    return os.path.isdir(d) and all(
        os.path.exists(os.path.join(d, f)) and os.path.getsize(os.path.join(d, f)) > 100
        for f in _MODEL_FILES
    )


def local_model_dir() -> str:
    """本项目自己的模型目录：data/models/faster-whisper-<尺寸>/

    找不到指定尺寸时，退回用项目里已经下好的任意尺寸 ——
    宁可精度差一点，也不要在演示现场去联网下几百 MB。
    """
    want = os.path.join(_REPO_ROOT, "data", "models", f"faster-whisper-{_MODEL_SIZE}")
    if _dir_ready(want):
        return want
    parent = os.path.join(_REPO_ROOT, "data", "models")
    if os.path.isdir(parent):
        for name in sorted(os.listdir(parent)):
            if name.startswith("faster-whisper-"):
                cand = os.path.join(parent, name)
                if _dir_ready(cand):
                    return cand
    return want


def model_ready() -> bool:
    """本地模型文件齐了没（会自动认项目里已有的任意尺寸）。"""
    return _dir_ready(local_model_dir())


def _get_model():
    global _MODEL
    if _MODEL is None:
        from faster_whisper import WhisperModel
        # 优先用项目内的本地模型目录：不依赖 HuggingFace 缓存、不受用户目录权限限制，
        # 队友只要把 data/models/faster-whisper-<尺寸>/ 拷过来就能用。
        if model_ready():
            _MODEL = WhisperModel(local_model_dir(), device="cpu", compute_type="int8")
        else:
            # 回退：让 faster-whisper 自己按名字去下载（首次约 150~500MB，演示前务必先跑一次）
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
