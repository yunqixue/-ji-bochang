#!/usr/bin/env node
/**
 * 表情图一致性审查 —— 把一批图裁成页面尺寸，拼成一张，一眼看出「是不是同一个人」
 *
 * 用法：
 *   node experiments/imgtool/review-sheet.js                       # 审 data/raw_images/
 *   node experiments/imgtool/review-sheet.js --dir 某个目录
 *
 * 输出：experiments/preview/  下每张一个 preview_*.webp + 一张 contact_sheet.webp
 *
 * 为什么要它：
 *   页面形象区是 3:4 的竖框，而生图工具默认吐横图（16:9、3:2）。
 *   横图裁进竖框只剩 38–42% 的宽度，人物会变得很小或者被切掉半个身子 ——
 *   只有拼在一起看，才知道哪几张根本进不了框。
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

// 拼图里的序号要渲染文字，fontconfig 必须有个可写缓存目录，
// 否则在沙箱里会刷一屏 "No writable cache directories" 并让进程退出码变 1。
// 必须在 require('sharp') 之前设好。
const repoRootEarly = path.resolve(__dirname, '..', '..');
process.env.XDG_CACHE_HOME = path.join(repoRootEarly, 'experiments', '.fontcache');
fs.mkdirSync(process.env.XDG_CACHE_HOME, { recursive: true });

const sharp = require('sharp');

const W = 768, H = 1024, THUMB_W = 320, THUMB_H = 427;
const IMG_EXT = new Set(['.png', '.jpg', '.jpeg', '.webp', '.avif', '.bmp']);

const argv = process.argv.slice(2);
const arg = (n, d) => { const i = argv.indexOf(`--${n}`); return i >= 0 && argv[i + 1] ? argv[i + 1] : d; };

const repoRoot = repoRootEarly;
const srcDir = path.resolve(repoRoot, arg('dir', path.join('data', 'raw_images')));
const outDir = path.resolve(repoRoot, 'experiments', 'preview');

(async () => {
  if (!fs.existsSync(srcDir)) {
    console.error(`找不到目录：${srcDir}`);
    process.exit(1);
  }
  const files = fs.readdirSync(srcDir).filter((f) => IMG_EXT.has(path.extname(f).toLowerCase())).sort();
  if (!files.length) {
    console.error(`${srcDir} 里没有图片。`);
    process.exit(1);
  }
  fs.mkdirSync(outDir, { recursive: true });

  const thumbs = [];
  console.log(`审查目录：${path.relative(repoRoot, srcDir)}    共 ${files.length} 张\n`);
  console.log('序号  文件                              原图尺寸      裁进竖框保留    构图提示');
  console.log('-'.repeat(96));

  for (let i = 0; i < files.length; i++) {
    const f = files[i];
    const input = fs.readFileSync(path.join(srcDir, f));
    const meta = await sharp(input).metadata();
    const buf = await sharp(input).resize(W, H, { fit: 'cover', position: 'centre' }).webp({ quality: 85 }).toBuffer();
    const name = `preview_${String(i + 1).padStart(2, '0')}_${path.parse(f).name}.webp`;
    fs.writeFileSync(path.join(outDir, name), buf);

    const keep = Math.min(100, ((W / H) / (meta.width / meta.height)) * 100);
    const hint = keep < 60 ? '⚠ 横图，两侧大量裁掉，人物会变小/被切' : keep < 90 ? '竖图，轻微裁切' : '比例接近，几乎不裁';
    console.log(`${String(i + 1).padStart(2, ' ')}.   ${f.padEnd(32)} ${`${meta.width}x${meta.height}`.padEnd(14)} ${(keep.toFixed(0) + '%').padEnd(14)} ${hint}`);

    thumbs.push({ buf: await sharp(buf).resize(THUMB_W, THUMB_H).toBuffer(), label: String(i + 1) });
  }

  // 拼一张：每格下面压一个序号，方便和上面的表对上
  const labelH = 36;
  const sheetW = THUMB_W * thumbs.length;
  const sheetH = THUMB_H + labelH;
  const layers = thumbs.flatMap((t, i) => [
    { input: t.buf, left: i * THUMB_W, top: 0 },
    {
      input: Buffer.from(
        `<svg width="${THUMB_W}" height="${labelH}"><rect width="${THUMB_W}" height="${labelH}" fill="#111"/><text x="${THUMB_W / 2}" y="26" font-family="Arial, Microsoft YaHei, sans-serif" font-size="22" fill="#fff" text-anchor="middle">${t.label}</text></svg>`
      ),
      left: i * THUMB_W,
      top: THUMB_H,
    },
  ]);

  const sheet = await sharp({ create: { width: sheetW, height: sheetH, channels: 3, background: '#111' } })
    .composite(layers)
    .webp({ quality: 88 })
    .toBuffer();
  fs.writeFileSync(path.join(outDir, 'contact_sheet.webp'), sheet);

  console.log('-'.repeat(96));
  console.log(`拼图：${path.relative(repoRoot, path.join(outDir, 'contact_sheet.webp'))}`);
  console.log('看拼图问三件事：① 是不是同一张脸 ② 衣服/发型变没变 ③ 人物在框里的大小一样吗');
})();
