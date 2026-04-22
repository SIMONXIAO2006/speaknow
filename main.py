"""即声 SpeakNow v4.3 - 全局热键 + 现代波形窗 + 双标点模式 + 热词

操作：
  Ctrl+Q          启停录音
  Ctrl+Shift+Q    切换标点模式（智能标点 / 无标点）

功能：
  - 波形窗：两行预览文字，实时显示识别结果
  - 热词表：.hotwords.json，每次录音自动注入 ASR，提升专业术语准确率
  - 托盘菜单"编辑热词表"：用记事本打开热词文件
"""

import json
import os
import sys
import time
import queue
import logging
import threading
import winsound

import numpy as np
import sounddevice as sd
import keyboard
import pystray
from PIL import Image, ImageDraw

from config import (
    SAMPLE_RATE, SEND_INTERVAL_S, HOTKEY, PUNC_TOGGLE_HOTKEY,
    PUNC_SMART, PUNC_NONE, SETTINGS_FILE, HOTWORDS_FILE,
    IDLE_TIMEOUT_S, VOICE_RMS_THRESHOLD, AUDIO_GAIN,
)
from asr_streaming import StreamingASR
from waveform import WaveformWindow

# ── 日志配置（降噪：第三方库只记WARNING以上） ──
logging.basicConfig(
    filename="speaknow.log",
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
for _noisy in ("PIL", "urllib3", "requests", "websocket"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)
log = logging.getLogger(__name__)


def do_type(text: str):
    """模拟 Ctrl+V 粘贴文字到当前焦点窗口"""
    import pyperclip
    old = pyperclip.paste()
    pyperclip.copy(text)
    time.sleep(0.05)
    keyboard.send("ctrl+v")
    time.sleep(0.2)
    try:
        pyperclip.copy(old)
    except Exception:
        pass


def load_punc_mode() -> bool:
    """读取标点模式偏好，True=智能标点（默认），False=无标点"""
    try:
        if SETTINGS_FILE.exists():
            d = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            return d.get("punc_smart", True)
    except Exception:
        pass
    return True


def save_punc_mode(smart: bool):
    """保存标点模式偏好"""
    try:
        SETTINGS_FILE.write_text(
            json.dumps({"punc_smart": smart}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_hotwords() -> list[str]:
    """加载热词表，返回字符串列表"""
    try:
        if HOTWORDS_FILE.exists():
            data = json.loads(HOTWORDS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(w).strip() for w in data if str(w).strip()]
    except Exception:
        pass
    return []


class App:
    def __init__(self):
        self._lock = threading.Lock()
        self._recording = False
        self._session_active = False
        self._wave = WaveformWindow()
        self._icon = None

        # 标点模式
        self._punc_smart = load_punc_mode()
        self._wave.set_punc_mode(self._punc_smart)

        self._wave.set_toggle_callback(self._toggle_recording)

    @property
    def _punc_params(self) -> dict:
        return PUNC_SMART if self._punc_smart else PUNC_NONE

    def _toggle_punc_mode(self):
        """切换标点模式"""
        self._punc_smart = not self._punc_smart
        self._wave.set_punc_mode(self._punc_smart)
        save_punc_mode(self._punc_smart)
        mode_name = "智能标点" if self._punc_smart else "无标点"
        log.info("Punctuation mode: %s", mode_name)

        # 如果正在录音，先停掉（新参数下次录音才生效）
        was_recording = self._session_active
        if was_recording:
            self._stop_recording()

        # 更新托盘菜单文字 + 通知
        if self._icon:
            try:
                self._icon.update_menu()
                hint = "下次录音生效" if was_recording else ""
                self._icon.notify(f"已切换：{mode_name} {hint}", "即声 SpeakNow")
            except Exception:
                pass

    def _toggle_recording(self):
        if self._session_active:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        with self._lock:
            if self._session_active:
                return
            self._session_active = True
            self._recording = True
        threading.Thread(target=self._record_session, daemon=True).start()

    def _stop_recording(self):
        self._recording = False

    def _record_session(self):
        try:
            self._wave.show(recording=True)

            asr = StreamingASR()
            result_queue: queue.Queue[str] = queue.Queue()

            def on_result(text: str, definite: bool):
                if definite:
                    result_queue.put(text)

            def on_preview(full_text: str):
                self._wave.update_preview(full_text)

            def on_fix_prev():
                """回溯修正上一句的句号->逗号"""
                import pyperclip
                keyboard.send('backspace')
                time.sleep(0.03)
                pyperclip.copy("，")
                keyboard.send('ctrl+v')
                time.sleep(0.05)

            hotwords = load_hotwords()
            asr.start(on_result, on_preview, on_fix_prev,
                      punc_params=self._punc_params, hotwords=hotwords)
            log.info("ASR mode: %s, punc: %s, hotwords: %d",
                     asr.mode, "smart" if self._punc_smart else "none", len(hotwords))
            winsound.Beep(880, 150)

            audio_queue: queue.Queue[np.ndarray] = queue.Queue()
            seq = 1

            def audio_callback(indata: np.ndarray, _frames, _ti, _status):
                chunk = indata.flatten()
                audio_queue.put(chunk.copy())
                self._wave.update_waveform(chunk)

            try:
                with sd.InputStream(
                    samplerate=SAMPLE_RATE, channels=1,
                    dtype="int16", blocksize=320,
                    callback=audio_callback,
                ):
                    session_start = time.time()
                    has_speech = False
                    idle_start = None

                    while self._recording:
                        time.sleep(SEND_INTERVAL_S)
                        chunks = []
                        while not audio_queue.empty():
                            try:
                                chunks.append(audio_queue.get_nowait())
                            except queue.Empty:
                                break

                        if chunks:
                            # 检测是否有有效语音（RMS超过阈值）
                            for ch in chunks:
                                rms = np.sqrt(np.mean(ch.astype(np.float32) ** 2))
                                if rms > VOICE_RMS_THRESHOLD:
                                    if not has_speech:
                                        has_speech = True
                                    idle_start = None
                                    break

                            # 音频增益（放大信号，适合小声/嘈杂环境）
                            pcm_data = np.concatenate(chunks).astype(np.float32)
                            if AUDIO_GAIN != 1.0:
                                pcm_data = np.clip(pcm_data * AUDIO_GAIN, -32768, 32767)
                            pcm = pcm_data.astype(np.int16).tobytes()
                            asr.send_audio(pcm, seq)
                            seq += 1

                        # 30秒无有效语音 → 自动停止
                        if not has_speech:
                            elapsed = time.time() - session_start
                            if elapsed >= IDLE_TIMEOUT_S:
                                log.info("Idle timeout (%.0fs no speech), auto-stop", elapsed)
                                self._recording = False
                        self._drain_results(result_queue)
            except Exception as e:
                log.error("Recording error: %s", e)

            asr.send_finish(seq)

            # 等待最后结果：最多 2 秒，空闲 0.8 秒提前退出
            idle_since = time.time()
            deadline = time.time() + 2.0
            while time.time() < deadline:
                self._drain_results(result_queue)
                if result_queue.empty():
                    if time.time() - idle_since > 0.8:
                        break
                    time.sleep(0.1)
                else:
                    idle_since = time.time()

            asr.close()
        except Exception as e:
            log.error("Session error: %s", e)
        finally:
            winsound.Beep(660, 100)
            with self._lock:
                self._session_active = False
                self._recording = False
            self._wave.show(recording=False)

    def _drain_results(self, result_queue: queue.Queue):
        while not result_queue.empty():
            try:
                text = result_queue.get_nowait()
                if text.strip():
                    log.info("Typing: %s", text[:50])
                    do_type(text)
            except queue.Empty:
                break

    def _punc_menu_text(self, _icon=None):
        return "标点: 智能模式" if self._punc_smart else "标点: 无标点模式"

    def run(self):
        winsound.Beep(1000, 100)
        winsound.Beep(1200, 100)

        self._wave.show(recording=False)

        # 注册全局热键
        keyboard.add_hotkey(HOTKEY, self._toggle_recording)
        keyboard.add_hotkey(PUNC_TOGGLE_HOTKEY, self._toggle_punc_mode)
        log.info("Hotkey registered: %s (record), %s (punc toggle)", HOTKEY, PUNC_TOGGLE_HOTKEY)

        ico_path = os.path.join(os.path.dirname(__file__), "app.ico")
        icon_img = (
            Image.open(ico_path) if os.path.exists(ico_path) else self._make_icon()
        )

        menu = pystray.Menu(
            pystray.MenuItem(self._punc_menu_text, self._on_menu_toggle_punc),
            pystray.MenuItem("编辑热词表", self._on_menu_edit_hotwords),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(f"录音: {HOTKEY}", lambda: None, enabled=False),
            pystray.MenuItem(f"标点: {PUNC_TOGGLE_HOTKEY}", lambda: None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._quit),
        )

        self._icon = pystray.Icon(
            "speaknow", icon_img,
            f"即声 SpeakNow v4.3 [{HOTKEY}]",
            menu=menu,
        )

        def notify_startup():
            time.sleep(1.5)
            try:
                self._icon.notify(f"Press {HOTKEY} to record, {PUNC_TOGGLE_HOTKEY} to toggle punctuation", "即声 SpeakNow")
            except Exception:
                pass

        threading.Thread(target=notify_startup, daemon=True).start()
        self._icon.run()

    def _on_menu_toggle_punc(self, icon, _item):
        self._toggle_punc_mode()

    @staticmethod
    def _on_menu_edit_hotwords(_icon, _item):
        """用记事本打开热词表"""
        import subprocess
        if not HOTWORDS_FILE.exists():
            HOTWORDS_FILE.write_text(
                '["Python", "GitHub", "VS Code", "AI"]\n',
                encoding="utf-8",
            )
        subprocess.Popen(["notepad", str(HOTWORDS_FILE)])

    @staticmethod
    def _make_icon():
        img = Image.new("RGB", (64, 64), "#4CC2FF")
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([22, 8, 42, 36], radius=10, fill="white")
        draw.arc([14, 24, 50, 48], 0, 180, fill="white", width=3)
        draw.line([32, 48, 32, 56], fill="white", width=3)
        draw.line([24, 56, 40, 56], fill="white", width=3)
        return img

    @staticmethod
    def _quit(icon, _item):
        keyboard.unhook_all()
        icon.stop()
        sys.exit(0)


if __name__ == "__main__":
    App().run()
