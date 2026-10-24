"""
演示兜底缓存自检  Owner: B

回答一个问题：**如果现在断网，演示那几句台词还能不能正常演出？**

它不需要启动服务，直接调用认知层验证四件事：
  1. 缓存文件存在、有几条
  2. 每一条台词都能命中（包括 ASR 会加句号的那种变体）
  3. 命中的回复和预置音频都在
  4. 音频文件真的还在磁盘上（缓存被清掉的话，声音就没了）

用法（项目根目录）：
    python experiments/test_fallback.py              # 全部检查
    python experiments/test_fallback.py --verbose    # 顺带打印每条回复
"""
from __future__ import annotations

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

CACHE_FILE = os.path.join(REPO_ROOT, "data", "demo_cache.json")
TTS_DIR = os.path.join(REPO_ROOT, "src", "presentation", "static", "tts")


def asr_variants(text: str) -> list[str]:
    """模拟语音识别可能给出的形态：加句号、全角转半角逗号、多余空格、漏字。"""
    variants = [
        text,
        text + "。",                          # ASR 几乎一定会在末尾加句号
        text.replace("，", ",") + "。",         # ASR 有时输出半角逗号
        " " + text + "？",                     # 前后空格 + 别的标点
    ]
    if len(text) > 8:
        # ASR 偶尔漏字/多字：只差一个字的句子必须还能命中（靠相似度兜底）
        variants.append(text[:4] + text[5:])
    return variants


# 实测到的真实同音错字（base 模型把「交」听成「教」）。
# 这类错字在线模式下模型能自己懂，但断网模式依赖缓存，必须也能命中。
HOMOPHONE_CASES = [
    ("明天要教的东西还没做完，越想越睡不着", "明天要交的东西还没做完，越想越睡不着"),
    ("第三轮被问到一个项目细节，我脑子一下就空了，卡了十几秒", None),
]


def main() -> int:
    ap = argparse.ArgumentParser(description="演示兜底缓存自检")
    ap.add_argument("--verbose", action="store_true", help="打印每条回复内容")
    args = ap.parse_args()

    print("=" * 84)
    print(" 演示兜底缓存自检 —— 模拟「现在断网」")
    print("=" * 84)

    # 1. 缓存文件
    if not os.path.exists(CACHE_FILE):
        print(f"❌ 没有缓存文件：{CACHE_FILE}")
        print("   先生成： python experiments/prewarm_demo --file docs/演示脚本.txt")
        return 1
    with open(CACHE_FILE, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    entries = payload.get("entries") or {}
    print(f"✅ 缓存文件存在（生成于 {payload.get('generated_at', '?')}）")
    print(f"   条数：{len(entries)}")
    if not entries:
        print("❌ 缓存是空的，断网时会全部退回固定模板")
        return 1

    # 2. 强制断网模式验证命中
    os.environ["DEMO_FALLBACK"] = "1"
    from src.cognition import agent  # noqa: PLC0415  必须在设好环境变量之后导入/调用

    hits = 0
    total = 0
    audio_missing = []
    print()
    print("-" * 84)
    for text, entry in entries.items():
        print(f"台词：{text}")
        for variant in asr_variants(text):
            total += 1
            _p, r = agent.respond(f"tb-{total}", variant)
            src = (r.debug or {}).get("fallback_source")
            ok = src == "demo_cache"
            if ok:
                hits += 1
            mark = "✅" if ok else "❌"
            kind = "原文" if variant == text else ("ASR变体" if variant.endswith("。") and "，" in variant
                                                   else "变体")
            print(f"   {mark} {kind:<8} {variant!r} → {src or '未命中'}")
            if args.verbose and ok:
                print(f"      回复：{r.reply_text}")
        audio = entry.get("audio_url") or ""
        if audio:
            path = os.path.join(TTS_DIR, os.path.basename(audio))
            if not os.path.exists(path) or os.path.getsize(path) < 1000:
                audio_missing.append((text, audio))
        else:
            audio_missing.append((text, "（无音频）"))
        print()

    # 3. 不在缓存里的输入应退到固定模板（保证不崩）
    _p, r = agent.respond("tb-miss", "我今天想吃火锅")
    miss_ok = (r.debug or {}).get("fallback_source") == "mock"
    print(f"{'✅' if miss_ok else '❌'} 非预置输入正常退回固定模板："
          f"{(r.debug or {}).get('fallback_source')} → {r.reply_text}")

    # 3.5 真实同音错字：语音识别听错一个字，也要能命中缓存
    print()
    homo_ok = True
    for i, (said, expect) in enumerate(HOMOPHONE_CASES):
        _p, r = agent.respond(f"tb-homo-{i}", said)
        src = (r.debug or {}).get("fallback_source")
        ok = src == "demo_cache"
        homo_ok = homo_ok and ok
        print(f"{'✅' if ok else '❌'} 同音错字 {said[:16]}… → {src or '未命中'}")

    # 4. 音频文件
    print()
    if audio_missing:
        print(f"❌ {len(audio_missing)} 条音频缺失（断网时这几句会没声音）：")
        for t, a in audio_missing:
            print(f"   {t} → {a}")
    else:
        print(f"✅ 全部 {len(entries)} 条的预置音频都在磁盘上")

    # 结论
    print()
    print("-" * 84)
    rate = hits / total * 100 if total else 0
    ok_all = (hits == total) and not audio_missing and miss_ok and homo_ok
    print(f" 命中率：{hits}/{total} = {rate:.0f}%")
    if ok_all:
        print(" 结论：断网也能正常演示这几句台词 ✅")
    else:
        print(" 结论：还有问题，见上面 ❌ 的行")
        if hits < total:
            print("       命中率不到 100% 通常是标点差异 → 检查 agent._norm_text")
    print("-" * 84)
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
