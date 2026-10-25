"""生成写实小雨的「说话张嘴帧」（硅基流动 Qwen-Image-Edit-2509）  Owner: 工具脚本

干什么：给 assets/images/expr_*.webp 每个表情配一张同构图的"张嘴说话"版本
       expr_<情绪>_talk.webp。两处同时受益：
         ① 主页面 2D 兜底：前端本来就会在说话时探测并切到 _talk 图（伪口型）
         ② 切片生成器：张嘴帧 + 词时间戳 → 伪口型视频切片

为什么走图生图：纯文生图每次换一张脸；用 expr 图当底图改嘴，才是同一个人。

用法（项目根目录）：
    python scripts/clipgen/gen_talk_frames.py            # 全部 7 个表情 + 疲惫
    python scripts/clipgen/gen_talk_frames.py --only happy

Key 读 api_key_siliconflow.txt 或环境变量 SILICONFLOW_API_KEY（同 gen_pet_assets.py）。
一张图几分钱；失败不重试超过 1 次。
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images")
API = "https://api.siliconflow.cn/v1/images/generations"

# 每个表情要生成什么。talk = 对应表情的张嘴说话帧；tired 是新增表情（疲惫）。
TARGETS = {
    "neutral_talk":   ("expr_neutral.webp",   "把她的嘴巴微微张开，像正在平静地说话；其余部分（长相、发型、衣服、姿势、背景、构图、光线）完全保持不变"),
    "happy_talk":     ("expr_happy.webp",     "把她的嘴巴张开，像正在开心地说话，保持笑容；其余部分完全保持不变"),
    "sad_talk":       ("expr_sad.webp",       "把她的嘴巴微微张开，像正在难过地低声说话；其余部分完全保持不变"),
    "anxious_talk":   ("expr_anxious.webp",   "把她的嘴巴微微张开，像正在紧张地说话；其余部分完全保持不变"),
    "angry_talk":     ("expr_angry.webp",     "把她的嘴巴张开，像正在生气地说话，保持皱眉；其余部分完全保持不变"),
    "surprised_talk": ("expr_surprised.webp", "把她的嘴巴再张开一点，像正在惊讶地说话；其余部分完全保持不变"),
    "empathic_talk":  ("expr_empathic.webp",  "把她的嘴巴微微张开，像正在温柔关切地说话；其余部分完全保持不变"),
    "tired":          ("expr_neutral.webp",   "把她的表情改成疲惫：眼皮半垂、眼神倦怠、轻微黑眼圈、嘴自然闭着；其余部分完全保持不变"),
    "tired_talk":     ("expr_neutral.webp",   "把她的表情改成疲惫：眼皮半垂、眼神倦怠，嘴巴微微张开像在疲惫地说话；其余部分完全保持不变"),
}


def load_key() -> str:
    key = (os.getenv("SILICONFLOW_API_KEY") or "").strip()
    if key:
        return key
    path = os.path.join(REPO_ROOT, "api_key_siliconflow.txt")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as fh:
            return fh.read().strip()
    return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="只生成某一个，例如 happy_talk")
    args = ap.parse_args()

    if not load_key():
        print("❌ 没有 Key：放到 api_key_siliconflow.txt 或设 SILICONFLOW_API_KEY")
        return 1

    from PIL import Image  # 仅本脚本用，解码/缩放

    targets = {k: v for k, v in TARGETS.items() if not args.only or k == args.only}
    ok = 0
    for name, (base_file, prompt) in targets.items():
        src = os.path.join(IMAGES_DIR, base_file)
        if not os.path.exists(src):
            print(f"   ❌ {name}: 底图不存在 {base_file}")
            continue

        # 底图转 png base64（API 收 data URI）
        img = Image.open(src).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        t0 = time.time()
        payload = {
            "model": "Qwen/Qwen-Image-Edit-2509",
            "prompt": prompt,
            "image": uri,
            "batch_size": 1,
            "num_inference_steps": 25,
        }
        key = load_key()
        req = urllib.request.Request(
            API, data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")[:160]
            print(f"   ❌ {name}: HTTP {exc.code} {body}")
            if exc.code == 402:
                print("   → 余额不足，先充值再跑")
                break
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ {name}: {type(exc).__name__} {str(exc)[:120]}")
            continue

        items = data.get("images") or data.get("data") or []
        url = items[0].get("url", "") if items and isinstance(items[0], dict) else (str(items[0]) if items else "")
        if not url:
            print(f"   ❌ {name}: 没有返回图片")
            continue

        try:
            req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=120) as r:
                raw = r.read()
            out = Image.open(io.BytesIO(raw)).convert("RGB")
            # 对齐到底图尺寸（768x1024），保证和闭口帧逐像素对齐可交叉淡入
            out = out.resize(img.size, Image.LANCZOS)
            out_path = os.path.join(IMAGES_DIR, f"expr_{name}.webp")
            out.save(out_path, "WEBP", quality=90, method=6)
            print(f"   ✅ {name:<15} {time.time() - t0:5.1f}s  {out.size[0]}x{out.size[1]}  {os.path.getsize(out_path) // 1024}KB")
            ok += 1
        except Exception as exc:  # noqa: BLE001
            print(f"   ❌ {name}: 后处理失败 {exc}")
        time.sleep(2)

    print(f"\n完成 {ok}/{len(targets)} 张 → {IMAGES_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
