"""即声 SpeakNow v4.3 - 现代波形悬浮窗（Canvas 矢量渲染）

- DPI 感知 + Canvas 矢量绘制（高分辨率清晰）
- 贝塞尔曲线波形（smooth=True, splinesteps=36）
- Win11 DWM 原生圆角（无黑角锯齿）+ 亚克力模糊
- 可拖拽 + 位置记忆
- Apple 风格柔和配色
- 两行预览 + 标点标签移入波形区
"""

import ctypes

# ── DPI 感知（必须在创建任何窗口前调用）──
for _fn in (
    lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
    lambda: ctypes.windll.user32.SetProcessDPIAware(),
):
    try:
        _fn()
        break
    except Exception:
        pass

import collections
import json
import threading
import tkinter as tk
import tkinter.font as tkfont
import numpy as np
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk

from config import CHUNK_DURATION_MS

BUFFER_CHUNKS = int(1000 / CHUNK_DURATION_MS)

# ── 窗口尺寸（逻辑像素） ──
WIN_W = 280
WIN_H = 96
CORNER_R = 14
POS_FILE = Path(__file__).parent / ".window_pos.json"

# ── 波形区域 ──
WAVE_L = 14
WAVE_TOP = 8
WAVE_BOT = 36

# ── 按钮区域 ──
BTN_SZ = 28
BTN_X = WIN_W - 12 - BTN_SZ
BTN_Y = (WAVE_TOP + WAVE_BOT - BTN_SZ) // 2
BTN_BBOX = (BTN_X, BTN_Y, BTN_X + BTN_SZ, BTN_Y + BTN_SZ)
BTN_CX = BTN_X + BTN_SZ // 2
BTN_CY = BTN_Y + BTN_SZ // 2

# ── 波形区域（派生） ──
WAVE_R = BTN_X - 10
WAVE_MID = (WAVE_TOP + WAVE_BOT) // 2
WAVE_HALF = (WAVE_BOT - WAVE_TOP) // 2
WAVE_W = WAVE_R - WAVE_L

# ── 音量条 ──
BAR_Y = 40
BAR_H = 4

# ── 预览文字（两行，像素级宽度控制） ──
PREVIEW_Y1 = 54
PREVIEW_Y2 = 72
TEXT_MAX_W = WAVE_R - WAVE_L   # 预览文字最大像素宽度 = 波形区域宽度
PV_FONT = ("Segoe UI Variable", 9)

# ── Apple 风格柔和配色 ──
C_BG          = "#1E1E2E"
C_WAVE_BG     = "#262638"
C_WAVE_SHADOW = "#2A5070"
C_WAVE        = "#7EB8DA"     # 柔和天蓝
C_WAVE_HI     = "#B0D8ED"
C_MIDLINE     = "#333348"
C_BAR_BG      = "#2C2C40"
C_VOL_OK      = "#7EB8DA"
C_VOL_WARN    = "#E8C468"
C_VOL_HOT     = "#E06060"
C_BTN_IDLE    = "#5AB0D8"
C_BTN_IDLE_BD = "#4899BF"
C_BTN_REC     = "#E06060"
C_BTN_REC_BD  = "#BF4F4F"
C_TEXT        = "#E4E4EA"
C_HINT        = "#707088"


class WaveformWindow:
    """v3.0 现代波形悬浮窗 - Canvas 矢量渲染"""

    def __init__(self):
        self._ready = threading.Event()
        self._visible = False
        self._recording = False
        self._on_toggle = None
        self._draw_pending = False
        self._punc_smart = True  # True=智能标点, False=无标点

        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        self._ready.wait(timeout=3)

        self._buffer: collections.deque[np.ndarray] = collections.deque(
            maxlen=BUFFER_CHUNKS
        )
        self._preview_text = ""
        self._volume = 0.0

    def set_toggle_callback(self, callback):
        self._on_toggle = callback

    def set_punc_mode(self, smart: bool):
        """设置标点模式：smart=True智能标点，smart=False无标点"""
        self._punc_smart = smart
        self._request_draw()

    # ── tkinter 主线程 ──────────────────────

    def _run(self):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.withdraw()

        # 定时刷新置顶（防止被其他窗口抢占）
        self._keep_topmost()

        self._setup_win32()
        self._place_initial()

        # 字体测量对象（用于像素级文字宽度计算）
        self._pv_font = tkfont.Font(self.root, PV_FONT)

        self.canvas = tk.Canvas(
            self.root, width=WIN_W, height=WIN_H,
            bg=C_BG, highlightthickness=0,
        )
        self.canvas.pack()

        # 生成高质量按钮图标（3x超采样抗锯齿）
        self._btn_play = self._make_play_btn()
        self._btn_stop = self._make_stop_btn()

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._drag_start = (0, 0)
        self._dragging = False

        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        self._ready.set()
        self.root.mainloop()

    # ── Win32 窗口美化 ─────────────────────

    def _setup_win32(self):
        hwnd = self.root.winfo_id()
        GWL_EXSTYLE = -20
        ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, ex | 0x08000000 | 0x00000080
        )

        # Win11 原生圆角（系统级抗锯齿，无黑角）
        self._try_native_rounded(hwnd)

        # 亚克力模糊
        self._try_acrylic(hwnd)

    def _try_native_rounded(self, hwnd):
        """圆角：Win11 用 DWM（无黑角），Win10 用 GDI 兜底"""
        dwm_ok = False
        try:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWMWCP_ROUND = 2
            val = ctypes.c_int(DWMWCP_ROUND)
            hr = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(val), ctypes.sizeof(val),
            )
            dwm_ok = (hr == 0)
        except Exception:
            pass
        if not dwm_ok:
            # Win10 fallback: GDI 圆角
            rgn = ctypes.windll.gdi32.CreateRoundRectRgn(
                0, 0, WIN_W + 1, WIN_H + 1, CORNER_R * 2, CORNER_R * 2
            )
            ctypes.windll.user32.SetWindowRgn(hwnd, rgn, True)

    def _try_acrylic(self, hwnd):
        try:
            class AP(ctypes.Structure):
                _fields_ = [
                    ("AccentState", ctypes.c_int),
                    ("AccentFlags", ctypes.c_int),
                    ("GradientColor", ctypes.c_uint),
                    ("AnimationId", ctypes.c_int),
                ]

            class WCA(ctypes.Structure):
                _fields_ = [
                    ("Attribute", ctypes.c_int),
                    ("Data", ctypes.POINTER(AP)),
                    ("SizeOfData", ctypes.c_size_t),
                ]

            ap = AP()
            ap.AccentState = 4
            ap.AccentFlags = 2
            ap.GradientColor = 0xCC1E1E2E

            wca = WCA()
            wca.Attribute = 19
            wca.Data = ctypes.pointer(ap)
            wca.SizeOfData = ctypes.sizeof(ap)
            ctypes.windll.user32.SetWindowCompositionAttribute(
                hwnd, ctypes.byref(wca)
            )
        except Exception:
            pass

    # ── 高质量按钮图标（PIL 3x超采样） ────────

    @staticmethod
    def _make_play_btn() -> ImageTk.PhotoImage:
        """播放按钮：蓝色圆 + 白色三角 + 阴影，3x抗锯齿"""
        s = 3  # 超采样倍率
        sz = BTN_SZ * s  # 84
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # 投影（右下偏移）
        d.ellipse([3*s, 3*s, sz-1, sz-1], fill=(0, 0, 0, 40))
        # 主体圆
        pad = 3 * s
        d.ellipse([0, 0, sz-pad-1, sz-pad-1], fill=(90, 176, 216))
        # 高光环（上半部亮一点）
        d.ellipse([2*s, 2*s, sz-pad-2*s-1, sz-pad-2*s-1], outline=(160, 210, 235, 120), width=s)
        # 播放三角（偏右补偿视觉重心）
        cx, cy = (sz-pad)//2, (sz-pad)//2
        d.polygon([
            (cx - 5*s, cy - 7*s),
            (cx - 5*s, cy + 7*s),
            (cx + 8*s, cy),
        ], fill=(255, 255, 255, 230))

        img = img.resize((BTN_SZ, BTN_SZ), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    @staticmethod
    def _make_stop_btn() -> ImageTk.PhotoImage:
        """停止按钮：红色圆 + 白色圆角方块 + 阴影"""
        s = 3
        sz = BTN_SZ * s
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)

        # 投影
        d.ellipse([3*s, 3*s, sz-1, sz-1], fill=(0, 0, 0, 40))
        # 主体圆
        pad = 3 * s
        d.ellipse([0, 0, sz-pad-1, sz-pad-1], fill=(224, 96, 96))
        # 高光环
        d.ellipse([2*s, 2*s, sz-pad-2*s-1, sz-pad-2*s-1], outline=(240, 160, 160, 100), width=s)
        # 停止方块（圆角）
        cx, cy = (sz-pad)//2, (sz-pad)//2
        sq = 5 * s
        d.rounded_rectangle([cx-sq, cy-sq, cx+sq, cy+sq], radius=2*s, fill=(255, 255, 255, 230))

        img = img.resize((BTN_SZ, BTN_SZ), Image.LANCZOS)
        return ImageTk.PhotoImage(img)

    # ── 位置管理 ────────────────────────────

    def _place_initial(self):
        pos = self._load_pos()
        if pos:
            self.root.geometry(f"{WIN_W}x{WIN_H}+{pos[0]}+{pos[1]}")
        else:
            sw = self.root.winfo_screenwidth()
            self.root.geometry(f"{WIN_W}x{WIN_H}+{sw - WIN_W - 30}+30")

    def _load_pos(self):
        try:
            if POS_FILE.exists():
                d = json.loads(POS_FILE.read_text(encoding="utf-8"))
                x, y = d.get("x"), d.get("y")
                if isinstance(x, int) and isinstance(y, int):
                    return x, y
        except Exception:
            pass
        return None

    def _save_pos(self):
        try:
            self.root.update_idletasks()
            POS_FILE.write_text(
                json.dumps({"x": self.root.winfo_x(), "y": self.root.winfo_y()}),
                encoding="utf-8",
            )
        except Exception:
            pass

    # ── 拖拽 ────────────────────────────────

    def _on_press(self, event):
        self._drag_start = (event.x_root, event.y_root)
        self._dragging = False

    def _on_motion(self, event):
        dx = event.x_root - self._drag_start[0]
        dy = event.y_root - self._drag_start[1]
        if not self._dragging and (abs(dx) > 3 or abs(dy) > 3):
            self._dragging = True
        if self._dragging:
            x = self.root.winfo_x() + dx
            y = self.root.winfo_y() + dy
            self.root.geometry(f"+{x}+{y}")
            self._drag_start = (event.x_root, event.y_root)

    def _on_release(self, event):
        if self._dragging:
            self._save_pos()
            return
        bx1, by1, bx2, by2 = BTN_BBOX
        if bx1 <= event.x <= bx2 and by1 <= event.y <= by2:
            if self._on_toggle:
                self._on_toggle()

    # ── 外部控制（与 v2.0 接口一致） ────────

    def show(self, recording=False):
        self._recording = recording
        if not self._visible:
            self._visible = True
            self._buffer.clear()
            self._preview_text = ""
            self._volume = 0.0
            try:
                self.root.after(0, self._do_show)
            except Exception:
                pass
        else:
            self._request_draw()

    def hide(self):
        if self._visible:
            self._visible = False
            self._recording = False
            self._buffer.clear()
            self._preview_text = ""
            try:
                self.root.after(0, self._do_hide)
            except Exception:
                pass

    def _do_show(self):
        self.root.deiconify()
        self._request_draw()

    def _do_hide(self):
        self.root.withdraw()

    def _keep_topmost(self):
        """每秒刷新置顶，防止被其他窗口抢走"""
        if self._visible:
            try:
                self.root.attributes("-topmost", True)
            except Exception:
                pass
        try:
            self.root.after(1000, self._keep_topmost)
        except Exception:
            pass

    # ── 数据更新 ────────────────────────────

    def update_waveform(self, chunk: np.ndarray):
        if not self._visible:
            return
        self._buffer.append(chunk.copy())
        rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
        self._volume = min(1.0, rms / 8000.0)
        self._request_draw()

    def update_preview(self, text: str):
        if not self._visible or text == self._preview_text:
            return
        self._preview_text = text
        self._request_draw()

    def _request_draw(self):
        if self._draw_pending:
            return
        self._draw_pending = True
        try:
            self.root.after(50, self._render)
        except Exception:
            self._draw_pending = False

    # ── Canvas 矢量绘制 ────────────────────

    def _render(self):
        self._draw_pending = False
        if not self._visible:
            return

        c = self.canvas
        c.delete("all")

        # ── 波形区域背景 ──
        c.create_rectangle(
            WAVE_L - 2, WAVE_TOP - 2, WAVE_R + 2, WAVE_BOT + 2,
            fill=C_WAVE_BG, outline="",
        )

        # ── 中线（静默时可见） ──
        c.create_line(
            WAVE_L, WAVE_MID, WAVE_R, WAVE_MID,
            fill=C_MIDLINE, width=1, dash=(3, 6),
        )

        # ── 波形曲线（三层：阴影 + 主线 + 高光） ──
        if len(self._buffer) > 0:
            all_data = np.concatenate(list(self._buffer))
            n = WAVE_W
            if len(all_data) > n:
                idx = np.linspace(0, len(all_data) - 1, n).astype(int)
                samples = all_data[idx]
            else:
                samples = all_data

            max_v = np.max(np.abs(samples.astype(np.float32))) + 1e-6
            scaled = (samples / max_v) * WAVE_HALF * 0.85

            pts = []
            for i, s in enumerate(scaled):
                pts.extend([WAVE_L + i, WAVE_MID - float(s)])

            if len(pts) >= 4:
                # 阴影层（宽、深色）
                c.create_line(
                    *pts, fill=C_WAVE_SHADOW, width=6,
                    smooth=True, splinesteps=36, capstyle="round",
                )
                # 主线（亮蓝色）
                c.create_line(
                    *pts, fill=C_WAVE, width=2,
                    smooth=True, splinesteps=36, capstyle="round",
                )
                # 高光层（细、浅色）
                c.create_line(
                    *pts, fill=C_WAVE_HI, width=1,
                    smooth=True, splinesteps=36, capstyle="round",
                )

        # ── 音量条 ──
        c.create_rectangle(
            WAVE_L, BAR_Y, WAVE_R, BAR_Y + BAR_H,
            fill=C_BAR_BG, outline="",
        )
        fill_w = int(WAVE_W * self._volume)
        if fill_w > 0:
            vc = C_VOL_OK if self._volume < 0.3 else C_VOL_WARN if self._volume < 0.7 else C_VOL_HOT
            c.create_rectangle(
                WAVE_L, BAR_Y, WAVE_L + fill_w, BAR_Y + BAR_H,
                fill=vc, outline="",
            )

        # ── 预览文字（两行，像素级裁剪） ──
        if self._preview_text and self._preview_text != "...":
            raw = self._preview_text
            mw = TEXT_MAX_W

            # 从末尾取尽可能多的字填满一行
            n = len(raw)
            while n > 0 and self._pv_font.measure(raw[-n:]) > mw:
                n -= 1

            if n >= len(raw):
                # 一行就够了
                c.create_text(
                    WAVE_L, PREVIEW_Y1, text=raw, fill=C_TEXT,
                    font=PV_FONT, anchor="w",
                )
            else:
                # 两行：line2 = 末尾能放下的，line1 = 剩余部分
                line2 = raw[-n:]
                rest = raw[:-n]
                # line1 裁剪：从头砍到能放下，加 "..."
                if rest and self._pv_font.measure(rest) <= mw:
                    line1 = rest
                else:
                    while rest and self._pv_font.measure("..." + rest) > mw:
                        rest = rest[1:]
                    line1 = "..." + rest if rest else ""
                c.create_text(
                    WAVE_L, PREVIEW_Y1, text=line1, fill=C_TEXT,
                    font=PV_FONT, anchor="w",
                )
                c.create_text(
                    WAVE_L, PREVIEW_Y2, text=line2, fill=C_TEXT,
                    font=PV_FONT, anchor="w",
                )
        elif self._recording:
            c.create_text(
                WAVE_L, PREVIEW_Y1, text="正在聆听...", fill=C_HINT,
                font=PV_FONT, anchor="w",
            )

        # ── 按钮（PIL 高质量图标） ──
        btn_img = self._btn_stop if self._recording else self._btn_play
        c.create_image(BTN_CX, BTN_CY, image=btn_img, tags="btn")

        # ── 标点模式标签（按钮下方，分两行居中） ──
        punc_color = C_VOL_OK if self._punc_smart else C_HINT
        punc_l1 = "智能" if self._punc_smart else "无"
        punc_l2 = "标点"
        c.create_text(
            BTN_CX, PREVIEW_Y1, text=punc_l1, fill=punc_color,
            font=("Segoe UI Variable", 7), anchor="center",
        )
        c.create_text(
            BTN_CX, PREVIEW_Y2, text=punc_l2, fill=punc_color,
            font=("Segoe UI Variable", 7), anchor="center",
        )
