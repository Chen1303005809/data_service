"""K 线 TCP 二进制协议客户端。

从 data_example/k_history.py 提取，适配为异步版本，并增强 TCP 层健壮性：
- 流式成帧解析，正确处理粘包/半包
- 按 maxseq 成帧判断响应结束，不依赖读超时
- 网络瞬时故障指数退避自动重试
- xor==0x03 错位切包修复
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
import zlib

from config import config

END_OF_PACKAGE = 0x03
FUNCID_KLINE = 1002
PROTOCOL_VERSION = 2

# 单包帧结构：header(8) + body(length) + xor(1) + end(1)
_HEADER_SIZE = 8
_EXTRA_DATA_SIZE = 16
_TRAILER_SIZE = 2  # xor(1) + end(1)
_MAX_BODY_SIZE = 60000  # body 上限保护，防御异常 len 字段

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 异常
# ---------------------------------------------------------------------------

class KlineError(Exception):
    """K 线请求相关错误的基类。"""


class ConnectionError(KlineError):
    """TCP 连接失败 / 对端断连。"""


class ConnectionTimeoutError(KlineError):
    """TCP 连接或读取超时。"""


class ProtocolError(KlineError):
    """协议解析错误（校验和、长度、解压、JSON 解析等）。"""


class RemoteError(KlineError):
    """服务端返回的业务错误。"""

    def __init__(self, code: int, message: str = ""):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


# ---------------------------------------------------------------------------
# 字节工具
# ---------------------------------------------------------------------------

def xor_sum(data: bytes) -> int:
    """逐字节异或校验和。"""
    s = 0
    for byte in data:
        s ^= byte
    return s


def pack_request(json_body: dict) -> bytes:
    """组装 K 线查询请求包。

    协议格式：
      ver(1) + funcid(4) + len(2) + zip_flag(1) + json_body + xor(1) + 0x03(1)
    """
    payload = json.dumps(json_body, separators=(",", ":")).encode("utf-8")
    buf = bytearray()
    buf += PROTOCOL_VERSION.to_bytes(1, "little")
    buf += FUNCID_KLINE.to_bytes(4, "little")
    buf += len(payload).to_bytes(2, "little")
    buf += int(0).to_bytes(1, "little")  # zip_flag = 0 不压缩
    buf += payload
    buf += xor_sum(payload).to_bytes(1, "little")
    buf += END_OF_PACKAGE.to_bytes(1, "little")
    return bytes(buf)


# ---------------------------------------------------------------------------
# 流式帧重组
# ---------------------------------------------------------------------------

class _StreamParser:
    """流式帧解析器：持续 feed 字节流，按完整帧切包并重组多包压缩数据。

    相比一次性 parse_stream：
    - 半包（body 未到齐）会保留在 buffer 等待下次拼接，不丢弃
    - 粘包（多帧合并在一段字节里）while 循环连续切包
    - 不用 find(0x03) 找结束符，避免 xor 校验和恰好为 0x03 时错位切包
    - 按 maxseq 个分片到齐判定一个响应结束
    """

    def __init__(self) -> None:
        self._buf = bytearray()
        self._sessions: dict[int, dict] = {}
        # 一个解析器实例只服务一次请求；收到第一个 reqid 即锁定
        self._expected_reqid: int | None = None
        self._expected_maxseq: int | None = None
        self._completed_json: str | None = None

    def feed(self, chunk: bytes) -> None:
        """喂入一段新到达的字节，尝试切包并重组。"""
        self._buf.extend(chunk)
        while True:
            frame = self._try_extract_frame()
            if frame is None:
                break  # 数据不足，等待更多字节
            self._ingest_frame(frame)
            if self._completed_json is not None:
                return  # 响应已完整，无需继续切包

    @property
    def completed(self) -> bool:
        return self._completed_json is not None

    @property
    def result(self) -> str:
        if self._completed_json is None:
            raise ProtocolError("response stream incomplete")
        return self._completed_json

    # -- 内部 ---

    def _try_extract_frame(self) -> bytes | None:
        """从 buffer 尝试切出一个完整帧；不完整则返回 None。"""
        if len(self._buf) < _HEADER_SIZE:
            return None
        length = struct.unpack("<H", self._buf[5:7])[0]
        if length > _MAX_BODY_SIZE:
            raise ProtocolError(
                f"frame body too large: {length} bytes (limit {_MAX_BODY_SIZE})"
            )
        frame_end = _HEADER_SIZE + length + _TRAILER_SIZE
        if len(self._buf) < frame_end:
            return None  # 半包，等下次

        frame = bytes(self._buf[:frame_end])
        del self._buf[:frame_end]
        return frame

    def _ingest_frame(self, frame: bytes) -> None:
        """解析单个帧并并入会话缓冲。"""
        length = struct.unpack("<H", frame[5:7])[0]
        body = frame[_HEADER_SIZE : _HEADER_SIZE + length]
        trailer = frame[_HEADER_SIZE + length : _HEADER_SIZE + length + _TRAILER_SIZE]
        expected_xor, end_byte = trailer[0], trailer[1]

        if end_byte != END_OF_PACKAGE:
            raise ProtocolError(
                f"frame end marker mismatch: expected 0x03, got 0x{end_byte:02x}"
            )
        actual_xor = xor_sum(body)
        if actual_xor != expected_xor:
            raise ProtocolError(
                f"xor checksum mismatch: expected=0x{expected_xor:02x}, "
                f"actual=0x{actual_xor:02x}"
            )

        # ExtraData
        if len(body) < _EXTRA_DATA_SIZE:
            raise ProtocolError(
                f"body too short for ExtraData: {len(body)} < {_EXTRA_DATA_SIZE}"
            )
        srclen = struct.unpack("<i", body[0:4])[0]
        ziplen = struct.unpack("<i", body[4:8])[0]
        currseq = struct.unpack("<H", body[8:10])[0]
        maxseq = struct.unpack("<H", body[10:12])[0]
        reqid = struct.unpack("<i", body[12:16])[0]
        fragment = body[_EXTRA_DATA_SIZE:]

        if maxseq == 0 or currseq == 0 or currseq > maxseq:
            raise ProtocolError(
                f"invalid seq: currseq={currseq}, maxseq={maxseq}"
            )
        # 锁定本次响应的 reqid / maxseq，后续帧必须一致
        if self._expected_reqid is None:
            self._expected_reqid = reqid
            self._expected_maxseq = maxseq
        elif reqid != self._expected_reqid:
            raise ProtocolError(
                f"unexpected reqid: {reqid} != {self._expected_reqid}"
            )
        elif maxseq != self._expected_maxseq:
            raise ProtocolError(
                f"inconsistent maxseq: {maxseq} != {self._expected_maxseq}"
            )

        sess = self._sessions.setdefault(
            reqid,
            {
                "srclen": srclen,
                "ziplen": ziplen,
                "maxseq": maxseq,
                "fragments": [None] * maxseq,
                "received": set(),
            },
        )
        # srclen/ziplen 在首帧记录；后续帧若不一致则报错（防御异常分片）
        if sess["srclen"] != srclen or sess["ziplen"] != ziplen:
            raise ProtocolError(
                f"inconsistent srclen/ziplen across frames: "
                f"srclen {sess['srclen']} vs {srclen}, "
                f"ziplen {sess['ziplen']} vs {ziplen}"
            )

        if currseq in sess["received"]:
            raise ProtocolError(f"duplicate seq: {currseq}")
        sess["fragments"][currseq - 1] = fragment
        sess["received"].add(currseq)

        if len(sess["received"]) == sess["maxseq"]:
            self._finalize(sess, reqid)

    def _finalize(self, sess: dict, reqid: int) -> None:
        zipped = b"".join(sess["fragments"])
        if len(zipped) != sess["ziplen"]:
            raise ProtocolError(
                f"compressed data length mismatch: "
                f"expected={sess['ziplen']}, actual={len(zipped)}"
            )
        try:
            raw = zlib.decompress(zipped)
        except zlib.error as exc:
            raise ProtocolError(f"zlib decompress failed: {exc}") from exc
        if len(raw) != sess["srclen"]:
            raise ProtocolError(
                f"decompressed data length mismatch: "
                f"expected={sess['srclen']}, actual={len(raw)}"
            )
        self._completed_json = raw.decode("utf-8")
        self._sessions.pop(reqid, None)


# ---------------------------------------------------------------------------
# 异步 TCP 收发
# ---------------------------------------------------------------------------

async def _send_and_receive(
    host: str,
    port: int,
    data: bytes,
    timeout: float,
) -> str:
    """建立 TCP 连接，发送请求，按协议成帧接收完整响应并返回 JSON 字符串。

    响应结束判据：流式解析器收到 maxseq 个分片、完成重组；不依赖读超时。
    """
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise ConnectionTimeoutError(
            f"connect to {host}:{port} timed out after {timeout}s"
        )
    except OSError as exc:
        raise ConnectionError(f"connect to {host}:{port} failed: {exc}") from exc

    parser = _StreamParser()
    try:
        writer.write(data)
        await writer.drain()

        # 边读边解析，响应一收齐就立即返回
        while not parser.completed:
            try:
                chunk = await asyncio.wait_for(reader.read(8192), timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise ConnectionTimeoutError(
                    f"read from {host}:{port} timed out after {timeout}s "
                    f"(response incomplete: {not parser.completed})"
                ) from exc
            except OSError as exc:
                # 对端 RST / 连接重置等
                raise ConnectionError(
                    f"read from {host}:{port} failed: {exc}"
                ) from exc

            if not chunk:
                # 对端主动关闭连接；若响应未完成则属异常断连
                if not parser.completed:
                    raise ConnectionError(
                        f"connection closed by peer before response complete "
                        f"(host={host}:{port})"
                    )
                break

            parser.feed(chunk)

        return parser.result
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------

class KlineClient:
    """K 线数据 TCP 客户端。"""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 10.0,
        max_retries: int = 3,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._max_retries = max_retries

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    async def fetch(self, request_body: dict) -> dict:
        """发送 K 线查询请求并返回解析后的 JSON 响应。

        网络瞬时故障（连接失败、超时、对端断连）会指数退避自动重试；
        协议错误与业务错误不重试（重试也不会成功）。
        """
        req_id = int(time.time() * 1000) % 1000000
        request_body["nRequestID"] = req_id
        data = pack_request(request_body)
        logger.debug(
            "kline request host=%s port=%d req_id=%d body=%s",
            self._host,
            self._port,
            req_id,
            request_body,
        )

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                json_str = await _send_and_receive(
                    self._host, self._port, data, self._timeout
                )
            except (ConnectionError, ConnectionTimeoutError) as exc:
                # 可重试：网络瞬时故障
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                delay = 0.1 * (2 ** attempt)  # 0.1s, 0.2s, 0.4s, ...
                logger.warning(
                    "kline attempt %d/%d failed (%s), retrying in %.1fs",
                    attempt + 1,
                    self._max_retries + 1,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # 请求已发送并收到完整响应，解析 JSON
            try:
                raw_json = json.loads(json_str)
            except json.JSONDecodeError as exc:
                raise ProtocolError(f"response JSON parse failed: {exc}") from exc

            errinfo = raw_json.get("errinfo", {})
            err_code = errinfo.get("Er", 0)
            if err_code != 0:
                raise RemoteError(code=err_code, message=errinfo.get("EM", ""))

            return raw_json

        # 重试耗尽
        assert last_exc is not None
        raise last_exc


# 全局单例
kline_client = KlineClient(
    host=config.kline_tcp_host,
    port=config.kline_tcp_port,
    timeout=config.kline_tcp_timeout,
    max_retries=config.kline_tcp_max_retries,
)
