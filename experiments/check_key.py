"""Key 检查器  Owner: B（谁都能跑）

用途：**"我配了 Key 但回复还是人机"** 是这两天最常出现的困惑。
      这个脚本直接拿你的 Key 调一次模型，明确告诉你：
        · 有没有读到 Key（读的是哪里）
        · 这个 Key 能不能用（余额不足 / 无效 / 网络不通 会分别说清楚）
        · 模型实际回了什么、花了多久

用法（在项目根目录）：
    python experiments/check_key.py
    或直接双击项目根目录的 配置Key.cmd（会先打开 api_key.txt 让你粘贴）

退出码：0 = Key 可用；1 = 有问题（跟着上面的中文提示处理）
"""
from __future__ import annotations

import os
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from src.cognition import agent  # noqa: E402

OK, BAD, WARN = "✅", "❌", "⚠️ "


def mask(key: str) -> str:
    if len(key) <= 12:
        return key[:3] + "…"
    return f"{key[:6]}…{key[-4:]}（共 {len(key)} 位）"


def explain(exc: Exception) -> str:
    """把常见异常翻成"知道下一步干什么"的中文。"""
    text = f"{type(exc).__name__}: {exc}"
    low = text.lower()
    if "401" in low or "authentication" in low or "invalid api key" in low or "unauthorized" in low:
        return "Key 无效或已被删除 —— 去 platform.deepseek.com 重新建一个，注意别粘到空格"
    if "402" in low or "insufficient" in low or "balance" in low or "quota" in low:
        return "Key 有效，但账户余额/额度不够了 —— 充值后再试"
    if "429" in low or "rate limit" in low:
        return "请求太频繁被限流了 —— 等一分钟再试"
    if "timeout" in low or "timed out" in low:
        return "连不上 DeepSeek（超时）—— 检查网络/代理；能上网页但这里超时，多看是不是被公司网络挡了"
    if "connect" in low or "ssl" in low or "getaddrinfo" in low or "resolve" in low:
        return "连不上 api.deepseek.com —— 网络问题，不是 Key 问题"
    if "model" in low and ("not found" in low or "does not exist" in low):
        return "模型名不对 —— 默认是 deepseek-chat，别改成不存在的名字"
    return "未知错误，把下面这行原文发给 B：" + text[:200]


def main() -> int:
    print("=" * 74)
    print(" DeepSeek Key 检查")
    print("=" * 74)

    env_key = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
    key = agent._load_api_key()

    if env_key:
        print(f" {OK} 来源：环境变量 DEEPSEEK_API_KEY（优先级高于 api_key.txt）")
    elif key:
        print(f" {OK} 来源：项目根目录的 api_key.txt")
    else:
        print(f" {BAD} 没有找到 Key")
        print()
        print(" 怎么配（两分钟）：")
        print("   1. 打开 https://platform.deepseek.com → API keys → 新建")
        print("   2. 复制那串 sk- 开头的字符")
        print("   3. 粘进项目根目录的 api_key.txt（整份文件里只放这一串，不要引号、不要多行）")
        print("   4. 再跑一次这个脚本")
        print()
        print(" 不配 Key 也能启动，但回复会变成固定模板（很机械），不能用来评价人设。")
        return 1

    if not key.startswith("sk-"):
        print(f" {WARN}这个 Key 不是以 sk- 开头（DeepSeek 的 Key 都以 sk- 开头），确认是不是粘错了")
    print(f" 当前 Key：{mask(key)}")

    if not key.startswith("sk-") or len(key) < 20:
        print(f" {BAD} Key 格式看起来不对，先检查是不是只粘了一半")
        return 1

    client = agent._build_client()
    if client is None:
        print(f" {BAD} openai 库没装好，跑：python -m pip install openai")
        return 1

    print()
    print(" 正在真实调用一次模型……")
    t0 = time.time()
    try:
        resp = client.chat.completions.create(
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
            messages=[{"role": "user", "content": "只回四个字：可以用了"}],
            max_tokens=20,
        )
        dt = time.time() - t0
        reply = (resp.choices[0].message.content or "").strip()
        print(f" {OK} 调用成功（{dt:.1f} 秒），模型回了：「{reply}」")
        print()
        print(" 结论：Key 可用。启动服务后 /api/health 里 llm 会是 true，回复是真人设。")
        print("       如果之前启动的服务还在跑，**必须重启**才会读到新 Key。")
        return 0
    except Exception as exc:                            # noqa: BLE001
        dt = time.time() - t0
        print(f" {BAD} 调用失败（{dt:.1f} 秒）：{explain(exc)}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
