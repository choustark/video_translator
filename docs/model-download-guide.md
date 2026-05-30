# 模型下载指南

video_translator 需要 AI 模型来跑 ASR（语音识别）和 TTS（语音合成）。本指南带你一步步完成模型下载和配置。

## 第一步：确认你的平台

打开终端，运行：

```bash
python -c "import platform; print(f'{platform.system()} / {platform.machine()}')"
```

根据输出确定你需要哪些模型：

| 输出 | 可用的 ASR 模型 | 推荐方案 |
|------|----------------|---------|
| `Darwin / arm64` | mlx-whisper（推荐）、faster-whisper | mlx-whisper + ChatTTS |
| `Darwin / x86_64` | faster-whisper | faster-whisper + ChatTTS |
| `Windows` | faster-whisper | faster-whisper + ChatTTS |
| `Linux` | faster-whisper | faster-whisper + ChatTTS |

> **注意**：mlx-whisper 是 Apple 的机器学习框架，**只能在 Apple Silicon (M 系列芯片) 的 Mac 上运行**。Intel Mac、Windows、Linux 用户只能用 faster-whisper。

## 第二步：安装依赖

### 安装 ffmpeg

```bash
# macOS
brew install ffmpeg

# Windows (用管理员权限的 PowerShell)
winget install ffmpeg

# Linux (Ubuntu/Debian)
sudo apt install ffmpeg
```

验证安装：

```bash
ffmpeg -version
```

### 安装 Python 依赖

项目本身用 `uv sync` 或 `pip install -e .` 安装。模型下载需要额外的库：

```bash
pip install huggingface_hub[hf_transfer]
```

按项目要求 `pip install -e .` 或 `uv sync` 必须在**第一步做**，这里只强调模型下载需要额外安装的包。

## 第三步：用脚本下载模型

项目提供了 `scripts/download_models.py`，它会自动从 HuggingFace 拉取模型到 `models/` 目录。

### 最简单的方式：自动检测下载

```bash
python scripts/download_models.py --auto
```

脚本会自动检测你的平台，下载推荐的模型组合。

### 先看看有哪些模型可选

```bash
python scripts/download_models.py --list
```

输出示例（Apple Silicon Mac）：

```
平台: macOS Apple Silicon (arm64)

mlx-whisper 模型 [✓ 本机可用]:
  whisper-large-v3-turbo              ← mlx-community/whisper-large-v3-turbo
  whisper-medium                      ← mlx-community/whisper-medium
  whisper-tiny                        ← mlx-community/whisper-tiny

faster-whisper 模型 [✓ 本机可用]:
  faster-whisper-medium               ← Systran/faster-whisper-medium
  faster-whisper-large-v3             ← Systran/faster-whisper-large-v3

ChatTTS 模型 [✓ 本机可用]:
  ChatTTS                             ← 2Noise/ChatTTS
```

在非 Apple Silicon 平台上，mlx-whisper 会自动标记为 `✗ 仅 Apple Silicon`。

### 手动指定模型

```bash
# 只下载 faster-whisper（跨平台）
python scripts/download_models.py --asr faster

# 只下载 mlx-whisper（仅 Apple Silicon）
python scripts/download_models.py --asr mlx

# 只下载 ChatTTS
python scripts/download_models.py --tts chattts

# 下载所有兼容你平台的模型
python scripts/download_models.py --all
```

## 第四步：模型大小和下载时间参考

| 模型 | 大小 | 用途 | 推荐场景 |
|------|------|------|---------|
| whisper-large-v3-turbo | ~1.5 GB | ASR（mlx） | macOS，高质量 |
| whisper-medium | ~1.2 GB | ASR（mlx） | macOS，均衡 |
| whisper-tiny | ~0.2 GB | ASR（mlx） | macOS，快速验证 |
| faster-whisper-medium | ~3 GB | ASR（CTranslate2） | Windows/Linux |
| faster-whisper-large-v3 | ~3 GB | ASR（CTranslate2） | Windows/Linux，高质量 |
| ChatTTS | ~1.5 GB | TTS | 跨平台本地 TTS |

> 下载时间取决于网络。国内用户建议走代理或镜像加速（见文末"网络问题"）。

## 第五步：验证下载结果

下载完成后检查目录结构：

```bash
ls -la models/asr/
ls -la models/tts/
```

以 Apple Silicon Mac 下载了全部模型为例，最终结构：

```
models/
├── asr/
│   ├── whisper-large-v3-turbo/   # mlx-whisper 模型
│   ├── whisper-medium/           # mlx-whisper 模型
│   └── whisper-tiny/             # mlx-whisper 模型
└── tts/
    └── ChatTTS/                  # ChatTTS 模型
```

Windows/Linux 用户的结构：

```
models/
├── asr/
│   ├── faster-whisper-medium/
│   └── faster-whisper-large-v3/
└── tts/
    └── ChatTTS/
```

## 第六步：配置 config.yaml

模型下载后，在 `config.yaml` 中指定模型路径。

### Apple Silicon（mlx-whisper + ChatTTS）

```yaml
asr:
  engine: "mlx-whisper"
  model_path: "models/asr/whisper-large-v3-turbo/"
  language: "en"
  proper_nouns: []

tts:
  engine: "chattts"
  model_path: "models/tts/ChatTTS/"
  voice: "default"
  speed: 1.0
```

### Windows / Linux（faster-whisper + ChatTTS）

```yaml
asr:
  engine: "faster-whisper"
  model_path: "models/asr/faster-whisper-medium/"
  language: "en"
  proper_nouns: []

tts:
  engine: "chattts"
  model_path: "models/tts/ChatTTS/"
  voice: "default"
  speed: 1.0
```

## 附：如果要用 CosyVoice

CosyVoice 目前无法一键下载，需要手动部署。参考：

→ [CosyVoice 部署指南](cosyvoice-deployment-guide.md)

如果不想折腾 CosyVoice，可以用 Edge-TTS（云端免费，零配置）：

```yaml
tts:
  engine: "edge-tts"
  voice: "zh-CN-XiaoxiaoNeural"
  speed: 1.0
```

## 模型组合推荐

| 方案 | ASR | TTS | 内存占用 | 适合谁 |
|------|-----|-----|---------|--------|
| 高质量 | whisper-large-v3-turbo | CosyVoice | ~7 GB | macOS，追求质量 |
| 均衡 | whisper-medium | ChatTTS | ~5.5 GB | macOS，日常使用 |
| 快速 | whisper-tiny | Edge-TTS | ~0.5 GB | 快速验证、低配机器 |
| Windows | faster-whisper-medium | ChatTTS | ~5 GB | Windows/Linux 日常 |
| Windows 轻量 | faster-whisper-medium | Edge-TTS | ~3 GB | Windows/Linux 低配 |

## 网络问题

如果下载很慢或失败，可以设置 HuggingFace 镜像：

```bash
export HF_ENDPOINT=https://hf-mirror.com
python scripts/download_models.py --auto
```

或者挂代理后运行。脚本使用的是 `huggingface_hub.snapshot_download()`，会自动遵循 `HF_ENDPOINT` 环境变量。
