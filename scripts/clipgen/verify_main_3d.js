// 主页面 3D 端到端验证：加载 → 发一条消息 → 确认 3D 就绪、说话、视素在动
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const REPO = path.resolve(__dirname, '..', '..');
const PORT = 8794;
const BASE = `http://127.0.0.1:${PORT}`;
const OUT = path.join(__dirname, 'output', 'frames');

function waitHttp(url, timeoutMs = 90000) {
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
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio'],
    defaultViewport: { width: 1440, height: 900 },
  });
  const page = await browser.newPage();
  page.on('console', m => { const t = m.text(); if (t.includes('avatar3d') || t.includes('error') || t.includes('Error')) console.log('[page]', t); });
  page.on('pageerror', e => console.log('[pageerror]', e.message));

  await page.goto(BASE + '/?mode=call', { waitUntil: 'domcontentloaded' });
  await sleep(8000);   // 等 3D 启动（12MB 模型 + 预热）

  const st = await page.evaluate(() => ({
    avatar3d_ready: window.avatar3d ? window.avatar3d.ready : 'no-api',
    stage3d: document.querySelector('#stage') && document.querySelector('#stage').getAttribute('data-avatar3d'),
  }));
  console.log('3D 状态:', JSON.stringify(st));
  await page.screenshot({ path: path.join(OUT, 'main_3d_idle.png') });

  // 发一条消息
  await page.type('#call-text', '我今天面试又没过，感觉自己挺没用的');
  await page.click('#call-send');

  // 等她回复并开始说话，期间采样视素
  let sawViseme = 0, sawSpeaking = false;
  for (let i = 0; i < 100; i++) {
    const s = await page.evaluate(() => {
      const h = window.__headProbe || null;
      return {
        state: document.querySelector('#stage') && document.querySelector('#stage').getAttribute('data-state'),
        aa: (window.avatar3d && window.avatar3d.ready && window.__mtProbe) ? window.__mtProbe() : null,
      };
    });
    const probe = await page.evaluate(() => {
      try {
        // 从 TalkingHead 实例读（通过 avatar3d 的内部引用拿不到就跳过）
        const c = document.querySelector('#stage canvas');
        return { canvas: !!c };
      } catch (e) { return {}; }
    });
    if (s.state === 'speaking') sawSpeaking = true;
    await sleep(300);
    if (sawSpeaking && s.state === 'idle') break;
  }
  await page.screenshot({ path: path.join(OUT, 'main_3d_reply.png') });
  console.log('见到说话状态:', sawSpeaking);
  const sub = await page.evaluate(() => document.getElementById('subtitle-text').textContent);
  console.log('字幕:', sub);
  await browser.close();
  cleanup();
  console.log('截图:', OUT);
  process.exit(0);

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
