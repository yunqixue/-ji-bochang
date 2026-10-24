// 按原分辨率抽参考帧，给"照着视频重画表情"用。
// 输出：data/ref_frames/<视频简称>/f01.jpg ...（不进仓库）
//       assets/samples/形象参考帧/全帧表.webp（带序号，给 A 挑）
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const sharp = require('sharp');

const repoRoot = path.resolve(__dirname, '..', '..');
const FFMPEG = path.join(__dirname, 'bin', 'ffmpeg.exe');
const VIDEO_DIR = path.join(repoRoot, 'data', 'videos');
const OUT_DIR = path.join(repoRoot, 'data', 'ref_frames');
const SHEET_DIR = path.join(repoRoot, 'assets', 'samples', '形象参考帧');
const STEP = 5; // 每 5 秒一帧

process.env.XDG_CACHE_HOME = path.join(repoRoot, 'experiments', '.fontcache');
fs.mkdirSync(process.env.XDG_CACHE_HOME, { recursive: true });

const SHORT = {
  '养赛博女儿,享幸福人生.mp4': '01_养女儿',
  '我叫戴安娜~微笑再美再甜不是你的都不特别~ (1).mp4': '02_微笑',
  '戴安娜_俺不知豆 (1).mp4': '03_不知豆',
  '累了一天回家打开识质存在看到戴安娜整个人都被治愈了.mp4': '04_治愈',
  '谁懂女儿伸手要抱抱的救赎感啊.mp4': '05_抱抱',
  '那..就叫你戴安娜怎么样.mp4': '06_叫名字',
};

(async () => {
  fs.mkdirSync(SHEET_DIR, { recursive: true });
  const videos = fs.readdirSync(VIDEO_DIR).filter((f) => /\.(mp4|mov)$/i.test(f)).sort();
  const rows = [];
  for (const v of videos) {
    const tag = SHORT[v] || path.parse(v).name.slice(0, 12);
    const dir = path.join(OUT_DIR, tag);
    fs.rmSync(dir, { recursive: true, force: true });
    fs.mkdirSync(dir, { recursive: true });
    const r = spawnSync(
      FFMPEG,
      ['-hide_banner', '-loglevel', 'error', '-y', '-i', path.join(VIDEO_DIR, v),
       '-vf', `fps=1/${STEP}`, '-q:v', '3', path.join(dir, 'f%02d.jpg')],
      { stdio: 'ignore' }
    );
    if (r.status !== 0) { console.error(`ffmpeg 失败：${v}`); continue; }
    const frames = fs.readdirSync(dir).filter((f) => f.endsWith('.jpg')).sort();
    console.log(`${tag}  →  ${frames.length} 帧  ${path.relative(repoRoot, dir)}`);
    rows.push({ tag, dir, frames });
  }

  const TW = 260;
  const probe = await sharp(path.join(rows[0].dir, rows[0].frames[0])).metadata();
  const TH = Math.round((TW / probe.width) * probe.height);
  const cols = Math.max(...rows.map((r) => r.frames.length));
  const layers = [];
  for (let r = 0; r < rows.length; r++) {
    for (let c = 0; c < rows[r].frames.length; c++) {
      const buf = await sharp(path.join(rows[r].dir, rows[r].frames[c]))
        .resize(TW, TH, { fit: 'cover' }).toBuffer();
      layers.push({ input: buf, left: c * TW, top: r * TH });
    }
  }
  const sheet = await sharp({
    create: { width: cols * TW, height: rows.length * TH, channels: 3, background: '#111' },
  }).composite(layers).webp({ quality: 80 }).toBuffer();
  const p = path.join(SHEET_DIR, '全帧表.webp');
  fs.writeFileSync(p, sheet);
  console.log(`\n全帧表：${path.relative(repoRoot, p)}`);
  rows.forEach((r, i) => console.log(`  第 ${i + 1} 行 = ${r.tag}（列 = 第几帧，从 1 开始，每帧间隔 ${STEP}s）`));
})();
