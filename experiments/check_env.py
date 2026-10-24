"""
环境自检  Owner: B（谁都能跑）

用途：开工第一件事，一条命令看清自己这台机器缺什么。
    省掉大量"为什么跑不起来 / 我这里报错"的群消息。

用法（在项目根目录）：
    python experiments/check_env.py
"""
from __future__ import annotations

import importlib
import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK, BAD, WARN = "✅", "❌", "⚠️ "

results: list[tuple[str, str, str]] = []   # (状态, 项目, 说明)


def add(status: str, item: str, note: str = "") -> None:
    results.append((status, item, note))


def check_python() -> None:
    v = sys.version_info
    if v >= (3, 10):
        add(OK, f"Python {v.major}.{v.minor}.{v.micro}", "")
    else:
        add(BAD, f"Python {v.major}.{v.minor}", "需要 3.10 或更高")


def check_module(name: str, label: str, required: bool = True, hint: str = "") -> None:
    try:
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", "")
        add(OK, label, ver)
    except Exception:
        add(BAD if required else WARN, label,
            hint or "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple " + name.replace("_", "-"))


def check_files() -> None:
    for rel, label, required in [
        ("app.py", "后端入口 app.py", True),
        ("src/shared/contracts.py", "契约 contracts.py", True),
        ("src/cognition/agent.py", "认知 agent.py", True),
        ("src/perception/asr.py", "感知 asr.py", True),
        ("src/presentation/tts.py", "表现 tts.py", True),
        ("src/presentation/static/index.html", "前端页面 index.html", False),
        ("AGENTS.md", "团队约定 AGENTS.md", True),
        ("assets/prompts/system_prompt.txt", "人设提示词", True),
    ]:
        path = os.path.join(REPO_ROOT, rel)
        if os.path.exists(path):
            add(OK, label, "")
        else:
            add(BAD if required else WARN, label,
                "还没写" if not required else "文件缺失")

    # 表情图
    img_dir = os.path.join(REPO_ROOT, "assets", "images")
    imgs = [f for f in os.listdir(img_dir) if f.startswith("expr_")] if os.path.isdir(img_dir) else []
    need = ["expr_neutral.webp", "expr_sad.webp", "expr_happy.webp"]
    missing = [n for n in need if n not in imgs]
    if not missing:
        add(OK, f"表情图 {len(imgs)} 张", "至少三张基础表情齐了")
    elif imgs:
        add(WARN, f"表情图 {len(imgs)} 张", f"缺 {', '.join(missing)}")
    else:
        add(WARN, "表情图 0 张", "页面只能显示占位块（A 负责出图）")


def check_asr_model() -> None:
    """语音识别模型是否就位（模型 150MB+ 不进仓库，队友要单独下载）。"""
    try:
        sys.path.insert(0, REPO_ROOT)
        from src.perception import asr  # noqa: PLC0415
    except Exception:
        add(WARN, "ASR 模型", "无法导入 src.perception.asr")
        return

    if not asr.available():
        add(WARN, "ASR 模型", "先装 faster-whisper，再下载模型")
        return
    if asr.model_ready():
        size = os.getenv("ASR_MODEL_SIZE", "small")
        add(OK, f"ASR 模型就绪（{size}）", "本地目录已有模型")
    else:
        add(WARN, "ASR 模型未下载", "python experiments/download_asr_model.py（约150MB）")


def check_env_vars() -> None:
    key = os.getenv("DEEPSEEK_API_KEY", "")
    key_file = os.path.join(REPO_ROOT, "api_key.txt")
    if key.startswith("sk-") and len(key) > 20:
        add(OK, "DEEPSEEK_API_KEY", "环境变量已配置（" + key[:6] + "…）")
    elif os.path.exists(key_file):
        try:
            content = open(key_file, "r", encoding="utf-8-sig").read().strip()
        except Exception:
            content = ""
        if content.startswith("sk-") and len(content) > 20:
            add(OK, "DEEPSEEK_API_KEY", "api_key.txt 已配置（" + content[:6] + "…）")
        else:
            add(WARN, "DEEPSEEK_API_KEY", "api_key.txt 存在但内容不像 Key")
    else:
        add(WARN, "DEEPSEEK_API_KEY", "没配 → 对话走 mock 模式（关键词回复，不好听）")
        add(WARN, "api_key.txt", "把 Key 粘进项目根目录的 api_key.txt 即可")

    model = os.getenv("ASR_MODEL_SIZE", "small")
    add(OK, "ASR 模型尺寸", model)


def check_tts_live() -> None:
    """真跑一次语音合成，而不是只检查 import。

    演示当天最容易翻车的就是语音：edge-tts 连微软服务器，国内约 1/5 失败；
    失败时会退到 Windows SAPI 离线合成（音色差但能出声）。
    只检查"库装没装"看不出来，所以这里真的生成一段。
    """
    try:
        sys.path.insert(0, REPO_ROOT)
        from src.presentation import tts  # noqa: PLC0415
    except Exception:
        add(BAD, "语音合成实测", "无法导入 src.presentation.tts")
        return

    if not tts.available():
        add(BAD, "语音合成实测", "没有可用的 TTS 后端")
        return

    url = tts.synthesize("环境自检，测试一下语音能不能出来。", 1.0, 0.0, retries=2)
    if not url:
        add(BAD, "语音合成实测", "合成失败：在线和离线兜底都没成功（演示时会没声音）")
    elif url.endswith(".mp3"):
        add(OK, "语音合成实测", "在线合成成功（音色好）")
    else:
        add(WARN, "语音合成实测", "在线失败、已用离线兜底（音色差但能出声）")


def check_service() -> None:
    """检查端口是否被占用（服务是否已经在跑）。"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.3)
    busy = sock.connect_ex(("127.0.0.1", 8000)) == 0
    sock.close()
    if busy:
        add(OK, "端口 8000", "已有服务在跑（可能你上次没关窗口）")
    else:
        add(OK, "端口 8000", "空闲，可以启动")


def main() -> int:
    print("=" * 78)
    print(" 环境自检 —— 项目目录: " + REPO_ROOT)
    print("=" * 78)

    check_python()
    check_module("fastapi", "fastapi")
    check_module("uvicorn", "uvicorn")
    check_module("multipart", "python-multipart")
    check_module("openai", "openai")
    check_module("edge_tts", "edge-tts（语音合成）", required=False,
                 hint="pip install -i https://pypi.tuna.tsinghua.edu.cn/simple edge-tts")
    check_module("faster_whisper", "faster-whisper（语音识别）", required=False,
                 hint="pip install -i https://pypi.tuna.tsinghua.edu.cn/simple faster-whisper")

    check_env_vars()

    check_asr_model()
    check_tts_live()
    check_files()
    check_service()

    print()
    bad = 0
    for status, item, note in results:
        if status == BAD:
            bad += 1
        print(f" {status} {item:<34} {note}")

    print()
    print("-" * 78)
    if bad == 0:
        print(" 结论：必需的都齐了，可以开工。")
        print("       启动服务：python -m uvicorn app:app --host 127.0.0.1 --port 8000")
    else:
        print(f" 结论：有 {bad} 项必需的东西缺失，先按上面的提示补。")
        print("       缺语音包不影响文字对话，可以先跑起来看效果。")
    print("-" * 78)
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
