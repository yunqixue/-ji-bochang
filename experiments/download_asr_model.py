"""
ASR 模型下载器  Owner: B

为什么需要它：
  语音识别模型（base 约 150MB、small 约 500MB）不进 git 仓库，
  而 faster-whisper 自带的下载走 huggingface_hub，在国内经常卡住不动，
  或者因为缓存目录没有写权限直接失败（实测 WinError 5）。

  这个脚本用最朴素的方式下载：urllib + 长度校验 + 多次重试，
  绕开 HF 缓存机制，直接把文件放进 data/models/faster-whisper-<尺寸>/。

用法（项目根目录）：
    python experiments/download_asr_model.py                 # 默认 base（约 150MB，够演示）
    python experiments/download_asr_model.py --size small    # 更准，约 500MB
    python experiments/download_asr_model.py --check         # 只检查本地模型是否完整

下载完成后，服务会自动优先使用本地模型（见 src/perception/asr.py 的 model_ready()）。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# faster-whisper 需要这四个文件；缺一个都跑不起来
FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
MIRRORS = [
    "https://hf-mirror.com/Systran/faster-whisper-{size}/resolve/main/",
    "https://huggingface.co/Systran/faster-whisper-{size}/resolve/main/",
]
# 多语言版词表固定 51865 行；英文版是 51864。用来识别"下错版本/下载被截断"
MULTILINGUAL_VOCAB_LINES = 51865


def model_dir(size: str) -> str:
    return os.path.join(REPO_ROOT, "data", "models", f"faster-whisper-{size}")


def check(size: str) -> bool:
    d = model_dir(size)
    ok = True
    print(f"检查模型目录：{d}")
    for f in FILES:
        p = os.path.join(d, f)
        if not os.path.exists(p):
            print(f"  ❌ 缺少 {f}")
            ok = False
            continue
        kb = os.path.getsize(p) // 1024
        print(f"  ✅ {f:<18} {kb} KB")
    vocab = os.path.join(d, "vocabulary.txt")
    if os.path.exists(vocab):
        with open(vocab, "r", encoding="utf-8", errors="ignore") as fh:
            n = sum(1 for _ in fh)
        if n >= MULTILINGUAL_VOCAB_LINES:
            print(f"  ✅ 词表 {n} 行（多语言版，可识别中文）")
        else:
            print(f"  ❌ 词表只有 {n} 行（多语言版应为 {MULTILINGUAL_VOCAB_LINES}）")
            print("     可能是下载被截断，或下成了英文版 —— 删掉 vocabulary.txt 重跑本脚本")
            ok = False
    return ok


def fetch(url: str, dst: str, attempts: int = 6) -> bool:
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=180) as resp:
                expect = resp.headers.get("Content-Length")
                data = resp.read()
            # 关键：必须校验长度。缺了这一步，中途断流会留下"看起来存在"的残片文件，
                # 后面所有报错都指向别处（真实踩过：vocabulary.txt 被截到 256KB，报错却是"模型是英文版"）
            if expect and len(data) != int(expect):
                print(f"     长度不符 {len(data)}/{expect}，重试")
                time.sleep(1.5)
                continue
            with open(dst, "wb") as fh:
                fh.write(data)
            return True
        except Exception as exc:                    # noqa: BLE001
            print(f"     第 {i + 1} 次失败：{type(exc).__name__}")
            time.sleep(1.5)
    return False


def download(size: str) -> int:
    d = model_dir(size)
    os.makedirs(d, exist_ok=True)
    print(f"目标目录：{d}\n")

    failed = []
    for name in FILES:
        dst = os.path.join(d, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 1024:
            print(f"  跳过 {name}（已存在 {os.path.getsize(dst) // 1024} KB）")
            continue
        ok = False
        for tpl in MIRRORS:
            base = tpl.format(size=size)
            print(f"  下载 {name}  ← {base.split('/')[2]}")
            if fetch(base + name, dst):
                print(f"     ✅ {os.path.getsize(dst) // 1024} KB")
                ok = True
                break
        if not ok:
            failed.append(name)

    if failed:
        print(f"\n❌ 这些文件没下成功：{', '.join(failed)}")
        print("   换一个网络环境重跑本脚本即可（已下好的会自动跳过）")
        return 1

    print()
    return 0 if check(size) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 faster-whisper 语音识别模型")
    ap.add_argument("--size", default=os.getenv("ASR_MODEL_SIZE", "base"),
                    choices=["tiny", "base", "small", "medium"],
                    help="模型尺寸：base 够演示（约150MB），small 更准（约500MB）")
    ap.add_argument("--check", action="store_true", help="只检查，不下载")
    args = ap.parse_args()

    if args.check:
        return 0 if check(args.size) else 1
    return download(args.size)


if __name__ == "__main__":
    raise SystemExit(main())
