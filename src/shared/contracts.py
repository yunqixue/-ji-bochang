"""
契约数据结构 —— 三个人共用的唯一事实来源。

对应 docs/接口契约.md v0.3：
  PerceptionResult   感知 → 认知
  CognitionResponse  认知 → 表现
  AvatarState        前端形象状态

★ 只许加字段，不许改已有字段名（改了要三人同意并更新接口契约）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# ---- 情绪标签：三层 + 形象必须用同一套（接口契约 §4）----
EMOTIONS = ["neutral", "happy", "sad", "anxious", "angry", "surprised"]
TARGET_EMOTIONS = EMOTIONS + ["empathic"]

# ---- 情绪 → 语音参数（对应 assets/prompts/persona_v1.md 第五节）----
# edge-tts 用 rate 百分比和 pitch 赫兹，这里给的是契约里的乘数与半音
EMOTION_VOICE: Dict[str, Dict[str, float]] = {
    "sad":       {"speech_rate": 0.85, "pitch_shift": -2.0, "intensity": 0.7},
    "anxious":   {"speech_rate": 0.90, "pitch_shift": -1.0, "intensity": 0.6},
    "angry":     {"speech_rate": 0.90, "pitch_shift": -2.0, "intensity": 0.6},
    "happy":     {"speech_rate": 1.05, "pitch_shift": 2.0,  "intensity": 0.7},
    "surprised": {"speech_rate": 1.00, "pitch_shift": 1.0,  "intensity": 0.6},
    "neutral":   {"speech_rate": 1.00, "pitch_shift": 0.0,  "intensity": 0.5},
    "empathic":  {"speech_rate": 0.90, "pitch_shift": -1.0, "intensity": 0.7},
}

# ---- 情绪 → 形象图片（前端按此取 assets/images/expr_<label>.webp）----
def avatar_image_name(expression: str) -> str:
    if expression not in TARGET_EMOTIONS:
        expression = "neutral"
    return f"expr_{expression}.webp"


@dataclass
class PerceptionResult:
    """感知层输出。C 也可以直接用它塞 mock。"""

    text: str
    emotion_label: str = "neutral"
    emotion_score: float = 0.5
    valence: float = 0.0          # -1.0 负 ~ 1.0 正
    arousal: float = 0.5          # 0.0 平静 ~ 1.0 激动
    modality: str = "text"        # text | audio
    timestamp: float = field(default_factory=time.time)
    raw: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "PerceptionResult":
        d = dict(d or {})
        return PerceptionResult(
            text=d.get("text", ""),
            emotion_label=d.get("emotion_label", "neutral"),
            emotion_score=float(d.get("emotion_score", 0.5)),
            valence=float(d.get("valence", 0.0)),
            arousal=float(d.get("arousal", 0.5)),
            modality=d.get("modality", "text"),
            timestamp=float(d.get("timestamp", time.time())),
            raw=d.get("raw", {}),
        )


@dataclass
class CognitionResponse:
    """认知层输出（表现层 + 形象都靠它）。"""

    reply_text: str
    target_emotion: str = "empathic"
    intensity: float = 0.6
    speech_rate: float = 1.0
    pitch_shift: float = 0.0
    gesture: Optional[str] = None
    memory_used: List[str] = field(default_factory=list)
    debug: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_emotion(cls, reply_text: str, emotion: str, **kw: Any) -> "CognitionResponse":
        """按情绪自动带出语速/音高，B 不用自己算。"""
        voice = EMOTION_VOICE.get(emotion, EMOTION_VOICE["neutral"])
        return cls(
            reply_text=reply_text,
            target_emotion=emotion,
            intensity=kw.pop("intensity", voice["intensity"]),
            speech_rate=kw.pop("speech_rate", voice["speech_rate"]),
            pitch_shift=kw.pop("pitch_shift", voice["pitch_shift"]),
            **kw,
        )


@dataclass
class AvatarState:
    """给前端的形象指令。"""

    expression: str = "neutral"
    state: str = "idle"           # idle | listening | thinking | speaking

    def to_dict(self) -> Dict[str, Any]:
        return {"expression": self.expression, "state": self.state}


def error_payload(message: str, fallback_text: str = "嗯……我刚才好像没听清，你能再说一遍吗？") -> Dict[str, Any]:
    """统一的失败返回（接口契约 §1「失败要显式」）。"""
    return {
        "error": message,
        "reply_text": fallback_text,
        "avatar": {"expression": "empathic", "state": "idle"},
    }
