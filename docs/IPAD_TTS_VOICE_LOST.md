# iPad 语音无声/音色不对 问题记录

**日期**: 2026-09-09
**影响范围**: iPad(iOS WebKit 旧内核)端语音朗读；安卓/桌面不受影响
**最终结论**: 非业务/网络问题，是「音频格式不兼容」+「容器部署环境缺转码组件」叠加，且该 iPad 的 DOM 媒体元素管线完全不可用。

---

## 1. 现象链路

1. 用户报告 iPad 上「所有语音都没声音」；安卓一切正常（音色正确 = 晓晓）。
2. 逐层诊断得到的稳定事实：
   - `/edu/api/tts` 请求在网络层**完全正常**：`HTTP 200`，字节完整；
   - iPad 上 `new Audio('http://…')`、`new Audio(blobURL)` 均**永不启动**（不报错、无 onplaying、play() 不 reject）——DOM 媒体元素管线整条失灵；
   - 同一份字节在安卓/桌面正常出声；
   - `speechSynthesis`（系统音）在该 iPad 上可用，但**仅手势内同步调用**能出声；
   - 用 Web Audio `decodeAudioData`（走独立系统管线）可解码并播放 → 终于能听到晓晓。

## 2. 根因（三层，缺一不可）

### 2.1 音频格式：edge-tts 输出 MPEG-2/24kHz
- 微软 edge-tts 固定输出 `audio-24khz-48kbitrate-mono-mp3`，即 **MPEG-2 Layer III @ 24kHz**（帧头示例 `FF F3 64`）。
- 旧版 iOS WebKit 对该码流**静默解码失败**：请求 200 + 字节齐全，但完全不发声、不抛错；安卓/桌面正常。
- 一次性扫盘确认：`instance/tts` 229/230 个缓存全是 MPEG-2，仅个别 MPEG-1/48k。

### 2.2 部署环境：容器缺转码组件
- 用 Docker 部署，`instance/` 是命名卷 `task-data`（非绑挂），其中缓存是**独立副本**，本地批量转码也覆盖不到；
- 镜像 `python:3.11-slim` 未装 ffmpeg，`_to_ios_mp3()` 找不到转码器时静默回退原字节 → 服务端「看似在转码」实际原样返回 MPEG-2；
- `FLASK_ENV=production` 不自动重载，路由改动需重启容器。

### 2.3 iPad 设备：DOM 媒体元素管线不可用
- 即使喂标准 MPEG-1(44.1k)字节，该 iPad 的 `<audio>` 元素仍旧不起播；
- 唯一可行方案：`fetch` 拿字节 → `AudioContext.decodeAudioData()` → `BufferSource` 播放 PCM（已实际出声，音色 = 晓晓）。

## 3. 修复方案（本仓库已实现）

| 层 | 改动 |
|---|---|
| 服务端转码 | `routes/education.py` 新增 `_to_ios_mp3()` / `_av_mp3()`：把非 MPEG-1 流转成 **MPEG-1 Layer III 44.1kHz mono @64k**。优先系统 ffmpeg，缺省回退 PyAV（`av` wheel 自带完整 ffmpeg 库，**无需系统 ffmpeg**）；两者皆缺才原样返回（安卓保底）。 |
| 缓存懒迁移 | `/api/tts` 路由对仍在磁盘/卷里的旧 MPEG-2 缓存做**懒转码**（首个请求转一次落盘）。 |
| 缓存版本号 | 响应 `Cache-Control: immutable` 会让浏览器长期复用旧音频——客户端 `ttsUrl()` 增加 `&cv=` 版本号，格式/压缩参数变更时升号强制重拉。 |
| 容器自动装组件 | `entrypoint.sh` 增加 `av` 启动预装（同 jionlp/edge-tts 模式，`KB_PREINSTALL=0` 可关），容器每次启动都自检；`requirements.txt` 已含 `av>=13.0.0`。`Dockerfile` 也加装系统 `ffmpeg` 作为优先通道。 |
| iOS 播放 | `static/js/edu/edu-speech.js` 的 🔊 在 iOS 上走 **Web Audio decodeAudioData**（主路）→ blob `<audio>`（兜底）→ 系统音（1.8s 超时才补，避免双音重叠）；AC 一出声立即 `speechSynthesis.cancel()` 切走系统音。 |

## 4. 验证 / 复现

- 探针：iOS 左下角固定小条显示实际收到音频格式，如 `iOS TTS: HTTP 200 … MPEG1(cv) sv=3`，出现 `AC解码已出声` 表示晓晓已切换到位。
- 冒烟：安卓端逐条朗读核对音色仍为晓晓（转码对两端皆透明）。

## 5. 回归保障

`tests/test_tts_transcode.py`（下称「老三样」不变量）：

1. MPEG-2 夹具能被识别；
2. `_to_ios_mp3()` 必须转出 **MPEG-1 / Layer III / 44.1kHz**；
3. `/api/tts` 对历史 MPEG-2 缓存懒转码后**只返回 MPEG-1**，且带 `X-TTS-V` 版本头。

依赖：ffmpeg 或 PyAV 任一就绪即跑；两者皆缺会 skip（此时必须给出明确的部署告警）。

## 6. 后续维护提醒

- **换 TTS 后端 / 升 edge-tts** 后跑一遍 `pytest tests/test_tts_transcode.py` 确认格式仍合规；
- 客户端 `cv=` 每次音频格式/编码参数变更都要**升号**，否则 iPad 仍可能复用 immutable 旧缓存；
- 换部署机器/重建容器时，确认容器日志出现 `[entrypoint][av] 预装成功`（或镜像已带 ffmpeg）。