"""K 线 TCP 二进制协议客户端。

从 data_example/k_history.py 提取，适配为异步版本。
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

logger = logging.getLogger(__name__)


class KlineError(Exception):
    """K 线请求相关错误的基类。"""


class ConnectionError(KlineError):
    """TCP 连接失败。"""


class ConnectionTimeoutError(KlineError):
    """TCP 连接或读取超时。"""


class ProtocolError(KlineError):
    """协议解析错误（校验和、解压等）。"""


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
# 响应重组
# ---------------------------------------------------------------------------

class ZipPackAssembler:
    """多包 zlib 压缩数据重组器。"""

    def __init__(self) -> None:
        self._session: dict[int, dict] = {}

    def feed_packet(self, packet: bytes) -> str | None:
        # 解析 RohonPdu Header
        length = struct.unpack("<H", packet[5:7])[0]
        body = packet[8 : 8 + length]

        expected_xor = packet[8 + length]
        actual_xor = xor_sum(body)
        if actual_xor != expected_xor:
            raise ProtocolError(
                f"xor checksum mismatch: expected={expected_xor}, actual={actual_xor}"
            )

        # 解析 ExtraData
        srclen = struct.unpack("<i", body[0:4])[0]
        ziplen = struct.unpack("<i", body[4:8])[0]
        currseq = struct.unpack("<H", body[8:10])[0]
        maxseq = struct.unpack("<H", body[10:12])[0]
        reqid = struct.unpack("<i", body[12:16])[0]
        fragment = body[16:]

        if reqid not in self._session:
            self._session[reqid] = {
                "srclen": srclen,
                "maxseq": maxseq,
                "ziplen": ziplen,
                "fragments": [None] * maxseq,
                "received": set(),
            }

        sess = self._session[reqid]
        sess["fragments"][currseq - 1] = fragment
        sess["received"].add(currseq)

        if len(sess["received"]) == sess["maxseq"]:
            zipped = b"".join(sess["fragments"])
            if len(zipped) != sess["ziplen"]:
                raise ProtocolError(
                    f"compressed data length mismatch: "
                    f"expected={sess['ziplen']}, actual={len(zipped)}"
                )
            raw = zlib.decompress(zipped)
            if len(raw) != sess["srclen"]:
                raise ProtocolError(
                    f"decompressed data length mismatch: "
                    f"expected={sess['srclen']}, actual={len(raw)}"
                )
            del self._session[reqid]
            return raw.decode("utf-8")

        return None


def parse_stream(byte_stream: bytes) -> list[str]:
    """解析原始字节流，返回完整的 JSON 字符串列表。"""
    results: list[str] = []
    assembler = ZipPackAssembler()
    buf = bytearray(byte_stream)

    while buf:
        if len(buf) <= 8:
            break
        single_length = struct.unpack("<H", buf[5:7])[0]
        end_idx = 8 + single_length + buf[8 + single_length :].find(
            END_OF_PACKAGE
        )
        if end_idx < 8 + single_length:
            # 找不到结束符，数据不完整
            break

        json_str = assembler.feed_packet(buf[:end_idx])
        del buf[: end_idx + 1]
        if json_str is not None:
            results.append(json_str)

    return results


# ---------------------------------------------------------------------------
# 异步 TCP 客户端
# ---------------------------------------------------------------------------

async def _send_and_receive(
    host: str,
    port: int,
    data: bytes,
    timeout: float,
) -> bytes:
    """通过 TCP 发送二进制请求并接收响应。"""
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
        raise ConnectionError(
            f"connect to {host}:{port} failed: {exc}"
        ) from exc

    try:
        writer.write(data)
        await writer.drain()

        chunks: list[bytes] = []
        try:
            while True:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=timeout)
                if not chunk:
                    break
                chunks.append(chunk)
        except asyncio.TimeoutError:
            # 读超时说明服务端已发送完所有数据
            pass

        return b"".join(chunks)
    except (OSError, asyncio.TimeoutError) as exc:
        raise ConnectionError(
            f"read from {host}:{port} failed: {exc}"
        ) from exc
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


class KlineClient:
    """K 线数据 TCP 客户端。"""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._req_counter: int = 0

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    async def fetch(self, request_body: dict) -> dict:
        """发送 K 线查询请求并返回解析后的 JSON 响应。"""
        self._req_counter += 1
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

        raw_bytes = await _send_and_receive(
            self._host,
            self._port,
            data,
            self._timeout,
        )

        if not raw_bytes:
            raise ConnectionError("empty response from server")

        parsed = parse_stream(raw_bytes)
        if not parsed:
            raise ProtocolError("no valid JSON found in response")

        # 取最后一个完整 JSON（正常情况下只有一个）
        raw_json = json.loads(parsed[-1])

        # 检查服务端错误
        errinfo = raw_json.get("errinfo", {})
        err_code = errinfo.get("Er", 0)
        if err_code != 0:
            raise RemoteError(code=err_code, message=errinfo.get("EM", ""))

        return raw_json


# 全局单例
kline_client = KlineClient(
    host=config.kline_tcp_host,
    port=config.kline_tcp_port,
    timeout=config.kline_tcp_timeout,
)
