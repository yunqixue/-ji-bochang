"""参考视频的声音采样  Owner: B

用途：桌面小人和 TTS 参数要"贴近视频里那个角色"，不能靠拍脑袋。
      这个脚本直接从参考视频里抽音频，量出**她的声学特征**：
        · 基频中位数 / 10%~90% 范围  → 决定 TTS 的音高基线
        · 有声占比                   → 判断视频里是不是有大段配乐
        · 语速（能量峰值/秒，粗略）   → 决定 TTS 的语速
      只用 PyAV + numpy，**不需要装 ffmpeg**。

用法（在项目根目录）：
    python experiments/analyze_ref_voice.py --dir "D:\\Deepseek工作任务台\\情感交互视频及人物构建资料"
    python experiments/analyze_ref_voice.py --dir ... --dump   # 顺便导出 wav 片段方便人耳核对

参考区间：成年男声 85–180Hz ｜ 成年女声 165–255Hz ｜ 女童 250–300Hz
"""
from __future__ import annotations

import argparse
import os
import sys
import wave

import av
import numpy as np

SR = 16000


def decode_audio(path: str, sr: int = SR) -> np.ndarray:
    """把 mp4/mov 里的音轨解成单声道 float32。没有音轨就返回空数组。"""
    chunks = []
    with av.open(path) as container:
        if not container.streams.audio:
            return np.zeros(0, np.float32)
        stream = container.streams.audio[0]
        res = av.AudioResampler(format="flt", layout="mono", rate=sr)
        for frame in container.decode(stream):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(0, np.float32)


def frame_energy(x: np.ndarray, sr: int = SR, win_ms: int = 30, hop_ms: int = 15):
    win, hop = int(sr * win_ms / 1000), int(sr * hop_ms / 1000)
    n = max(0, (len(x) - win) // hop)
    return np.array([float(np.sqrt((x[i * hop:i * hop + win] ** 2).mean())) for i in range(n)])


def f0_series(x: np.ndarray, sr: int = SR, fmin: int = 70, fmax: int = 500):
    """自相关估基频；只在有能量的帧上算。"""
    win, hop = int(0.040 * sr), int(0.020 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    vals = []
    for i in range(0, max(0, len(x) - win), hop):
        fr = x[i:i + win]
        fr = fr - fr.mean()
        if float(np.sqrt((fr ** 2).mean())) < 0.01:
            continue
        ac = np.correlate(fr, fr, mode="full")[win - 1:]
        ac = ac / (ac[0] + 1e-9)
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] > 0.3:
            vals.append(sr / k)
    return np.array(vals)


def analyze(path: str) -> dict | None:
    x = decode_audio(path)
    if len(x) < SR // 2:
        return None
    energy = frame_energy(x)
    if len(energy) == 0:
        return None
    thr = max(float(np.percentile(energy, 50)) * 1.4, 0.01)
    speech_ratio = float((energy > thr).mean())
    f0 = f0_series(x)
    # 粗略语速：能量包络的上升沿个数 / 有声时长
    above = (energy > thr).astype(int)
    onsets = int(np.sum((above[1:] == 1) & (above[:-1] == 0)))
    voiced_sec = max(1e-6, float(above.mean()) * len(x) / SR)
    return {
        "file": os.path.basename(path),
        "dur": len(x) / SR,
        "speech_ratio": speech_ratio,
        "f0_median": float(np.median(f0)) if len(f0) else 0.0,
        "f0_p10": float(np.percentile(f0, 10)) if len(f0) else 0.0,
        "f0_p90": float(np.percentile(f0, 90)) if len(f0) else 0.0,
        "onsets_per_sec": onsets / voiced_sec,
        "rms": float(np.sqrt((x ** 2).mean())),
    }


def dump_wav(x: np.ndarray, path: str, sr: int = SR) -> None:
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def main() -> int:
    ap = argparse.ArgumentParser(description="参考视频的声音采样")
    ap.add_argument("--dir", required=True, help="放参考视频的目录")
    ap.add_argument("--dump", action="store_true", help="顺便导出整段 wav 到 data/ref_audio/")
    args = ap.parse_args()

    root = args.dir
    if not os.path.isdir(root):
        print(f"❌ 目录不存在：{root}")
        return 1
    vids = sorted(
        os.path.join(root, f) for f in os.listdir(root)
        if os.path.splitext(f)[1].lower() in (".mp4", ".mov", ".mkv", ".webm")
    )
    if not vids:
        print(f"❌ {root} 里没有视频文件")
        return 1

    out_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ref_audio"
    )
    if args.dump:
        os.makedirs(out_dir, exist_ok=True)

    print("=" * 92)
    print(" 参考视频声音采样（只用 PyAV，不需要 ffmpeg）")
    print("=" * 92)
    print(f"{'文件':<34}{'时长':>7}{'有声占比':>9}{'基频中位':>9}{'P10':>7}{'P90':>7}{'峰值/秒':>8}")
    rows = []
    for v in vids:
        r = analyze(v)
        if not r:
            print(f"{os.path.basename(v)[:32]:<34}  没有可用音轨")
            continue
        rows.append(r)
        print(f"{r['file'][:32]:<34}{r['dur']:6.1f}s{r['speech_ratio'] * 100:8.0f}%"
              f"{r['f0_median']:8.0f}Hz{r['f0_p10']:6.0f}{r['f0_p90']:7.0f}{r['onsets_per_sec']:8.1f}")
        if args.dump:
            p = os.path.join(out_dir, os.path.splitext(r["file"])[0] + ".wav")
            dump_wav(decode_audio(v), p)
            print(f"    ↳ 已导出 {p}")

    if not rows:
        return 1
    med = np.median([r["f0_median"] for r in rows if r["f0_median"] > 0])
    print()
    print("-" * 92)
    print(f" 全部视频的基频中位：{med:.0f} Hz")
    if med < 180:
        print(" → 落在**男声**区间（85–180Hz）")
    elif med < 250:
        print(" → 落在**成年女声**区间（165–255Hz）")
    elif med < 300:
        print(" → 落在**女童/少女**区间（250–300Hz）")
    else:
        print(" → 比常见女童更高，可能有音效/配乐干扰，需要人工听一段确认")
    print(" 下一步：把这个 Hz 数写进 TTS_PITCH_BASE（当前 20Hz），并据此定 --voice 基线")
    print("-" * 92)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
