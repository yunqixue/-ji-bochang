# assets/images · 形象素材

放 7 张表情图（**同一个人**），文件名固定，前端按名字直接取：

```
expr_neutral.webp     平静（默认）
expr_happy.webp       开心
expr_sad.webp         难过
expr_anxious.webp     焦虑
expr_angry.webp       生气
expr_surprised.webp   惊讶
expr_empathic.webp    共情（智能体回复时的表情）
```

## 规则

| 项 | 要求 |
|---|---|
| 格式 | `.webp`（png 也能用，但体积大 3 倍） |
| 尺寸 | 768 × 1024 |
| 体积 | 单张 < 300KB |
| 背景 | 统一纯色 `#F5F0E8` |
| 命名 | 严格用上面的名字，**大小写一致**（Linux 服务器区分大小写） |

## 生成方法

见 `assets/prompts/形象生成提示词.md` —— 关键是**用参考图/固定种子**，否则 7 张会变成 7 个人。

## 降级

时间不够只做 `neutral` / `sad` / `happy` 三张，其余情绪前端复用 `neutral`。
**但 `neutral` 必须在 D1 20:00 前交出来**，否则 C 无法开始接前端。

## 原图不进仓库

生图的原始大图（几 MB 的 png）放共享云盘，仓库里只放压缩后的 webp。
