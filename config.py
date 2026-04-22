"""即声 SpeakNow v4.3 - 配置文件"""

import os
import sys
from pathlib import Path

# ============ 火山引擎凭证（从 .env 文件或环境变量读取） ============
# 获取方式：https://console.volcengine.com/speech/service/overview
# 复制 .env.example 为 .env，填入你的 APP ID 和 Access Token


def _load_env():
    """从 .env 文件加载环境变量（简易解析，无需额外依赖）"""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                if key and key not in os.environ:
                    os.environ[key] = value


_load_env()

APP_KEY = os.environ.get("VOLC_APP_KEY", "")
ACCESS_KEY = os.environ.get("VOLC_ACCESS_KEY", "")
API_KEY = os.environ.get("VOLC_API_KEY", "")


def _check_credentials():
    """校验必要凭证是否存在"""
    missing = []
    if not APP_KEY:
        missing.append("VOLC_APP_KEY")
    if not ACCESS_KEY:
        missing.append("VOLC_ACCESS_KEY")
    if missing:
        print("=" * 50)
        print("  即声 SpeakNow - 凭证配置缺失")
        print("=" * 50)
        print(f"  缺少: {', '.join(missing)}")
        print()
        print("  请按以下步骤配置:")
        print("  1. 复制 .env.example 为 .env")
        print("  2. 在 .env 中填入你的火山引擎凭证")
        print("  3. 获取地址: https://console.volcengine.com/speech/service/overview")
        print("=" * 50)
        sys.exit(1)


_check_credentials()

# ============ 流式 ASR 配置 ============
STREAM_URL = "wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async"
STREAM_RESOURCE_ID = "volc.seedasr.sauc.duration"   # 流式语音识别模型2.0 小时版

# ============ 旧版录音文件识别（备用） ============
RESOURCE_ID = "volc.seedasr.auc"
SUBMIT_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
QUERY_URL = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query"

# ============ 快捷键配置 ============
HOTKEY = "ctrl+q"              # 全局热键启停录音
PUNC_TOGGLE_HOTKEY = "ctrl+shift+q"  # 切换标点模式

# ============ 音频配置 ============
SAMPLE_RATE = 16000
CHANNELS = 1
CHUNK_DURATION_MS = 20
SAMPLE_WIDTH = 2
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_DURATION_MS / 1000)  # 320
AUDIO_GAIN = 1.0  # 音频增益（1.0=原始, 2.0=放大2倍；放大同时放大噪音，谨慎使用）

# ============ 流式发送配置 ============
SEND_INTERVAL_S = 0.2   # 每 200ms 发一次音频包
SEND_CHUNK_COUNT = int(SEND_INTERVAL_S / (CHUNK_DURATION_MS / 1000))  # 10 个 chunk = 200ms

# ============ 静音自动停止 ============
SILENCE_TIMEOUT_S = 3.0   # 检测到有效语音后，静音超过此秒数自动停止录音
VOICE_RMS_THRESHOLD = 200  # RMS 阈值，低于此视为静音（int16 范围 0~32767，调低适合小声说话）
IDLE_TIMEOUT_S = 30        # 开始录音后，一直没说话（无有效语音）超过此秒数自动停止

# ============ 标点模式参数 ============
# 智能标点模式（宽松断句 + 标点 + 回溯修正）
PUNC_SMART = {
    "enable_punc": True,
    "end_window_size": 1500,       # 放宽到1500避免一停顿就断句
    "force_to_speech_time": 1200,  # 需要更多语音才尝试判停
}

# 无标点模式（纯文字输出）
PUNC_NONE = {
    "enable_punc": False,
    "end_window_size": 1500,
    "force_to_speech_time": 1200,
}

# ============ 用户偏好文件 ============
SETTINGS_FILE = Path(__file__).parent / ".settings.json"

# ============ 热词表 ============
HOTWORDS_FILE = Path(__file__).parent / ".hotwords.json"
