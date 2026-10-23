"""
对话日志查看器  Owner: B

logs/chat.jsonl 是给机器看的（一行一个 JSON），人直接读很痛苦。
这个脚本把最近几轮渲染成表格。

用法（项目根目录）：
    python experiments/show_log.py                 # 最近 10 轮
    python experiments/show_log.py -n 30           # 最近 30 轮
    python experiments/show_log.py --all           # 全部
    python experiments/show_log.py --errors        # 只看降级成 mock 的（排查用）
    python experiments/show_log.py --session 2c67  # 只看某个会话（前缀匹配）
    python experiments/show_log.py --csv out.csv   # 导出 CSV（可用 Excel 打开）
    python experiments/show_log.py --stats         # 只统计：情绪分布、降级率、平均长度
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(REPO_ROOT, "logs", "chat.jsonl")


def load(path: str) -> list[dict]:
    if not os.path.exists(path):
        print(f"❌ 找不到日志：{path}")
        print("   可能原因：服务还没跑过（服务每处理一轮对话就写一行），")
        print("             或者服务不是在项目目录下启动的（日志会写到别处）。")
        sys.exit(1)
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def short(text: str, width: int) -> str:
    text = (text or "").replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def show_table(rows: list[dict]) -> None:
    print("=" * 100)
    print(f" {'时间':<9} {'情绪':<10} {'表情':<10} {'LLM':<5} {'对方说':<26} 回复")
    print("=" * 100)
    for r in rows:
        llm = "✅" if r.get("used_llm") else "❌mock"
        emo = r.get("emotion") or ("sad(危机)" if r.get("crisis") else "-")
        print(
            f" {short(r.get('ts', ''), 9):<9} {emo:<10} {short(r.get('target_emotion', ''), 10):<10}"
            f" {llm:<5} {short(r.get('input', ''), 26):<26} {short(r.get('reply', ''), 60)}"
        )
    print("-" * 100)
    print(f" 共 {len(rows)} 轮")


def show_errors(rows: list[dict]) -> None:
    bad = [r for r in rows if not r.get("used_llm") and not r.get("crisis")]
    if not bad:
        print(f"✅ 没有降级记录（{len(rows)} 轮里全部走了真实 LLM）")
        return
    print(f"⚠️  有 {len(bad)} 轮降级成了 mock 模板（这些回复不是模型说的，是兜底话术）：\n")
    for r in bad:
        print(f"  [{r.get('ts')}] 对方说：{short(r.get('input', ''), 40)}")
        print(f"      降级原因：{r.get('llm_error') or '（未记录）'}")
        print(f"      兜底回复：{short(r.get('reply', ''), 50)}\n")


def show_stats(rows: list[dict]) -> None:
    if not rows:
        print("日志是空的")
        return
    emo = Counter(r.get("emotion", "?") for r in rows)
    tgt = Counter(r.get("target_emotion", "?") for r in rows)
    crisis = sum(1 for r in rows if r.get("crisis"))
    mock = sum(1 for r in rows if not r.get("used_llm") and not r.get("crisis"))
    avg_in = sum(len(r.get("input", "")) for r in rows) / len(rows)
    avg_out = sum(len(r.get("reply", "")) for r in rows) / len(rows)

    print("=" * 60)
    print(f" 总轮数：{len(rows)}　会话数：{len({r.get('session') for r in rows})}")
    print(f" 平均输入 {avg_in:.1f} 字　平均回复 {avg_out:.1f} 字")
    print(f" 危机路径触发：{crisis} 次　降级 mock：{mock} 次")
    print("-" * 60)
    print(" 对方情绪分布：" + "　".join(f"{k}×{v}" for k, v in emo.most_common()))
    print(" 智能体表情分布：" + "　".join(f"{k}×{v}" for k, v in tgt.most_common()))
    print("=" * 60)


def export_csv(rows: list[dict], out: str) -> None:
    path = out if os.path.isabs(out) else os.path.join(REPO_ROOT, out)
    fields = ["ts", "session", "input", "emotion", "target_emotion", "used_llm", "reply", "llm_error"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"✅ 已导出 {len(rows)} 轮 → {path}（Excel 可直接打开）")


def main() -> int:
    ap = argparse.ArgumentParser(description="查看对话日志")
    ap.add_argument("-n", type=int, default=10, help="显示最近几轮，默认 10")
    ap.add_argument("--all", action="store_true", help="显示全部")
    ap.add_argument("--errors", action="store_true", help="只看降级成 mock 的记录")
    ap.add_argument("--stats", action="store_true", help="只出统计")
    ap.add_argument("--session", type=str, default=None, help="只看某个会话（前缀匹配）")
    ap.add_argument("--csv", type=str, default=None, help="导出 CSV 到指定文件")
    args = ap.parse_args()

    rows = load(LOG_PATH)
    if args.session:
        rows = [r for r in rows if str(r.get("session", "")).startswith(args.session)]
        print(f"筛选会话前缀「{args.session}」→ {len(rows)} 轮\n")

    if args.stats:
        show_stats(rows)
    elif args.errors:
        show_errors(rows)
    elif args.csv:
        export_csv(rows, args.csv)
    else:
        show_table(rows if args.all else rows[-args.n:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
