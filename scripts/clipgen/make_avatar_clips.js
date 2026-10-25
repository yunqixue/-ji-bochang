/**
 * 3D 形象切片批量生成器
 *
 * 做什么：驱动本机 Edge（无头）打开 static/dev/clips.html，
 *         把「喜 乐 怒 哀 平静 疲惫」六个情绪各录成一条带口型、带声音的 webm。
 *
 * 用法（在本目录 scripts/clipgen 下）：
 *   node make_avatar_clips.js            # 生成全部 6 条
 *   node make_avatar_clips.js xi nu      # 只生成指定条目
 *
 * 输出：scripts/clipgen/output/clip_<名字>_<情绪>.webm
 *
 * 依赖：puppeteer-core（本目录 npm i 已装）；本机 Edge；项目虚拟环境的 python。
 * 无头模式 WebGL 失败时会自动改用有头模式（会弹出一个浏览器窗口，别关它）。
 */
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const http = require('http');

const REPO = path.resolve(__dirname, '..', '..');
const OUT_DIR = path.join(__dirname, 'output');
const PORT = 8791;
const BASE = `http://127.0.0.1:${PORT}`;

// 切片清单（与 clips.html 内一致；命令行参数可以只挑其中几个）
const ALL = ['xi', 'le', 'nu', 'ai', 'pingjing', 'pibei'];

const EDGE_CANDIDATES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  process.env.LOCALAPPDATA + '\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
];

function findBrowser() {
  for (const p of EDGE_CANDIDATES) {
    if (fs.existsSync(p)) return p;
  }
  throw new Error('没找到 Edge/Chrome 浏览器');
}

function waitHttp(url, timeoutMs = 60000) {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    (function probe() {
      http.get(url, res => { res.resume(); resolve(); })
        .on('error', () => {
          if (Date.now() - t0 > timeoutMs) { reject(new Error('后端起不来：' + url)); }
          else { setTimeout(probe, 500); }
        });
    })();
  });
}

async function main() {
  const only = process.argv.slice(2);
  const wanted = only.length ? ALL.filter(x => only.includes(x)) : ALL;
  if (!wanted.length) { console.error('没有匹配的切片名，可选：' + ALL.join(' ')); process.exit(1); }

  fs.mkdirSync(OUT_DIR, { recursive: true });

  // ---- 起后端（切片页要调 /api/tts 和 /static）----
  console.log('[1/4] 启动后端 …');
  const server = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(PORT)], {
    cwd: REPO, stdio: ['ignore', 'pipe', 'pipe'],
  });
  server.stderr.on('data', d => process.stderr.write('[server] ' + d));
  const cleanup = () => { try { server.kill(); } catch (e) { } };
  process.on('exit', cleanup);
  process.on('SIGINT', () => { cleanup(); process.exit(130); });

  await waitHttp(BASE + '/api/health');
  console.log('      后端就绪');

  // ---- 起浏览器 ----
  console.log('[2/4] 启动浏览器 …');
  const puppeteer = require('puppeteer-core');
  const exe = findBrowser();
  async function launch(headless) {
    return puppeteer.launch({
      executablePath: exe,
      headless: headless,                       // 'new' 无头；失败回退 false（有头）
      args: [
        '--autoplay-policy=no-user-gesture-required',
        '--mute-audio',                          // 录制走内部音轨，别让机器真出声
        '--no-proxy-server',                     // 本机渲染全走 localhost，绕开系统代理抖动
        '--window-size=1280,1080',
        '--use-angle=default',
      ],
      defaultViewport: { width: 1280, height: 1080 },
    });
  }

  let browser = await launch('new');
  let page = await browser.newPage();
  // 把页面里的日志/报错透传出来，失败时知道死在哪一步
  const wire = (p) => {
    p.on('console', m => console.log('  [page]', m.text()));
    p.on('pageerror', e => console.log('  [pageerror]', e.message));
  };
  wire(page);

  async function runStudio() {
    const only = wanted.length === ALL.length ? '' : '&only=' + wanted.join(',');
    const url = `${BASE}/static/dev/clips.html?batch=1&collect=1${only}`;
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    // 等初始化：ready 或 error
    await page.waitForFunction(
      () => window.__state === 'ready' || window.__state === 'error',
      { timeout: 120000, polling: 500 }
    );
    const state = await page.evaluate(() => ({ state: window.__state, error: window.__error }));
    if (state.state === 'error') { throw new Error('切片页初始化失败：' + state.error); }
    console.log('[3/4] 3D 形象就绪，开始录制（每条约 10 秒）…');
    await page.waitForFunction(() => window.__allDone || window.__error, { timeout: 10 * 60 * 1000, polling: 1000 });
    const err = await page.evaluate(() => window.__error);
    if (err) { throw new Error('录制失败：' + err); }
    return page.evaluate(() => window.__clips);
  }

  let clips;
  try {
    clips = await runStudio();
  } catch (e) {
    console.warn('      无头模式失败（' + e.message + '），改用有头模式重试 —— 会弹出浏览器窗口，别动它');
    await browser.close().catch(() => { });
    browser = await launch(false);
    page = await browser.newPage();
    wire(page);
    clips = await runStudio();
  }

  // ---- 落盘 ----
  console.log('[4/4] 保存文件 …');
  const saved = [];
  for (const name of wanted) {
    const dataUrl = clips[name];
    if (!dataUrl) { console.warn(`      跳过 ${name}（页面没产出）`); continue; }
    const b64 = dataUrl.split(',')[1];
    // 从页面侧的命名习惯还原文件名；clips 的 key 是清单里的 name
    const file = path.join(OUT_DIR, `clip_${name}.webm`);
    fs.writeFileSync(file, Buffer.from(b64, 'base64'));
    saved.push(file);
    console.log(`      ✓ ${file}  ${(fs.statSync(file).size / 1024).toFixed(0)} KB`);
  }

  await browser.close().catch(() => { });
  cleanup();
  console.log(`完成：${saved.length}/${wanted.length} 条切片在 ${OUT_DIR}`);
}

main().catch(e => { console.error('失败：', e.message); process.exit(1); });
