"""无 AI 的「张嘴帧」生成：cv2 检测人脸 → 嘴部区域局部下拉伸（免费、离线）  Owner: 工具脚本

原理：嘴上沿不动，越靠下位移越大（高斯权重），形成自然的张嘴。
产出 expr_<情绪>_talk.webp，与闭口帧同尺寸，可交叉淡入。

用法：python scripts/clipgen/gen_talk_frames_cv.py [--only happy]
"""
from __future__ import annotations

import argparse
import os
import sys

import cv2
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images")

EMOTIONS = ["neutral", "happy", "sad", "anxious", "angry", "surprised", "empathic"]

# 嘴部位置：在这套图（同一底图衍生）上用网格图人工标定过一次，
# expr_neutral.webp 上嘴中心 ≈ (0.50w, 0.472h)。各表情图构图一致，共用即可。
# 换了底图风格就重标定：scripts 里打个网格图看一眼的事。
MOUTH_CX, MOUTH_CY = 0.50, 0.472
MOUTH_HW, MOUTH_HH = 0.11, 0.045     # 影响区半宽（相对 w）、半高（相对 h）


def warp_mouth(img, strength=1.6):
    """嘴部下拉伸 + 补口腔暗色（闭口图光拉伸看不出张嘴，必须画出缝）。
    strength 控制张嘴幅度（1.6 标准说话）。"""
    h, w = img.shape[:2]
    cx, cy = w * MOUTH_CX, h * MOUTH_CY
    mw, mh = w * MOUTH_HW, h * MOUTH_HH

    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = (xx - cx) / mw
    dy = (yy - cy) / mh
    wmask = np.exp(-(dx * dx + dy * dy))            # 高斯权重，中心 1
    # 只把"嘴中心以下"的像素往下拉；嘴上沿固定
    below = np.clip((yy - cy) / mh, 0, 2) / 2
    shift = (wmask * below * 10 * strength).astype(np.float32)
    map_y = np.clip(yy - shift, 0, h - 1)           # 采样上方像素 = 视觉上往下移
    out = cv2.remap(img, xx, map_y, cv2.INTER_LINEAR)

    # 补口腔：一条水平深色软边椭圆当"张开的嘴缝"，幅度跟着 strength 走
    cavity_h = 3.2 * strength                        # 缝高（像素）
    cav_mask = np.exp(-(((xx - cx) / (mw * 0.55)) ** 2 + ((yy - cy - 2) / cavity_h) ** 2))
    cav_mask = np.clip(cav_mask * 1.35, 0, 0.88)[..., None]
    # 口腔色：深红棕，比肤色暗得多但不死黑
    skin = out[int(cy), int(cx)].astype(np.float32)
    cavity_color = np.array([skin[0] * 0.28, skin[1] * 0.30, skin[2] * 0.38], dtype=np.float32)
    out = (out.astype(np.float32) * (1 - cav_mask) + cavity_color * cav_mask).astype(np.uint8)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()

    names = [e for e in EMOTIONS if not args.only or e == args.only]
    ok = 0
    for e in names:
        src = os.path.join(IMAGES_DIR, f"expr_{e}.webp")
        if not os.path.exists(src):
            print(f"   跳过 {e}（没有 expr_{e}.webp）")
            continue
        img = cv2.imdecode(np.fromfile(src, dtype=np.uint8), cv2.IMREAD_COLOR)
        out = warp_mouth(img)
        out_path = os.path.join(IMAGES_DIR, f"expr_{e}_talk.webp")
        cv2.imencode(".webp", out, [cv2.IMWRITE_WEBP_QUALITY, 90])[1].tofile(out_path)
        print(f"   ✅ expr_{e}_talk.webp  {os.path.getsize(out_path) // 1024}KB")
        ok += 1
    print(f"完成 {ok}/{len(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
