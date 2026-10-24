"""对话"人味"评测  Owner: B

用途：用户反馈「几乎每句都以问号结尾，像在面试」。这个脚本把这件事**量化**，
      改提示词前后各跑一次就能看出到底有没有变，而不是凭感觉说"好像好点了"。

测的都是单一对话指标：
    · 反问率      回复是否以问号结尾（真人聊天不会句句反问）
    · 每轮问句数  一轮里问了几个问题（连着问＝逼供）
    · 复述模板率  是否"复述他的话 + 啊…"开头（"面试没过啊…"这种模板）
    · 客服腔      命中"我理解""建议你""你可以试试"这类
    · 平均字数

用法（先确保服务在跑）：
    python experiments/eval_humanness.py
    python experiments/eval_humanness.py --base http://127.0.0.1:8000

注意：每条都用一个**全新会话**，避免多轮记忆干扰指标；最后单独跑一段 4 轮对话，
      看"连续几轮"会不会越来越像审问。
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid

sys.path.insert(0, ".")

from experiments.smoke_test import post_chat_multipart  # noqa: E402

# 单轮样本：覆盖倾诉 / 中性 / 提问 / 要建议 / 要分享 / 轻快 / 极短
PROBES = [
    "我今天面试没过",
    "今天天气不错",
    "我最近总觉得自己在原地踏步",
    "你能给我点建议吗",
    "我想让你分享一些你觉得好玩的经历",
    "今天跟朋友吃了顿火锅，挺开心的",
    "嗯",
    "我有点累",
    "我跟我妈吵架了，她根本不听我说",
    "明天要交的东西还没做完，越想越睡不着",
    "你是 AI 吗",
    "算了，没什么好说的",
]

# 连续 4 轮：看会不会越聊越像审问
CHAIN = [
    "我今天面试又没过，感觉自己挺没用的",
    "第三轮被问到一个项目细节，我脑子一下就空了",
    "嗯…可能我就是不适合这一行吧",
    "不知道，就是觉得很累",
]

CUSTOMER_SERVICE = ["我理解你的感受", "我理解您", "作为你的助手", "有什么可以帮你",
                    "建议你", "你可以试试", "希望对你有帮助", "希望能帮到你"]


def ends_with_question(text: str) -> bool:
    t = (text or "").rstrip()
    return bool(t) and t[-1] in "？?"


def count_questions(text: str) -> int:
    return (text or "").count("？") + (text or "").count("?")


def template_open(text: str, user_text: str) -> bool:
    """回复是不是"复述他的话 + 啊/呀…"这种模板开头。

    做法：回复开头 2~8 个字里，有连续 2 字以上出现在用户输入里，且紧跟"啊/呀/呢"。
    """
    t = (text or "").strip()
    m = re.match(r"^(.{2,8}?)(啊|呀|呢)", t)
    if not m:
        return False
    frag = m.group(1)
    for i in range(len(frag) - 1):
        if frag[i:i + 2] in (user_text or ""):
            return True
    return False


def metrics(replies: list[tuple[str, str]]) -> dict:
    n = len(replies)
    if n == 0:
        return {}
    return {
        "n": n,
        "反问率": sum(ends_with_question(r) for _, r in replies) / n,
        "每轮问句数": sum(count_questions(r) for _, r in replies) / n,
        "复述模板率": sum(template_open(r, u) for u, r in replies) / n,
        "客服腔率": sum(any(k in r for k in CUSTOMER_SERVICE) for _, r in replies) / n,
        "平均字数": sum(len(r) for _, r in replies) / n,
    }


def show(title: str, m: dict) -> None:
    print(f"\n{title}（{m['n']} 条）")
    print(f"  反问率      {m['反问率'] * 100:5.0f}%   ← 越低越不像面试官")
    print(f"  每轮问句数  {m['每轮问句数']:5.2f} 个  ← 超过 1.0 就是连珠炮")
    print(f"  复述模板率  {m['复述模板率'] * 100:5.0f}%   ← \"他说的话 + 啊…\" 这种公式开头")
    print(f"  客服腔率    {m['客服腔率'] * 100:5.0f}%")
    print(f"  平均字数    {m['平均字数']:5.1f} 字")


def main() -> int:
    ap = argparse.ArgumentParser(description="对话人味评测：反问率 / 问句数 / 模板化")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--verbose", action="store_true", help="打印每一条回复")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    print("=" * 82)
    print(" 对话人味评测（单轮样本，每条一个全新会话）")
    print("=" * 82)

    single: list[tuple[str, str]] = []
    for text in PROBES:
        code, data = post_chat_multipart(base, "hum-" + uuid.uuid4().hex[:8], text)
        if code != 200:
            print(f"  ✗ {text[:16]} → HTTP {code}")
            continue
        reply = ((data.get("response") or {}).get("reply_text") or "").strip()
        single.append((text, reply))
        if args.verbose:
            print(f"  用户：{text}")
            print(f"  回复：{reply}  {'[问]' if ends_with_question(reply) else '[陈述]'}")
            print()

    show("单轮样本", metrics(single))

    print()
    print("=" * 82)
    print(" 连续 4 轮（看会不会越聊越像审问）")
    print("=" * 82)
    sid = "hchain-" + uuid.uuid4().hex[:8]
    chain: list[tuple[str, str]] = []
    for text in CHAIN:
        code, data = post_chat_multipart(base, sid, text)
        if code != 200:
            continue
        reply = ((data.get("response") or {}).get("reply_text") or "").strip()
        chain.append((text, reply))
        print(f"  用户：{text}")
        print(f"  回复：{reply}  {'[问]' if ends_with_question(reply) else '[陈述]'}")
    show("连续 4 轮", metrics(chain))

    print()
    print("-" * 82)
    print(" 怎么看结果：反问率 40–65% 最像真人（大概一半接话、一半反问）；")
    print(" 接近 100% 就是「每句都在问」，每轮问句数 >1 是连珠炮，复述模板率高会显得套路。")
    print("-" * 82)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
