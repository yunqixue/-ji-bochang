"""音色试听样本生成器  Owner: B

用途：**"她的声音听起来像男生"这种主观判断，光靠嘴争没用** ——
      这个脚本把同一句话用不同音色/音高各合成一遍，顺手量出每段的基频中位数，
      再生成一个可以直接双击打开的试听页（experiments/voicetest/index.html），
      谁觉得不对就听着挑一个。

用法（在项目根目录）：
    python experiments/make_voice_samples.py

产物：
    experiments/voicetest/*.mp3      9 段试听
    experiments/voicetest/index.html 试听页（双击打开，不需要起服务）

参考区间（用来判断"是不是男声"）：
    成年男声 85–180 Hz ｜ 成年女声 165–255 Hz ｜ 女童 250–300 Hz
    低于 180 Hz 基本可以断定是男声；高于 350 Hz 往往开始失真发尖。
"""
from __future__ import annotations

import asyncio
import os
import sys

import av
import edge_tts
import numpy as np

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "experiments", "voicetest")

TEXT = "哎…面试没过啊。今天哪一下最让你难受？"

# (文件名, 发音人, 音高, 语速, 说明)
CASES = [
    ("now2",   "zh-CN-XiaoyiNeural",    "+5Hz",  "-10%", "★现在线上用的（基线抬 20Hz 之后）"),
    ("now",    "zh-CN-XiaoyiNeural",    "-15Hz", "-10%", "基线抬升之前的那一版（压低 1 个半音）"),
    ("yi_p0",  "zh-CN-XiaoyiNeural",    "+0Hz",  "+0%",  "小雨-Yi 原调"),
    ("yi_p25", "zh-CN-XiaoyiNeural",    "+25Hz", "+0%",  "小雨-Yi 升 25Hz"),
    ("yi_p40", "zh-CN-XiaoyiNeural",    "+40Hz", "+0%",  "小雨-Yi 升 40Hz"),
    ("xx_p0",  "zh-CN-XiaoxiaoNeural",  "+0Hz",  "+0%",  "晓晓-Xiaoxiao 原调"),
    ("xx_p25", "zh-CN-XiaoxiaoNeural",  "+25Hz", "+0%",  "晓晓-Xiaoxiao 升 25Hz"),
    ("hy_p0",  "zh-TW-HsiaoYuNeural",   "+0Hz",  "+0%",  "晓雨-HsiaoYu 原调（台湾腔）"),
    ("hy_p25", "zh-TW-HsiaoYuNeural",   "+25Hz", "+0%",  "晓雨-HsiaoYu 升 25Hz（台湾腔）"),
    ("hc_p0",  "zh-TW-HsiaoChenNeural", "+0Hz",  "+0%",  "晓臻-HsiaoChen 原调（台湾腔）"),
]


def decode(path: str, sr: int = 16000) -> np.ndarray:
    with av.open(path) as container:
        stream = container.streams.audio[0]
        res = av.AudioResampler(format="flt", layout="mono", rate=sr)
        chunks = []
        for frame in container.decode(stream):
            for f in res.resample(frame):
                chunks.append(f.to_ndarray().reshape(-1))
        for f in res.resample(None):
            chunks.append(f.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.float32) if chunks else np.zeros(1, np.float32)


def median_f0(x: np.ndarray, sr: int = 16000, fmin: int = 70, fmax: int = 450) -> float:
    """自相关法估基频中位数。够用，不需要 scipy。"""
    win, hop = int(0.040 * sr), int(0.020 * sr)
    lo, hi = int(sr / fmax), int(sr / fmin)
    vals = []
    for i in range(0, len(x) - win, hop):
        frame = x[i:i + win]
        frame = frame - frame.mean()
        if float(np.sqrt((frame ** 2).mean())) < 0.01:      # 静音段跳过
            continue
        ac = np.correlate(frame, frame, mode="full")[win - 1:]
        ac = ac / (ac[0] + 1e-9)
        seg = ac[lo:hi]
        if len(seg) == 0:
            continue
        k = int(np.argmax(seg)) + lo
        if ac[k] > 0.3:
            vals.append(sr / k)
    return float(np.median(vals)) if vals else 0.0


async def gen(key: str, voice: str, pitch: str, rate: str) -> bool:
    path = os.path.join(OUT, key + ".mp3")
    if os.path.exists(path) and os.path.getsize(path) > 1000:
        print(f"  = {key:<8} 已存在，跳过")
        return True
    for attempt in range(8):
        try:
            comm = edge_tts.Communicate(TEXT, voice, rate=rate, pitch=pitch)
            await comm.save(path)
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                return True
        except Exception:                                  # noqa: BLE001  网络抖，重试
            pass
        await asyncio.sleep(0.8 * (attempt + 1))
    print(f"  × {key:<8} 8 次都失败（多半是连不上微软服务器，过一会儿重跑即可）")
    return False


async def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    ok = 0
    for key, voice, pitch, rate, _label in CASES:
        ok += await gen(key, voice, pitch, rate)
    print(f"\n合成成功 {ok}/{len(CASES)}")

    print(f"\n{'文件':<12}{'时长':>7}{'基频中位':>10}  说明")
    for key, _v, _p, _r, label in CASES:
        path = os.path.join(OUT, key + ".mp3")
        if not os.path.exists(path):
            continue
        x = decode(path)
        f0 = median_f0(x)
        flag = "  ← 偏低，可能是男声" if f0 and f0 < 180 else ""
        print(f"{key:<12}{len(x)/16000:6.1f}s{f0:9.0f}Hz  {label}{flag}")

    page = os.path.join(OUT, "index.html")
    print(f"\n试听页：{page}")
    print("双击它就能听（不需要起服务）。听完挑一个，改 tts.py 里的 VOICE / 音高偏移即可。")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
