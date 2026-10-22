# 情感交互智能体 Agent 开发

给普通用户用的情感陪伴对话智能体：**语音说一句话 → 识别情绪 → 以固定人设多轮回应 → 合成语音 → 屏幕上的角色换表情**。

- 交付形式：现场演示 + 代码仓库
- 周期：三天冲刺
- 三人分工：A 张敬伟（产品与情感设计）/ B 丘羽鑫（记忆与人格工程）/ C 梁苇（交互与工程落地）

---

## 30 秒跑起来

```powershell
# 1. 装依赖（国内用清华源快很多）
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple fastapi "uvicorn[standard]" python-multipart openai edge-tts

# 2. 语音识别（可选，装不上不影响文字对话）
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple faster-whisper

# 3. 把 DeepSeek Key 粘进项目根目录的 api_key.txt（已 gitignore，不会进仓库）
#    没有 Key 也能跑，只是回复会走内置 mock 模板

# 4. 启动
双击 run.cmd
#    或命令行： python -m uvicorn app:app --host 127.0.0.1 --port 8000

# 5. 打开
浏览器访问 http://127.0.0.1:8000
```

**先自检再排查**：`python experiments/check_env.py` 一条命令看清缺什么。

> 服务不是常驻的，关掉窗口就停。**改了代码必须重启服务**，否则还跑旧代码。

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
| GET | `/api/health` | 健康检查：`{"ok":true,"asr":是否可用,"tts":是否可用,"llm":是否配了Key}` |
| POST | `/api/chat` | 主接口。multipart：`session_id` + （`text` 或 `audio` 二选一） |
| POST | `/api/reset` | 清空某个会话的记忆 |

返回结构（注意 `avatar` 和 `audio_url` 是前端要用的两个关键字段）：

```json
{
  "session_id": "uuid", "turn": 3,
  "perception": {"text":"...", "emotion_label":"sad", "emotion_score":0.7, "valence":-0.6, "arousal":0.3},
  "response": {"reply_text":"...", "target_emotion":"empathic", "speech_rate":0.9, "pitch_shift":-1.0},
  "audio_url": "/static/tts/xxx.mp3",
  "avatar": {"expression":"empathic", "state":"speaking"},
  "latency_ms": 3400
}
```

完整字段与硬规则见 `docs/接口契约.md`；**代码里的唯一事实来源是 `src/shared/contracts.py`**。

---

## 目录

```
├── AGENTS.md                    团队约定（DSH 每次会话自动加载）
├── 使用方法.txt                  三个人怎么协作（pull/push、报错对照）
├── 口令卡.txt                    跟 AI 说话用的固定说法
├── run.cmd / push.cmd / pull.cmd 双击用的三个按钮
├── app.py                       后端入口，把三层串起来
├── requirements.txt             依赖清单
├── docs/                        任务板、分工、契约、技术选型、疑难排查、决策记录
├── src/perception/              语音识别（ASR）
├── src/cognition/               情绪判断 + 人设对话 + 多轮记忆 + 红线兜底
├── src/presentation/            语音合成（TTS）+ 前端页面 + 静态资源
├── src/shared/                  契约数据结构（三人共用）
├── assets/prompts/              人设卡、系统提示词、危机话术、生图提示词
├── assets/images/               7 张表情图 expr_*.webp（A 出图）
├── assets/samples/              测试用例 test_cases.jsonl
├── experiments/                 自检、评测、预演脚本
└── data/                        数据集与模型（不进仓库，见 MANIFEST.md）
```

---

## 三个工具脚本

```powershell
# 环境自检：缺依赖 / 缺 Key / 缺表情图 / 端口占用，一眼看清
python experiments/check_env.py

# 情绪判断评测：改提示词前后各跑一次，看准确率变化（唯一客观依据）
python experiments/eval_emotion            # mock 模式，秒出
python experiments/eval_emotion --llm      # 真实调用 DeepSeek

# 演示预演：把演示台词提前生成音频缓存，现场 0.003 秒命中、不碰网络
$env:DEEPSEEK_TEMPERATURE="0.3"
python experiments/prewarm_demo --file docs/演示脚本.txt
```

---

## 已知限制与坑（都是实测踩过的）

| 现象 | 原因 | 对策 |
|---|---|---|
| 语音偶尔没有 | edge-tts 连微软服务器，国内约 1/5 失败 | 已自动重试并兜底到 Windows SAPI；**演示前跑 `prewarm_demo`** |
| 首次对话很慢（约 10 秒） | LLM + TTS 冷启动 | 服务启动时会自动预热，等 15 秒再用 |
| 改完代码没变化 | 服务没重启 | 关掉窗口重新双击 `run.cmd` |
| 队友机器装不上 faster-whisper | Python 版本不一致（3.14 无轮子） | **演示统一跑在 B 的机器上**（Python 3.10） |
| 访问 `/` 看到提示页 | 前端页面文件缺失 | 正常兜底，页面存在后自动生效 |
| 提交报 `Author identity unknown` | 没设 git 身份 | 见 `docs/疑难排查.md` 第 3 节 |

---

## 仓库规则（重要的几条）

1. **`AGENTS.md` 是团队大脑**，三个 AI 每次会话都会读它 —— 想让 AI 长期遵守什么，写进这个文件，不要只在聊天里说
2. **提交说明必须三行**：改了什么 / 为什么 / 影响谁（见 `AGENTS.md` 7.5 节）
3. **密钥、模型、数据集、TTS 缓存一律不进仓库**（单文件 > 5MB 就走云盘 + `data/MANIFEST.md` 登记）
4. **每人只改自己目录**，改公共接口前先改契约再群里说
