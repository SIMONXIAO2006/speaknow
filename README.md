# 即声 SpeakNow

> Windows 桌面语音输入工具 — 按下快捷键，说话即文字

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Platform](https://img.shields.io/badge/Platform-Windows-lightgrey.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

**SpeakNow** 是一款轻量的 Windows 桌面语音输入工具，基于[火山引擎大模型语音识别](https://www.volcengine.com/product/voice-tech)引擎，支持实时流式识别。按下快捷键说话，松开后文字自动输入到任意应用的光标位置。

## 功能特性

- **实时波形可视化** — Apple 风格浮动窗口，贝塞尔曲线波形 + 音量指示
- **全局热键** — `Ctrl+Q` 启停录音，任何应用中随时可用
- **双行文字预览** — 识别过程中实时显示文字，像素级裁剪不溢出
- **智能标点** — 自动添加标点符号，支持回溯修正（句号→逗号）
- **标点模式切换** — `Ctrl+Shift+Q` 一键切换智能/无标点模式
- **热词支持** — 自定义专业术语词表，提升识别准确率
- **自动重连** — WebSocket 断线自动重连（指数退避，最多 3 次）
- **双引擎** — WebSocket 流式优先，自动回退 HTTP 分段模式
- **静音自动停止** — 3 秒无语音自动结束，30 秒无有效语音超时退出
- **位置记忆** — 悬浮窗可拖拽，位置自动保存

## 快速开始

### 前置条件

- Windows 10 / 11
- Python 3.10+
- 火山引擎账号（新用户有免费额度）

### 安装步骤

```bash
# 1. 克隆仓库
git clone https://github.com/YOUR_USERNAME/speaknow.git
cd speaknow

# 2. 配置凭证
cp .env.example .env
# 编辑 .env，填入你的火山引擎 APP ID 和 Access Token

# 3. 安装依赖
pip install -r requirements.txt

# 4. 启动
python main.py
```

### 获取火山引擎凭证

1. 注册 [火山引擎](https://console.volcengine.com) 账号
2. 进入 [语音技术控制台](https://console.volcengine.com/speech/service/overview)，开通「语音识别」服务
3. 在「应用管理」创建应用，勾选「流式语音识别」
4. 进入应用详情，复制 **APP ID** 和 **Access Token**

## 使用方法

| 操作 | 快捷键 / 方式 |
|------|---------------|
| 开始 / 停止录音 | `Ctrl+Q` |
| 切换标点模式 | `Ctrl+Shift+Q` |
| 点击录音按钮 | 点击浮动窗口右侧按钮 |
| 编辑热词表 | 右键托盘图标 → 编辑热词表 |
| 退出 | 右键托盘图标 → Quit |

## 配置

### 凭证（.env 文件）

| 变量 | 必填 | 说明 |
|------|------|------|
| `VOLC_APP_KEY` | 是 | 应用 APP ID |
| `VOLC_ACCESS_KEY` | 是 | Access Token |
| `VOLC_API_KEY` | 否 | API Key（仅 HTTP 备用模式） |

### 热词

首次使用时自动创建 `.hotwords.json`，可随时编辑：

```json
["Python", "GitHub", "VS Code", "ChatGPT", "AI"]
```

每次录音自动加载并注入 ASR 引擎，提升专业术语的识别准确率。

## 项目结构

```
speaknow/
├── main.py              # 主程序：托盘、热键、录音控制
├── asr_streaming.py     # ASR 引擎：WS 流式 + HTTP 备用
├── waveform.py          # 波形窗：Canvas 矢量渲染
├── config.py            # 配置：凭证、音频参数、快捷键
├── .env.example         # 凭证模板
├── hotwords.example.json # 热词示例
├── requirements.txt     # Python 依赖
├── 启动.bat             # Windows 启动脚本
└── app.ico              # 应用图标
```

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| 启动报错"凭证配置缺失" | 检查 `.env` 文件是否存在，`VOLC_APP_KEY` 和 `VOLC_ACCESS_KEY` 是否已填写 |
| 识别没有反应 | 确认麦克风正常工作，检查火山引擎控制台服务是否已开通 |
| 波形有显示但无文字 | 可能是网络问题，查看 `speaknow.log` 日志 |
| 热键不生效 | 可能被其他软件占用，在 `config.py` 中修改 `HOTKEY` |

## 致谢

- [火山引擎语音识别](https://www.volcengine.com/product/voice-tech) — ASR 引擎
- [sounddevice](https://python-sounddevice.readthedocs.io/) — 音频采集
- [pystray](https://github.com/moses-palmer/pystray) — 系统托盘
- [Pillow](https://python-pillow.org/) — 图像处理

## 许可证

[MIT License](LICENSE)
