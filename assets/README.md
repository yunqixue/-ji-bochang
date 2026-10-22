# assets · 素材与提示词

小文件素材放这里（**单文件 < 5MB**），大的走云盘并在 `data/MANIFEST.md` 登记。

| 子目录 | 放什么 |
|---|---|
| `prompts/` | 系统提示词、人格设定、对话策略 prompt（**要版本化**） |
| `samples/` | 评测样本：典型情绪场景的输入输出对照 |
| `images/` | 表情图、界面素材 |
| `audio/` | 短音效、TTS 参考音 |

## 提示词版本规则

提示词是核心资产，改动影响全局效果：

```
prompts/
├── persona_v1.md
├── persona_v2.md        ← 改了就新开文件，别覆盖
└── CHANGELOG.md         ← 每次改动写一行：改了什么、为什么、效果差异
```

谁改提示词，必须在 `prompts/CHANGELOG.md` 留痕，并在任务板通知另外两人 —— 否则别人跑实验会因为 prompt 悄悄变了而对不上。
