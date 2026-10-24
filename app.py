"""
后端入口（把三层串起来的胶水）。  Owner: C

启动：
    双击 run.cmd            （推荐，会自动打开浏览器）
    或：python -m uvicorn app:app --host 127.0.0.1 --port 8000

接口严格按 docs/接口契约.md v0.3 实现。
注意：所有接口都是同步 def，因为 TTS 内部用了 asyncio.run。
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.cognition import agent
from src.perception import asr
from src.presentation import tts
from src.shared.contracts import error_payload

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(REPO_ROOT, "src", "presentation", "static")
IMAGES_DIR = os.path.join(REPO_ROOT, "assets", "images")
# 桌面小人的 Q 版立绘单独放 assets/pet/，用 /pet 挂出去（页面右下角浮层用）
PET_DIR = os.path.join(REPO_ROOT, "assets", "pet")


def _warmup() -> None:
    """预热：把 LLM 连接和 edge-tts 连接提前建立。

    实测冷启动 LLM 6.2s + TTS 5.4s ≈ 10s，热了之后 3~4s。
    演示时没人愿意看评委等 10 秒，所以服务一启动就在后台预热。
    """
    try:
        tts.synthesize("嗯，我在听。")
        print("[warmup] TTS 就绪")
    except Exception as exc:                      # noqa: BLE001
        print(f"[warmup] TTS 预热失败（不影响使用）：{exc}")
    try:
        if agent.api_key_configured():
            agent.respond("__warmup__", "你好")
            agent.reset("__warmup__")
            print("[warmup] LLM 就绪")
        else:
            print("[warmup] 没配 Key，走 mock 模式")
    except Exception as exc:                      # noqa: BLE001
        print(f"[warmup] LLM 预热失败（不影响使用）：{exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_warmup, daemon=True).start()
    yield


app = FastAPI(title="情感交互智能体", version="0.3", lifespan=lifespan)

os.makedirs(os.path.join(STATIC_DIR, "tts"), exist_ok=True)
os.makedirs(PET_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/avatar", StaticFiles(directory=IMAGES_DIR), name="avatar")
app.mount("/pet", StaticFiles(directory=PET_DIR), name="pet")


@app.get("/")
def index():
    page = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(page):
        # C 的页面还没写时，给一个能看懂的自检页，而不是 500 白屏
        return HTMLResponse(
            """<!doctype html><html lang="zh"><meta charset="utf-8">
<title>页面还没写</title>
<body style="font-family:system-ui;max-width:640px;margin:60px auto;line-height:1.8">
<h2>后端已经跑起来了，但前端页面还没有</h2>
<p>缺少文件：<code>src/presentation/static/index.html</code>（由 C 负责）</p>
<ul>
  <li>接口是通的，可以先用 <a href="/docs">/docs</a> 调试 <code>/api/chat</code></li>
  <li>健康检查：<a href="/api/health">/api/health</a></li>
</ul>
<p style="color:#888">这个提示页是后端的兜底，页面写好后会自动显示聊天界面。</p>
</body></html>""",
            status_code=200,
        )
    # ★ 页面必须不缓存。
    #   今天踩了三次同一个坑：改了网页，浏览器还用缓存里的旧页面，于是"改了没变化"、
    #   "背景切不了"、"表情不动"——全都是旧的 HTML 在跑，白查半天。
    #   这个页面只有一个 HTML 文件、内容全在里面，禁缓存没有任何副作用。
    no_cache = {"Cache-Control": "no-store, must-revalidate", "Pragma": "no-cache"}
    return FileResponse(page, headers=no_cache)


@app.get("/api/health")
def health() -> dict:
    demo = agent.demo_cache_status()
    return {
        "ok": True,
        "asr": asr.available(),
        "tts": tts.available(),
        "llm": agent.api_key_configured(),
        # 演示兜底：demo_cache=True 表示预置了问答缓存（断网也能演）；
        # offline_mode=True 表示当前故意不连模型（演练断网 / 验证兜底链路）
        "demo_cache": demo["ready"],
        "demo_cache_entries": demo["entries"],
        "offline_mode": demo["offline_mode"],
        # 「为什么这次没出语音」—— 最近一次合成的结果，空字符串表示没失败过。
        # tts_last_backend：edge（在线，音色好）/ sapi（离线兜底，音色差）/ cache（复用已生成）
        "tts_last_backend": tts.last_backend(),
        "tts_last_error": tts.last_error(),
    }


@app.post("/api/reset")
def reset(session_id: str = Form(...)) -> dict:
    agent.reset(session_id)
    return {"ok": True, "session_id": session_id}


@app.post("/api/chat")
def chat(
    session_id: str = Form(...),
    text: str | None = Form(None),
    audio: UploadFile | None = File(None),
):
    started = time.time()

    try:
        # ---- 1. 感知层：有录音就走 ASR，否则用文字 ----
        if audio is not None and (audio.filename or ""):
            raw = audio.file.read()
            user_text = asr.transcribe(raw)
            modality = "audio"
        else:
            user_text = (text or "").strip()
            modality = "text"

        if not user_text:
            return JSONResponse(error_payload("没有收到内容", "嗯？我这边什么都没听到，再说一次？"))

        # ---- 2. 认知层：情绪判断 + 人设回复 + 记忆 ----
        perception, response = agent.respond(session_id, user_text, modality)

        # ---- 3. 表现层：合成语音（失败不算请求失败）----
        # 命中演示预置缓存时，直接用上次合成好的音频（已存在 static/tts/），
        # 不再走在线合成 —— 断网场景下这是唯一能出声的路径。
        cached_audio = (response.debug or {}).get("cached_audio_url") or ""
        audio_url = cached_audio or tts.synthesize(
            response.reply_text, response.speech_rate, response.pitch_shift
        )

        avatar = {
            "expression": response.target_emotion,
            "state": "speaking" if audio_url else "idle",
        }

        return {
            "session_id": session_id,
            "turn": agent.get_memory(session_id)["count"],
            "perception": perception.to_dict(),
            "response": response.to_dict(),
            "audio_url": audio_url,
            "avatar": avatar,
            # 逐词时间戳（edge-tts WordBoundary），前端 3D 口型同步用；
            # 离线兜底/老缓存没有它时是 None，前端退回音量驱动口型
            "lipsync": tts.timings_for(audio_url),
            "latency_ms": int((time.time() - started) * 1000),
        }

    except RuntimeError as exc:                     # 我们主动抛的可读错误（如 ASR 没装）
        return JSONResponse(error_payload(str(exc)))
    except Exception as exc:                        # noqa: BLE001  兜底，演示不能白屏
        return JSONResponse(error_payload(f"服务出错了：{exc}"))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8000")))
