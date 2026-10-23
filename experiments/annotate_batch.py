#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对话标注表批量跑 —— 省掉 30 次手工复制粘贴

做了什么：
  1. 读 assets/samples/对话标注表_30条.csv
  2. 逐条 POST 到 /api/chat（多轮那几组自动复用同一个 session_id）
  3. 把「实际识别情绪 / 实际回复 / 判对?」三列填回去，其余列不动
  4. 跑完打印：情绪判对率、最长的 5 条回复（大概就是"过长"）、请求失败的条目

为什么要有它：
  - 手工复制 30 条回复又慢又容易改字，标注表要的是**原文**，改了字这张表就废了
  - 判对? 用预期情绪自动比，省 30 次肉眼核对
  - 像不像人 / 客服腔 / 说教 / 严重度 这些仍然只能人填，脚本不碰

用法：
    python experiments\\annotate_batch.py                      # 打本机 8000
    python experiments\\annotate_batch.py --url https://xxx.trycloudflare.com
    python experiments\\annotate_batch.py --only T2            # 只跑 T2x 那几条（红线组）
    python experiments\\annotate_batch.py --dry-run            # 只打印不请求

注意：
  - 服务没起来会立刻报错，别傻等
  - 会**覆盖**这三列，其他列（包括你已经填的）原样保留
  - 演示组（演示1/2/3）各自共用一个会话，多轮记忆才测得出来
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_CSV = REPO / "assets" / "samples" / "对话标注表_30条.csv"

COL_EMOTION = "实际识别情绪"
COL_REPLY = "实际回复（原样粘贴）"
COL_OK = "判对?"
COL_EXPECT = "预期情绪"
COL_GROUP = "分组"
COL_INPUT = "用户输入"
COL_ID = "编号"

EMOTIONS = {"neutral", "happy", "sad", "anxious", "angry", "surprised", "empathic"}


def _post_multipart(base: str, fields: dict[str, str], timeout: float) -> dict:
    """urlencoded 被服务端拒掉时（422）的兜底：老老实实拼 multipart/form-data。"""
    boundary = "----annotbatch7f3a"
    parts = []
    for k, v in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8")
        )
    body = b"".join(parts) + f"--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_chat(base: str, session_id: str, text: str, timeout: float) -> dict:
    fields = {"session_id": session_id, "text": text}
    body = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        base.rstrip("/") + "/api/chat",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (400, 415, 422):
            return _post_multipart(base, fields, timeout)
        raise


def session_for(row: dict, counter: dict) -> str:
    group = (row.get(COL_GROUP) or "").strip()
    if group.startswith("演示"):
        return "annot-" + group
    return f"annot-{row.get(COL_ID, 'x')}"


def main() -> int:
    ap = argparse.ArgumentParser(description="批量跑对话标注表")
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="服务地址")
    ap.add_argument("--csv", default=str(DEFAULT_CSV), help="标注表路径（原地填回）")
    ap.add_argument("--out", default=None, help="另存到别的文件，不覆盖原表")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--delay", type=float, default=0.3, help="每条之间歇几秒，别把服务打爆")
    ap.add_argument("--only", default=None, help="只跑编号以此开头的，如 T2")
    ap.add_argument("--dry-run", action="store_true", help="只打印不请求")
    args = ap.parse_args()

    src = Path(args.csv)
    out = Path(args.out) if args.out else src
    if not src.exists():
        print(f"找不到标注表：{src}")
        return 2

    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames or []
        rows = list(reader)

    missing = [c for c in (COL_EMOTION, COL_REPLY, COL_OK, COL_INPUT) if c not in fields]
    if missing:
        print(f"标注表缺列：{missing}\n表头是：{fields}")
        return 2

    todo = [r for r in rows if args.only is None or (r.get(COL_ID) or "").startswith(args.only)]
    print(f"服务：{args.url}    共 {len(todo)} 条（表里 {len(rows)} 条）")
    if args.dry_run:
        for r in todo:
            print(f"  {r.get(COL_ID):<5}{r.get(COL_GROUP) or '':<14}{r.get(COL_INPUT)}")
        return 0

    # 先探活，避免 30 条全超时才报错
    try:
        with urllib.request.urlopen(args.url.rstrip("/") + "/api/health", timeout=10) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        print(f"健康检查：{health}")
    except Exception as e:
        print(f"服务连不上（{args.url}）：{e}\n先把服务起起来，或用 --url 指到 C 给的链接。")
        return 2

    sessions: dict[str, str] = {}
    errors: list[str] = []
    filled = 0
    right = 0
    t0 = time.time()

    for i, row in enumerate(todo, 1):
        rid = row.get(COL_ID) or f"#{i}"
        text = (row.get(COL_INPUT) or "").strip()
        if not text:
            continue
        key = session_for(row, sessions)
        sid = sessions.setdefault(key, key)
        try:
            data = post_chat(args.url, sid, text, args.timeout)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
            row[COL_REPLY] = f"[请求失败：{e}]"
            errors.append(f"{rid}: {e}")
            print(f"  {rid:<5}失败 {e}")
            continue

        perception = data.get("perception") or {}
        emotion = (perception.get("emotion_label") or "").strip()
        reply = ((data.get("response") or {}).get("reply_text") or "").strip()
        reply = reply.replace("\r\n", "\n").replace("\n", " ⏎ ")

        row[COL_EMOTION] = emotion
        row[COL_REPLY] = reply
        expect = (row.get(COL_EXPECT) or "").strip()
        ok = "Y" if emotion and expect and emotion == expect else "N"
        row[COL_OK] = ok
        filled += 1
        right += ok == "Y"
        flag = "" if ok == "Y" else f"  ← 预期 {expect}"
        if data.get("error"):
            flag += f"  ⚠ error: {data['error']}"
        print(f"  {rid:<5}{emotion:<10}{ok}{flag}  {reply[:40]}")
        time.sleep(args.delay)

    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(rows)

    elapsed = time.time() - t0
    print("\n" + "-" * 60)
    print(f"填了 {filled} 条，情绪判对 {right}/{filled}" + (f"，用时 {elapsed:.0f}s" if filled else ""))
    print(f"已写回：{out}")

    longest = sorted((r for r in todo if r.get(COL_REPLY)), key=lambda r: len(r.get(COL_REPLY) or ""), reverse=True)[:5]
    if longest:
        print("\n最长的 5 条（大概率就是「过长」，超过 3 句记 Y）：")
        for r in longest:
            n = len(r.get(COL_REPLY) or "")
            print(f"  {r.get(COL_ID):<5}{n:>3} 字  { (r.get(COL_REPLY) or '')[:50]}")

    if errors:
        print(f"\n{len(errors)} 条请求失败，重跑一次同样的命令就会补上：")
        for e in errors[:10]:
            print("  - " + e)

    print("\n接下来：打开表，填「像不像人 1-5 / 客服腔 / 说教 / 过长 / 接住情绪 / 严重度」，然后汇总到 问题清单.md")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
