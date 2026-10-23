#!/usr/bin/env node
/**
 * 表情图一键规整 —— 把生图工具下载的原图变成前端能直接用的 webp
 *
 * 用法：
 *   1. 把原图放进 data/raw_images/，文件名就是表情名：neutral.png / sad.jpg / happy.webp
 *   2. 双击 experiments/prep-images.cmd （或在仓库根目录跑 node experiments/imgtool/prep-images.js）
 *   3. 脚本把 768x1024、<300KB 的 webp 写进 assets/images/expr_<名字>.webp
 *
 * 为什么要有这个脚本：
 *   - 石梦/豆包导出的图是 1024x1536 的 png，直接放进去页面加载慢，尺寸也不对
 *   - 7 张图背景色必须完全一致，否则切表情时会「闪一下」——脚本会检查四角背景色
 *   - 文件名写错（nutral / Neutral / expr_neutral）前端就永远找不到图，脚本会直接报错拦住
 *
 * 原图不放仓库：data/ 已在 .gitignore 里，原图丢了去共享云盘拿。
 */

const fs = require('fs');
const path = require('path');
const sharp = require('sharp');

const EXPRESSIONS = ['neutral', 'happy', 'sad', 'anxious', 'angry', 'surprised', 'empathic'];
const W = 768;
const H = 1024;
const MAX_BYTES = 300 * 1024;
const BG = { r: 0xf5, g: 0xf0, b: 0xe8 };
const IMG_EXT = new Set(['.png', '.jpg', '.jpeg', '.webp', '.avif', '.bmp', '.tif', '.tiff']);

const argv = process.argv.slice(2);
function arg(name, fallback) {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
}

const repoRoot = path.resolve(__dirname, '..', '..');
const rawDir = path.resolve(repoRoot, arg('raw', path.join('data', 'raw_images')));
const outDir = path.resolve(repoRoot, arg('out', path.join('assets', 'images')));
// 生图工具会把「豆包 AI 生成」压在图右下角。演示时大屏一放大就看得见，
// 所以入图前先切掉底部一条：--trim-bottom 0.09 = 砍掉下边 9% 的高度。
const trimBottom = Number(arg('trim-bottom', '0'));

function bytes(n) {
  return n >= 1024 ? `${(n / 1024).toFixed(0)}KB` : `${n}B`;
}

function pad(s, n) {
  // 中文按两个宽度算，让表格在 cmd 里也能对齐
  let width = 0;
  for (const ch of s) width += /[\u3000-\u9fff\uff00-\uffef]/.test(ch) ? 2 : 1;
  return s + ' '.repeat(Math.max(0, n - width));
}

// 注意：仓库路径含中文，libvips 按路径读写会报 "unable to open for write"，
// 所以所有读写都走 fs 的 Buffer，绕开 libvips 的路径处理。
async function cornerColors(buf) {
  const { data, info } = await sharp(buf)
    .resize(4, 4, { fit: 'fill' })
    .removeAlpha()
    .raw()
    .toBuffer({ resolveWithObject: true });
  const px = (x, y) => {
    const o = (y * info.width + x) * info.channels;
    return { r: data[o], g: data[o + 1], b: data[o + 2] };
  };
  return [px(0, 0), px(3, 0), px(0, 3), px(3, 3)];
}

function colorDelta(c) {
  return Math.max(Math.abs(c.r - BG.r), Math.abs(c.g - BG.g), Math.abs(c.b - BG.b));
}

// 四角彼此差得远 = 这张图有背景画面（照片风），纯背景色校验对它没意义
function cornerSpread(corners) {
  let worst = 0;
  for (let i = 0; i < corners.length; i++) {
    for (let j = i + 1; j < corners.length; j++) {
      worst = Math.max(
        worst,
        Math.abs(corners[i].r - corners[j].r),
        Math.abs(corners[i].g - corners[j].g),
        Math.abs(corners[i].b - corners[j].b)
      );
    }
  }
  return worst;
}

async function convert(file, stem) {
  const input = fs.readFileSync(file);
  const src = sharp(input, { failOn: 'error' });
  const meta = await src.metadata();
  const srcAspect = meta.width / meta.height;
  const targetAspect = W / H;
  const cropNote =
    (trimBottom > 0 ? `底部裁 ${Math.round(trimBottom * 100)}% 去水印；` : '') +
    (Math.abs(srcAspect - targetAspect) / targetAspect > 0.05
      ? `裁切 ${meta.width}x${meta.height} → ${W}x${H}`
      : '尺寸吻合，无裁切');

  // 先按质量 82 压；超 300KB 就逐档往下压，最低 50
  let quality = 82;
  let buf;
  let lastMeta;
  for (;;) {
    let p = sharp(input).rotate(); // 按 EXIF 摆正，手机/网页下载的图常见
    if (trimBottom > 0) {
      const m = await sharp(input).metadata();
      const keepH = Math.max(1, Math.round(m.height * (1 - trimBottom)));
      p = p.extract({ left: 0, top: 0, width: m.width, height: keepH });
    }
    buf = await p
      .resize(W, H, { fit: 'cover', position: 'centre' })
      .webp({ quality, effort: 6 })
      .toBuffer();
    lastMeta = await sharp(buf).metadata();
    if (buf.length <= MAX_BYTES || quality <= 50) break;
    quality -= 8;
  }

  if (lastMeta.format !== 'webp' || lastMeta.width !== W || lastMeta.height !== H) {
    throw new Error(`输出校验失败：${lastMeta.format} ${lastMeta.width}x${lastMeta.height}`);
  }
  if (buf.length > MAX_BYTES) {
    throw new Error(`压到 q${quality} 仍 ${bytes(buf.length)}，超过 300KB（原图太大，先手动缩一次）`);
  }

  const target = path.join(outDir, `expr_${stem}.webp`);
  fs.writeFileSync(target, buf);

  const corners = await cornerColors(input);
  const worst = Math.max(...corners.map(colorDelta));
  const spread = cornerSpread(corners);
  return { target, srcW: meta.width, srcH: meta.height, size: buf.length, quality, cropNote, bgDelta: worst, bgSpread: spread };
}

(async () => {
  if (!fs.existsSync(rawDir)) {
    console.error(`找不到原图目录：${rawDir}\n先建好它，把原图按表情名放进去（neutral.png / sad.jpg ...）`);
    process.exit(1);
  }
  fs.mkdirSync(outDir, { recursive: true });

  const files = fs
    .readdirSync(rawDir)
    .filter((f) => IMG_EXT.has(path.extname(f).toLowerCase()))
    .sort();

  if (!files.length) {
    console.error(`原图目录是空的：${rawDir}\n放一张 neutral.png 进去再跑。`);
    process.exit(1);
  }

  console.log(`原图：${path.relative(repoRoot, rawDir)}    输出：${path.relative(repoRoot, outDir)}\n`);
  console.log(`${pad('表情', 12)}${pad('结果', 8)}${pad('体积', 8)}${pad('质量', 6)}${pad('原图', 14)}备注`);
  console.log('-'.repeat(78));

  const problems = [];
  const done = [];
  const skipped = [];

  for (const f of files) {
    const stem = path.parse(f).name.trim().toLowerCase();
    const full = path.join(rawDir, f);

    if (!EXPRESSIONS.includes(stem)) {
      skipped.push(`${f}（文件名不是合法表情名，允许：${EXPRESSIONS.join(' / ')}）`);
      continue;
    }
    if (done.some((d) => d.stem === stem)) {
      problems.push(`${f}：表情名重复（前面已有 ${stem}），只保留第一张`);
      continue;
    }

    try {
      const r = await convert(full, stem);
      done.push({ stem, ...r });
      const flat = r.bgSpread <= 24; // 四角颜色接近 = 纯色底，才做 #F5F0E8 校验
      const bgNote = !flat
        ? '有背景画面（非纯色），跳过纯色校验'
        : r.bgDelta > 12
        ? `⚠ 背景色和 #F5F0E8 差 ${r.bgDelta}，切换时会闪`
        : '背景色一致';
      console.log(
        `${pad(stem, 12)}${pad('OK', 8)}${pad(bytes(r.size), 8)}${pad('q' + r.quality, 6)}${pad(`${r.srcW}x${r.srcH}`, 14)}${r.cropNote}；${bgNote}`
      );
      if (flat && r.bgDelta > 12) problems.push(`${stem}：背景色偏离 #F5F0E8（差 ${r.bgDelta}），换表情会闪一下`);
    } catch (e) {
      console.log(`${pad(stem, 12)}${pad('FAIL', 8)}${e.message}`);
      problems.push(`${f}：${e.message}`);
    }
  }

  console.log('-'.repeat(78));
  console.log(`成功 ${done.length} 张 → ${path.relative(repoRoot, outDir)}`);
  const missing = EXPRESSIONS.filter((e) => !done.some((d) => d.stem === e));
  if (missing.length) console.log(`还没有：${missing.join(' / ')}`);

  if (skipped.length) {
    console.log('\n跳过（名字不对，前端永远找不到，必须改）：');
    skipped.forEach((s) => console.log('  - ' + s));
  }
  if (problems.length) {
    console.log('\n要处理的：');
    problems.forEach((p) => console.log('  - ' + p));
  }

  if (done.length) {
    console.log('\n记得：把原图也留一份到共享云盘，再在 data/MANIFEST.md 登记。');
    console.log('前端不用改代码，图一进 assets/images/ 就生效（刷新页面）。');
  }
  process.exit(problems.length || skipped.length ? 1 : 0);
})();
