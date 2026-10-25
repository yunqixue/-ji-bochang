# clipgen — 3D 形象切片生成器

把 3D 形象按不同情绪录成带口型、带声音的 webm 短片。

## 快速开始

```bash
cd scripts/clipgen
node make_avatar_clips.js            # 全部 6 条：喜 乐 怒 哀 平静 疲惫
node make_avatar_clips.js xi ai      # 只生成指定的
```

输出在 `output/clip_<名字>.webm`（640×960、30fps、VP9+Opus）。

要求：项目能跑（python 依赖装过）、本机有 Edge/Chrome、`static/avatar/xiaoyu.glb` 存在。
脚本会自己起后端（端口 8791）、开无头浏览器渲染，全程不用手点。

## 想改台词/情绪/背景/取景

改 `src/presentation/static/dev/clips.html` 顶部的 `CLIPS` 清单：

```js
{ name: 'xi', label: '喜', mood: 'happy', text: '要说的话（200 字以内）' }
```

- `mood` 可选：`neutral / happy / angry / sad / fear / disgust / love / sleep`
- 背景：URL 加 `?bg=cafe`（home/cafe/park/night/study，来自 assets/images/bg_*.webp；`bg=none` 纯色方便抠像）
- 取景：URL 加 `?view=upper`（head 脸部特写 / upper 半身 / mid 腰上 / full 全身）

## 手动模式（不用 node）

启动 `run.cmd` 后浏览器打开：

```
http://127.0.0.1:8000/static/dev/clips.html?batch=1
```

点「开始」，六条依次录制并自动下载。单条：`?mood=happy&text=你好呀&name=test`。

## 排障

| 现象 | 原因 |
|---|---|
| 无头模式失败自动转有头 | 正常兜底，弹出的浏览器窗口别关，跑完自己关 |
| 「TTS 没出声音」 | edge-tts 连不上，重跑即可（有重试） |
| 切片里没声音 | 重来；若复现，检查 clips.html 里 recDest 音轨没被 stop |
| 表情不动/嘴不动 | 模型 GLB 缺 morphTargets，重下时 URL 必须带 `?morphTargets=ARKit,Oculus%20Visemes` |

`probe_lipsync.js` / `probe_render.js` 是两个调试探针：前者打印说话时视素数值流，后者钉住嘴型截屏验证渲染链路。
