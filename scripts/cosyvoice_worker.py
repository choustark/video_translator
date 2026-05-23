"""CosyVoice TTS Worker — 在 conda Python 3.10 环境中运行。

通过 stdin 接收 JSON 输入，逐段合成语音，通过 stdout 输出 NDJSON 结果。
日志输出到 stderr，不影响 stdout 的 JSON 通信。

通信协议：
    stdin  → JSON: {"model_path": "...", "speaker": "中文女", "speed": 1.0,
                    "segments": [{"index": 0, "text": "...", "output_path": "..."}, ...]}
    stdout ← NDJSON (每行一个 JSON):
             {"type": "result", "index": 0, "duration": 2.35, "status": "ok"}
             {"type": "done", "total": 50, "success_count": 50}
             {"type": "error", "message": "..."}  (致命错误)
    stderr ← 日志 (供主进程诊断)
"""

import json
import logging
import sys

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
            for result in cosyvoice.inference_sft(text, speaker, speed=speed):
                speech_tensor = result["tts_speech"]
                break

            if speech_tensor is None:
                _output({"type": "result", "index": idx, "duration": 0.0, "status": "error",
                         "error": "inference_sft 未返回结果"})
                continue

            torchaudio.save(output_path, speech_tensor, 22050)
            duration = round(speech_tensor.shape[-1] / 22050, 3)
            _output({"type": "result", "index": idx, "duration": duration, "status": "ok"})
            success_count += 1

        except Exception as e:
            logger.exception("段 %d 合成失败", idx)
            _output({"type": "result", "index": idx, "duration": 0.0, "status": "error",
                     "error": str(e)})

    _output({"type": "done", "total": total, "success_count": success_count})


if __name__ == "__main__":
    main()
