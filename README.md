# 情感交互智能体 Agent 开发

给普通用户用的情感陪伴对话智能体：**语音说一句话 → 识别情绪 → 以固定人设多轮回应 → 合成语音 → 屏幕上的角色换表情**。

- 交付形式：现场演示 + 代码仓库（**10-25 晚上 20:00 前截止**）
- 周期：三天冲刺（10-23 ～ 10-25）
- 三人分工：A 张敬伟（产品与情感设计）/ B 丘羽鑫（记忆与人格工程）/ C 梁苇（交互与工程落地）

---

## 30 秒跑起来

```powershell
# 1. 装依赖（国内用清华源快很多）
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple fastapi "uvicorn[standard]" python-multipart openai edge-tts

# 2. 语音识别（可选，装不上不影响文字对话）
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple faster-whisper
#    装完还要下模型（约150MB）：
python experiments/download_asr_model.py

# 3. 配 Key（★ 必须做，否则回复是固定模板，一听就是机器）
双击 配置Key.cmd          # 自动打开 DeepSeek 页面 + 记事本，粘进去后会真的调一次模型告诉你行不行
#    也可以手动：把 Key 粘进项目根目录的 api_key.txt，然后 python experiments/check_key.py
#    队友怎么配、怎么验证：见 docs/队友怎么试用.md

# 4. 启动（都是双击，不用敲命令）
双击 自检.cmd            # 先看一眼：缺什么、语音到底能不能出声（30 秒出结果）
双击 run.cmd             # 正常模式：真实模型，端口 8000
双击 启动_离线保险.cmd     # 保险模式：只认演示脚本那 9 句，端口 8001，可以和上面同时开着

# 5. 打开
浏览器访问 http://127.0.0.1:8000
```

> 改了前端页面（`index.html`）要按 **Ctrl + F5 硬刷新**，否则浏览器会用缓存里的旧页面。
> 改了后端代码必须重启服务。两个都是「改了没变化」的头号原因。

**先自检再排查**：双击 `自检.cmd`（等价 `python experiments/check_env.py`），一条命令看清缺什么。

> 服务不是常驻的，关掉窗口就停。

---

## 三个人从哪开始

| 你是谁 | 先看 | 你负责的目录 |
|---|---|---|
| **A** | `docs/分工方案_三天版.md` 一之二节 | `docs/`、`assets/prompts/`、`assets/images/` |
| **B** | `docs/接口契约.md` + `src/cognition/` | `src/perception/`、`src/cognition/` |
| **C** | `docs/接口契约.md` + `src/presentation/` | `src/presentation/`、`app.py` |

协作流程看 `使用方法.txt`，跟 AI 说话的口令看 `口令卡.txt`。

---

## 接口一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 聊天页面（`src/presentation/static/index.html`） |
| GET | `/docs` | FastAPI 自动生成的接口调试页，可直接发请求试 |
| GET | `/api/health` | 健康检查：`asr`/`tts`/`llm` 是否可用、兜底缓存有几条、当前是不是离线模式、**上一次语音为什么没出声** |
| POST | `/api/chat` | 主接口。multipart：`session_id` + （`text` 或 `audio` 二选一） |
| POST | `/api/reset` | 清空某个会话的记忆 |

返回结构（注意 `avatar` 和 `audio_url` 是前端要用的两个关键字段）：

```json
{
  "session_id": "uuid", "turn": 3,
  "perception": {"text":"...", "emotion_label":"sad", "emotion_score":0.7, "valence":-0.6, "arousal":0.3},
  "response": {"reply_text":"...", "target_emotion":"empathic", "speech_rate":0.9, "pitch_shift":-1.0,
               "debug": {"used_llm": true, "fallback_source": "", "repeat_input": false,
                         "repeat_fixed": false, "repeat_score": 0.0}},
  "audio_url": "/static/tts/xxx.mp3",
  "avatar": {"expression":"empathic", "state":"speaking"},
  "lipsync": {"words": ["哎","又","没","过","啊"], "wtimes": [0,180,360,540,720],
              "wdurations": [180,180,180,180,200], "estimated": false},
  "latency_ms": 3400
}
```

`lipsync` 是给口型用的逐字时间戳（`words` / `wtimes` 毫秒 / `wdurations`）。
edge-tts 能给逐字信息时 `estimated=false`；命中**预演生成的老音频**时拿不到逐字信息，
会按字数均分造一份近似值（`estimated=true`）—— 不这样 3D 那边就只能晃头不动嘴。
没有 `lipsync` 时前端照常播声音，只是嘴型对不齐。

`response.debug` 是排查用的，前端不依赖它：
`used_llm`（是不是真模型回的）· `fallback_source`（命中预置缓存时是 `demo_cache`）·
`repeat_input`（对方是否重复了上一句）· `repeat_fixed`（是否检测到自己在重复并换掉了）。

完整字段与硬规则见 `docs/接口契约.md`；**代码里的唯一事实来源是 `src/shared/contracts.py`**。

---

## 屏幕上的角色：三层，坏一层不影响演示

演示时屏幕上有**三个互相独立**的东西，从"最好看"到"最保险"排：

| 层 | 是什么 | 什么时候在 | 出问题怎么办 |
|---|---|---|---|
| ① 3D 会说话的头像 | Three.js + TalkingHead 加载 `src/presentation/static/avatar/xiaoyu.glb`，带眨眼 / 呼吸 / 头部微动 / 口型 | 浏览器支持 WebGL2 且模型文件在 | 地址加 **`?no3d=1`** 直接关掉，自动回到 ② |
| ② 2D 立绘表情 | `assets/images/expr_*.webp` 按情绪换图；有 `expr_*_talk.webp` 就自动做口型 | 一直兜底 | — |
| ③ Q 版小人（右下角） | 128px 的金发小水手，**完全独立于上面两层** | 一直可见 | 点它右上角 `×` 关掉 |

### Q 版小人会在什么时候做什么

这是演示时最能出效果的部分 —— 也是"角色真的会随情绪变化"最直观的证据，讲的时候随手点两下就行：

- 一进页面 **1.2 秒后挥手打招呼**（不用操作，打开就在）
- 她说完一句话 → **嘴一张一合**，并且跟着情绪换：开心地说 / 难过地低声说 / **生气地说**
- 情绪判成生气 → 换**生气脸**（皱眉 + 叉腰）
- **点它一下** = 摸头：身体压扁 → 回弹 → 冒一颗爱心
- **按住拖动** = 挪到任何位置（不会挡住输入框就行）
- 待机时随机蹦一下 / 摇摆 / 歪头 / 左右挪，约 30% 概率再招一次手

素材在 `assets/pet/`（11 张 `q_*.webp`，透明底、约 40KB/张）。
要加新表情就改 `experiments/gen_pet_assets.py` 里的 `EXPRESSIONS` 再跑一次：
以现有帧为底图只改表情，**一张几毛钱**，脚本会自动抠图、去掉生图服务自带的「AI 生成」角标、裁边、导出 WebP。

> 另有一个**独立桌面窗口版**：双击 `启动桌面小人.cmd`（`desktop_pet.py`，PySide6），
> 把小人放到桌面上、不依赖浏览器窗口，双屏演示时的备选。和页面里的小人互不影响。
> 需要额外装 `python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6-Essentials`
> —— **它不是演示必需项**，装不上就只用页面里的小人。

---

## 目录

```
├── AGENTS.md                    团队约定（DSH 每次会话自动加载）
├── 使用方法.txt                  三个人怎么协作（pull/push、报错对照）
├── 口令卡.txt                    跟 AI 说话用的固定说法
├── run.cmd                      双击：启动正常模式（端口 8000）
├── 启动_离线保险.cmd               双击：启动保险模式（端口 8001，可与 8000 并存）
├── 启动桌面小人.cmd               双击：把 Q 版小人放到桌面上（不依赖浏览器，备选）
├── 自检.cmd                      双击：环境自检，并把结果翻译成"该走哪个模式"
├── 配置Key.cmd                   双击：配 DeepSeek Key，并真的调一次模型验证
├── start-demo.cmd               双击：起服务 + 开临时公网隧道（给不在场的人看）
├── push.cmd / pull.cmd          双击：上传 / 下载
├── 强制上传.cmd                  双击：push 失败时的备用上传（先 pull 再 push）
├── app.py                       后端入口，把三层串起来
├── desktop_pet.py               桌面小人（PySide6 独立窗口，备选方案）
├── requirements.txt             依赖清单
├── docs/                        任务板、分工、契约、技术选型、疑难排查、决策记录、
│                                演示当天操作手册、演示脚本、演示预演记录
├── src/perception/              语音识别（ASR）
├── src/cognition/               情绪判断 + 人设对话 + 多轮记忆 + 红线兜底 + 防复读
├── src/presentation/            语音合成（TTS）+ 前端页面 + 静态资源
│   └── static/avatar/           3D 形象模型 xiaoyu.glb（11.7MB，已在仓库里；说明见同目录 md）
├── src/shared/                  契约数据结构（三人共用）
├── assets/prompts/              人设卡、系统提示词、危机话术、生图提示词
├── assets/images/               7 张表情图 expr_*.webp（A 出图；有 expr_*_talk.webp 就自动做口型）
├── assets/pet/                  Q 版小人表情 11 张 q_*.webp + 参考图抠图 diana_*.webp
├── assets/samples/              测试用例、30 条对话标注表、体验问题清单
├── experiments/                 自检、冒烟测试、评测、预演、小人生图与抠图脚本
├── logs/                        对话日志 chat.jsonl（不进仓库）
└── data/                        数据集与模型（不进仓库，见 MANIFEST.md）
```

---

## 工具脚本（都在 `experiments/`，改完代码按需跑）

```powershell
# 环境自检：缺依赖 / 缺 Key / 缺表情图 / 端口占用 / 语音能不能真出声，一眼看清
python experiments/check_env.py

# 下载语音识别模型（150MB+，不进仓库；自带长度校验，能识别被截断的残片）
python experiments/download_asr_model.py
python experiments/download_asr_model.py --check     # 只检查本地模型是否完整

# 冒烟测试：16 项（服务、页面、情绪、记忆、红线、耗时）
# 彩排前一小时跑一遍，比人工点更快发现坏掉的东西
python experiments/smoke_test.py

# 人设行为评测：10 条硬规矩（坦白身份 / 不懂就说不懂 / 不卖萌 / 不给大人方案 /
# 被要求分享时必须真的讲一段 / 被问日常要讲具体小事 / 红线话术…）
python experiments/eval_behavior.py

# 情绪判断评测：改提示词前后各跑一次，看准确率变化（唯一客观依据）
python experiments/eval_emotion            # mock 模式，秒出
python experiments/eval_emotion --llm      # 真实调用 DeepSeek

# 断网兜底自检：44 项（9 句台词 × 各种标点/漏字/同音错字变体，是否都能命中预置缓存）
python experiments/test_fallback.py

# 演示预演：把演示台词提前生成音频缓存，现场 0.003 秒命中、不碰网络
$env:DEEPSEEK_TEMPERATURE="0.3"
python experiments/prewarm_demo --file docs/演示脚本.txt

# Q 版小人：以现有帧为底图只改一个表情（省钱，一张几毛），自动抠图去水印裁边
python experiments/gen_pet_assets.py --base assets/pet/q_calm.webp --only angry
python experiments/gen_pet_assets.py --base assets/pet/q_calm.webp --only wave

# 抠参考图（黑底 → 透明，保留最大连通块顺带去掉生图服务角标）
python experiments/make_cutout.py --src assets/pet/diana_front.webp --out assets/pet/diana_front.webp
python experiments/make_cutout.py --src 图.webp --out 出来.webp --method flood   # 快，但会吃掉白衬衫
```

---

## 演示有两种模式（现场照着选）

| | 模式 A · 正常 | 模式 B · 保险 |
|---|---|---|
| 怎么开 | 双击 `run.cmd` | 双击 `启动_离线保险.cmd` |
| 端口 | 8000 | **8001**（可以和 A 同时开着，随时切窗口） |
| 回复 | 真实模型，能应对临时提问 | 预置的 9 条真实回复，质量已验证 |
| 延迟 | 约 3.8 秒/句（实测 3.3–4.7 秒） | **约 10 毫秒/句** |
| 声音 | 取决于网络，偶尔一句没声 | **100%**（音频提前生成，不碰网络） |
| 代价 | — | **只认演示脚本那 9 句**，临时改词会掉到固定模板 |

现场怎么判断、怎么切、出问题怎么办：见 **`docs/演示当天操作.md`**（含"没声音怎么办"三态判断表）。

---

## 演示保险：断网也能演

现场断网 / LLM 挂掉时，如果直接退到固定模板，回复会变得重复又机械（最尴尬的情况）。
所以做了一层**预置缓存兜底**：

```powershell
# ① 演示前预演：把演示台词跑一遍，同时生成「兜底缓存」
$env:DEEPSEEK_TEMPERATURE="0.3"
python experiments/prewarm_demo --file docs/演示脚本.txt
#    产物：data/demo_cache.json（输入 → 真实回复 + 已合成音频），当前 9 条

# ② 演练断网：故意不连模型，验证兜底链路是否真的能顶住
#    最省事的方式是直接双击 启动_离线保险.cmd
```

**降级顺序**（每层都比上层差，但都不会中断）：

```
真实模型 → 预置缓存（真实回复 + 已合成音频，听不出差别）→ 固定模板（最机械）
```

`/api/health` 会报告兜底状态，便于现场确认：

```json
{"llm": true, "demo_cache": true, "demo_cache_entries": 9, "offline_mode": false,
 "tts_last_backend": "edge", "tts_last_error": ""}
```

`tts_last_backend` 是上一次成功用的后端：`edge`（在线，音色好）/ `sapi`（离线兜底，音色差）/
`cache`（复用已生成的音频）；`tts_last_error` 是**上一次没出声的中文原因**，成功时为空。
**"为什么这次没声音"直接看这两项就行**，详见 `docs/疑难排查.md` 第 16 节。

> 匹配做了归一化：全角/半角标点、空格、首尾句号都不影响命中 ——
> 因为**语音识别的输出自带句号**，不处理就会匹配不上（实测踩过）。
> 另外还做了**相似度兜底**：实测识别把「明天要**交**的东西」听成「**教**」，
> 只差一个字就会全部落空，所以精确匹配不中时按相似度（≥0.75）再试一次。
>
> 预演如果某句语音没合成成功，会**沿用上一次那一对「回复 + 音频」**（成对沿用，
> 不会出现声文不符）—— 不会因为一晚网络差就把这张保命表清空。
>
> ⚠️ 兜底缓存只对"演示台词里出现的那几句"有效。演示时**照脚本说话**，
> 临时改词会掉到固定模板；同一句重复说也会得到同一条预置回复（这是兜底模式的固有特性）。

---

## 页面调试参数（测界面 / 录演示用）

在地址后面加参数就能直接定到某个状态，不用真的发消息：

| 参数 | 作用 |
|---|---|
| `?mode=call` / `?mode=text` | 直接进通话视图 / 文字视图 |
| `?theme=cyber` | 直接切主题（`sweet` `cream` `cyber` `nature` `night`） |
| `?expr=sad` | 固定某个表情（`neutral/happy/sad/anxious/angry/surprised/empathic`） |
| `?cycle=1` | 每 0.9 秒自动换一张表情，确认换图真的生效 |
| `?state=speaking` | 固定在"说话中"（看光晕和波形） |
| `?voice=0.6` | 把音量固定成 0.6（检查"随声音推近"的视觉效果，不依赖真实音频） |
| `?voiceauto=1` | 音量自动起伏 —— **这台机器没声音时也能看到动效对不对** |
| `?bg=房间` | 换背景场景（C 留的接口）：需要 `assets/images/bg_房间.webp`，没有图就自动回落到"当前表情虚化" |
| `?no3d=1` | **关掉 3D 头像**，只用 2D 立绘（3D 出问题时的应急开关，等价 `?avatar3d=0`） |
| `?petmood=angry` | 把小人定在某个表情（`calm/happy/sad/surprised/angry`） |
| `?petwave=1` | 小人一直保持挥手图 |
| `?petbubble=1` | 直接弹出对话气泡（看气泡样式，不用真说话） |
| `?petact=pat` / `?petact=hop` | 预览小人的动作（摸头 / 蹦一下） |
| `?petclick=1` | 页面加载后自动对小人派发一次点击 —— 端到端验证"摸头"链路是否通 |

可以叠加，例如 `http://127.0.0.1:8000/?theme=cream&voiceauto=1&petmood=sad`。

---

## 看日志（调提示词必用）

服务窗口里只有 `POST /api/chat 200` 这种访问日志，**看不到它判成什么情绪、回复了什么**。
所以每轮对话还会追加一行到 `logs/chat.jsonl`（已 gitignore，不进仓库）：

```powershell
# 最近 20 轮原始记录
Get-Content logs\chat.jsonl -Tail 20

# 只看回复（改提示词时最实用）
Get-Content logs\chat.jsonl -Tail 20 | ForEach-Object { ($_ | ConvertFrom-Json).reply }

# 只看有没有偷偷降级成 mock（used_llm 为 false 就是降级了）
Get-Content logs\chat.jsonl | ForEach-Object {
    $j = $_ | ConvertFrom-Json
    if (-not $j.used_llm) { "降级：" + $j.input + " → " + $j.llm_error }
}
```

一条记录长这样：

```json
{"session":"xxx","input":"我今天面试又没过","emotion":"sad","score":0.7,
 "target_emotion":"empathic","speech_rate":0.9,"pitch_shift":-1.0,
 "reply":"哎…又没过啊。面完到现在一直想着这事吧？","used_llm":true,"llm_error":"","ts":"..."}
```

设 `CHAT_LOG=0` 可关闭写日志。

---

## 已知限制与坑（都是实测踩过的）

| 现象 | 原因 | 对策 |
|---|---|---|
| 语音偶尔没有 | edge-tts 连微软服务器，国内有一定失败率（实测 6 句挂 1 句，下一句又正常） | 已自动重试 3 次并兜底到 Windows SAPI；**查原因看 `/api/health` 的 `tts_last_error`**；演示前跑 `prewarm_demo` |
| 一直没声音，从来好过 | 本机没有可用的中文语音包 | 装中文语音包，或演示直接用模式 B（预置音频，不碰网络） |
| 同一句话连说两遍，回复一模一样 | 温度 0.3 + 无防重复约束（**已修**） | 现在会检测重复输入并换说法，`response.debug` 里有 `repeat_input` / `repeat_fixed` 可查 |
| 首次对话很慢（约 10 秒） | LLM + TTS 冷启动 | 服务启动时会自动预热，等 15 秒再用 |
| 改完前端没变化 | 浏览器用了缓存的旧页面 | **Ctrl + F5 硬刷新** |
| 改完后端没变化 | 服务没重启 | 关掉窗口重新双击 `run.cmd` |
| 队友机器装不上 faster-whisper | Python 版本不一致（3.14 无轮子） | **演示统一跑在 B 的机器上**（Python 3.10） |
| 访问 `/` 看到提示页 | 前端页面文件缺失 | 正常兜底，页面存在后自动生效 |
| 提交报 `Author identity unknown` | 没设 git 身份 | 见 `docs/疑难排查.md` 第 3 节 |
| 说话时口型不动 | `assets/images/` 里没有 `expr_*_talk.webp`（张嘴图） | A 出 1 张就自动生效，前端不用改 |
| 3D 头像在晃但嘴不动 | `xiaoyu.glb` 可能没带 Oculus Visemes 变形通道（模型没口型骨骼） | 演示前加 **`?no3d=1`** 关掉 3D；2D 立绘和 Q 版小人的口型都是好的，不影响演示（C 在查） |
| Q 版小人挡住按钮 | 浮层定位在右下角 | 已挪到 `right:200px; bottom:152px`；也可以**用鼠标直接拖走**，或点 `×` 关掉 |
| 小人图上有「AI 生成」角标 | 生图服务自带水印 | 生成脚本只保留最大连通块，角标作为独立小块被一起去掉；换新图后重跑脚本即可 |
| 小人的图有白边 / 背景没抠干净 | 抠图容差不对 | `make_cutout.py --tol` 调大或换 `--method grabcut` |

---

## 仓库规则（重要的几条）

1. **`AGENTS.md` 是团队大脑**，三个 AI 每次会话都会读它 —— 想让 AI 长期遵守什么，写进这个文件，不要只在聊天里说
2. **提交说明必须三行**：改了什么 / 为什么 / 影响谁（见 `AGENTS.md` 7.5 节）
3. **密钥、模型、数据集、TTS 缓存一律不进仓库**（单文件 > 5MB 就走云盘 + `data/MANIFEST.md` 登记）
   > 已知例外：`src/presentation/static/avatar/xiaoyu.glb`（11.7MB）已经在仓库里。
   > 演示前不动它（动一次要全队重新拉），**下个项目记得先登记再决定**。
4. **每人只改自己目录**，改公共接口前先改契约再群里说
