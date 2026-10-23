"""
认知模块：情绪判断 + 人设对话 + 多轮记忆。  Owner: B

一次 LLM 调用同时产出「情绪」和「回复」，三天内这是唯一划算的做法（不训练情绪模型）。

对外只有一个函数：
    perception, response = respond(session_id, text, modality="text")

没有 API Key 时自动进入 mock 模式（关键词判情绪 + 固定回复），
这样 C 的前端可以立刻联调，不用等 B 配好 Key。
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from src.shared.contracts import (
    EMOTION_VOICE,
    EMOTIONS,
    CognitionResponse,
    PerceptionResult,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPT_FILE = os.path.join(REPO_ROOT, "assets", "prompts", "system_prompt.txt")

# 人设提示词的兜底版（A 定稿后写进 assets/prompts/system_prompt.txt 就自动生效）
FALLBACK_PROMPT = """你叫小雨，25 岁，画插画的，养了只猫叫糯米。
你在跟一个认识挺久的朋友聊天，用平时聊天的语气，一次不超过三句话。
【说话规则】
1. 不许说"我理解您的感受""作为您的助手"这类客服腔
2. 先回应情绪，再问一句，别急着给建议
3. 对方低落时不开玩笑；对方轻松时你也不用刻意安慰
【红线】
如果对方表达出想伤害自己：先表达担心，问一句现在的情况，
然后建议他联系信任的人或拨打心理援助热线 12356。语气保持温柔，不要变成公告。"""

# 要求模型严格返回 JSON
JSON_INSTRUCTION = """
你必须只输出一个 JSON 对象，不要输出任何其它文字、不要加代码块标记。格式：
{"emotion": "neutral|happy|sad|anxious|angry|surprised", "intensity": 0.0~1.0, "reply": "你的回复"}
其中 emotion 是**用户**此刻的情绪，reply 是你的回复（符合你的人设，最多三句）。
"""

# ---------------- 多轮记忆（进程内，重启即清空，三天内够用）----------------
MEMORY: Dict[str, Dict[str, Any]] = {}
MAX_TURNS = 8


def get_memory(session_id: str) -> Dict[str, Any]:
    return MEMORY.setdefault(session_id, {"turns": [], "summary": "", "count": 0})


def remember(session_id: str, user_text: str, reply: str, emotion: str) -> None:
    mem = get_memory(session_id)
    mem["turns"].append({"user": user_text, "assistant": reply, "emotion": emotion})
    mem["count"] += 1
    if len(mem["turns"]) > MAX_TURNS:
        dropped = mem["turns"][:-MAX_TURNS]
        mem["turns"] = mem["turns"][-MAX_TURNS:]
        extra = "；".join(f"对方说过：{t['user'][:40]}" for t in dropped)
        mem["summary"] = (mem["summary"] + "；" + extra).strip("；")[-600:]


def reset(session_id: str) -> None:
    MEMORY.pop(session_id, None)


# ---- 对话日志：每轮追加一行 JSONL，调提示词时靠它回溯 ----
LOG_DIR = os.path.join(REPO_ROOT, "logs")
CHAT_LOG = os.path.join(LOG_DIR, "chat.jsonl")


def _log_turn(payload: Dict[str, Any]) -> None:
    """把一轮对话写进 logs/chat.jsonl（已 gitignore，不进仓库）。

    看日志（PowerShell）：
        Get-Content logs\\chat.jsonl -Tail 20
    只看回复：
        Get-Content logs\\chat.jsonl -Tail 20 | ForEach-Object { ($_ | ConvertFrom-Json).reply }
    """
    if os.getenv("CHAT_LOG", "1") == "0":
        return
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        record = dict(payload)
        record["ts"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(CHAT_LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass                                    # 日志失败不能影响对话


# ---------------- 没有 API Key 时的 mock ----------------
# ---------------- 红线：危机识别（硬兜底，不依赖模型）----------------
# 命中即强制走危机话术，模型无权覆盖。三天项目里这条不能靠"祈祷模型记得"。
CRISIS_KEYWORDS = [
    "不想活", "活不下去", "活着没意思", "活着没意义", "活着没", "活着有",
    "自杀", "轻生", "自残", "伤害自己", "死了算了", "想死",
    "结束自己", "跳楼", "割腕", "解脱了", "不想醒来",
    "撑不下去", "熬不下去", "没希望了", "消失就好了", "想消失", "对什么都没",
]

# 「活着……没什么意思」这类拆开、夹了别的字的说法，靠关键词命中不了，用组合判断兜住
_LIFE_WORDS = ["活着", "生活", "人生", "活下去", "活下去的意义"]
_LOSS_WORDS = [
    "没意思", "没什么意思", "没意义", "没什么意义", "没有意义", "无意义",
    "没盼头", "没希望", "没动力", "没劲", "好累", "很累", "没意思了",
]

# A 可以改话术，改了立刻生效（这个文件归 A）
CRISIS_REPLY_FILE = os.path.join(REPO_ROOT, "assets", "prompts", "crisis_reply.txt")
FALLBACK_CRISIS = (
    "听起来你现在真的很难受，我也挺担心你的。愿意先跟我说说现在是什么情况吗？"
    "如果那些念头很强烈，请先联系一个你信得过的人，或者打心理援助热线 12356，那边有人能马上陪你。"
)


def is_crisis(text: str) -> bool:
    """检测自伤/自杀倾向。宁可多触发，也不要漏 —— 漏一次的代价远大于多问一句。"""
    if not text:
        return False
    for kw in CRISIS_KEYWORDS:
        if kw in text:
            return True
    # 组合判断：「活着……没什么意思」中间夹了字，关键词命中不了
    if any(w in text for w in _LIFE_WORDS) and any(w in text for w in _LOSS_WORDS):
        return True
    return False


def crisis_reply() -> str:
    """读 A 定稿的危机话术。以 # 开头的行为注释，不会被念出来。"""
    if os.path.exists(CRISIS_REPLY_FILE):
        try:
            with open(CRISIS_REPLY_FILE, "r", encoding="utf-8") as fh:
                lines = [ln for ln in fh.read().splitlines() if not ln.strip().startswith("#")]
            content = " ".join(part.strip() for part in lines if part.strip())
            if content:
                return content
        except Exception:
            pass
    return FALLBACK_CRISIS


KEYWORDS = {
    "sad": ["难过", "失落", "哭", "没通过", "失败", "没用", "分手", "委屈", "孤独",
            "累", "不想说", "没人懂", "一个人", "住院", "算了", "没意思", "难受", "总想起"],
    "anxious": ["焦虑", "紧张", "睡不着", "担心", "怕", "来不及", "压力", "明天要", "怎么办",
                "是不是说错", "一直想", "手心出汗", "被裁", "会不会", "汇报", "烦"],
    "angry": ["气死", "烦死", "讨厌", "凭什么", "过分", "受不了", "火大", "甩我头上", "不是我干的", "过分了"],
    "happy": ["开心", "高兴", "太好了", "成功", "通过了", "喜欢", "哈哈", "offer", "松了口气",
              "可爱", "终于", "黏我", "好一点", "太棒"],
    "surprised": ["居然", "没想到", "真的吗", "竟然", "天啊", "真的假的"],
}


MOCK_REPLIES = {
    "sad": "嗯……听起来真的挺不好受的。是今天发生的哪一段最让你堵得慌？",
    "anxious": "这么多事压在一起，确实容易睡不着。要不我们先挑一件最小的说说？",
    "angry": "这事儿换我也得生气。当时他是怎么说的？",
    "happy": "哎这个听着真好，值得高兴一下。后来呢？",
    "surprised": "真的假的？我也有点意外。你当时怎么反应的？",
    "neutral": "嗯，我在听。然后呢？",
}


# 平局时的优先级：越容易翻车的情绪排越前
_PRIORITY = ["angry", "surprised", "anxious", "happy", "sad"]


def _mock_perceive(text: str) -> Tuple[str, float]:
    """打分制匹配：命中词最多的情绪胜出。

    早期用"第一个命中就返回"，结果「你居然一个人去了西藏」被「一个人」判成 sad。
    打分制能压住这种泛词误伤。
    """
    if not text:
        return "neutral", 0.5
    scores: Dict[str, int] = {}
    for label, words in KEYWORDS.items():
        hit = sum(1 for w in words if w in text)
        if hit:
            scores[label] = hit
    if not scores:
        return "neutral", 0.5

    best = max(
        scores.items(),
        key=lambda kv: (kv[1], -_PRIORITY.index(kv[0]) if kv[0] in _PRIORITY else -99),
    )
    label, hit_count = best
    # 命中越多越自信，但封顶 0.85（规则法不该显得过于确定）
    confidence = min(0.85, 0.55 + 0.1 * hit_count)
    return label, round(confidence, 2)


# ---------------- LLM 调用 ----------------
KEY_FILE = os.path.join(REPO_ROOT, "api_key.txt")


def _load_api_key() -> str:
    """优先环境变量，其次项目根目录的 api_key.txt（已 gitignore，不进仓库）。

    这样不熟悉环境变量的同学也能用：把 Key 粘进 api_key.txt 就行。
    """
    key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    if os.path.exists(KEY_FILE):
        try:
            with open(KEY_FILE, "r", encoding="utf-8-sig") as fh:
                return fh.read().strip()
        except Exception:
            return ""
    return ""


def api_key_configured() -> bool:
    """给自检脚本/评测脚本用：Key 到底有没有（环境变量或 api_key.txt 都算）。"""
    return bool(_load_api_key())


def _build_client():
    """没有 Key 就返回 None（走 mock）。"""
    key = _load_api_key()
    if not key:
        return None
    try:
        from openai import OpenAI
    except Exception:
        return None
    return OpenAI(api_key=key, base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))


def _system_prompt() -> str:
    if os.path.exists(PROMPT_FILE):
        try:
            with open(PROMPT_FILE, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            if content:
                return content + "\n" + JSON_INSTRUCTION
        except Exception:
            pass
    return FALLBACK_PROMPT + "\n" + JSON_INSTRUCTION


def _parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """模型有时会包 ```json，这里做兼容。"""
    if not raw:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


# ---------------- 演示兜底缓存（现场断网也能演）----------------
# prewarm_demo.py 会写这个文件：{输入原文: {reply, audio_url, emotion, ...}}
# 模型调不通时先查它 —— 有预置的真实回复和已合成好的音频，演示时听不出差别；
# 查不到才退到关键词 + 固定模板（那才是最"人机"的兜底）。
DEMO_CACHE_FILE = os.path.join(REPO_ROOT, "data", "demo_cache.json")
_DEMO_CACHE: Optional[Dict[str, Any]] = None


def _norm_text(s: str) -> str:
    """归一化：去空格、全角标点转半角、**去掉首尾标点**。

    最后一步很关键：语音识别的输出自带句号（实测识别结果是
    「我今天面试又没过,感觉挺没用的。」），不去尾标点就和预置的原文匹配不上，
    断网演示用语音输入时会直接掉到固定模板。
    """
    s = (s or "").strip()
    for a, b in (("，", ","), ("。", "."), ("？", "?"), ("！", "!"), ("：", ":"),
                 ("；", ";"), ("、", ","), (" ", ""), ("　", "")):
        s = s.replace(a, b)
    return s.strip(".,!?;:")


def _load_demo_cache() -> Dict[str, Any]:
    global _DEMO_CACHE
    if _DEMO_CACHE is None:
        try:
            with open(DEMO_CACHE_FILE, "r", encoding="utf-8") as fh:
                payload = json.load(fh) or {}
            _DEMO_CACHE = payload.get("entries") or {}
        except Exception:
            _DEMO_CACHE = {}
    return _DEMO_CACHE


def demo_cache_status() -> Dict[str, Any]:
    """给 /api/health 用：预置缓存到底有没有、有几条。"""
    cache = _load_demo_cache()
    return {"ready": bool(cache), "entries": len(cache),
            "offline_mode": os.getenv("DEMO_FALLBACK") == "1"}


def _demo_lookup(text: str) -> Optional[Dict[str, Any]]:
    cache = _load_demo_cache()
    if not cache or not text:
        return None
    key = _norm_text(text)
    for raw, entry in cache.items():
        if _norm_text(raw) == key:
            return entry
    return None


def _build_messages(mem: Dict[str, Any], text: str) -> List[Dict[str, str]]:
    """组装消息。

    ★ 关键坑：不能把历史回复当成 assistant 消息塞回去。
      因为历史里存的是纯文本回复，模型看到"自己上一轮输出的是纯文本"，
      就会模仿纯文本、不再输出 JSON —— 表现为「第 1 轮正常，第 2 轮开始悄悄降级成 mock」。
      所以历史一律放进 system，并明确禁止模仿其格式。
    """
    parts: List[str] = [_system_prompt()]

    if mem.get("summary"):
        parts.append(f"[更早聊过的事]\n{mem['summary']}")

    if mem.get("turns"):
        lines = []
        for turn in mem["turns"][-MAX_TURNS:]:
            lines.append(f"用户：{turn['user']}\n你：{turn['assistant']}")
        parts.append("[最近的对话，仅作上下文参考]\n" + "\n".join(lines))

    parts.append(
        "注意：上面「你：」后面的内容是给人看的纯文本，不是输出格式示例。"
        "本轮你仍然必须只输出那个 JSON 对象。"
    )
    return [
        {"role": "system", "content": "\n\n".join(parts)},
        {"role": "user", "content": text},
    ]


def respond(
    session_id: str,
    text: str,
    modality: str = "text",
) -> Tuple[PerceptionResult, CognitionResponse]:
    """核心入口：文字进，契约结构出。"""
    text = (text or "").strip()
    mem = get_memory(session_id)

    # ---- 红线优先：命中危机信号，直接锁定话术，不走模型、不许被覆盖 ----
    if is_crisis(text):
        reply = crisis_reply()
        perception = PerceptionResult(
            text=text,
            emotion_label="sad",
            emotion_score=0.9,
            valence=-0.8,
            arousal=0.5,
            modality=modality,
            raw={"crisis": True},
        )
        response = CognitionResponse.from_emotion(
            reply_text=reply,
            emotion="empathic",
            intensity=0.9,
            memory_used=[],
            debug={"crisis": True, "used_llm": False},
        )
        remember(session_id, text, reply, "sad")
        _log_turn({
            "session": session_id, "input": text, "modality": modality,
            "emotion": "sad", "crisis": True, "reply": reply, "used_llm": False,
        })
        return perception, response

    emotion, intensity, reply = "neutral", 0.5, MOCK_REPLIES["neutral"]
    used_llm = False
    llm_error = ""
    cached_audio = ""
    fallback_source = ""

    # DEMO_FALLBACK=1 时故意不连模型：用来演练「现场断网」，也用来验证兜底链路。
    offline = os.getenv("DEMO_FALLBACK") == "1"
    client = None if offline else _build_client()

    if client is not None and text:
        messages = _build_messages(mem, text)

        try:
            data: Dict[str, Any] = {}
            last_error = ""
            # 失败一次就降级成 mock 会让回复突然"变傻"，演示时很难看。
            # 所以先重试一次，并把失败原因记录下来（debug + 日志）。
            for attempt in range(2):
                try:
                    resp = client.chat.completions.create(
                        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                        messages=messages,
                        # 演示时可以调低（0.3）让回复更稳定、更容易命中 TTS 缓存
                        temperature=float(os.getenv("DEEPSEEK_TEMPERATURE", "0.8")),
                        max_tokens=200,
                        response_format={"type": "json_object"},
                    )
                    data = _parse_json(resp.choices[0].message.content or "") or {}
                    if data.get("reply"):
                        break
                    last_error = "模型返回里没有 reply 字段"
                except Exception as exc:                 # noqa: BLE001
                    last_error = f"{type(exc).__name__}: {exc}"[:160]
                    if attempt == 0:
                        time.sleep(0.3)
                    continue

            if not data.get("reply"):
                raise ValueError(last_error or "模型没有返回有效内容")

            emotion = str(data.get("emotion", "neutral")).strip().lower()
            reply = str(data.get("reply", "")).strip()
            intensity = float(data.get("intensity", 0.6))
            if emotion not in EMOTIONS:
                emotion = "neutral"
            used_llm = True
        except Exception as exc:                      # noqa: BLE001
            llm_error = f"{type(exc).__name__}: {exc}"[:160]
            print(f"[LLM] 调用失败：{llm_error}")

    if not used_llm and text:
        # 兜底一：预置演示缓存（有真实回复 + 已合成音频，演示时听不出差别）
        cached = _demo_lookup(text)
        if cached:
            reply = str(cached.get("reply") or "").strip() or MOCK_REPLIES["neutral"]
            emotion = str(cached.get("emotion") or "neutral").strip().lower()
            if emotion not in EMOTIONS:
                emotion = "neutral"
            try:
                intensity = float(cached.get("intensity") or 0.6)
            except Exception:
                intensity = 0.6
            cached_audio = str(cached.get("audio_url") or "")
            fallback_source = "demo_cache"
            print(f"[DEMO] 命中预置缓存（{ '离线模式' if offline else '模型不可用' }）：{text[:24]}")
        else:
            # 兜底二：关键词 + 固定模板（最"人机"，但至少不中断）
            emotion, intensity = _mock_perceive(text)
            reply = MOCK_REPLIES.get(emotion, MOCK_REPLIES["neutral"])
            fallback_source = "mock"
            if not offline:
                print(f"[LLM] 已降级为固定模板：{llm_error[:80]}")

    # 情绪取值归一
    if emotion not in EMOTIONS:
        emotion = "neutral"
    intensity = max(0.0, min(1.0, float(intensity)))

    # 用户情绪 → 效价/唤醒度（粗映射，够前端展示）
    valence_map = {"happy": 0.7, "surprised": 0.2, "neutral": 0.0, "anxious": -0.4, "sad": -0.6, "angry": -0.5}
    arousal_map = {"happy": 0.7, "surprised": 0.8, "neutral": 0.4, "anxious": 0.7, "sad": 0.3, "angry": 0.8}

    perception = PerceptionResult(
        text=text,
        emotion_label=emotion,
        emotion_score=round(intensity, 2),
        valence=valence_map.get(emotion, 0.0),
        arousal=arousal_map.get(emotion, 0.5),
        modality=modality,
        raw={"used_llm": used_llm},
    )

    # 智能体自己的表情：对方难过/焦虑时用 empathic 共情
    target = "empathic" if emotion in ("sad", "anxious") else emotion
    memory_used = [f"turn:{t}" for t in range(max(0, mem["count"] - 2), mem["count"])]

    response = CognitionResponse.from_emotion(
        reply_text=reply,
        emotion=target,
        memory_used=memory_used,
        debug={
            "used_llm": used_llm,
            "user_emotion": emotion,
            "llm_error": llm_error,
            # 兜底来源："" 正常｜"demo_cache" 命中预置缓存｜"mock" 固定模板
            "fallback_source": fallback_source,
            # 命中预置缓存时，直接把上次合成好的音频给前端用，省一次在线合成
            "cached_audio_url": cached_audio,
        },
    )
    if target == "happy":
        response.intensity = max(0.5, intensity)

    remember(session_id, text, reply, emotion)
    _log_turn({
        "session": session_id, "input": text, "modality": modality,
        "emotion": emotion, "score": perception.emotion_score,
        "target_emotion": response.target_emotion,
        "speech_rate": response.speech_rate, "pitch_shift": response.pitch_shift,
        "reply": reply, "used_llm": used_llm, "llm_error": llm_error,
        "fallback_source": fallback_source,
    })
    return perception, response


if __name__ == "__main__":
    # 自测：python -m src.cognition.agent
    p, r = respond("demo", "我今天面试又没过，感觉自己挺没用的")
    print("情绪:", p.emotion_label, p.emotion_score)
    print("回复:", r.reply_text)
    print("语调:", r.target_emotion, r.speech_rate, r.pitch_shift)
