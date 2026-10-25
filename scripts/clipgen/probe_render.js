// 渲染路径验证：直接把 viseme_aa 钉在 0.8，截屏看嘴张不张
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const REPO = path.resolve(__dirname, '..', '..');
const PORT = 8793;
const BASE = `http://127.0.0.1:${PORT}`;
const OUT = path.join(__dirname, 'output', 'frames');

function waitHttp(url, timeoutMs = 60000) {
  const t0 = Date.now();
  return new Promise((resolve, reject) => {
    (function probe() {
      http.get(url, res => { res.resume(); resolve(); }).on('error', () => {
        if (Date.now() - t0 > timeoutMs) reject(new Error('后端起不来'));
        else setTimeout(probe, 500);
      });
    })();
  });
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const server = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(PORT)], { cwd: REPO, stdio: 'ignore' });
  const cleanup = () => { try { server.kill(); } catch (e) { } };
  process.on('exit', cleanup);
  await waitHttp(BASE + '/api/health');

  const puppeteer = require('puppeteer-core');
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: 'new',
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio', '--no-proxy-server'],
    defaultViewport: { width: 1280, height: 1080 },
  });
  const page = await browser.newPage();
  page.on('pageerror', e => console.log('[pageerror]', e.message));
  // 支持命令行传 URL 查询串，如 node probe_render.js "glb=/static/avatar/candidate.glb"
  const qs = process.argv[2] || '';
  await page.goto(`${BASE}/static/dev/clips.html${qs ? '?' + qs : ''}`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.__state === 'ready' || window.__state === 'error', { timeout: 120000, polling: 300 });
  console.log('state:', await page.evaluate(() => window.__state), 'err:', await page.evaluate(() => window.__error));

  // 基线
  await page.screenshot({ path: path.join(OUT, 'probe_base.png') });
  // 张嘴 0.8
  await page.evaluate(() => window.__head.setFixedValue('viseme_aa', 0.8));
  await new Promise(r => setTimeout(r, 800));
  console.log('viseme_aa value:', await page.evaluate(() => window.__head.mtAvatar['viseme_aa'].value));
  console.log('viseme_aa applied:', await page.evaluate(() => window.__head.mtAvatar['viseme_aa'].applied));
  console.log('mesh influence:', await page.evaluate(() => {
    const mt = window.__head.mtAvatar['viseme_aa'];
    return mt.ms.map((arr, i) => arr[mt.is[i]].toFixed(3)).join(',');
  }));
  await page.screenshot({ path: path.join(OUT, 'probe_aa08.png') });
  // 复原
  await page.evaluate(() => window.__head.setFixedValue('viseme_aa', null));

  // 试验 1：注视镜头
  await page.evaluate(() => window.__head.lookAtCamera(500));
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(OUT, 'probe_lookcam.png') });

  // 试验 2：固定抬头
  await page.evaluate(() => window.__head.setFixedValue('bodyRotateX', -0.15));
  await new Promise(r => setTimeout(r, 800));
  await page.screenshot({ path: path.join(OUT, 'probe_headup.png') });

  await browser.close();
  cleanup();
  console.log('截图在', OUT);
  process.exit(0);
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
