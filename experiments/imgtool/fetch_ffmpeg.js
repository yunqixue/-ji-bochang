// 下载 ffmpeg 静态二进制。
// 为什么用 Node 而不是 PowerShell：这台机器 PowerShell 的 HTTPS 走 schannel，报
// 「基础连接已经关闭: 接收时发生错误」，git pull 也是同一个病；Node 自己的 TLS 栈是通的。
// 为什么不用 npm install ffmpeg-static：它的 postinstall 要 spawn 子进程拉二进制，
// 沙箱里 spawn 管道会 EPERM。这里直接 fetch。
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const OUT_DIR = path.resolve(__dirname, 'bin');
const OUT = path.join(OUT_DIR, 'ffmpeg.exe');

const CANDIDATES = [
  'https://github.com/eugeneware/ffmpeg-static/releases/download/b6.0/ffmpeg-win32-x64.gz',
  'https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.0/ffmpeg-win32-x64.gz',
  'https://cdn.npmmirror.com/binaries/ffmpeg-static/b6.0/ffmpeg-win32-x64.gz',
];

(async () => {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  let lastErr;
  for (const url of CANDIDATES) {
    process.stdout.write(`try ${url}\n`);
    try {
      const res = await fetch(url, { redirect: 'follow' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const gz = Buffer.from(await res.arrayBuffer());
      process.stdout.write(`  下载 ${(gz.length / 1048576).toFixed(1)} MB，解压…\n`);
      const exe = zlib.gunzipSync(gz);
      fs.writeFileSync(OUT, exe);
      process.stdout.write(`  写入 ${OUT}（${(exe.length / 1048576).toFixed(1)} MB）\n`);
      return;
    } catch (e) {
      lastErr = e;
      process.stdout.write(`  失败：${e.message}\n`);
    }
  }
  process.stdout.write(`全部失败：${lastErr && lastErr.message}\n`);
  process.exit(1);
})();
