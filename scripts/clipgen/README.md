# clipgen — 形象切片生成器

两条路线，各出一套 6 情绪切片（喜 乐 怒 哀 平静 疲惫）：

## A. 3D 路线（TalkingHead + xiaoyu.glb，真口型）

```bash
cd scripts/clipgen
node make_avatar_clips.js            # 全部 6 条 → output/clip_*.webm
node make_avatar_clips.js xi ai      # 只生成指定的
```

要求：`static/avatar/xiaoyu.glb` 存在、本机有 Edge/Chrome。

## B. 照片路线（写实立绘 + 伪口型，零依赖离线跑）

```bash
cd 项目根目录
python scripts/clipgen/gen_talk_frames_cv.py     # 先做张嘴帧（expr_*_talk.webp，免费离线）
python scripts/clipgen/make_photo_clips.py       # 出 6 条 → output/photo_clip_*.mp4
python scripts/clipgen/make_photo_clips.py xi    # 只出指定的
```

原理：`expr_<情绪>.webp`（闭口）+ `expr_<情绪>_talk.webp`（cv2 嘴部变形+口腔暗缝）
按 **edge-tts 词时间戳**逐词开合，外加呼吸起伏（zoompan）。带声音，768×1024 mp4。

> 副产品：`expr_*_talk.webp` 生成后，**主页面 2D 兜底的伪口型自动生效**（前端本来就会探测这组图）。

改台词/情绪：`make_photo_clips.py` 顶部的 `CLIPS` 清单。

## 手动模式（3D 路线）

启动 `run.cmd` 后浏览器打开 `http://127.0.0.1:8000/static/dev/clips.html?batch=1`，点「开始」。
参数：`?mood=happy&text=你好&name=test` 单条；`?bg=cafe` 换背景；`?view=upper` 换取景；`?glb=` 换模型。

## 排障

| 现象 | 原因 |
|---|---|
| 无头模式失败自动转有头 | 正常兜底，弹出的浏览器窗口别关，跑完自己关 |
| 「TTS 没出声音」 | edge-tts 连不上，重跑即可（有重试） |
| 3D 切片里没声音 | 重来；若复现，检查 clips.html 里 recDest 音轨没被 stop |
| 3D 表情不动/嘴不动 | 模型 GLB 缺 morphTargets（见 static/avatar/下载形象模型.md） |
| 照片切片嘴不动 | 没跑 gen_talk_frames_cv.py，或 ffmpeg 报 zoompan 变量错（时间变量是 time 不是 t） |

`probe_lipsync.js` / `probe_render.js` 是调试探针：前者打印说话时视素数值流，后者钉住嘴型截屏验证渲染链路。
