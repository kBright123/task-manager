# -*- coding: utf-8 -*-
"""iPad 语音失声回归测试: edge-tts 输出的 MPEG-2/24k 在旧 iOS WebKit 静默失败.

保障不变量:
1) 服务端 `_to_ios_mp3` 必须把 MPEG-2 流转成标准 MPEG-1 Layer III(≈44.1kHz);
2) `/edu/api/tts` 对历史 MPEG-2 缓存懒转码后, 返回给客户端的必须是 MPEG-1;
   否则 iOS/iPad 请求正常(HTTP 200)却静默无声, 安卓正常——极易误判成网络问题。
"""
import hashlib
import os
import shutil

import pytest

import routes.education as edu
from tests.conftest import _csrf_client

FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures')
MPEG2_FIXTURE = os.path.join(FIXTURE_DIR, 'tts-mpeg2-24k.mp3')


def _has_tool():
    """验证转码依赖是否就绪: 系统 ffmpeg 或 PyAV 任选其一即可."""
    if shutil.which('ffmpeg'):
        return True
    try:
        import av  # noqa: F401
        return True
    except ImportError:
        return False


def _next_frame_header(b):
    """跳过 ID3 后解析第一个 MP3 帧头, 返回 (version, layer, sample_rate, bitrate_kbps)."""
    i = 0
    if b[0:3] == b'ID3':
        size = 0
        for byte in b[6:10]:
            size = (size << 7) | (byte & 0x7F)
        i = 10 + size
    while i + 3 < len(b):
        if b[i] == 0xFF and (b[i + 1] & 0xE0) == 0xE0:
            d, e = b[i + 1], b[i + 2]
            ver = {0b11: 'MPEG1', 0b10: 'MPEG2', 0b00: 'MPEG2.5'}.get((d >> 3) & 3, '?')
            layer = {0b01: 3, 0b10: 2, 0b11: 1}.get((d >> 1) & 3, 0)
            sri = (e >> 2) & 3
            sr = {0: 44100, 1: 48000, 2: 32000}.get(sri, 0) if ver == 'MPEG1' \
                else {0: 22050, 1: 24000, 2: 16000}.get(sri, 0)
            return ver, layer, sr, (e >> 4) & 15
        i += 1
    return None


def _key(le, vkey, text):
    return hashlib.sha1((le + '|' + vkey + '|' + text).encode('utf-8')).hexdigest()[:24]


@pytest.mark.skipif(not _has_tool(), reason='需要 ffmpeg 或 PyAV 才能转码')
def test_mpeg2_fixture_is_detected():
    with open(MPEG2_FIXTURE, 'rb') as f:
        head = f.read(3)
    assert edu._mpeg_ver(head) == 'mpeg2'


@pytest.mark.skipif(not _has_tool(), reason='需要 ffmpeg 或 PyAV 才能转码')
def test_to_ios_mp3_converts_mpeg2_to_mpeg1_44k():
    with open(MPEG2_FIXTURE, 'rb') as f:
        raw = f.read()
    raw_hdr = _next_frame_header(raw)
    assert raw_hdr and raw_hdr[0] == 'MPEG2'  # 夹具确实是问题格式

    out = edu._to_ios_mp3(raw)
    assert out and len(out) > 500
    hdr = _next_frame_header(out)
    assert hdr is not None, '转码后必须是合法 MP3 帧'
    ver, layer, sr, bitrate_idx = hdr
    assert ver == 'MPEG1', '转码后必须是 MPEG-1(旧 iOS WebKit 可解)'
    assert layer == 3, '必须是 Layer III'
    assert sr == 44100, '采样率应转到 44.1kHz, 实际 %s' % sr
    assert bitrate_idx, '必须有有效码率索引'


@pytest.mark.skipif(not _has_tool(), reason='需要 ffmpeg 或 PyAV 才能转码')
def test_tts_route_lazy_converts_cached_mpeg2():
    """历史缓存是 MPEG-2 时, 首次请求必须懒转码为 MPEG-1 才返回, 且响应带 X-TTS-V."""
    text = '回归测试专用文本-保证唯一不被真实缓存命中'
    le, vkey = 'zh', 'xiaoxiao'
    key = _key(le, vkey, text)
    cache_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             'instance', 'tts')
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, key + '.mp3')

    with open(MPEG2_FIXTURE, 'rb') as f:
        raw = f.read()
    existed = os.path.exists(path)
    with open(path, 'wb') as f:
        f.write(raw)
    try:
        from app import app
        app.config['TESTING'] = True
        c = app.test_client()
        with c.session_transaction() as s:
            s['_user_id'] = '1'
            s['_fresh'] = True
            s['_csrf_token'] = 'test-csrf'
        c = _csrf_client(c)

        import urllib.parse
        url = '/edu/api/tts?text=' + urllib.parse.quote(text) + '&v=' + vkey + '&cv=1'
        r = c.get(url)
        assert r.status_code == 200
        assert r.headers.get('X-TTS-V') == '3'
        hdr = _next_frame_header(r.data)
        assert hdr is not None
        assert hdr[0] == 'MPEG1' and hdr[2] == 44100, '路由返回的音频必须是 MPEG-1/44.1k'
        # 懒转码应已落盘, 后续请求直接命中 MPEG-1
        with open(path, 'rb') as f:
            again = f.read()
        assert _next_frame_header(again)[0] == 'MPEG1'
    finally:
        if os.path.exists(path) and not existed:
            os.remove(path)