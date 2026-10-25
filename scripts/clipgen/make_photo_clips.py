"""写实小雨照片切片生成器：图片 + 词时间戳 → 伪口型说话视频  Owner: 工具脚本

路线说明（为什么不是 3D/不是 AI 视频模型）：
  3D 方案在「另一个管线」（TalkingHead + xiaoyu.glb）；本脚本走照片路线 ——
  用 assets/images/expr_*.webp（团队 AI 立绘）+ cv2 张嘴帧（gen_talk_frames_cv.py）
  + edge-tts 词时间戳，ffmpeg 合成「呼吸起伏 + 按词开合嘴」的 mp4。
  零模型下载、离线可跑、一分钟出全套。

用法（项目根目录，需要先跑过 gen_talk_frames_cv.py）：
    python scripts/clipgen/make_photo_clips.py            # 全部 6 条
    python scripts/clipgen/make_photo_clips.py xi ai      # 只出指定条目

输出：scripts/clipgen/output/photo_clip_<名字>.mp4（768x1024，h264+aac）
"""
from __future__ import annotations

import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

from src.presentation import tts  # noqa: E402

FFMPEG = os.path.join(REPO_ROOT, "experiments", "imgtool", "bin", "ffmpeg.exe")
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images")
TTS_DIR = os.path.join(REPO_ROOT, "src", "presentation", "static", "tts")
OUT_DIR = os.path.join(REPO_ROOT, "scripts", "clipgen", "output")

# 喜乐怒哀平静疲惫 → 用哪张表情图 + 说什么
CLIPS = [
    {"name": "xi",       "label": "喜",   "expr": "happy",    "text": "哈哈，太好啦！听到这个消息，我真的替你开心！"},
    {"name": "le",       "label": "乐",   "expr": "happy",    "text": "能这样陪着你聊天，我觉得特别幸福。", "rate": 0.95},
    {"name": "nu",       "label": "怒",   "expr": "angry",    "text": "这也太过分了吧！我都替你生气！", "pitch": -2.0},
    {"name": "ai",       "label": "哀",   "expr": "sad",      "text": "别难过……不管怎么样，我都会一直陪着你的。", "rate": 0.85, "pitch": -2.0},
    {"name": "pingjing", "label": "平静", "expr": "neutral",  "text": "嗯，我在听呢，你慢慢说，不着急。", "rate": 0.9},
    {"name": "pibei",    "label": "疲惫", "expr": "empathic", "text": "今天聊了好久呀，我都有点累了呢……", "rate": 0.82, "pitch": -1.0},
]


def mouth_expr(lipsync: dict | None, duration_s: float) -> str:
    """词时间戳 → ffmpeg enable 表达式：每个词的中段张嘴，词间闭拢。
    没有时间戳就退成固定节奏（0.5s 周期开 0.3s）。"""
    if lipsync and lipsync.get("words"):
        parts = []
        for t0, d in zip(lipsync["wtimes"], lipsync["wdurations"]):
            s = (t0 + d * 0.15) / 1000.0
            e = (t0 + d * 0.90) / 1000.0
            if e > s:
                parts.append(f"between(t,{s:.3f},{e:.3f})")
        if parts:
            return "+".join(parts)
    return f"lt(mod(t\\,0.5)\\,0.3)*between(t,0,{duration_s:.3f})"


def make_clip(clip: dict) -> str | None:
    closed = os.path.join(IMAGES_DIR, f"expr_{clip['expr']}.webp")
    opened = os.path.join(IMAGES_DIR, f"expr_{clip['expr']}_talk.webp")
    if not (os.path.exists(closed) and os.path.exists(opened)):
        print(f"   ❌ {clip['name']}: 缺图（{clip['expr']} 或它的 talk 帧）")
        return None

    # 语音（edge-tts，含词时间戳；失败也能用固定节奏兜底）
    url = tts.synthesize(clip["text"], clip.get("rate", 1.0), clip.get("pitch", 0.0))
    if not url:
        print(f"   ❌ {clip['name']}: TTS 全部后端失败")
        return None
    audio = os.path.join(TTS_DIR, os.path.basename(url))
    lipsync = tts.timings_for(url, clip["text"])

    # 音频时长（ffprobe 不在就用 ffmpeg -i 解析）
    probe = subprocess.run(
        [FFMPEG, "-i", audio], capture_output=True, text=True, encoding="utf-8", errors="ignore")
    dur = 3.0
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            hms = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = hms.split(":")
            dur = int(h) * 3600 + int(m) * 60 + float(s)
            break

    expr = mouth_expr(lipsync, dur)
    fc = (
        "[0:v]scale=768:1024[closed];"
        "[1:v]scale=768:1024[open];"
        f"[closed][open]overlay=0:0:enable='{expr}'[mix];"
        # 呼吸：极轻微缩放 + 上下浮动，4 秒一循环（注意：zoompan 的时间变量是 time，不是 t）
        "[mix]zoompan=z='1+0.012*sin(2*PI*time/4)':x='iw/2-(iw/zoom/2)':"
        "y='ih*0.30-(ih/zoom/2)+6*sin(2*PI*time/4)':d=1:s=768x1024:fps=30[v]"
    )

    out = os.path.join(OUT_DIR, f"photo_clip_{clip['name']}.mp4")
    cmd = [
        FFMPEG, "-y",
        "-loop", "1", "-framerate", "30", "-i", closed,
        "-loop", "1", "-framerate", "30", "-i", opened,
        "-i", audio,
        "-filter_complex", fc,
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", "21",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-shortest", out,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if r.returncode != 0 or not os.path.exists(out):
        print(f"   ❌ {clip['name']}: ffmpeg 失败 {r.stderr[-300:]}")
        return None
    kb = os.path.getsize(out) // 1024
    sync = "词时间戳" if (lipsync and lipsync.get("words")) else "固定节奏"
    print(f"   ✅ {clip['label']}({clip['name']})  {dur:.1f}s  {kb}KB  口型: {sync}")
    return out


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    only = set(sys.argv[1:])
    targets = [c for c in CLIPS if not only or c["name"] in only]
    if not targets:
        print("没有匹配的切片名，可选：" + " ".join(c["name"] for c in CLIPS))
        return 1
    ok = 0
    for clip in targets:
        print(f"[{clip['label']}] {clip['text']}")
        if make_clip(clip):
            ok += 1
    print(f"\n完成 {ok}/{len(targets)} → {OUT_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
