"""把参考图做成透明立绘（桌面小人用）  Owner: B

为什么单独写一个脚本：桌面小人要"贴"在桌面上，必须是有 alpha 通道的透明 PNG。
而手上这批参考图（豆包生成的三视图）是 **JPG，背景被烤进了"透明网格"图案**，
右上/右下还带 "豆包 AI 生成" 水印 —— 既不能直接用，也不能当"照片背景"简单抠图。

做法（专门针对这种伪造的棋盘格背景，不需要下载任何模型）：
  1. 从四角采样，估出棋盘格的两种颜色
  2. 全图找出"像棋盘格"的像素作为候选背景
  3. 从图像四边做**洪泛填充**，只把与边框连通的那部分判为背景
     （这一步很关键：白衬衫的颜色和棋盘格很接近，但它被身体轮廓包住、不与边框连通，所以不会被吃掉）
  4. 边缘做 1px 羽化，并把水印区域整块清成透明
  5. 输出 PNG，并生成"深底 / 浅底 / 棋盘格"三张预览，方便用眼睛核对边缘

用法：
    python experiments/make_cutout.py --src "…\\d2a3ceeef9482efc9ec81d7891a8ecf6_720.jpg" --out data/cutout/front.png
"""
from __future__ import annotations

import argparse
import os

import cv2
import numpy as np


def sample_checker_colors(bgr: np.ndarray) -> list[np.ndarray]:
    """从四角各取一小块，聚出棋盘格的两种颜色。"""
    h, w = bgr.shape[:2]
    k = 14
    patches = [
        bgr[2:2 + k, 2:2 + k], bgr[2:2 + k, w - 2 - k:w - 2],
        bgr[h - 2 - k:h - 2, 2:2 + k], bgr[h - 2 - k:h - 2, w - 2 - k:w - 2],
        bgr[2:2 + k, w // 2:w // 2 + k], bgr[h - 2 - k:h - 2, w // 2:w // 2 + k],
    ]
    px = np.concatenate([p.reshape(-1, 3) for p in patches]).astype(np.float32)
    # 两簇：按亮度分
    lum = px.mean(axis=1)
    thr = np.median(lum)
    c1 = px[lum <= thr].mean(axis=0)
    c2 = px[lum > thr].mean(axis=0)
    return [c1, c2]


def build_alpha(bgr: np.ndarray, tol: float = 16.0) -> np.ndarray:
    h, w = bgr.shape[:2]
    f = bgr.astype(np.float32)
    colors = sample_checker_colors(bgr)

    # 1) 候选背景：和任一种棋盘色足够接近
    dist = np.minimum(
        np.linalg.norm(f - colors[0], axis=2),
        np.linalg.norm(f - colors[1], axis=2),
    )
    cand = (dist < tol).astype(np.uint8)

    # 2) 从四边洪泛：只清除与边框连通的候选点
    ff = cand.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    seeds = []
    step = 12
    for x in range(0, w, step):
        seeds += [(x, 0), (x, h - 1)]
    for y in range(0, h, step):
        seeds += [(0, y), (w - 1, y)]
    for sx, sy in seeds:
        if ff[sy, sx] == 1:
            cv2.floodFill(ff, mask, (sx, sy), 2)
    bg = (ff == 2).astype(np.uint8)

    alpha = np.where(bg == 1, 0, 255).astype(np.uint8)

    # 3) 补掉主体内部零星的小洞（棋盘格透过发丝造成的小孔）
    holes = (alpha == 0).astype(np.uint8)
    num, lab, stats, _ = cv2.connectedComponentsWithStats(holes, 8)
    for i in range(1, num):
        if stats[i, cv2.CC_STAT_AREA] < 60:
            alpha[lab == i] = 255

    # 4) 边缘 1px 羽化，避免硬锯齿
    alpha = cv2.GaussianBlur(alpha, (3, 3), 0.6)

    # 5) 水印区域直接清透明（右下角）
    wh, ww = int(h * 0.055), int(w * 0.16)
    alpha[h - wh:h, w - ww:w] = 0
    return alpha


def estimate_checker(bgr: np.ndarray):
    """估出棋盘格的 (格边长, 相位, 两种颜色)。

    ★ 关键：必须在**确定是背景的 ROI** 上拟合（这里取左上角一小块），
      而且 tile/phase 用细网格搜。原来用整条边框带 + 粗网格，两种颜色被平均成
      244/243（几乎一样），等于没识别出图案 —— 实测就是这个坑。
      这批参考图的棋盘格其实差 25 个灰阶（231 vs 255），识别对了才好分离。
    """
    h, w = bgr.shape[:2]
    roi = bgr[4:min(200, h - 4), 4:min(260, w - 4)].astype(np.float32)
    rh, rw = roi.shape[:2]
    yy, xx = np.mgrid[0:rh, 0:rw]

    best = None
    for tile in range(6, 66, 2):
        for phase in range(0, tile):
            cell = (((xx + phase) // tile) + (yy // tile)) % 2
            m0 = roi[cell == 0].mean(axis=0)
            m1 = roi[cell == 1].mean(axis=0)
            if abs(float(m0.mean() - m1.mean())) < 6.0:
                continue                      # 两色几乎一样 → 不是这个参数
            pred = np.where(cell[:, :, None] == 0, m0, m1)
            err = float(np.abs(roi - pred).mean())
            if best is None or err < best[0]:
                best = (err, tile, phase, m0, m1)
    if best is None:                          # 兜底：直接用两极颜色
        px = roi.reshape(-1, 3)
        lum = px.mean(axis=1)
        thr = np.median(lum)
        return 16, 0, px[lum <= thr].mean(axis=0), px[lum > thr].mean(axis=0)
    return best[1], best[2], best[3], best[4]


def build_alpha_v2(bgr: np.ndarray, tol: float = 20.0) -> np.ndarray:
    """按"预测棋盘格 + 局部是否真的在明暗交替"来判背景。

    为什么必须加第二条判据：棋盘格的两种颜色都接近白色（比如 245 和 232），
    **纯白衬衫每一像素也都能落在容差里**，光靠"和预测色接近"会把整件衬衫判成背景
    （实测就是这样，衬衫整块被吃掉）。而真正的棋盘格在局部是**明暗交替**的，
    均匀的衬衫不是 —— 用这一点把两者分开。
    """
    h, w = bgr.shape[:2]
    tile, phase, c0, c1 = estimate_checker(bgr)
    yy, xx = np.mgrid[0:h, 0:w]
    cell = ((((xx + phase) // tile) + (yy // tile)) % 2).astype(np.uint8)
    pred = np.where(cell[:, :, None] == 0, c0, c1).astype(np.float32)

    diff = np.abs(bgr.astype(np.float32) - pred).max(axis=2)
    near_pred = (diff < tol).astype(np.float32)

    # 局部"明暗交替强度"：窗口内 cell=0 与 cell=1 两组像素的平均亮度差
    win = max(5, tile + 1)   # 窗口要接近一个格：窗口太大（跨两格以上）会把明暗交替平均掉，swing 恒为 0
    f = bgr.astype(np.float32).mean(axis=2)
    c0m = (cell == 0).astype(np.float32)
    c1m = 1.0 - c0m
    k = np.ones((win, win), np.float32)
    n0 = cv2.filter2D(c0m, -1, k, borderType=cv2.BORDER_REPLICATE)
    n1 = cv2.filter2D(c1m, -1, k, borderType=cv2.BORDER_REPLICATE)
    s0 = cv2.filter2D(f * c0m, -1, k, borderType=cv2.BORDER_REPLICATE)
    s1 = cv2.filter2D(f * c1m, -1, k, borderType=cv2.BORDER_REPLICATE)
    m0 = s0 / np.maximum(n0, 1e-3)
    m1 = s1 / np.maximum(n1, 1e-3)
    swing = np.abs(m0 - m1)

    cand = ((near_pred > 0) & (swing > 4.0)).astype(np.uint8)

    # 只清除与边框连通的部分
    ff = cand.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    for x in range(0, w, 8):
        for pt in ((x, 0), (x, h - 1)):
            if ff[pt[1], pt[0]] == 1:
                cv2.floodFill(ff, mask, pt, 2)
    for y in range(0, h, 8):
        for pt in ((0, y), (w - 1, y)):
            if ff[pt[1], pt[0]] == 1:
                cv2.floodFill(ff, mask, pt, 2)
    bg = (ff == 2).astype(np.uint8)

    # 边界补一轮：把紧贴背景的近似棋盘色也吃掉（消除 1-2px 的白色描边）
    grow = cv2.dilate(bg, np.ones((3, 3), np.uint8), iterations=1)
    bg = ((grow == 1) & (near_pred > 0)).astype(np.uint8)

    alpha = np.where(bg == 1, 0, 255).astype(np.uint8)

    holes = (alpha == 0).astype(np.uint8)
    num, lab, stats, _ = cv2.connectedComponentsWithStats(holes, 8)
    for i in range(1, num):
        if stats[i, cv2.CC_STAT_AREA] < 40:
            alpha[lab == i] = 255

    alpha = cv2.GaussianBlur(alpha, (3, 3), 0.6)
    wh, ww = int(h * 0.055), int(w * 0.16)
    alpha[h - wh:h, w - ww:w] = 0          # 清掉右下角水印
    print(f"   棋盘格参数：格边长 {tile}px，相位 {phase}，"
          f"两色亮度 {c0.mean():.0f}/{c1.mean():.0f}")
    return alpha


def build_alpha_grabcut(bgr: np.ndarray, scale: float = 0.45, iters: int = 3):
    """**主用方法**：GrabCut + "棋盘格振荡"给初值。

    试出来的顺序（记下来免得下次重走）：
      1. "和背景色接近就算背景" → 白衬衫和背景几乎同色，整件衬衫被吃掉
      2. "按预测棋盘格逐像素比对" → 这批图的棋盘格是**糊的**（每格内部是渐变），单像素分不开
      3. "局部是否真的在明暗交替"(swing) → 能分开（背景 14.5 / 白衬衫 1.6），
         但背景里有大片 swing 很低（JPEG 把图案磨平），连通性一断就漏
      4. **拿 swing 强的地方当"确定背景"给 GrabCut 当初值** → 效果好且稳。
         注意：GrabCut 在 1280×640 上要跑两分钟，缩到 45% 只要几秒，掩膜再放大回来。
    """
    h, w = bgr.shape[:2]
    small = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]

    tile, phase, c0, c1 = estimate_checker(bgr)
    t = max(4, int(tile * scale))
    yy, xx = np.mgrid[0:sh, 0:sw]
    cell = ((((xx + phase) // t) + (yy // t)) % 2).astype(np.uint8)
    win = t + 2
    k = np.ones((win, win), np.float32)
    f = small.astype(np.float32).mean(axis=2)
    c0m = (cell == 0).astype(np.float32)
    c1m = 1.0 - c0m
    s0 = cv2.filter2D(f * c0m, -1, k)
    s1 = cv2.filter2D(f * c1m, -1, k)
    n0 = cv2.filter2D(c0m, -1, k)
    n1 = cv2.filter2D(c1m, -1, k)
    swing = np.abs(s0 / np.maximum(n0, 1e-3) - s1 / np.maximum(n1, 1e-3))

    subj = (swing > 8).astype(np.uint8)          # 强振荡 = 确定是棋盘格背景
    ys, xs = np.where(subj == 0)
    if len(xs) == 0:
        return np.full((h, w), 255, np.uint8), (0, 0, w, h)
    pad = 4
    x0, x1 = max(0, xs.min() - pad), min(sw - 1, xs.max() + pad)
    y0, y1 = max(0, ys.min() - pad), min(sh - 1, ys.max() + pad)
    rect = (x0, y0, max(2, x1 - x0), max(2, y1 - y0))

    mask = np.zeros((sh, sw), np.uint8)
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(small, mask, rect, bgd, fgd, iters, cv2.GC_INIT_WITH_RECT)
    a_small = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)

    a = cv2.resize(a_small, (w, h), interpolation=cv2.INTER_LINEAR)
    num, lab, stats, _ = cv2.connectedComponentsWithStats((a > 128).astype(np.uint8), 8)
    if num > 1:                                   # 只留最大连通域，清掉零散斑点
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        a = np.where(lab == biggest, 255, 0).astype(np.uint8)
    a = cv2.GaussianBlur(a, (5, 5), 1.2)           # 羽化，避免硬锯齿
    wh, ww = int(h * 0.055), int(w * 0.16)
    a[h - wh:h, w - ww:w] = 0                      # 清掉右下角"豆包 AI 生成"水印
    return a, rect


def previews(bgra: np.ndarray, out_prefix: str) -> None:
    h, w = bgra.shape[:2]
    rgb = bgra[:, :, :3].astype(np.float32)
    a = (bgra[:, :, 3:4].astype(np.float32) / 255.0)

    def comp(bg_bgr):
        bg = np.full_like(rgb, bg_bgr, dtype=np.float32)
        return (rgb * a + bg * (1 - a)).astype(np.uint8)

    # 棋盘预览
    tile = 16
    yy, xx = np.mgrid[0:h, 0:w]
    chk = (((yy // tile) + (xx // tile)) % 2).astype(np.float32)
    board = (np.dstack([chk, chk, chk]) * 90 + 110).astype(np.float32)
    chk_img = (rgb * a + board * (1 - a)).astype(np.uint8)

    cv2.imwrite(out_prefix + "_on_dark.png", comp((28, 22, 20)))
    cv2.imwrite(out_prefix + "_on_light.png", comp((245, 246, 248)))
    cv2.imwrite(out_prefix + "_on_checker.png", chk_img)


def imread_unicode(path: str):
    """cv2.imread 在 Windows 上读不了中文路径，用 imdecode 绕过去。"""
    data = np.fromfile(path, dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_unicode(path: str, img) -> bool:
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img)
    if not ok:
        return False
    buf.tofile(path)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="参考图 → 透明立绘")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--tol", type=float, default=16.0)
    ap.add_argument("--method", default="grabcut", choices=["grabcut", "flood"], help="grabcut 效果好（默认）；flood 快但会吃掉白衬衫")
    args = ap.parse_args()

    if not os.path.exists(args.src):
        print("❌ 找不到：" + args.src)
        return 1
    bgr = imread_unicode(args.src)
    if bgr is None:
        print("❌ 读不了这张图")
        return 1

    method = (args.method or "grabcut").lower()
    if method == "grabcut":
        alpha, rect = build_alpha_grabcut(bgr)
        print(f"   方法：GrabCut（初值矩形 {rect}）")
    else:
        alpha = build_alpha(bgr, args.tol)
        print("   方法：颜色+洪泛（快，但白衬衫容易被吃）")
    bgra = np.dstack([bgr, alpha])
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    imwrite_unicode(args.out, bgra)
    prefix = os.path.splitext(args.out)[0]
    previews(bgra, prefix)

    kept = float((alpha > 128).mean()) * 100
    print(f"✅ 输出：{args.out}")
    print(f"   主体占画面 {kept:.1f}%（抠图后保留的像素比例）")
    print(f"   预览：{prefix}_on_dark.png / _on_light.png / _on_checker.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
