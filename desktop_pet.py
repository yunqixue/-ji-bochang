"""桌面小人（戴安娜）  Owner: B

一个贴在 Windows 桌面上的透明小窗：会呼吸、会换站姿、能说话、能陪玩三个小游戏。
素材是 `assets/pet/diana_*.webp`（透明立绘，出自参考图抠图，见 experiments/make_cutout.py）。

用法：
    双击 启动桌面小人.cmd        ← 推荐
    或：python desktop_pet.py
    或：python desktop_pet.py --shot 预览.png   ← 不开窗口，直接截图看渲染效果（自测用）

依赖：PySide6（界面）+ PyAV（mp3 转 wav，用来播放语音）
     pip install -i https://pypi.tuna.tsinghua.edu.cn/simple PySide6-Essentials
     注意 PySide6-Essentials 不含 QtMultimedia，所以语音走"PyAV 转 wav + winsound"这条路。

和网页的关系：**不替代网页**，是一个独立的小程序。
     · 双击小人 → 打开完整聊天页（http://127.0.0.1:8000）
     · 右键「说句话」→ 直接调后端 /api/chat，回复显示在气泡里并朗读
     · 后端没开也能用：三个游戏是纯本地的，说话会给出提示而不是崩掉
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import urllib.request
import uuid

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
PET_DIR = os.path.join(REPO_ROOT, "assets", "pet")
API_BASE = os.getenv("PET_API_BASE", "http://127.0.0.1:8000")
WAV_DIR = os.path.join(REPO_ROOT, "data", "pet_audio")

# 三个姿势（都是透明立绘）
POSES = {
    "front": os.path.join(PET_DIR, "diana_front.webp"),
    "side": os.path.join(PET_DIR, "diana_side.webp"),
    "back": os.path.join(PET_DIR, "diana_back.webp"),
}


# ---------------------------------------------------------------- 语音播放
def play_mp3_via_wav(url_path: str) -> None:
    """把 mp3 转成 wav 再交给 winsound 异步播放。

    为什么不直接用 QtMultimedia：PySide6-Essentials 里没有 QtMultimedia，
    为了播放一段语音再装 200MB 的 Addons 不值。PyAV 本来就有（faster-whisper 的依赖），
    winsound 是标准库，这条路零新增依赖。
    """
    try:
        import av
        import numpy as np
        import wave
        import winsound
    except Exception:
        return
    try:
        os.makedirs(WAV_DIR, exist_ok=True)
        wav_path = os.path.join(WAV_DIR, os.path.basename(url_path) + ".wav")
        if not os.path.exists(wav_path):
            chunks = []
            with av.open(url_path) as container:
                stream = container.streams.audio[0]
                res = av.AudioResampler(format="s16", layout="mono", rate=24000)
                for frame in container.decode(stream):
                    for f in res.resample(frame):
                        chunks.append(f.to_ndarray().reshape(-1))
                for f in res.resample(None):
                    chunks.append(f.to_ndarray().reshape(-1))
            if not chunks:
                return
            pcm = np.concatenate(chunks)
            with wave.open(wav_path, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(pcm.astype("<i2").tobytes())
        winsound.PlaySound(wav_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


# ---------------------------------------------------------------- 气泡
class Bubble(QtWidgets.QWidget):
    """小人头顶的对话气泡。无边框、半透明、点一下消失。"""

    def __init__(self) -> None:
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
                         | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self._text = ""
        self._font = QtGui.QFont("Microsoft YaHei", 10)
        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def set_text(self, text: str, hold_ms: int = 4200) -> None:
        self._text = (text or "").strip()
        if not self._text:
            return
        fm = QtGui.QFontMetrics(self._font)
        max_w = 300
        rect = fm.boundingRect(QtCore.QRect(0, 0, max_w - 28, 2000),
                               QtCore.Qt.TextWordWrap, self._text)
        self.resize(max(140, rect.width() + 28), rect.height() + 26)
        self.repaint()
        self.show()
        self.raise_()
        self._hide_timer.start(max(hold_ms, 1200 + len(self._text) * 90))

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QtGui.QColor(255, 252, 246, 244))
        p.setPen(QtGui.QPen(QtGui.QColor(120, 140, 160, 90), 1))
        p.drawRoundedRect(r, 12, 12)
        # 小尖角
        path = QtGui.QPainterPath()
        cx = self.width() / 2
        path.moveTo(cx - 8, self.height() - 2)
        path.lineTo(cx, self.height() + 8)
        path.lineTo(cx + 8, self.height() - 2)
        p.setBrush(QtGui.QColor(255, 252, 246, 244))
        p.setPen(QtCore.Qt.NoPen)
        p.drawPath(path)
        p.setPen(QtGui.QColor(40, 48, 58))
        p.setFont(self._font)
        p.drawText(r.adjusted(14, 12, -14, -8), QtCore.Qt.TextWordWrap, self._text)

    def mousePressEvent(self, _event) -> None:  # noqa: N802
        self.hide()


# ---------------------------------------------------------------- 桌面小人
class DesktopPet(QtWidgets.QWidget):
    TICK_MS = 40                     # 25fps，够顺滑又不吃 CPU
    WALK_SPEED = 1.6

    def __init__(self) -> None:
        super().__init__(None, QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint
                         | QtCore.Qt.Tool)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("桌面小人")
        self.setMouseTracking(True)

        self.pose = "front"
        self.pix: dict[str, QtGui.QPixmap] = {}
        for key, path in POSES.items():
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                self.pix[key] = pm
        if not self.pix:
            raise SystemExit("❌ 找不到立绘：assets/pet/diana_*.webp")

        self.base = self.pix.get("front") or next(iter(self.pix.values()))
        self.resize(self.base.width(), self.base.height() + 10)

        self.t = 0.0
        self.walk_dir = 0
        self.muted = False
        self.dragging = False
        self.drag_delta = QtCore.QPoint()
        self.session_id = "pet-" + uuid.uuid4().hex[:8]
        self.bubble = Bubble()

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self.TICK_MS)

        self._idle_timer = QtCore.QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.timeout.connect(self._random_mood)
        self._idle_timer.start(9000)

        self.move_to_corner()

    # ---------- 位置 ----------
    def move_to_corner(self) -> None:
        g = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        self.move(g.right() - self.width() - 40, g.bottom() - self.height() - 10)

    # ---------- 动画 ----------
    def _tick(self) -> None:
        self.t += self.TICK_MS / 1000.0
        if self.walk_dir:
            g = QtGui.QGuiApplication.primaryScreen().availableGeometry()
            nx = self.x() + int(self.walk_dir * self.WALK_SPEED * (self.TICK_MS / 1000.0) * 60)
            if nx < g.left() or nx + self.width() > g.right():
                self.walk_dir = -self.walk_dir
            else:
                self.move(nx, self.y())
        if self.bubble.isVisible():
            self._place_bubble()
        self.repaint()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        pm = self.pix.get(self.pose, self.base)

        # 呼吸：极缓慢的纵向缩放；走动时上下颠一下
        breathe = 1.0 + 0.012 * math.sin(self.t * 1.6)
        bob = math.sin(self.t * 6.0) * 3.0 if self.walk_dir else 0.0
        # 站立时的轻微摇摆，像在重心换脚
        sway = math.sin(self.t * 0.9) * 0.8 if not self.walk_dir else 0.0

        cx = self.width() / 2
        p.translate(cx, self.height() - 4 + bob)
        p.rotate(sway)
        p.scale(1.0, breathe)
        p.drawPixmap(QtCore.QRectF(-cx, -pm.height(), pm.width(), pm.height()),
                     pm, QtCore.QRectF(pm.rect()))

    # ---------- 鼠标 ----------
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == QtCore.Qt.LeftButton:
            self.dragging = True
            self.drag_delta = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self.dragging and (e.buttons() & QtCore.Qt.LeftButton):
            self.move(e.globalPosition().toPoint() - self.drag_delta)
            if self.bubble.isVisible():
                self._place_bubble()
            e.accept()

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self.dragging = False
        e.accept()

    def mouseDoubleClickEvent(self, _e) -> None:  # noqa: N802
        self.open_web()

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        m = QtWidgets.QMenu(self)
        m.addAction("说句话…", self.ask_and_talk)
        m.addSeparator()
        m.addAction("玩：猜数字", self.game_guess)
        m.addAction("玩：石头剪刀布", self.game_rps)
        m.addAction("玩：词语接龙", self.game_word_chain)
        m.addSeparator()
        m.addAction("换个站姿", self.cycle_pose)
        m.addAction("走两步", self.walk_around)
        act_mute = m.addAction("静音")
        act_mute.setCheckable(True)
        act_mute.setChecked(self.muted)
        act_mute.triggered.connect(self.toggle_mute)
        m.addSeparator()
        m.addAction("打开完整聊天页", self.open_web)
        m.addAction("退出", self.close)
        m.exec(e.globalPos())

    # ---------- 气泡 ----------
    def _place_bubble(self) -> None:
        g = QtGui.QGuiApplication.primaryScreen().availableGeometry()
        bx = self.x() + self.width() // 2 - self.bubble.width() // 2
        by = self.y() - self.bubble.height() - 12
        bx = max(g.left() + 4, min(bx, g.right() - self.bubble.width() - 4))
        by = max(g.top() + 4, by)
        self.bubble.move(bx, by)

    def say(self, text: str, hold_ms: int = 4200) -> None:
        self.bubble.set_text(text, hold_ms)
        self._place_bubble()

    # ---------- 动作 ----------
    def cycle_pose(self) -> None:
        order = ["front", "side", "back"]
        cur = order.index(self.pose) if self.pose in order else 0
        for step in range(1, len(order) + 1):
            nxt = order[(cur + step) % len(order)]
            if nxt in self.pix:
                self.pose = nxt
                break
        self.repaint()

    def walk_around(self) -> None:
        self.walk_dir = random.choice([-1, 1])
        if "side" in self.pix:
            self.pose = "side"
        QtCore.QTimer.singleShot(2600, self._stop_walk)

    def _stop_walk(self) -> None:
        self.walk_dir = 0
        self.pose = "front"

    def _random_mood(self) -> None:
        if self.bubble.isVisible():
            self._idle_timer.start(9000)
            return
        if random.random() < 0.35:
            self.cycle_pose()
        self._idle_timer.start(random.randint(12000, 22000))

    def toggle_mute(self, checked: bool) -> None:
        self.muted = checked

    def open_web(self) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(API_BASE))

    # ---------- 说话（走后端） ----------
    def ask_and_talk(self) -> None:
        text, ok = QtWidgets.QInputDialog.getText(self, "跟她说句话", "你：")
        if not ok or not text.strip():
            return
        self.talk(text.strip())

    def talk(self, text: str) -> None:
        self.say("……", 1500)
        QtWidgets.QApplication.processEvents()
        threading_call(lambda: self._talk_worker(text))

    def _talk_worker(self, text: str) -> None:
        reply, audio, err = "", "", ""
        try:
            boundary = "----pet" + uuid.uuid4().hex
            body = b""
            for name, value in (("session_id", self.session_id), ("text", text)):
                body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                         f"{value}\r\n").encode("utf-8")
            body += f"--{boundary}--\r\n".encode("utf-8")
            req = urllib.request.Request(
                API_BASE + "/api/chat", data=body, method="POST",
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            reply = ((data.get("response") or {}).get("reply_text") or "").strip()
            audio = data.get("audio_url") or ""
        except Exception as exc:                     # noqa: BLE001
            err = f"{type(exc).__name__}"
        QtCore.QTimer.singleShot(0, lambda: self._talk_done(reply, audio, err))

    def _talk_done(self, reply: str, audio: str, err: str) -> None:
        if err or not reply:
            self.say("连不上后端的聊天服务。\n先双击 run.cmd 把服务开起来，再试一次～\n（三个小游戏不用开服务也能玩）",
                     hold_ms=6000)
            return
        self.say(reply)
        if audio and not self.muted:
            path = os.path.join(REPO_ROOT, "src", "presentation", "static", "tts",
                                os.path.basename(audio))
            if os.path.exists(path):
                threading_call(lambda: play_mp3_via_wav(path))
            else:
                full = audio if audio.startswith("http") else API_BASE + audio
                tmp = os.path.join(WAV_DIR, os.path.basename(audio))
                os.makedirs(WAV_DIR, exist_ok=True)

                def grab():
                    try:
                        urllib.request.urlretrieve(full, tmp)
                        play_mp3_via_wav(tmp)
                    except Exception:
                        pass
                threading_call(grab)

    # ---------- 三个小游戏 ----------
    def game_guess(self) -> None:
        target = random.randint(1, 100)
        tries = 0
        self.say(f"我想好了一个 1 到 100 的数，你猜猜看？", 5000)
        while True:
            text, ok = QtWidgets.QInputDialog.getText(self, "猜数字", f"第 {tries + 1} 次，你猜：")
            if not ok:
                self.say("好，不玩了，歇会儿～")
                return
            try:
                guess = int("".join(ch for ch in text if ch.isdigit()))
            except ValueError:
                self.say("要猜数字哦，像 37 这样。")
                continue
            tries += 1
            if guess == target:
                msg = (f"对啦！就是 {target}，你只用了 {tries} 次。"
                       if tries <= 6 else f"对啦，是 {target}。猜了 {tries} 次，下回再快点儿？")
                self.say(msg, 6000)
                return
            hint = "再大一点" if guess < target else "再小一点"
            far = abs(guess - target) > 20
            self.say(f"{guess} 呀…{hint}{'，差得有点远' if far else ''}。", 4000)
            if tries >= 10:
                self.say(f"次数用完啦，我想的是 {target}。要不要再来一局？", 6000)
                return

    RPS = {"石头": "剪刀", "剪刀": "布", "布": "石头"}

    def game_rps(self) -> None:
        win = lose = draw = 0
        self.say("石头剪刀布！你先出～", 4000)
        for _ in range(3):
            text, ok = QtWidgets.QInputDialog.getText(self, "石头剪刀布", "你出（石头 / 剪刀 / 布）：")
            if not ok:
                break
            mine = next((k for k in self.RPS if k in (text or "")), "")
            if not mine:
                self.say("要出「石头」「剪刀」或「布」哦。")
                continue
            pet = random.choice(list(self.RPS))
            if pet == mine:
                draw += 1
                r = "平了！"
            elif self.RPS[mine] == pet:
                win += 1
                r = "这局你赢。"
            else:
                lose += 1
                r = "这局我赢！"
            self.say(f"我出{pet}，你出{mine}——{r}（你 {win} 胜 {lose} 负 {draw} 平）", 5000)
        self.say(f"三局结束：你 {win} 胜 {lose} 负 {draw} 平。再玩一次？", 6000)

    # 接龙词库：够用就行，接不上就说接不上（这比瞎编一个词诚实）
    WORDS = ["天空", "空气", "气球", "球鞋", "鞋带", "带来", "来回", "回家", "家里", "里面",
             "面包", "包子", "子弹", "弹珠", "珠宝", "宝贝", "贝壳", "壳子", "紫色", "色彩",
             "彩虹", "虹桥", "桥头", "头发", "发明", "明天", "天空", "糖果", "果汁", "汁水",
             "水果", "果冻", "冻住", "住手", "手心", "心情", "情况", "况且", "且慢", "慢慢"]

    def game_word_chain(self) -> None:
        used: set[str] = set()
        cur = random.choice(self.WORDS)
        used.add(cur)
        self.say(f"词语接龙！我先来：{cur}", 5000)
        for _ in range(8):
            last = cur[-1]
            text, ok = QtWidgets.QInputDialog.getText(
                self, "词语接龙", f"要接「{last}」开头的词（两个字就行）：")
            if not ok:
                break
            word = (text or "").strip()
            if len(word) < 2:
                self.say("两个字以上哦。")
                continue
            if word[0] != last:
                self.say(f"这个开头是「{word[0]}」，要接「{last}」开头～")
                continue
            if word in used:
                self.say("这个我刚说过啦，换一个？")
                continue
            used.add(word)
            cands = [w for w in self.WORDS if w.startswith(word[-1]) and w not in used]
            if not cands:
                self.say(f"{word}！这个我接不上了……你赢了。", 6000)
                return
            cur = random.choice(cands)
            used.add(cur)
            self.say(f"{word} → 我接：{cur}", 5000)
        self.say("接得挺好，先到这儿～", 4000)


# ---------------------------------------------------------------- 工具
def threading_call(fn) -> None:
    """简单的后台线程执行，别让 HTTP/音频把界面卡住。"""
    import threading
    threading.Thread(target=fn, daemon=True).start()


def grab_preview(path: str) -> int:
    """离屏渲染一张图（自测用：不弹窗也能看到小人画出来的样子）。"""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    pet = DesktopPet()
    pet.resize(pet.base.width(), pet.base.height() + 10)
    pm = QtGui.QPixmap(pet.size())
    pm.fill(QtCore.Qt.transparent)
    pet.render(pm)
    pm.save(path)
    print("已保存预览：" + path)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="桌面小人（戴安娜）")
    ap.add_argument("--shot", help="不弹窗，只渲染一张预览图（自测用）")
    args = ap.parse_args()
    if args.shot:
        return grab_preview(args.shot)

    app = QtWidgets.QApplication(sys.argv)
    pet = DesktopPet()
    pet.show()
    pet.say("我在这儿啦～ 右键看看能做什么", 5000)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
