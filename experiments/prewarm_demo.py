"""
演示预演 / 语音预热  Owner: B

为什么需要这个：
  edge-tts 走微软服务器，国内实测约 1/6 会连不上；而本机没有中文离线语音包，
  所以 TTS 失败就只能没声音。演示现场不能赌网络。

这个脚本做的事：
  把演示要说的每一句话，提前跑一遍完整链路（LLM 回复 + TTS 合成），
  音频就进了缓存。演示时同样的输入再跑一次，TTS 直接命中缓存（0.003s，不碰网络）。

用法（在项目根目录）：
    # 用内置的示例台词
    python -m experiments.prewarm_demo

    # 用 A 写的演示脚本（每行一句"用户会说的话"，空行和 # 开头忽略）
    python -m experiments.prewarm_demo --file docs/演示脚本.txt

    # 顺带把温度调低，让回复更稳定（更容易命中缓存）
    $env:DEEPSEEK_TEMPERATURE = "0.3"
    python -m experiments.prewarm_demo --file docs/演示脚本.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.cognition import agent  # noqa: E402
from src.presentation import tts  # noqa: E402

DEFAULT_LINES = [
    "我今天面试又没过，感觉挺没用的",
    "明天要交的东西还没做完，越想越睡不着",
    "跟你说完好像好一点了",
    "上次说的那个面试后来怎么样了",
]


def load_lines(path: str | None) -> list[str]:
    if not path:
        return DEFAULT_LINES
    full = path if os.path.isabs(path) else os.path.join(REPO_ROOT, path)
    if not os.path.exists(full):
        print(f"⚠️  找不到 {path}，改用内置示例台词。")
        return DEFAULT_LINES
    lines = []
    with open(full, "r", encoding="utf-8") as fh:
        for raw in fh:
            text = raw.strip()
            if text and not text.startswith("#"):
                lines.append(text)
    return lines or DEFAULT_LINES


def main() -> int:
    parser = argparse.ArgumentParser(description="演示预演：提前生成回复与语音缓存")
    parser.add_argument("--file", type=str, default=None, help="台词文件，每行一句用户会说的话")
    parser.add_argument("--session", type=str, default="prewarm", help="会话 id（同一会话能测多轮记忆）")
    args = parser.parse_args()

    if not agent.api_key_configured():
        print("❌ 没配 Key（api_key.txt 或 DEEPSEEK_API_KEY），先配好再预演。")
        return 1
    if not tts.available():
        print("❌ 没有可用的 TTS（edge-tts 未安装）。")
        return 1

    lines = load_lines(args.file)
    print(f"预演台词 {len(lines)} 句 ｜ temperature={os.getenv('DEEPSEEK_TEMPERATURE', '0.8')}")
    print("=" * 84)

    # 上一次的缓存：万一这次语音合成失败，就沿用上一次「回复+音频」这一对，
    # 不能因为一晚网络不好就把整张兜底表清空（演示前一天发生这个最致命）。
    cache_path = os.path.join(REPO_ROOT, "data", "demo_cache.json")
    tts_dir = os.path.join(REPO_ROOT, "src", "presentation", "static", "tts")
    old_entries: dict[str, dict] = {}
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                old_entries = (json.load(fh) or {}).get("entries") or {}
        except Exception:
            old_entries = {}

    agent.reset(args.session)
    ok_tts = 0
    reused = 0
    report_lines = ["# 演示预演记录", "", "由 `python -m experiments.prewarm_demo` 生成。", ""]
    # 同时生成「演示兜底缓存」：模型调不通 / 现场断网时，agent 会先查这张表，
    # 用这里存下的真实回复和已合成音频顶上，演示时听不出差别。
    cache_entries: dict[str, dict] = {}

    for i, text in enumerate(lines, 1):
        t0 = time.perf_counter()
        perception, response = agent.respond(args.session, text)
        t_llm = time.perf_counter() - t0

        t1 = time.perf_counter()
        # 预演用 8 次重试：网络不稳也慢慢补，反正不赶时间
        audio_url = tts.synthesize(response.reply_text, response.speech_rate,
                                   response.pitch_shift, retries=8)
        t_tts = time.perf_counter() - t1

        tip = "（缓存命中）" if t_tts < 0.2 else ""
        if audio_url:
            ok_tts += 1
        print(f"[{i}/{len(lines)}] 用户: {text}")
        print(f"         情绪: {perception.emotion_label}  表情: {response.target_emotion}"
              f"  LLM {t_llm:.2f}s  TTS {t_tts:.2f}s {tip}")
        print(f"         回复: {response.reply_text}")
        print(f"         语音: {audio_url or '❌ 无（演示时会只显示文字）'}")
        print("-" * 84)

        if audio_url and response.debug.get("used_llm"):
            cache_entries[text] = {
                "reply": response.reply_text,
                "emotion": perception.emotion_label,
                "intensity": perception.emotion_score,
                "target_emotion": response.target_emotion,
                "speech_rate": response.speech_rate,
                "pitch_shift": response.pitch_shift,
                "audio_url": audio_url,
            }
        elif text in old_entries:
            # 这次没合成出语音（或这一轮没走真实模型）→ 沿用上一次的「回复+音频」。
            # 必须成对沿用：只换文字会声文不符，比没声音更糟。
            prev = old_entries[text]
            prev_audio = os.path.join(tts_dir, os.path.basename(prev.get("audio_url") or ""))
            if prev.get("audio_url") and os.path.exists(prev_audio) and os.path.getsize(prev_audio) > 1000:
                cache_entries[text] = prev
                reused += 1
                print(f"         ↳ 这次没生成成功，沿用上一次的回复+音频：{prev.get('reply', '')[:30]}")

        report_lines += [
            f"## 第 {i} 句", "",
            f"- 用户：{text}",
            f"- 判定情绪：`{perception.emotion_label}`（{perception.emotion_score}）",
            f"- 智能体表情：`{response.target_emotion}`，语速 {response.speech_rate}，音高 {response.pitch_shift}",
            f"- 回复：{response.reply_text}",
            f"- 语音文件：`{audio_url}`" if audio_url else "- 语音：**生成失败**",
            "",
        ]

    # 写兜底缓存
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "note": "由 experiments/prewarm_demo.py 生成；agent 在模型不可用时优先查这张表",
                "entries": cache_entries,
            },
            fh, ensure_ascii=False, indent=2,
        )
    print(f"兜底缓存：{len(cache_entries)} 条 → {cache_path}")
    if reused:
        print(f"   其中 {reused} 条沿用上一次的（这次没生成成功，但演示时照样有声音）")
    if len(cache_entries) < len(lines):
        print("⚠️ 有几句没进缓存（语音合成失败，或那一轮没走真实模型），断网时会退回固定模板。")

    print(f"语音生成成功 {ok_tts}/{len(lines)}")
    if ok_tts < len(lines):
        print("⚠️ 有失败项，重跑一次通常能补上（已生成的会命中缓存，不会重复花钱）。")

    out_path = os.path.join(REPO_ROOT, "docs", "演示预演记录.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(report_lines))
    print(f"预演记录已写入: {out_path}")
    print("演示前请确认：音频缓存已生成，且不要清空 src/presentation/static/tts/")
    return 0 if ok_tts == len(lines) else 1


if __name__ == "__main__":
    raise SystemExit(main())
