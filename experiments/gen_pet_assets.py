"""生成桌面小人的 Q 版表情素材（硅基流动）  Owner: B

为什么要有这个脚本：桌面小人要 4~5 个表情，而且**必须是同一个角色**。
纯文生图每次换一张脸，所以流程固定成两步：
    ① 文生图（Qwen-Image）出一张底图 —— 只要一张，反复用
    ② 图生图**改表情**（Qwen-Image-Edit-2509）—— 改的是同一张底图，所以是同一个角色
     这是"角色一致性"唯一靠得住的做法，也是选这家 API 的原因。
然后自动抠掉背景、清掉"AI 生成"水印、裁到主体、导出透明 WebP。

用法（在项目根目录）：
    python experiments/gen_pet_assets.py --base "D:\\...\\Qwen_Image.png"      # 只改表情
    python experiments/gen_pet_assets.py --make-base                           # 先出一张新底图

Key 读 `api_key_siliconflow.txt`（已 gitignore，绝不进仓库），也可以放环境变量 SILICONFLOW_API_KEY。

成本提醒：一张图几分钱。脚本每次只发 1 张，失败不重试超过 2 次，避免烧额度。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO_ROOT, "assets", "pet")
API = "https://api.siliconflow.cn/v1/images/generations"

BASE_PROMPT = (
    "Q版黏土人风格的可爱动漫少女半身像，超大头身比，蓝色齐肩短发加双马尾，"
    "白色蕾丝发带，又大又亮的眼睛带高光，脸颊有腮红，白色水手领配蓝色蝴蝶结，"
    "平涂上色、清晰的粗描边、贴纸风格，纯黑色背景，正面看向镜头，平静微笑"
)

EXPRESSIONS = {
    "happy":    "把她的表情改成开心地大笑，眼睛弯成月牙，嘴角明显上扬；其余部分（发型、衣服、姿势、构图）完全保持不变",
    "sad":      "把她的表情改成难过，眉毛下垂、眼睛含着泪光、嘴角向下；其余部分完全保持不变",
    "surprised": "把她的表情改成惊讶，眼睛睁大、嘴巴张成小圆形；其余部分完全保持不变",
    "blink":    "把她的眼睛改成闭着的（眨眼状态），其余部分完全保持不变",
    # 说话用的张嘴帧：每个表情各一张，说话时和对应表情交替，口型才跟得上情绪
    "happy_talk":    "把她的表情改成开心地笑并且嘴巴张开（像在开心地说话），其余部分完全保持不变",
    "sad_talk":      "把她的表情改成难过并且嘴巴微微张开（像在低声说话），其余部分完全保持不变",
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


def call(payload: dict, timeout: int = 240) -> dict:
    key = load_key()
    if not key:
        raise SystemExit("❌ 没有 Key：放到 api_key_siliconflow.txt 或设 SILICONFLOW_API_KEY")
    req = urllib.request.Request(
        API, data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def first_url(data: dict) -> str:
    items = data.get("images") or data.get("data") or []
    if not items:
        return ""
    it = items[0]
    return it.get("url", "") if isinstance(it, dict) else str(it)


def download(url: str, path: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
        with open(path, "wb") as fh:
            fh.write(raw)
        return True
    except Exception:
        return False


def cutout(path: str) -> np.ndarray:
    """抠掉纯黑背景（贴纸白边把人物围住，黑色进不来），并清掉右下角水印。"""
    img = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError("读不了 " + path)
    bgr = img[:, :, :3] if img.shape[2] == 4 else img
    h, w = bgr.shape[:2]

    near_black = (bgr.max(axis=2) < 30).astype(np.uint8)
    ff = near_black.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    for pt in ((1, 1), (w - 2, 1), (1, h - 2), (w - 2, h - 2)):
        if ff[pt[1], pt[0]] == 1:
            cv2.floodFill(ff, mask, pt, 2)
    bg = (ff == 2).astype(np.uint8)
    alpha = np.where(bg == 1, 0, 255).astype(np.uint8)

    # 水印固定压在右下角，直接清成透明（比识别文字可靠）
    alpha[int(h * 0.90):, int(w * 0.72):] = 0

    alpha = cv2.GaussianBlur(alpha, (3, 3), 0.8)
    alpha[alpha < 24] = 0
    return np.dstack([bgr, alpha])


def export(bgra: np.ndarray, out_webp: str, height: int = 560) -> tuple[int, int, int]:
    a = bgra[:, :, 3]
    ys, xs = np.where(a > 30)
    if len(xs) == 0:
        raise RuntimeError("抠完是空的")
    crop = bgra[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    h = height
    w = max(1, int(crop.shape[1] * h / crop.shape[0]))
    crop = cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA)
    os.makedirs(os.path.dirname(out_webp), exist_ok=True)
    tmp_png = out_webp.replace(".webp", "._tmp.png")
    cv2.imencode(".png", crop)[1].tofile(tmp_png)
    from PIL import Image
    Image.open(tmp_png).convert("RGBA").save(out_webp, "WEBP", quality=92, method=6)
    os.remove(tmp_png)
    return w, h, os.path.getsize(out_webp)


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Q 版表情素材")
    ap.add_argument("--base", help="已有的底图路径（推荐，省钱：只跑改表情）")
    ap.add_argument("--make-base", action="store_true", help="先出一张新底图")
    ap.add_argument("--only", help="只做某个表情，例如 sad")
    args = ap.parse_args()

    work = os.path.join(REPO_ROOT, "data", "pet_gen")
    os.makedirs(work, exist_ok=True)
    base_path = args.base

    if args.make_base or not base_path:
        print("[1/2] 生成底图（Qwen-Image）…")
        t0 = time.time()
        data = call({"model": "Qwen/Qwen-Image", "prompt": BASE_PROMPT,
                     "image_size": "1024x1024", "batch_size": 1,
                     "num_inference_steps": 30, "guidance_scale": 7.5})
        url = first_url(data)
        if not url:
            print("   ❌ 没有返回图片：", str(data)[:200])
            return 1
        base_path = os.path.join(work, "base.png")
        if not download(url, base_path):
            print("   ❌ 下载失败")
            return 1
        print(f"   ✅ {time.time() - t0:.0f}s → {base_path}")

    with open(base_path, "rb") as fh:
        uri = "data:image/png;base64," + base64.b64encode(fh.read()).decode()

    print(f"[2/2] 按底图改表情（Qwen-Image-Edit-2509），底图 {os.path.basename(base_path)}")
    targets = {k: v for k, v in EXPRESSIONS.items() if not args.only or k == args.only}
    ok = 0
    for name, prompt in targets.items():
        t0 = time.time()
        try:
            data = call({"model": "Qwen/Qwen-Image-Edit-2509", "prompt": prompt, "image": uri,
                         "image_size": "1024x1024", "batch_size": 1, "num_inference_steps": 25})
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "ignore")[:160]
            print(f"   ❌ {name}: HTTP {exc.code} {body}")
            if exc.code == 402:
                print("   → 余额不足，充值后再跑（脚本不会重试，免得白烧额度）")
                break
            continue
        except Exception as exc:                      # noqa: BLE001
            print(f"   ❌ {name}: {type(exc).__name__} {str(exc)[:120]}")
            continue
        url = first_url(data)
        if not url:
            print(f"   ❌ {name}: 没有返回图片")
            continue
        raw_path = os.path.join(work, f"{name}.png")
        if not download(url, raw_path):
            print(f"   ❌ {name}: 下载失败")
            continue
        try:
            bgra = cutout(raw_path)
            w, h, size = export(bgra, os.path.join(OUT_DIR, f"q_{name}.webp"))
            print(f"   ✅ {name:<9} {time.time() - t0:5.1f}s  {w}x{h}  {size // 1024}KB")
            ok += 1
        except Exception as exc:                      # noqa: BLE001
            print(f"   ❌ {name}: 后处理失败 {exc}")
        time.sleep(2)

    print(f"\n完成 {ok}/{len(targets)} 张 → {OUT_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
