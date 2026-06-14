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


def _normalize_prompt_wav(prompt_wav, sample_rate: int, torchaudio_module):
    """把 torchaudio.load 出来的参考音频归一化到 CosyVoice cross_lingual 要求的格式。

    要求：16kHz 单声道 float32 tensor，shape 接近 (1, N) 或 (N,)。

    Why: CosyVoice 内部 frontend 按固定 16kHz chunk 处理 prompt_wav，
    非 16kHz / 立体声输入会被静音吞掉，最终 torchaudio.save 报
    "Invalid file: tensor([[0., 0., 0., ...]])"。

    Args:
        torchaudio_module: 注入的 torchaudio 模块（worker main 内局部 import）。
            通过参数注入而非全局 import，便于单元测试 mock。
    """
    # 1) 多声道 → 单声道（取各声道均值）
    if prompt_wav.dim() > 1 and prompt_wav.shape[0] > 1:
        logger.info("prompt_wav 多声道 shape=%s, 取均值转单声道", tuple(prompt_wav.shape))
        prompt_wav = prompt_wav.mean(dim=0, keepdim=True)

    # 2) 非 16kHz → 重采样到 16kHz
    if sample_rate != 16000:
        logger.info("prompt_wav 重采样 %dHz → 16000Hz", sample_rate)
        prompt_wav = torchaudio_module.functional.resample(
            prompt_wav, orig_freq=sample_rate, new_freq=16000
        )
        sample_rate = 16000

    # 3) 转到 CPU（避免 MPS tensor 直接进 cross_lingual 后无法 save）
    if prompt_wav.device.type != "cpu":
        prompt_wav = prompt_wav.cpu()

    return prompt_wav, sample_rate


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

    # D60: 参考音频加载（致命错误时整体退出，让引擎层走降级链）
    # D60 hotfix: CosyVoice cross_lingual 硬性要求 16kHz 单声道 prompt_wav，
    # torchaudio.load 不会自动归一化，需在 worker 层强制处理，
    # 否则非规格化输入会静音失败（_AUDIO_BACKEND 走默认 soundfile 时）。
    prompt_wav = None
    if reference_audio:
        if not Path(reference_audio).is_file():
            _output(
                {
                    "type": "error",
                    "message": f"参考音频文件不存在: {reference_audio}",
                }
            )
            sys.exit(1)
        try:
            logger.info("加载参考音频: %s", reference_audio)
            prompt_wav, sample_rate = torchaudio.load(reference_audio)
            prompt_wav, sample_rate = _normalize_prompt_wav(prompt_wav, sample_rate, torchaudio)
            logger.info(
                "参考音频归一化完成 shape=%s dtype=%s sr=%d max_abs=%.4f 走 cross_lingual",
                tuple(prompt_wav.shape),
                prompt_wav.dtype,
                sample_rate,
                float(prompt_wav.abs().max()),
            )
        except Exception as e:
            logger.exception("参考音频加载失败")
            _output({"type": "error", "message": f"参考音频加载失败: {e}"})
            sys.exit(1)

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
            if prompt_wav is not None:
                # D60 声音克隆路径
                for result in cosyvoice.inference_cross_lingual(text, prompt_wav, speed=speed):
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

            torchaudio.save(output_path, speech_tensor, 22050)
            duration = round(speech_tensor.shape[-1] / 22050, 3)
            _output({"type": "result", "index": idx, "duration": duration, "status": "ok"})
            success_count += 1

        except Exception as e:
            logger.exception("段 %d 合成失败", idx)
            # D60 hotfix: 合成失败时打印 speech_tensor 诊断，
            # 便于排查"Invalid file: tensor([[0., 0., ...]])" 这类静音问题
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
