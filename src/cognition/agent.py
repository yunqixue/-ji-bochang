"""
认知模块：情绪判断 + 人设对话 + 多轮记忆。  Owner: B

一次 LLM 调用同时产出「情绪」和「回复」，三天内这是唯一划算的做法（不训练情绪模型）。

对外只有一个函数：
    perception, response = respond(session_id, text, modality="text")

没有 API Key 时自动进入 mock 模式（关键词判情绪 + 固定回复），
这样 C 的前端可以立刻联调，不用等 B 配好 Key。
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from src.shared.contracts import (
    EMOTION_VOICE,
    EMOTIONS,
    CognitionResponse,
    PerceptionResult,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROMPT_FILE = os.path.join(REPO_ROOT, "assets", "prompts", "system_prompt.txt")
# 本地「话术库」：按情绪给模型的倾听要点（skills 的离线替代，存在就注入，不存在不影响）
EMOTION_GUIDE_FILE = os.path.join(REPO_ROOT, "assets", "prompts", "emotion_guide.txt")

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
{"emotion": "neutral|happy|sad|anxious|angry|surprised", "intensity": 0.0~1.0, "valence": -1.0~1.0, "arousal": 0.0~1.0, "reply": "你的回复"}
- emotion 是**用户**此刻的情绪；intensity 是情绪强度。
- valence 是用户心情好坏：-1 最差 ~ 1 最好（难过/生气给负数，开心给正数）。
- arousal 是用户激动程度：0 很平静 ~ 1 很激动（惊讶/生气偏高，平静偏低）。
- 写 reply 之前，先在脑子里想清楚「他现在是什么处境、什么心情」，再落笔。
- reply 符合你的人设，最多三句、40 字以内。
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


def _recent_distress(mem: Dict[str, Any], window: int = 3) -> bool:
    """最近几轮里对方有没有说过难过/焦虑的事（用于「情绪余温」）。"""
    for turn in (mem.get("turns") or [])[-window:]:
        if turn.get("emotion") in ("sad", "anxious", "angry"):
            return True
    return False


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


# 固定模板回复定义见下方 _mock_reply / MOCK_REPLIES（每个情绪多条变体 + 关键词嵌位）


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


# ---------------- 固定模板回复（最后一层兜底）----------------
# 这一层只在「模型不可用 + 预置缓存没命中」时用到。
# 早期每个情绪只有一句固定台词，反复念会让人立刻觉得"这是个死板的东西"。
# 现在改成：每个情绪多条变体随机选 + 把用户原话里的关键词嵌进去（{kw}），
# 同样的情绪也不至于每次一模一样，而且能接上对方刚说的话。
MOCK_REPLIES: Dict[str, List[str]] = {
    "sad": [
        "哎…{kw}这事，听着就挺难受的。是今天发生的吗？",
        "「{kw}」…嗯，我听着呢。你当时什么感觉？",
        "这个真挺磨人的。你现在最想说的是哪一句？",
        "嗯…心里堵着的时候，说出来会松一点。要说说吗？",
    ],
    "anxious": [
        "这么悬着，脑子肯定停不下来。{kw}那块最难的是哪一步？",
        "嗯…越想越睡不着的那种感觉，我懂。先挑最小的一件说说？",
        "你担心的事，最坏会到什么程度？", 
        "那现在有没有哪一件是你能先放下的？",
    ],
    "angry": [
        "这事儿换我也得气。{kw}当时是怎么说的？",
        "哎…被人这么对待确实憋屈。后来呢？",
        "你生气的点，是被冤枉，还是没人站你这边？",
    ],
    "happy": [
        "哎这个听着真好。{kw}…后来呢？",
        "哈哈，那确实值得高兴。多讲点？",
        "听起来你今天挺顺的呀。最开心的是哪一刻？",
    ],
    "surprised": [
        "真的假的？那你当时什么反应？",
        "这么突然…{kw}之前完全没迹象吗？",
        "我也有点意外。你现在是高兴多一点，还是懵多一点？",
    ],
    "neutral": [
        "嗯，{kw}…然后呢？",
        "我在听。你接着说。",
        "哦这样啊。那你现在打算怎么办？",
    ],
}

_KEY_FILLERS = [
    "我今天", "我今天其实", "今天", "感觉", "觉得", "真的", "其实", "有点", "挺",
    "特别", "非常", "还是", "就是", "然后", "所以", "因为", "而且", "但是",
    "我", "你", "他", "她", "的", "了", "呢", "啊", "吧", "呀", "吗", "着", "过",
    "是", "在", "也", "都", "就", "还", "又", "很", "太", "不", "没", "有",
]


def _key_phrase(text: str, limit: int = 8) -> str:
    """从用户的话里抠出一小段可以嵌进模板的关键词，让模板回复显得"有在听"。

    纯规则：去标点 → 去掉常见虚词 → 取最长的一段 → 截断。
    抠不出来就返回空字符串（模板里的 {kw} 会被整体去掉）。
    """
    if not text:
        return ""
    s = _norm_text(text)
    for ch in ",.!?;:\"'()[]{}<>、~·—-":
        s = s.replace(ch, " ")
    for w in _KEY_FILLERS:
        s = s.replace(w, " ")
    chunks = [c.strip() for c in s.split() if len(c.strip()) >= 2]
    if not chunks:
        return ""
    best = max(chunks, key=len)
    return best[:limit]


def _mock_reply(emotion: str, text: str) -> str:
    """挑一条变体，并把关键词嵌进去；长度控制在一句话能念完。"""
    variants = MOCK_REPLIES.get(emotion) or MOCK_REPLIES["neutral"]
    tpl = random.choice(variants)
    kw = _key_phrase(text)
    if "{kw}" in tpl:
        if not kw:
            # 抠不出来就换一条不需要关键词的
            plain = [v for v in variants if "{kw}" not in v]
            tpl = random.choice(plain) if plain else tpl.replace("{kw}", "你说的这个")
        else:
            tpl = tpl.replace("{kw}", kw)
    return tpl[:60]


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


def _web_search(query: str, count: int = 3) -> str:
    """调 DeepSeek 网页搜索（POST /v1/tools/search），返回给模型读的一段摘要文本。

    只在 WEB_SEARCH=1 时调用；失败抛异常，由调用方兜住（搜索失败不该打断聊天）。
    """
    key = _load_api_key()
    if not key:
        return ""
    base = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    url = base + "/v1/tools/search"
    payload = json.dumps({
        "query": (query or "")[:128],
        "ori_question": (query or "")[:128],
        "count": count,
        "need_content": False,
    }).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + key},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    results = data.get("results") or []
    blocks = []
    for r in results[:count]:
        title = (r.get("title") or "").strip()
        summary = (r.get("summary") or r.get("snippet") or "").strip()
        if title and summary:
            blocks.append(f"- {title}：{summary}")
    if not blocks:
        return ""
    return (
        "【下面是刚联网搜到的资料。请用你自己的、简单的话说给对方听，"
        "不要只说「这个我不懂」；如果这些资料和当前聊天无关，就忽略它。】\n"
        + "\n".join(blocks)
    )


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


def _emotion_guide() -> str:
    """读本地话术库（assets/prompts/emotion_guide.txt），按情绪给模型倾听要点。"""
    if os.path.exists(EMOTION_GUIDE_FILE):
        try:
            with open(EMOTION_GUIDE_FILE, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            if content:
                return content
        except Exception:
            pass
    return ""


def _system_prompt() -> str:
    parts = []
    if os.path.exists(PROMPT_FILE):
        try:
            with open(PROMPT_FILE, "r", encoding="utf-8") as fh:
                content = fh.read().strip()
            if content:
                parts.append(content)
        except Exception:
            pass
    if not parts:
        parts.append(FALLBACK_PROMPT)
    guide = _emotion_guide()
    if guide:
        parts.append(guide)
    parts.append(JSON_INSTRUCTION)
    return "\n\n".join(parts)


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
    """按用户原话找预置回复。

    先精确匹配；不中再按相似度兜底。为什么要兜底：语音识别会出现同音错字，
    实测 base 模型把「明天要交的东西还没做完」识别成「明天要教的东西还没做完」——
    只差一个字，精确匹配就落空，断网演示会掉到固定模板，一眼看出是假的。
    相似度阈值 0.75：同音错字通常 >0.9，不同句子远低于 0.75。
    """
    cache = _load_demo_cache()
    if not cache or not text:
        return None
    key = _norm_text(text)
    for raw, entry in cache.items():
        if _norm_text(raw) == key:
            return entry

    best_entry: Optional[Dict[str, Any]] = None
    best_ratio = 0.0
    for raw, entry in cache.items():
        ratio = difflib.SequenceMatcher(None, key, _norm_text(raw)).ratio()
        if ratio > best_ratio:
            best_ratio, best_entry = ratio, entry
    if best_entry is not None and best_ratio >= 0.75:
        return best_entry
    return None


def _sim(a: str, b: str) -> float:
    """两句归一化后的相似度（0~1）。用来发现"对方又说了同一句 / 自己又回了同一句"。"""
    a, b = _norm_text(a), _norm_text(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _build_messages(mem: Dict[str, Any], text: str, repeat_input: bool = False,
                    repeat_streak: int = 0, avoid_reply: str = "") -> List[Dict[str, str]]:
    """组装消息。

    ★ 关键坑：不能把历史回复当成 assistant 消息塞回去。
      因为历史里存的是纯文本回复，模型看到"自己上一轮输出的是纯文本"，
      就会模仿纯文本、不再输出 JSON —— 表现为「第 1 轮正常，第 2 轮开始悄悄降级成 mock」。
      所以历史一律放进 system，并明确禁止模仿其格式。

    repeat_input:  对方这次说的和上一句几乎一样。
    repeat_streak: 连续重复了几次（1 = 刚重复一次，2+ = 已经重复好几遍）。
    avoid_reply:   上一次生成的回复和前面撞了，重试时要显式避开它。
    """
    parts: List[str] = [_system_prompt()]

    if mem.get("summary"):
        parts.append(f"[更早聊过的事]\n{mem['summary']}")

    if mem.get("turns"):
        lines = []
        for turn in mem["turns"][-MAX_TURNS:]:
            lines.append(f"用户：{turn['user']}\n你：{turn['assistant']}")
        parts.append("[最近的对话，仅作上下文参考]\n" + "\n".join(lines))

    if repeat_input and repeat_streak <= 1:
        # 刚重复一次：点出来是自然的，像真人会说"你刚说过这句"
        parts.append(
            "★ 对方这次把同一句话又说了一遍。"
            "不要再用上次那套回应（不许重复自己说过的话），"
            "可以温和地点出来（「你刚说过这句，是不是还在想这个呀」），"
            "然后换一个更具体的方向往下问。"
        )
    elif repeat_input:
        # 连续重复好几遍：再点出来就像在指责了，必须换个说法继续陪着
        parts.append(
            f"★ 同一句话对方已经连着说了 {repeat_streak + 1} 遍。"
            "**不要再提「你刚说过」「你说了好几遍」这类话** —— 说多了像在指责。"
            "也不许再追问同一件事的细节（已经问过两轮了）。"
            "这一轮这样做：先用一句很短的话表示你还在听（比如「嗯，我听着呢」），"
            "然后二选一 —— 要么给一个**新的角度**接着这件事（比如「是不是到现在还没缓过来」），"
            "要么把话头**轻轻挪一点**（问问 ta 现在在干嘛、吃饭了没、累不累）。"
            "★ 另外：**不许再用「糯米/奶奶」这类你自己的小事来转移话题**，"
            "同一个招连续用会显得你在敷衍。你自己的小事整段对话里最多提一次；"
            "**开口那句也不要每轮都一样**（别连着几轮都用「嗯，我听着呢」开头的同一句）。"
        )

    if avoid_reply:
        parts.append(
            f"★ 你刚才想说的「{avoid_reply}」和前面已经说过的话太像了，"
            "换一种完全不同的说法，或者问一个不一样的问题。"
        )

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

    emotion, intensity, reply = "neutral", 0.5, _mock_reply("neutral", "")
    used_llm = False
    llm_error = ""
    cached_audio = ""
    fallback_source = ""
    model_valence: Optional[float] = None
    model_arousal: Optional[float] = None

    # DEMO_FALLBACK=1 时故意不连模型：用来演练「现场断网」，也用来验证兜底链路。
    offline = os.getenv("DEMO_FALLBACK") == "1"
    client = None if offline else _build_client()

    repeat_input = False
    repeat_streak = 0
    repeat_fixed = False
    repeat_score = 0.0
    if client is not None and text:
        # 对方把同一句话又（又又）说了一遍？
        for turn in reversed(mem.get("turns") or []):
            if _sim(turn["user"], text) >= 0.8:
                repeat_streak += 1
            else:
                break
        repeat_input = repeat_streak >= 1
        if repeat_input:
            print(f"[LLM] 同一句已连说 {repeat_streak + 1} 遍，本轮要求换方向")
        previous_replies = [t["assistant"] for t in (mem.get("turns") or [])][-3:]

        # 联网搜索：WEB_SEARCH=1 时，每轮先搜一次、把结果喂给模型（失败不打断聊天）
        web_context = ""
        if os.getenv("WEB_SEARCH") == "1":
            try:
                web_context = _web_search(text)
            except Exception as exc:                     # noqa: BLE001
                print(f"[WEB] 搜索失败：{type(exc).__name__}: {exc}")

        def _ask(avoid: str) -> Dict[str, Any]:
            """问一次模型；网络/格式失败重试一次。avoid 非空时要求避开那句话。"""
            msgs = _build_messages(mem, text, repeat_input=repeat_input,
                                   repeat_streak=repeat_streak, avoid_reply=avoid)
            if web_context:
                msgs[0]["content"] += "\n\n" + web_context
            err = ""
            for attempt in range(2):
                try:
                    resp = client.chat.completions.create(
                        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                        messages=msgs,
                        # 演示时可以调低（0.3）让回复更稳定、更容易命中 TTS 缓存
                        temperature=float(os.getenv("DEEPSEEK_TEMPERATURE", "0.8")),
                        max_tokens=200,
                        response_format={"type": "json_object"},
                    )
                    d = _parse_json(resp.choices[0].message.content or "") or {}
                    if d.get("reply"):
                        return d
                    err = "模型返回里没有 reply 字段"
                except Exception as exc:                 # noqa: BLE001
                    err = f"{type(exc).__name__}: {exc}"[:160]
                    if attempt == 0:
                        time.sleep(0.3)
            raise ValueError(err or "模型没有返回有效内容")

        try:
            data: Dict[str, Any] = _ask("")
            first_reply = str(data.get("reply", "")).strip()

            # ★ 防重复：实测用户把同一句话连说两遍时，模型会一字不差地再回一遍，
            #   看起来像复读机。这里检测"和前面 3 句里任何一句几乎一样"，命中就带着
            #   "换种说法"再问一次，取更像样的那个。只多一次调用，且只在撞车时发生。
            repeat_score = max([_sim(first_reply, p) for p in previous_replies] or [0.0])
            if repeat_score >= 0.85:
                try:
                    data2 = _ask(first_reply)
                    second_reply = str(data2.get("reply", "")).strip()
                    if second_reply and _sim(second_reply, first_reply) < repeat_score:
                        data = data2
                        repeat_fixed = True
                        repeat_score = max([_sim(second_reply, p) for p in previous_replies] or [0.0])
                        print(f"[LLM] 检测到自己要重复（{repeat_score:.2f}），已换一种说法")
                except Exception as exc:                 # noqa: BLE001
                    print(f"[LLM] 防重复重试失败，沿用原回复：{type(exc).__name__}: {exc}")

            emotion = str(data.get("emotion", "neutral")).strip().lower()
            reply = str(data.get("reply", "")).strip()
            intensity = float(data.get("intensity", 0.6))
            # 模型直接判断的效价/唤醒度（正确读取感受的核心）；没给或不是数字就留 None，后面退回映射表
            try:
                model_valence = float(data.get("valence"))
            except Exception:
                model_valence = None
            try:
                model_arousal = float(data.get("arousal"))
            except Exception:
                model_arousal = None
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
            reply = str(cached.get("reply") or "").strip() or _mock_reply("neutral", text)
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
            reply = _mock_reply(emotion, text)
            fallback_source = "mock"
            if not offline:
                print(f"[LLM] 已降级为固定模板：{llm_error[:80]}")

    # 情绪取值归一
    if emotion not in EMOTIONS:
        emotion = "neutral"
    intensity = max(0.0, min(1.0, float(intensity)))

    # 用户情绪 → 效价/唤醒度：优先用模型直接判断的，没有才用粗映射
    valence_map = {"happy": 0.7, "surprised": 0.2, "neutral": 0.0, "anxious": -0.4, "sad": -0.6, "angry": -0.5}
    arousal_map = {"happy": 0.7, "surprised": 0.8, "neutral": 0.4, "anxious": 0.7, "sad": 0.3, "angry": 0.8}
    valence = model_valence if model_valence is not None else valence_map.get(emotion, 0.0)
    valence = max(-1.0, min(1.0, valence))
    arousal = model_arousal if model_arousal is not None else arousal_map.get(emotion, 0.5)
    arousal = max(0.0, min(1.0, arousal))

    perception = PerceptionResult(
        text=text,
        emotion_label=emotion,
        emotion_score=round(intensity, 2),
        valence=round(valence, 2),
        arousal=round(arousal, 2),
        modality=modality,
        raw={"used_llm": used_llm},
    )

    # 智能体自己的表情：对方难过/焦虑时用 empathic 共情
    target = "empathic" if emotion in ("sad", "anxious") else emotion
    # 情绪余温：这一句本身没带情绪（比如「你还记得我说过什么吗」会被判成 neutral），
    # 但刚才几轮对方一直在说难过的事 —— 这时把脸切回"平常"会显得没在听。
    # 只影响表情/语调，不改 perception 里判定的用户情绪。
    if target == "neutral" and _recent_distress(mem):
        target = "empathic"
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
            # 防复读：这一轮对方是否重复了上一句 / 是否检测到自己在重复并救回来了
            "repeat_input": repeat_input,
            "repeat_fixed": repeat_fixed,
            "repeat_score": round(repeat_score, 2),
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
