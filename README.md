# 即声 SpeakNow

> A lightweight Windows desktop voice input tool — press hotkey, speak, and text appears at your cursor.
> 轻量级 Windows 桌面语音输入工具 — 按下快捷键，说话即文字。

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**SpeakNow** is a lightweight Windows desktop voice input tool powered by [Volcengine (ByteDance) ASR](https://www.volcengine.com/product/voice-tech). Press a hotkey, speak naturally, and the recognized text is automatically typed into any application at the cursor position. Supports real-time streaming recognition with low latency.

**即声 SpeakNow** 是一款轻量的 Windows 桌面语音输入工具，基于[火山引擎大模型语音识别](https://www.volcengine.com/product/voice-tech)引擎，支持实时流式识别。按下快捷键说话，文字自动输入到任意应用的光标位置。

---

## Features / 功能特性

- **Real-time Waveform / 实时波形可视化** — Apple-style floating window with Bézier curve waveform & volume indicator
  Apple 风格浮动窗口，贝塞尔曲线波形 + 音量指示
- **Global Hotkey / 全局热键** — `Ctrl+Q` to start/stop recording, works in any app
  `Ctrl+Q` 启停录音，任何应用中随时可用
- **Dual-line Preview / 双行文字预览** — Live text display during recognition, pixel-accurate clipping
  识别过程中实时显示文字，像素级裁剪不溢出
- **Smart Punctuation / 智能标点** — Auto punctuation with backtracking fix (period → comma when continuation detected)
  自动添加标点符号，支持回溯修正（连接词开头时句号→逗号）
- **Punctuation Toggle / 标点模式切换** — `Ctrl+Shift+Q` to switch between smart/none punctuation modes
  `Ctrl+Shift+Q` 一键切换智能/无标点模式
- **Hotwords / 热词支持** — Custom terminology list for improved domain-specific recognition accuracy
  自定义专业术语词表，提升识别准确率
- **Auto Reconnect / 自动重连** — WebSocket reconnects with exponential backoff (up to 3 retries)
  WebSocket 断线自动重连（指数退避，最多 3 次）
- **Dual Engine / 双引擎** — WebSocket streaming preferred, automatic fallback to HTTP segmented mode
  WebSocket 流式优先，自动回退 HTTP 分段模式
- **Silence Detection / 静音自动停止** — Auto-stop after 3s silence; 30s idle timeout
  3 秒无语音自动结束，30 秒无有效语音超时退出
- **Position Memory / 位置记忆** — Draggable floating window with auto-saved position
  悬浮窗可拖拽，位置自动保存

---

## Quick Start / 快速开始

### Prerequisites / 前置条件

- Windows 10 / 11
- Python 3.10+
- [Volcengine](https://console.volcengine.com) account (free tier available / 新用户有免费额度)

### Installation / 安装步骤

```bash
# 1. Clone / 克隆仓库
git clone https://github.com/simonxiao2006/speaknow.git
cd speaknow

# 2. Configure credentials / 配置凭证
cp .env.example .env
# Edit .env, fill in your Volcengine APP ID and Access Token
# 编辑 .env，填入你的火山引擎 APP ID 和 Access Token

# 3. Install dependencies / 安装依赖
pip install -r requirements.txt

# 4. Run / 启动
python main.py
```

### Get Volcengine Credentials / 获取火山引擎凭证

1. Sign up at [Volcengine Console](https://console.volcengine.com)
   注册 [火山引擎](https://console.volcengine.com) 账号
2. Go to [Speech Tech Console](https://console.volcengine.com/speech/service/overview), enable "Speech Recognition" service
   进入 [语音技术控制台](https://console.volcengine.com/speech/service/overview)，开通「语音识别」服务
3. Create an app in "App Management", check "Streaming Speech Recognition"
   在「应用管理」创建应用，勾选「流式语音识别」
4. Copy **APP ID** and **Access Token** from app details
   进入应用详情，复制 **APP ID** 和 **Access Token**

---

## Usage / 使用方法

| Action / 操作 | Hotkey / 快捷键 |
|------|---------------|
| Start / Stop recording / 开始/停止录音 | `Ctrl+Q` |
| Toggle punctuation / 切换标点模式 | `Ctrl+Shift+Q` |
| Click record button / 点击录音按钮 | Click right-side button on floating window |
| Edit hotwords / 编辑热词表 | Right-click tray icon → Edit Hotwords |
| Exit / 退出 | Right-click tray icon → Quit |

---

## Configuration / 配置

### Credentials / 凭证（.env file）

| Variable / 变量 | Required / 必填 | Description / 说明 |
|------|------|------|
| `VOLC_APP_KEY` | Yes / 是 | App ID |
| `VOLC_ACCESS_KEY` | Yes / 是 | Access Token |
| `VOLC_API_KEY` | No / 否 | API Key (HTTP fallback mode only / 仅 HTTP 备用模式) |

### Hotwords / 热词

Auto-created on first use. Edit `.hotwords.json` anytime:
首次使用时自动创建 `.hotwords.json`，可随时编辑：

```json
["Python", "GitHub", "VS Code", "ChatGPT", "AI"]
```

Loaded automatically on each recording to boost domain-specific recognition accuracy.
每次录音自动加载并注入 ASR 引擎，提升专业术语的识别准确率。

---

## Project Structure / 项目结构

```
speaknow/
├── main.py              # Main: tray, hotkeys, recording control / 主程序
├── asr_streaming.py     # ASR engine: WS streaming + HTTP fallback / 识别引擎
├── waveform.py          # Waveform window: Canvas vector rendering / 波形窗
├── config.py            # Config: credentials, audio params, hotkeys / 配置
├── .env.example         # Credential template / 凭证模板
├── hotwords.example.json # Hotwords example / 热词示例
├── requirements.txt     # Python dependencies / Python 依赖
├── 启动.bat             # Windows launch script / 启动脚本
└── app.ico              # App icon / 应用图标
```

---

## Troubleshooting / 故障排除

| Problem / 问题 | Solution / 解决方案 |
|------|----------|
| "Credentials missing" on startup / 启动报错"凭证配置缺失" | Check `.env` exists with `VOLC_APP_KEY` and `VOLC_ACCESS_KEY` filled in |
| No recognition response / 识别没有反应 | Verify microphone works, check Volcengine console service is enabled |
| Waveform shows but no text / 波形有显示但无文字 | Possible network issue, check `speaknow.log` |
| Hotkey not working / 热键不生效 | May be occupied by other software, change `HOTKEY` in `config.py` |

---

## Acknowledgments / 致谢

- [Volcengine Speech Recognition](https://www.volcengine.com/product/voice-tech) — ASR engine / 语音识别引擎
- [sounddevice](https://python-sounddevice.readthedocs.io/) — Audio capture / 音频采集
- [pystray](https://github.com/moses-palmer/pystray) — System tray / 系统托盘
- [Pillow](https://python-pillow.org/) — Image processing / 图像处理

## License / 许可证

[MIT License](LICENSE)
