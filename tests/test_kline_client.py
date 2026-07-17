"""kline.client 协议解析与收发健壮性测试。"""

from __future__ import annotations

import asyncio
import struct
import zlib

import pytest

from kline.client import (
    ConnectionError as KlineConnectionError,
    ConnectionTimeoutError,
    KlineClient,
    ProtocolError,
    RemoteError,
    _StreamParser,
    pack_request,
    xor_sum,
)

END = 0x03
FUNCID = 1002


def _build_frame(reqid: int, currseq: int, maxseq: int, fragment: bytes,
                 srclen: int, ziplen: int) -> bytes:
    """构造单个响应帧。"""
    extra = (
        struct.pack("<i", srclen)
        + struct.pack("<i", ziplen)
        + struct.pack("<H", currseq)
        + struct.pack("<H", maxseq)
        + struct.pack("<i", reqid)
    )
    body = extra + fragment
    header = (
        b"\x02"
        + struct.pack("<I", FUNCID)
        + struct.pack("<H", len(body))
        + b"\x00"
    )
    return header + body + bytes([xor_sum(body)]) + bytes([END])


def _build_response_frames(payload: bytes, reqid: int = 1, chunk_size: int = 1334) -> bytes:
    """把 payload 压缩后切成多帧，拼成一段字节流。"""
    zipped = zlib.compress(payload)
    fragments = [zipped[i:i + chunk_size] for i in range(0, len(zipped), chunk_size)]
    maxseq = len(fragments)
    stream = b""
    for i, frag in enumerate(fragments, start=1):
        stream += _build_frame(reqid, i, maxseq, frag, len(payload), len(zipped))
    return stream


# ---------------------------------------------------------------------------
# 流式解析：粘包 / 半包 / 错位切包
# ---------------------------------------------------------------------------

def test_stream_parser_single_chunk():
    payload = b'{"Ins":"AP610","data":[]}'
    stream = _build_response_frames(payload)
    parser = _StreamParser()
    parser.feed(stream)
    assert parser.completed
    assert parser.result == payload.decode()


def test_stream_parser_byte_by_byte_half_packets():
    """逐字节喂入，模拟最极端的半包场景。"""
    payload = b'{"Ins":"AP610","data":[{"TiD":"20260701"}]}'
    stream = _build_response_frames(payload)
    parser = _StreamParser()
    for b in stream:
        parser.feed(bytes([b]))
    assert parser.completed
    assert parser.result == payload.decode()


def test_stream_parser_sticky_packets():
    """两段完整响应粘在同一段字节里（本服务一个连接只一个响应，此处验证连续切包不串味）。"""
    p1 = b'{"Ins":"AP610","data":[]}'
    p2 = b'{"Ins":"FG8888","data":[{"TiD":"20260702"}]}'
    stream = _build_response_frames(p1, reqid=1) + _build_response_frames(p2, reqid=2)
    parser = _StreamParser()
    parser.feed(stream)
    # 单实例只锁定第一个 reqid，完成第一个即停
    assert parser.completed
    assert parser.result == p1.decode()


def test_stream_parser_split_at_arbitrary_boundary():
    """在任意位置切断字节流分两次喂入，均应正确重组。"""
    payload = b'{"Ins":"AP610","data":[{"TiD":"20260701"},{"TiD":"20260702"}]}'
    stream = _build_response_frames(payload)
    for split in range(1, len(stream)):
        parser = _StreamParser()
        parser.feed(stream[:split])
        assert not parser.completed, f"不应在切点 {split} 处提前完成"
        parser.feed(stream[split:])
        assert parser.completed, f"切点 {split} 处重组失败"
        assert parser.result == payload.decode()


def test_stream_parser_xor_collision_not_misframed():
    """body 内部含有 0x03 字节时，旧的 find(0x03) 写法会错位切包；按 length 切帧不会。"""
    # 构造合法 body：ExtraData(16) + fragment，让 fragment 中含 0x03
    fragment = b"\x03\x03\x03"  # fragment 内有结束符字节
    extra = (
        struct.pack("<i", 100)            # srclen
        + struct.pack("<i", len(fragment))  # ziplen（这里不真正解压，只验切帧）
        + struct.pack("<H", 1)            # currseq
        + struct.pack("<H", 2)            # maxseq=2，避免 _finalize 触发
        + struct.pack("<i", 1)            # reqid
    )
    body = extra + fragment
    header = b"\x02" + struct.pack("<I", FUNCID) + struct.pack("<H", len(body)) + b"\x00"
    frame = header + body + bytes([xor_sum(body)]) + bytes([END])
    # frame 内 body 含 3 个 0x03，但 length 指明 body 长度，切帧应跨越这些字节
    parser = _StreamParser()
    parser.feed(frame)
    # 只到第 1/2 帧，未完成；关键是没抛错且 buf 被精确消费（无残留即说明切对了）
    assert not parser.completed


def test_stream_parser_bad_xor_raises():
    payload = b'{"Ins":"AP610"}'
    stream = bytearray(_build_response_frames(payload))
    # 篡改 trailer 的 xor 字节（header(8)+body(len)+xor(1)）
    length = struct.unpack("<H", stream[5:7])[0]
    xor_pos = 8 + length
    stream[xor_pos] ^= 0xFF
    parser = _StreamParser()
    with pytest.raises(ProtocolError, match="xor checksum mismatch"):
        parser.feed(bytes(stream))


def test_stream_parser_bad_end_marker_raises():
    payload = b'{"Ins":"AP610"}'
    stream = bytearray(_build_response_frames(payload))
    length = struct.unpack("<H", stream[5:7])[0]
    end_pos = 8 + length + 1
    stream[end_pos] = 0x04
    parser = _StreamParser()
    with pytest.raises(ProtocolError, match="end marker mismatch"):
        parser.feed(bytes(stream))


def test_stream_parser_duplicate_seq_raises():
    """重组过程中遇到重复 currseq 应报错。"""
    payload = b'{"Ins":"AP610","data":[{"x":1}]}' * 50  # 足够大以产生多帧
    stream = bytearray(_build_response_frames(payload, reqid=1, chunk_size=10))
    # 取出第一帧，插到第二帧之后（响应未完成时遇到重复 seq）
    length = struct.unpack("<H", stream[5:7])[0]
    frame1 = bytes(stream[: 8 + length + 2])
    frame2_start = 8 + length + 2
    length2 = struct.unpack("<H", stream[frame2_start + 5 : frame2_start + 7])[0]
    frame2_end = frame2_start + 8 + length2 + 2
    stream[frame2_end:frame2_end] = frame1  # 在第二帧后插入重复的第一帧
    parser = _StreamParser()
    with pytest.raises(ProtocolError, match="duplicate seq"):
        parser.feed(bytes(stream))


def test_stream_parser_body_too_large_raises():
    # 伪造 length 超过 _MAX_BODY_SIZE
    stream = bytearray(b"\x02" + struct.pack("<I", FUNCID) + struct.pack("<H", 60001) + b"\x00")
    parser = _StreamParser()
    with pytest.raises(ProtocolError, match="too large"):
        parser.feed(bytes(stream) + b"\x00" * 70000)


# ---------------------------------------------------------------------------
# pack_request 往返
# ---------------------------------------------------------------------------

def test_pack_request_roundtrip():
    body = {"InstrumentID": "AP610", "CycleType": 3}
    data = pack_request(body)
    # header
    assert data[0] == 0x02
    assert struct.unpack("<I", data[1:5])[0] == FUNCID
    length = struct.unpack("<H", data[5:7])[0]
    assert data[7] == 0x00  # zip_flag
    payload = data[8:8 + length]
    assert xor_sum(payload) == data[8 + length]
    assert data[-1] == END


# ---------------------------------------------------------------------------
# fetch 重试与错误分类（用假 server）
# ---------------------------------------------------------------------------

class _FakeServer:
    """在本地随机端口起一个 TCP server，按脚本响应。"""

    def __init__(self, handler):
        self._handler = handler
        self._server: asyncio.AbstractServer | None = None
        self.host = "127.0.0.1"
        self.port = 0

    async def start(self):
        self._server = await asyncio.start_server(self._handler, self.host, 0)
        sock = self._server.sockets[0]
        self.port = sock.getsockname()[1]

    async def stop(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()


@pytest.fixture
def fast_retry_sleep(monkeypatch):
    """把 asyncio.sleep 替换为立即返回的 awaitable，加速重试测试。"""

    async def _no_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


@pytest.mark.asyncio
async def test_fetch_retries_on_connection_failure():
    # 指向一个必定连不上的端口，触发 ConnectionError 重试
    client = KlineClient("127.0.0.1", 1, timeout=1.0, max_retries=2)
    with pytest.raises((KlineConnectionError, ConnectionTimeoutError)):
        await client.fetch({"InstrumentID": "AP610"})


@pytest.mark.asyncio
async def test_fetch_retries_on_peer_reset(fast_retry_sleep):
    """服务端接受连接后立即 RST，应触发重试并最终抛 ConnectionError。"""
    reset_count = {"n": 0}

    async def handler(reader, writer):
        reset_count["n"] += 1
        await reader.read(1024)
        # 不回任何数据直接关闭，模拟断连
        writer.close()

    server = _FakeServer(handler)
    await server.start()
    try:
        client = KlineClient(server.host, server.port, timeout=1.5, max_retries=2)
        with pytest.raises(KlineConnectionError):
            await client.fetch({"InstrumentID": "AP610"})
        # 首次 + 2 次重试 = 3 次连接
        assert reset_count["n"] == 3
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_fetch_success_after_transient_failure(fast_retry_sleep):
    """前 N 次断连，第 N+1 次正常返回，应最终成功。"""
    call = {"n": 0}

    async def handler(reader, writer):
        call["n"] += 1
        await reader.read(4096)
        if call["n"] < 3:
            writer.close()  # 前两次断连
            return
        # 第三次正常返回
        payload = b'{"Ins":"AP610","errinfo":{"Er":0},"data":[]}'
        writer.write(_build_response_frames(payload, reqid=1))
        await writer.drain()
        writer.close()

    server = _FakeServer(handler)
    await server.start()
    try:
        client = KlineClient(server.host, server.port, timeout=2.0, max_retries=3)
        result = await client.fetch({"InstrumentID": "AP610"})
        assert result["Ins"] == "AP610"
        assert call["n"] == 3
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_fetch_remote_error_not_retried(fast_retry_sleep):
    """业务错误（errinfo.Er != 0）不应重试。"""
    call = {"n": 0}

    async def handler(reader, writer):
        call["n"] += 1
        await reader.read(4096)
        payload = b'{"Ins":"AP610","errinfo":{"Er":1001,"EM":"bad symbol"},"data":[]}'
        writer.write(_build_response_frames(payload, reqid=1))
        await writer.drain()
        writer.close()

    server = _FakeServer(handler)
    await server.start()
    try:
        client = KlineClient(server.host, server.port, timeout=2.0, max_retries=3)
        with pytest.raises(RemoteError) as exc:
            await client.fetch({"InstrumentID": "BAD"})
        assert exc.value.code == 1001
        assert call["n"] == 1  # 没有重试
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_fetch_protocol_error_not_retried(fast_retry_sleep):
    """协议错误（坏 xor）不应重试。"""
    call = {"n": 0}

    async def handler(reader, writer):
        call["n"] += 1
        await reader.read(4096)
        payload = b'{"Ins":"AP610","data":[]}'
        stream = bytearray(_build_response_frames(payload, reqid=1))
        length = struct.unpack("<H", stream[5:7])[0]
        stream[8 + length] ^= 0xFF  # 破坏 xor
        writer.write(bytes(stream))
        await writer.drain()
        writer.close()

    server = _FakeServer(handler)
    await server.start()
    try:
        client = KlineClient(server.host, server.port, timeout=2.0, max_retries=3)
        with pytest.raises(ProtocolError):
            await client.fetch({"InstrumentID": "AP610"})
        assert call["n"] == 1  # 没有重试
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# 退避公式
# ---------------------------------------------------------------------------

def test_compute_backoff_exponential(monkeypatch):
    """jitter 固定为 0 时，退避严格等于 base * 2^attempt。"""
    monkeypatch.setattr("kline.client.random.uniform", lambda _a, _b: 0.0)
    assert KlineClient.compute_backoff(0, 1.0) == pytest.approx(1.0)
    assert KlineClient.compute_backoff(1, 1.0) == pytest.approx(2.0)
    assert KlineClient.compute_backoff(2, 1.0) == pytest.approx(4.0)
    assert KlineClient.compute_backoff(3, 1.0) == pytest.approx(8.0)


def test_compute_backoff_within_jitter_range():
    """默认 jitter 时，delay 落在 [base*2^attempt, base*2^attempt + base] 内。"""
    base = 1.0
    for attempt in range(4):
        delay = KlineClient.compute_backoff(attempt, base)
        lower = base * (2 ** attempt)
        upper = lower + base
        assert lower <= delay <= upper
