# 表情图一键规整（experiments/imgtool）

> 用途：把生图工具下载的原图，变成前端能直接用的 `assets/images/expr_*.webp`
> 谁用：**A**（生图的人）｜ 依赖：Node 24（这台机器已有）

## 怎么用（30 秒）

1. 把原图放进 `data/raw_images/`，**文件名就是表情名**（大小写无所谓，脚本会转小写）：

   ```
   data/raw_images/neutral.png
   data/raw_images/sad.jpg
   data/raw_images/happy.webp
   ```

   合法名字只有 7 个：`neutral` / `happy` / `sad` / `anxious` / `angry` / `surprised` / `empathic`

2. 双击 **`experiments/prep-images.cmd`**（或在仓库根目录跑 `node experiments/imgtool/prep-images.js`）

3. 输出在 `assets/images/expr_<名字>.webp`，**前端不用改任何代码**，刷新页面就生效

## 它替你检查了什么

| 检查 | 为什么 |
|---|---|
| 缩放到 **768×1024**，居中裁切 | 页面形象区就是这个比例，尺寸不对会被拉变形 |
| 转 **webp**，超过 300KB 自动降质量（82 → 50） | 7 张图变大图，页面加载会明显卡 |
| 文件名必须合法 | 写成 `nutral.webp` 前端永远找不到图，也不报错，就一直是占位块 |
| 四角背景色 vs `#F5F0E8` | 7 张背景不一致，切表情时会「闪一下」，演示时很显眼 |
| 重复表情名 | 两张 `neutral` 只会留第一张，另一张白做 |

退出码：`0` 全部合格；`1` 上面列了要处理的项。脚本不会替你改图，只会告诉你哪里不对。

## 原图去哪了

`data/raw_images/` 属于 `data/`，**已在 `.gitignore` 里，不进仓库**。
原图（几 MB 的 png）丢一份到共享云盘，并在 `data/MANIFEST.md` 登记。

## 换机器重装（只有这一次）

```powershell
cd experiments/imgtool
npm install sharp --cache .\.npmcache
```

`--cache` 不能省：npm 默认缓存写在用户目录，这台机器的沙箱不让写，会报
`The operation was rejected by your operating system`。

> 为什么不用 Python 的 Pillow：这台机器 `pip install` 在解包阶段被系统拒绝
> （`Permission denied: ...\pip-unpack-xxx\...whl.metadata`，工作区内的临时目录也一样）。
> Node 侧的 sharp 自带 libwebp，一次装上就能用，所以走这条路。
> 换到 B/C 的机器上如果 Pillow 能装，用 Pillow 也行，产出格式一致。

## 已知坑

- **仓库路径含中文**，libvips 直接按路径读写会报 `unable to open for write`。
  脚本已经改成用 `fs.readFileSync` 读成 Buffer 再交给 sharp，不要再改回传路径。
- 原图如果是 HEIC/RAW，先在工具里导出 png/jpg 再来跑。
