// 探针：观察说话时 viseme 动画队列与 morph 值的实际变化
const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const fs = require('fs');

const REPO = path.resolve(__dirname, '..', '..');
const PORT = 8792;
const BASE = `http://127.0.0.1:${PORT}`;

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
  const server = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', String(PORT)], { cwd: REPO, stdio: 'ignore' });
  const cleanup = () => { try { server.kill(); } catch (e) { } };
  process.on('exit', cleanup);
  await waitHttp(BASE + '/api/health');

  const puppeteer = require('puppeteer-core');
  const browser = await puppeteer.launch({
    executablePath: 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    headless: 'new',
    args: ['--autoplay-policy=no-user-gesture-required', '--mute-audio', '--no-proxy-server'],
  });
  const page = await browser.newPage();
  page.on('console', m => console.log('[page]', m.text()));
  page.on('pageerror', e => console.log('[pageerror]', e.message));

  await page.goto(`${BASE}/static/dev/clips.html?collect=1&mood=happy&name=probe&text=今天天气真不错我们一起去公园走走吧`, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(() => window.__state === 'ready' || window.__state === 'error', { timeout: 120000, polling: 300 });
  console.log('state:', await page.evaluate(() => window.__state), 'err:', await page.evaluate(() => window.__error));

  console.log('lipsync.zh loaded:', await page.evaluate(() => !!(window.__head && window.__head.lipsync && window.__head.lipsync.zh)));
  console.log('has viseme_aa mt:', await page.evaluate(() => !!(window.__head.mtAvatar['viseme_aa'])));
  console.log('viseme_aa meshes:', await page.evaluate(() => window.__head.mtAvatar['viseme_aa'] && window.__head.mtAvatar['viseme_aa'].ms.length));

  // 录制进行中每 150ms 采样 viseme_aa 的值和队列长度
  for (let i = 0; i < 40; i++) {
    const s = await page.evaluate(() => ({
      speaking: window.__head.isSpeaking,
      queue: window.__head.animQueue.length,
      aa: window.__head.mtAvatar['viseme_aa'] ? +window.__head.mtAvatar['viseme_aa'].value.toFixed(3) : null,
      pp: window.__head.mtAvatar['viseme_PP'] ? +window.__head.mtAvatar['viseme_PP'].value.toFixed(3) : null,
      done: window.__allDone, err: window.__error
    }));
    console.log(JSON.stringify(s));
    if (s.done || s.err) break;
    await new Promise(r => setTimeout(r, 150));
  }
  await browser.close();
  cleanup();
  process.exit(0);
})().catch(e => { console.error('FAIL', e.message); process.exit(1); });
