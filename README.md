# Video Translator

> [中文版本](README_zh.md)

An Apple Silicon-native English-to-Chinese video translation tool. Drop in a video, get Chinese dubbed video + subtitles with one click.

## Why

Existing video translation tools (pyvideotrans, VideoLingo) bundle AI models for you — you're locked into their choices. **video_translator flips this: you bring the models, the software does the orchestration.** Switch to a new model the day it's released, no waiting for a software update.

## Highlights

- **Model sovereignty** — ASR / Translation / TTS: each stage independently selectable and replaceable (Strategy pattern architecture)
- **Apple Silicon native** — mlx-whisper + MPS/Metal acceleration; no other open-source project ships this
- **Ultra-low cost** — Translation via API (GLM/DeepSeek), ASR/TTS run locally for free. ~$0.04 per 10-minute video
- **Speed-adaptive alignment** — Four-layer progressive strategy to sync Chinese dubbing with English video timing
- **Three output artifacts** — Composited video (hard-subbed) + SRT subtitles + Chinese audio. Everything you need, no post-processing
- **Pre-translation validation** — ffmpeg / model files / API key / format / duration all checked upfront. Problems caught before you start.

## Six-Stage Pipeline

```
Audio Extraction(ffmpeg) → ASR(mlx-whisper) → Translation(API) → TTS(CosyVoice/Edge-TTS) → Speed-Adaptive → Compositing(ffmpeg)
```

## Installation

### Prerequisites

- macOS 12+ (Apple Silicon)
- Python 3.13+
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)
- 16GB+ RAM (24GB recommended)
- 10-15GB disk space (for models)

### Setup

```bash
# Clone the repo
git clone git@github.com:choustark/video_translator.git
cd video_translator

# Install dependencies (uv recommended)
uv sync

# Or with pip
pip install -e .
```

### Download Models

A one-click download script auto-detects your platform and pulls the required models:

```bash
# Install download dependency
pip install huggingface_hub[hf_transfer]

# Auto-detect platform, download recommended models (recommended)
python scripts/download_models.py --auto

# List all available models + platform compatibility
python scripts/download_models.py --list
```

**Apple Silicon Mac** automatically downloads mlx-whisper + ChatTTS. **Windows / Linux** automatically downloads faster-whisper + ChatTTS.

For CosyVoice (higher-quality local TTS), manual setup is required — see the [CosyVoice Deployment Guide](docs/cosyvoice-deployment-guide.md) (Chinese). Prefer zero-config? Use Edge-TTS (cloud, free).

See the [Model Download Guide](docs/model-download-guide.md) (Chinese) for details.

### API Key

The translation backend requires an API key. Create a `.env` file:

```bash
# GLM (Zhipu) — default backend, lowest cost
GLM_API_KEY=your_key_here

# DeepSeek
DEEPSEEK_API_KEY=your_key_here
```

## Usage

```bash
# Launch the desktop app
python main.py
```

1. **Configure** — Set ASR model path, translation backend + API key, and TTS engine in the settings panel
2. **Drop video** — Drag and drop an mp4/mkv/mov/avi video into the main window
3. **Validate** — The system auto-checks your environment; green checkmarks mean you're good to go
4. **Translate** — Click the button and the six-stage pipeline runs automatically with real-time progress
5. **Get results** — Find all three output artifacts in the `output/` directory

### Preset Configurations

| Preset | ASR | Translation | TTS | RAM |
|--------|-----|-------------|-----|-----|
| High Quality (default) | large-v3-turbo | GLM API | CosyVoice | ~7GB |
| Balanced | medium | DeepSeek | CosyVoice | ~5.5GB |
| Fast | tiny | DeepSeek | Edge-TTS | ~0.5GB |
| Fully Offline | medium | NLLB (local) | CosyVoice | ~8GB |

You can also save custom presets and switch between them for different video types.

## Tech Stack

| Component | Technology | Notes |
|-----------|------------|-------|
| Desktop Framework | PySide6 | Official Qt Python bindings |
| ASR | mlx-whisper | Apple Silicon MPS acceleration |
| Translation | GLM / DeepSeek / OpenAI / DeepL | Strategy pattern, extensible |
| TTS | CosyVoice / ChatTTS / Edge-TTS | Local-first, cloud fallback |
| AV Processing | ffmpeg | Video ingest, extraction, compositing, subtitle burn-in |
| Config | YAML + pydantic | Type-safe validation |
| Python | 3.13+ | Leveraging latest language features |

## Project Structure

```
video_translator/
├── main.py                 # Entry point
├── config.yaml             # Default configuration
├── pyproject.toml          # Project metadata
├── src/
│   ├── asr/                # ASR engines (mlx-whisper)
│   ├── translation/        # Translation backends (GLM/DeepSeek/...)
│   ├── tts/                # TTS engines (CosyVoice/Edge-TTS)
│   ├── composer/           # AV compositing + speed-adaptive alignment
│   ├── gui/                # PySide6 UI components
│   ├── pipeline.py         # Pipeline orchestrator
│   ├── config.py           # Config management
│   ├── models.py           # Data models
│   └── validators.py       # Pre-translation validation
├── tests/                  # Tests (pytest)
├── docs/                   # Documentation (model download guide, etc.)
├── scripts/                # Utility scripts (model download, etc.)
└── models/                 # AI model files (.gitignore)
```

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/
```

## Roadmap

### v1 (MVP) ✅

- [x] PySide6 desktop UI (drag-and-drop video + config panel + progress display)
- [x] End-to-end six-stage pipeline
- [x] Pre-translation validation (ffmpeg / model / API key / format / duration)
- [x] Speed-adaptive alignment (centered silence padding + atempo speed adjustment)
- [x] Config management (multi-preset + save + restore)
- [x] Three output artifacts (composited video + SRT + audio)

### v1.1 (Quality Improvements) ✅

- [x] Multiple translation backends (DeepSeek / OpenAI)
- [x] User abort mechanism
- [x] Secure API key storage (.env)
- [x] Speed-adaptive alignment (centered silence padding + atempo)
- [x] Subtitle style preset system
- [x] Translation duration constraint + colloquial optimization
- [x] ASR proper noun guidance + fragment merging

### v1.2 (UI Streamlining + Cross-Platform) ✅

- [x] Remove speed slider (replaced by three-layer automation)
- [x] Real-time audio extraction progress
- [x] FasterWhisperEngine implementation (cross-platform ASR)
- [x] Windows cross-platform support
- [x] ChatTTS engine integration
- [x] One-click copy ASR/translation results

### v2.0 (Advanced Experience) 🔜

- [ ] Long video segmentation (>10 minutes)
- [ ] Per-sentence re-synthesis
- [ ] Multi-language support
- [ ] Lip sync (Wav2Lip / MuseTalk)
- [ ] Multi-speaker recognition (WhisperX)

### v3.0 (Differentiation)

- [ ] GPT-SoVITS voice cloning
- [ ] dmg / pkg installer
- [ ] Batch queue
- [ ] Official product naming

## License

MIT

### Third-Party Dependencies

This project uses the following open-source libraries:

- **ChatTTS** — MIT License (https://github.com/2noise/ChatTTS)
- **CosyVoice** — Apache 2.0 License (https://github.com/FunAudioLLM/CosyVoice) (https://github.com/FunAudioLLM/CosyVoice)
- **mlx-whisper** — MIT License
- **faster-whisper** — MIT License
- **PySide6 (Qt)** — LGPLv3 License
- **edge-tts** — MIT License

**Note:** `pyproject.toml` includes core dependencies. ChatTTS and CosyVoice are optional user-installed dependencies — see engine-specific setup guides.
