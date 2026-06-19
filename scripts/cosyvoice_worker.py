"""CosyVoice TTS Worker — 在 conda Python 3.10 环境中运行。

通过 stdin 接收 JSON 输入，逐段合成语音，通过 stdout 输出 NDJSON 结果。
日志输出到 stderr，不影响 stdout 的 JSON 通信。

通信协议：
    stdin  → JSON: {"model_path": "...", "speaker": "中文女", "speed": 1.0,
                    "reference_audio": "/abs/path/ref.wav",  # 可选，空则走 SFT
                    "segments": [{"index": 0, "text": "...", "output_path": "..."}, ...]}
    stdout ← NDJSON (每行一个 JSON):
             {"type": "result", "index": 0, "duration": 2.35, "status": "ok"}
             {"type": "done", "total": 50, "success_count": 50}
             {"type": "error", "message": "..."}  (致命错误)
    stderr ← 日志 (供主进程诊断)

D60 声音克隆：当 reference_audio 字段非空且文件存在时，所有段通过
CosyVoice.inference_cross_lingual(text, prompt_wav) 合成，使用参考音频的音色。

D60 hotfix #3（2026-06-19）：CosyVoice 的 inference_cross_lingual 期望 prompt_wav
是文件路径（字符串），不是 tensor —— 内部 load_wav 会再调一次 torchaudio.load。
主进程在 spawn 本 worker 前已用 ffmpeg 把任意格式 → 16kHz mono WAV 临时文件，
本 worker 直接把路径字符串透传给 inference_cross_lingual 即可。
"""

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("cosyvoice_worker")


def _output(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError) as e:
        _output({"type": "error", "message": f"输入 JSON 解析失败: {e}"})
        sys.exit(1)

    model_path = input_data.get("model_path", "")
    segments = input_data.get("segments", [])
    speaker = input_data.get("speaker", "中文女")
    speed = input_data.get("speed", 1.0)
    reference_audio = input_data.get("reference_audio", "")

    if not model_path or not segments:
        _output({"type": "error", "message": "缺少 model_path 或 segments"})
        sys.exit(1)

    try:
        import torchaudio
        from cosyvoice.cli.cosyvoice import CosyVoice
    except ImportError as e:
        _output({"type": "error", "message": f"CosyVoice import 失败: {e}"})
        sys.exit(1)

    try:
        logger.info("加载模型: %s", model_path)
        cosyvoice = CosyVoice(model_path)
        logger.info("模型加载完成, 可用说话人: %s", cosyvoice.list_available_spks())
    except Exception as e:
        _output({"type": "error", "message": f"模型加载失败: {e}"})
        sys.exit(1)

    # D60: 参考音频路径校验。主进程已用 ffmpeg 转成 16kHz mono WAV 临时文件，
    # 这里只检查路径存在，不再做 tensor 归一化（CosyVoice 内部 load_wav 自带 mean + resample）。
    prompt_wav_path: str | None = None
    if reference_audio:
        if not Path(reference_audio).is_file():
            _output(
                {
                    "type": "error",
                    "message": f"参考音频文件不存在: {reference_audio}",
                }
            )
            sys.exit(1)
        prompt_wav_path = reference_audio
        logger.info("使用参考音频（路径透传给 cross_lingual）: %s", prompt_wav_path)

    total = len(segments)
    success_count = 0

    for seg in segments:
        idx = seg["index"]
        text = seg.get("text", "")
        output_path = seg.get("output_path", "")

        if not text.strip() or not output_path:
            _output({"type": "result", "index": idx, "duration": 0.0, "status": "skipped"})
            continue

        try:
            speech_tensor = None
            if prompt_wav_path is not None:
                # D60 声音克隆路径：直接传文件路径，CosyVoice 内部 load_wav 处理
                for result in cosyvoice.inference_cross_lingual(text, prompt_wav_path, speed=speed):
                    speech_tensor = result["tts_speech"]
                    break
            else:
                # 默认 SFT 路径（向后兼容）
                for result in cosyvoice.inference_sft(text, speaker, speed=speed):
                    speech_tensor = result["tts_speech"]
                    break

            if speech_tensor is None:
                _output(
                    {
                        "type": "result",
                        "index": idx,
                        "duration": 0.0,
                        "status": "error",
                        "error": "推理未返回结果",
                    }
                )
                continue

            # 防御：CosyVoice 推理返回的 speech_tensor 在 Apple Silicon 上可能落在
            # MPS 设备上，torchaudio.save 不接受 MPS tensor；部分版本返回 3D (1, 1, N)。
            if speech_tensor.device.type != "cpu":
                logger.info("speech_tensor 搬到 CPU idx=%d device=%s", idx, speech_tensor.device)
                speech_tensor = speech_tensor.cpu()
            while speech_tensor.dim() > 2:
                logger.info(
                    "speech_tensor squeeze idx=%d shape=%s", idx, tuple(speech_tensor.shape)
                )
                speech_tensor = speech_tensor.squeeze(0)

            torchaudio.save(output_path, speech_tensor, 22050)
            duration = round(speech_tensor.shape[-1] / 22050, 3)
            _output({"type": "result", "index": idx, "duration": duration, "status": "ok"})
            success_count += 1

        except Exception as e:
            logger.exception("段 %d 合成失败", idx)
            # 合成失败时打印 speech_tensor 诊断，便于排查保存侧问题
            if speech_tensor is not None:
                try:
                    logger.error(
                        "speech_tensor 诊断 idx=%d shape=%s dtype=%s device=%s max_abs=%.6f",
                        idx,
                        tuple(speech_tensor.shape),
                        speech_tensor.dtype,
                        speech_tensor.device,
                        float(speech_tensor.abs().max()),
                    )
                except Exception:
                    pass
            _output(
                {
                    "type": "result",
                    "index": idx,
                    "duration": 0.0,
                    "status": "error",
                    "error": str(e),
                }
            )

    _output({"type": "done", "total": total, "success_count": success_count})


if __name__ == "__main__":
    main()
