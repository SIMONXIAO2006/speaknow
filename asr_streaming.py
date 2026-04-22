"""即声 SpeakNow v4.3 - 分段流式 ASR（WebSocket 断线自动重连 + nostream 二遍识别 + 智能标点）

策略：优先 WebSocket 流式识别，失败则回退 HTTP 分段模式。
WebSocket 断线时自动重连（最多 3 次，指数退避）。
"""

import io
import json
import struct
import base64
import uuid
import time
import logging
import threading
from typing import Callable

import requests
import websocket

from config import (
    APP_KEY, ACCESS_KEY, API_KEY,
    STREAM_URL, STREAM_RESOURCE_ID,
    SUBMIT_URL, QUERY_URL, RESOURCE_ID,
)

log = logging.getLogger(__name__)

ResultCallback = Callable[[str, bool], None]
PreviewCallback = Callable[[str], None]


# ── 二进制帧协议（WebSocket 流式用） ──────

def _build_header(msg_type: int, flags: int, serialization: int = 0, compression: int = 1) -> bytes:
    version = 0b0001
    header_size = 0b0001
    b0 = (version << 4) | header_size
    b1 = (msg_type << 4) | flags
    b2 = (serialization << 4) | compression
    b3 = 0x00
    return bytes([b0, b1, b2, b3])


def build_config_frame(config: dict) -> bytes:
    header = _build_header(msg_type=0b0001, flags=0b0000, serialization=0b0001, compression=0b0001)
    payload = __import__("gzip").compress(__import__("json").dumps(config, ensure_ascii=False).encode("utf-8"))
    return header + struct.pack(">I", len(payload)) + payload


def build_audio_frame(pcm_data: bytes, seq: int) -> bytes:
    """音频帧：msg_type=2, flags=0（不带 sequence）, compression=gzip"""
    import gzip
    header = _build_header(msg_type=0b0010, flags=0b0000, serialization=0b0000, compression=0b0001)
    payload = gzip.compress(pcm_data)
    return header + struct.pack(">I", len(payload)) + payload


def build_finish_frame(seq: int) -> bytes:
    import gzip
    header = _build_header(msg_type=0b0010, flags=0b0010, serialization=0b0000, compression=0b0001)
    payload = gzip.compress(b"")
    return header + struct.pack(">I", len(payload)) + payload


# ── HTTP 分段识别 ──────────────────────────

def pcm_to_wav(pcm_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    data_size = len(pcm_bytes)
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm_bytes)
    return buf.getvalue()


def recognize_http(pcm_bytes: bytes, hotwords: list[str] | None = None) -> str:
    """用 HTTP submit/query 识别一段音频（v3 标准格式）"""
    if len(pcm_bytes) < 3200:  # < 0.1s
        return ""

    wav_b64 = base64.b64encode(pcm_to_wav(pcm_bytes)).decode()
    reqid = str(uuid.uuid4())

    headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Request-Id": reqid,
        "X-Api-Sequence": "-1",
    }

    payload = {
        "user": {"uid": "voice_input"},
        "audio": {
            "data": wav_b64,
            "format": "wav",
            "codec": "raw",
            "rate": 16000,
            "bits": 16,
            "channel": 1,
        },
        "request": {
            "model_name": "bigmodel",
            "enable_itn": True,
            "enable_punc": True,
        },
    }

    # 注入热词
    if hotwords:
        payload["request"]["corpus"] = {
            "context": json.dumps(
                {"hotwords": [{"word": w} for w in hotwords]}
            )
        }

    # Submit
    try:
        r = requests.post(SUBMIT_URL, json=payload, headers=headers, timeout=10)
    except Exception as ex:
        log.error("HTTP submit error: %s", ex)
        return ""

    sc = r.headers.get("X-Api-Status-Code", "")
    msg = r.headers.get("X-Api-Message", "")
    log.debug("Submit: status=%s msg=%s body=%s", sc, msg, r.text[:200])

    if sc and int(sc) != 20000000:
        log.error("Submit failed: %s %s %s", sc, msg, r.text[:200])
        return ""

    # Poll query
    query_headers = {
        "Content-Type": "application/json",
        "x-api-key": API_KEY,
        "X-Api-Resource-Id": RESOURCE_ID,
        "X-Api-Request-Id": reqid,
    }

    for _ in range(20):
        time.sleep(0.3)
        try:
            qr = requests.post(QUERY_URL, json={}, headers=query_headers, timeout=10)
        except Exception:
            continue

        qsc = qr.headers.get("X-Api-Status-Code", "")
        if qsc:
            code = int(qsc)
            if code == 20000000:
                data = qr.json()
                return data.get("result", {}).get("text", "")
            elif code == 20000003:
                return ""  # silence
            elif code in (20000001, 20000002):
                continue
            else:
                log.error("Query error: %s %s", qsc, qr.headers.get("X-Api-Message", ""))
                return ""
        else:
            data = qr.json()
            if "result" in data:
                return data["result"].get("text", "")

    log.warning("Query timeout")
    return ""


# ── WebSocket 流式客户端 ───────────

def _parse_response(data: bytes) -> tuple[int, dict | None]:
    if len(data) < 4:
        return -1, None
    b0, b1, b2, b3 = data[0], data[1], data[2], data[3]
    msg_type = (b1 >> 4) & 0x0F
    flags = b1 & 0x0F
    compression = b2 & 0x0F
    offset = 4

    if msg_type == 0b1111:
        if len(data) < offset + 8:
            return msg_type, {"error": "frame too short"}
        error_code = struct.unpack(">I", data[offset:offset + 4])[0]
        error_size = struct.unpack(">I", data[offset + 4:offset + 8])[0]
        offset += 8
        error_msg = data[offset:offset + error_size].decode("utf-8", errors="replace")
        return msg_type, {"error_code": error_code, "error_msg": error_msg}

    if flags in (0b0001, 0b0011):
        if len(data) < offset + 4:
            return msg_type, None
        offset += 4

    if len(data) < offset + 4:
        return msg_type, None
    payload_size = struct.unpack(">I", data[offset:offset + 4])[0]
    offset += 4

    payload_bytes = data[offset:offset + payload_size]
    if compression == 0b0001:
        import gzip
        try:
            payload_bytes = gzip.decompress(payload_bytes)
        except Exception:
            return msg_type, None

    import json
    try:
        result = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return msg_type, None
    return msg_type, result


class StreamingASR:
    """自动选择模式：优先 WebSocket 流式，失败则用 HTTP 分段

    用法不变：
        asr = StreamingASR()
        asr.start(on_result)
        asr.send_audio(pcm_bytes, seq)
        asr.send_finish(seq)
        asr.close()
    """

    def __init__(self):
        self._mode = "http"  # "websocket" or "http"
        self._ws: websocket.WebSocket | None = None
        self._running = False
        self._on_result: ResultCallback | None = None
        self._on_preview: PreviewCallback | None = None
        self._on_fix_prev: Callable[[], None] | None = None
        self._error: str | None = None

        # WS 模式：当前分句已输出的流式文本（用于计算 delta 和二次修正）
        self._ws_typed = ""

        # 标点智能修正：记录上一句 definitive 文本
        self._prev_definite_text = ""

        # 标点参数（由 start() 传入）
        self._punc_params: dict = {}

        # 热词表（由 start() 传入）
        self._hotwords: list[str] = []

        # HTTP 分段模式的状态
        self._audio_accumulator = bytearray()
        self._http_lock = threading.Lock()
        self._submitted_text = ""

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def mode(self) -> str:
        return self._mode

    def start(self, on_result: ResultCallback, on_preview: PreviewCallback | None = None,
              on_fix_prev: Callable[[], None] | None = None, punc_params: dict | None = None,
              hotwords: list[str] | None = None) -> bool:
        self._on_result = on_result
        self._on_preview = on_preview
        self._on_fix_prev = on_fix_prev
        self._punc_params = punc_params or {}
        self._hotwords = hotwords or []
        self._error = None
        self._audio_accumulator = bytearray()
        self._submitted_text = ""
        self._ws_typed = ""
        self._prev_definite_text = ""

        # 先尝试 WebSocket 流式
        if APP_KEY and ACCESS_KEY and STREAM_RESOURCE_ID:
            if self._try_ws_connect():
                self._mode = "websocket"
                log.info("Using WebSocket streaming mode")
                return True
            else:
                log.warning("WebSocket failed, falling back to HTTP segmented mode")

        # 回退到 HTTP 分段模式
        self._mode = "http"
        self._running = True
        log.info("Using HTTP segmented mode")
        return True

    def _try_ws_connect(self) -> bool:
        """首次连接：建立 WS + 启动接收线程"""
        try:
            if self._ws_setup_connection():
                self._running = True
                threading.Thread(target=self._ws_recv_loop, daemon=True).start()
                return True
        except Exception as e:
            self._error = str(e)
            log.debug("WS connect failed: %s", e)
        return False

    def _ws_setup_connection(self) -> bool:
        """建立 WebSocket 连接并发送 config，返回是否成功"""
        connect_id = str(uuid.uuid4())
        headers = {
            "X-Api-App-Key": APP_KEY,
            "X-Api-Access-Key": ACCESS_KEY,
            "X-Api-Resource-Id": STREAM_RESOURCE_ID,
            "X-Api-Connect-Id": connect_id,
        }
        self._ws = websocket.WebSocket()
        self._ws.connect(STREAM_URL, header=headers, timeout=5)

        config = {
            "user": {"uid": "voice_input"},
            "audio": {"format": "pcm", "rate": 16000, "bits": 16, "channel": 1},
            "request": {
                "model_name": "bigmodel",
                "enable_itn": True,
                "enable_punc": self._punc_params.get("enable_punc", True),
                "enable_ddc": self._punc_params.get("enable_punc", True),
                "show_utterances": True,
                "enable_nonstream": True,
                "result_type": "single",
                "end_window_size": self._punc_params.get("end_window_size", 1500),
                "force_to_speech_time": self._punc_params.get("force_to_speech_time", 1200),
                "enable_accelerate_text": True,
                "accelerate_score": 10,
            },
        }

        # 注入热词（提升专业术语识别准确率）
        if self._hotwords:
            config["request"]["corpus"] = {
                "context": json.dumps(
                    {"hotwords": [{"word": w} for w in self._hotwords]}
                )
            }
            log.info("Hotwords injected: %d words", len(self._hotwords))

        self._ws.send(build_config_frame(config), opcode=websocket.ABNF.OPCODE_BINARY)
        resp_data = self._ws.recv()
        msg_type, resp = _parse_response(resp_data)
        if msg_type == 0b1111:
            log.error("WS config error: %s", resp)
            self._ws.close()
            self._ws = None
            return False
        return True

    def _ws_reconnect(self) -> bool:
        """断线重连：关闭旧连接，建立新连接"""
        try:
            if self._ws:
                self._ws.close()
        except Exception:
            pass
        self._ws = None
        try:
            if self._ws_setup_connection():
                log.info("WS reconnected successfully")
                return True
        except Exception as e:
            log.error("WS reconnect failed: %s", e)
        return False

    def send_audio(self, pcm_data: bytes, seq: int) -> bool:
        if self._mode == "websocket":
            return self._ws_send_audio(pcm_data, seq)
        else:
            return self._http_send_audio(pcm_data, seq)

    def send_finish(self, seq: int) -> bool:
        if self._mode == "websocket":
            if self._ws:
                frame = build_finish_frame(seq)
                try:
                    self._ws.send(frame, opcode=websocket.ABNF.OPCODE_BINARY)
                except Exception:
                    pass
            return True
        else:
            # HTTP 模式：提交剩余音频
            return self._http_submit_remaining()

    def close(self):
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    # ── WebSocket 模式 ──

    def _ws_send_audio(self, pcm_data: bytes, seq: int) -> bool:
        if not self._ws or not self._running:
            return False
        try:
            self._ws.send(build_audio_frame(pcm_data, seq), opcode=websocket.ABNF.OPCODE_BINARY)
            return True
        except Exception:
            self._running = False
            return False

    def _ws_recv_loop(self):
        """接收 WS 结果，断线时自动重连（最多 3 次，指数退避）"""
        retries = 0
        MAX_RETRIES = 3
        while self._running:
            if self._ws is None:
                break
            try:
                self._ws.settimeout(5)
                data = self._ws.recv()
                if isinstance(data, str):
                    continue
                msg_type, resp = _parse_response(data)
                if resp and msg_type == 0b1001:
                    self._handle_ws_result(resp)
                elif msg_type == 0b1111:
                    log.error("WS server error: %s", resp)
                    self._running = False
                    break
                retries = 0  # 成功接收，重置计数
            except websocket.WebSocketTimeoutException:
                continue  # 正常超时，继续等
            except Exception as e:
                if not self._running:
                    break
                retries += 1
                if retries > MAX_RETRIES:
                    log.error("WS failed after %d retries: %s", MAX_RETRIES, e)
                    break
                backoff = min(1 << retries, 8)  # 2, 4, 8 秒
                log.warning("WS error (%d/%d): %s, reconnecting in %ds", retries, MAX_RETRIES, e, backoff)
                time.sleep(backoff)
                if self._ws_reconnect():
                    retries = 0
                # 重连失败则下一轮继续尝试（retries 递增）
        self._running = False

    # ── 标点回溯修正 ──

    # 连接词：新句以这些开头 → 上一句的句号应改为逗号
    _CONNECTORS = frozenset([
        "然后", "所以", "但是", "不过", "而且", "或者", "因为", "如果",
        "虽然", "同时", "另外", "此外", "因此", "于是", "接着", "随后",
        "并且", "而", "但", "可", "就", "还",
    ])

    @staticmethod
    def _first_word(text: str) -> str:
        """取文本开头的第一个词（2-3字）"""
        t = text.lstrip()
        if len(t) >= 3 and t[:3] in ("接下来", "与此同时"):
            return t[:3]
        if len(t) >= 2:
            return t[:2]
        return t[:1] if t else ""

    def _fix_prev_period(self, new_text: str):
        """回溯修正：如果新句以连接词开头，将上一句末尾句号改为逗号（仅智能标点模式）"""
        if not self._punc_params.get("enable_punc", True):
            return
        if not self._on_fix_prev:
            return
        if not self._prev_definite_text or not self._prev_definite_text.endswith("。"):
            return
        fw = self._first_word(new_text)
        if fw in self._CONNECTORS:
            self._on_fix_prev()
            self._prev_definite_text = self._prev_definite_text[:-1] + "，"
            log.info("Punct fix: prev period → comma (connector: %s)", fw)

    def _handle_ws_result(self, resp: dict):
        result = resp.get("result")
        if not result:
            return
        text = result.get("text", "")
        if not text:
            return

        utterances = result.get("utterances", [])

        # 预览：始终显示当前识别文本（流式结果在波形窗实时展示）
        if self._on_preview:
            self._on_preview(text)

        # 只在 definitive(nostream 二次修正) 时输出文本到目标窗口
        # 原因：enable_ddc 语义顺滑会修正中间结果，导致字符数变化，
        # select_back 替换机制无法精确匹配，产生重复输出。
        # definitive 来自 nostream 重识别，准确率更高、标点更好。
        has_definite = False
        if self._on_result:
            for u in utterances:
                if u.get("definite", False) and u.get("text", "").strip():
                    text = u["text"]
                    # 回溯修正：如果新句以连接词开头，修正上一句句号
                    self._fix_prev_period(text)
                    self._prev_definite_text = text
                    self._on_result(text, True)
                    log.info("WS: definite(nostream), %d chars: %s", len(text), text[:50])
                    has_definite = True

        if has_definite:
            # Reset for next sentence
            non_def = "".join(
                u.get("text", "") for u in utterances if not u.get("definite", False)
            )
            self._ws_typed = non_def
        else:
            self._ws_typed = text


    # ── HTTP 分段模式 ──

    def _http_send_audio(self, pcm_data: bytes, seq: int) -> bool:
        """累积音频数据，每 2 秒提交一次"""
        with self._http_lock:
            self._audio_accumulator.extend(pcm_data)

            # 每 2 秒提交一次（seq 每 200ms +1，2s = 10 个 seq）
            if seq % 10 == 0 and len(self._audio_accumulator) >= 6400:  # >= 0.2s
                pcm = bytes(self._audio_accumulator)
                self._audio_accumulator = bytearray()
                # 在后台线程提交识别
                threading.Thread(
                    target=self._http_recognize_and_callback,
                    args=(pcm,),
                    daemon=True,
                ).start()
                # 通知上层正在处理
                if self._on_result:
                    self._on_result("...", False)
        return True

    def _http_submit_remaining(self) -> bool:
        """提交剩余的音频"""
        with self._http_lock:
            pcm = bytes(self._audio_accumulator)
            self._audio_accumulator = bytearray()

        if len(pcm) < 3200:  # < 0.1s
            return True

        # 同步等待最后一部分识别完成
        text = recognize_http(pcm)
        if text and text.strip() and self._on_result:
            self._on_result(text.strip(), True)
            log.info("HTTP final segment: %s", text[:50])
        return True

    def _http_recognize_and_callback(self, pcm: bytes):
        """后台识别一段音频并回调"""
        text = recognize_http(pcm, hotwords=self._hotwords)
        if text and text.strip() and self._on_result:
            self._on_result(text.strip(), True)
            log.info("HTTP segment result: %s", text[:50])
