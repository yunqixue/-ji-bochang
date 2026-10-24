// 从 data/videos/*.mp4 抽帧，拼成一张总览图，用来看角色在每段视频里的表情与动作。
// ffmpeg 用 spawn 但 stdio: 'ignore' —— 沙箱里捕获子进程输出会 EPERM，我们只要它落的文件。
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');
const sharp = require('sharp');

const repoRoot = path.resolve(__dirname, '..', '..');
const FFMPEG = path.join(__dirname, 'bin', 'ffmpeg.exe');
const VIDEO_DIR = path.join(repoRoot, 'data', 'videos');
const OUT_DIR = path.join(repoRoot, 'experiments', 'video_frames');
const EACH = 8; // 每条视频抽 8 帧

process.env.XDG_CACHE_HOME = path.join(repoRoot, 'experiments', '.fontcache');
fs.mkdirSync(process.env.XDG_CACHE_HOME, { recursive: true });

function listVideos() {
  return fs
    .readdirSync(VIDEO_DIR)
    .filter((f) => /\.(mp4|mov|webm|mkv)$/i.test(f))
    .sort();
}

function extract(file, outDir) {
  fs.rmSync(outDir, { recursive: true, force: true });
  fs.mkdirSync(outDir, { recursive: true });
  // fps=1/N 均匀抽帧；先缩到 480 宽，够看表情
  const step = Math.max(1, Math.round(48 / EACH));
  const r = spawnSync(
    FFMPEG,
    ['-hide_banner', '-loglevel', 'error', '-y', '-i', path.join(VIDEO_DIR, file),
     '-vf', `fps=1/${step},scale=480:-1`, '-q:v', '4', path.join(outDir, 'f%02d.jpg')],
    { stdio: 'ignore' }
  );
  if (r.status !== 0) throw new Error(`ffmpeg 退出码 ${r.status}`);
  return fs.readdirSync(outDir).filter((f) => f.endsWith('.jpg')).sort();
}

(async () => {
  const videos = listVideos();
  if (!videos.length) { console.error(`${VIDEO_DIR} 里没有视频`); process.exit(1); }
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const rows = [];
  for (const v of videos) {
    const dir = path.join(OUT_DIR, path.parse(v).name.split('').slice(0, 40).join(''));
    const frames = extract(v, dir);
    console.log(`${v}  →  ${frames.length} 帧`);
    rows.push({ name: v, dir, frames });
  }

  // 拼总览：每行一条视频，每帧缩到 190 宽
  const TW = 190;
  const first = await sharp(path.join(rows[0].dir, rows[0].frames[0])).metadata();
  const TH = Math.round((TW / first.width) * first.height);
  const cols = Math.max(...rows.map((r) => r.frames.length));
  const layers = [];
  for (let r = 0; r < rows.length; r++) {
    for (let c = 0; c < rows[r].frames.length; c++) {
      const buf = await sharp(path.join(rows[r].dir, rows[r].frames[c]))
        .resize(TW, TH, { fit: 'cover' })
        .toBuffer();
      layers.push({ input: buf, left: c * TW, top: r * TH });
    }
  }
  const sheet = await sharp({
    create: { width: cols * TW, height: rows.length * TH, channels: 3, background: '#111' },
  }).composite(layers).webp({ quality: 82 }).toBuffer();
  const sheetPath = path.join(OUT_DIR, 'overview.webp');
  fs.writeFileSync(sheetPath, sheet);
  console.log(`\n总览：${path.relative(repoRoot, sheetPath)}（行序 = 文件名排序，从上到下）`);
  rows.forEach((r, i) => console.log(`  第 ${i + 1} 行：${r.name}`));
})();
