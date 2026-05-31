# Video Translator

> [English version](README.md)

Apple Silicon 原生的英文→中文视频翻译工具。拖入视频，一键输出中文配音视频 + 字幕。

## 为什么做这个

市面上的视频翻译工具（pyvideotrans、VideoLingo）把 AI 模型打包给你用，你被工具的选择锁定。video_translator 反过来——**你自带模型，软件只做编排**。新模型发布后直接切换，不用等软件更新。

## 项目亮点

- **模型自主权** — ASR / 翻译 / TTS 每个环节独立可选、可替换（策略模式架构）
- **Apple Silicon 原生优化** — mlx-whisper + MPS/Metal 加速，其他同类项目均未实现
- **极低成本** — 翻译走 API（GLM/DeepSeek），ASR/TTS 本地免费，10 分钟视频约 ¥0.3
- **语速自适应对齐** — 四层递进策略解决中文配音与英文画面的时间同步问题
- **三种输出** — 合成视频（硬字幕烧录）+ SRT 字幕 + 中文音频，拿到所有材料不用二次处理
- **翻译前校验** — ffmpeg / 模型文件 / API Key / 格式 / 时长全检查，不开始就拦截问题

## 六阶段管线

```
音频提取(ffmpeg) → ASR(mlx-whisper) → 翻译(API) → TTS(CosyVoice/Edge-TTS) → 语速自适应 → 合成(ffmpeg)
```

## 安装

### 前置条件

- macOS 12+ (Apple Silicon)
- Python 3.13+
- [ffmpeg](https://ffmpeg.org/)（`brew install ffmpeg`）
- 16GB+ 内存（推荐 24GB）
- 10-15GB 磁盘空间（存放模型）

### 安装步骤

```bash
# 克隆仓库
git clone git@github.com:choustark/video_translator.git
cd video_translator

# 安装依赖（推荐用 uv）
uv sync

# 或用 pip
pip install -e .
```

### 下载模型

项目提供一键下载脚本，自动检测平台并拉取所需模型：

```bash
# 安装下载依赖
pip install huggingface_hub[hf_transfer]

# 自动检测平台，下载推荐模型（推荐）
python scripts/download_models.py --auto

# 查看所有可用模型 + 平台兼容性
python scripts/download_models.py --list
```

**Apple Silicon Mac** 会自动下载 mlx-whisper + ChatTTS，**Windows / Linux** 会自动下载 faster-whisper + ChatTTS。

如需 CosyVoice（更高质量的本地 TTS），需手动部署，见 [CosyVoice 部署指南](docs/cosyvoice-deployment-guide.md)。不想折腾本地 TTS 可用 Edge-TTS（云端免费，零配置）。

详细说明见 [模型下载指南](docs/model-download-guide.md)。

### API Key

翻译后端需要 API Key。创建 `.env` 文件：

```bash
# GLM（智谱）— 默认后端，成本最低
GLM_API_KEY=your_key_here

# DeepSeek
DEEPSEEK_API_KEY=your_key_here
```

## 使用

```bash
# 启动桌面应用
python main.py
```

1. **配置** — 在设置面板中指定 ASR 模型路径、翻译后端 + API Key、TTS 引擎
2. **拖入视频** — 将 mp4/mkv/mov/avi 视频拖入主界面
3. **校验** — 系统自动检查环境，绿色勾表示一切就绪
4. **开始翻译** — 点击按钮，六阶段管线自动执行，实时显示进度
5. **获取结果** — 翻译完成后在 `output/` 目录找到三种产物

### 预设配置方案

| 方案 | ASR | 翻译 | TTS | 内存占用 |
|------|-----|------|-----|---------|
| 高质量（默认） | large-v3-turbo | GLM API | CosyVoice | ~7GB |
| 均衡 | medium | DeepSeek | CosyVoice | ~5.5GB |
| 快速 | tiny | DeepSeek | Edge-TTS | ~0.5GB |
| 全离线 | medium | NLLB 本地 | CosyVoice | ~8GB |

也可保存自定义方案，按视频类型灵活切换。

## 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 桌面框架 | PySide6 | Qt 官方 Python 绑定 |
| ASR | mlx-whisper | Apple Silicon MPS 加速 |
| 翻译 | GLM / DeepSeek / OpenAI / DeepL | 策略模式，可扩展 |
| TTS | CosyVoice / ChatTTS / Edge-TTS | 本地优先，云端降级 |
| 音视频处理 | ffmpeg | 拖入视频、提取、合成、字幕烧录 |
| 配置 | YAML + pydantic | 类型安全校验 |
| Python | 3.13+ | 利用最新语言特性 |

## 项目结构

```
video_translator/
├── main.py                 # 入口
├── config.yaml             # 默认配置
├── pyproject.toml          # 项目配置
├── src/
│   ├── asr/                # ASR 引擎（mlx-whisper）
│   ├── translation/        # 翻译后端（GLM/DeepSeek/...）
│   ├── tts/                # TTS 引擎（CosyVoice/Edge-TTS）
│   ├── composer/           # 音视频合成 + 语速自适应
│   ├── gui/                # PySide6 UI 组件
│   ├── pipeline.py         # 管线编排器
│   ├── config.py           # 配置管理
│   ├── models.py           # 数据模型
│   └── validators.py       # 翻译前校验
├── tests/                  # 测试（pytest）
├── docs/                   # 文档（模型下载指南等）
├── scripts/                # 辅助脚本（模型下载等）
└── models/                 # AI 模型文件（.gitignore）
```

## 开发

```bash
# 安装开发依赖
uv sync --group dev

# 运行测试
uv run pytest

# 代码检查
uv run ruff check src/ tests/

# 类型检查
uv run mypy src/
```

## 路线图

### v1（当前 — MVP） ✅

- [x] PySide6 桌面 UI（拖入视频 + 配置面板 + 进度展示）
- [x] 六阶段管线完整跑通
- [x] 翻译前校验（ffmpeg / 模型 / API Key / 格式 / 时长）
- [x] 语速自适应（居中静音填充 + atempo 加速）
- [x] 配置管理（多方案 + 预设 + 记忆）
- [x] 三种输出（合成视频 + SRT + 音频）

### v1.1（质量提升） ✅

- [x] 多翻译后端（DeepSeek / OpenAI）
- [x] 用户中止机制
- [x] API Key 安全存储（.env）
- [x] 语速自适应（居中静音填充 + atempo 加速）
- [x] 字幕样式预设系统
- [x] 翻译时长约束 + 口语化优化
- [x] ASR 专有名词引导 + 片段合并

### v1.2（界面精简 + 跨平台） ✅

- [x] 移除语速滑块（已由三层自动化覆盖）
- [x] 音频提取实时进度
- [x] FasterWhisperEngine 实现（跨平台 ASR）
- [x] Windows 跨平台支持
- [x] ChatTTS 引擎集成
- [x] ASR/翻译结果一键复制

### v2.0（体验进阶）🔜

- [ ] 长视频分段处理（>10 分钟）
- [ ] 单句编辑重合成
- [ ] 多语言支持
- [ ] 唇形同步（Wav2Lip / MuseTalk）
- [ ] 多说话人识别（WhisperX）

### v3.0（差异化）

- [ ] GPT-SoVITS 声音克隆
- [ ] dmg / pkg 安装包
- [ ] 批量队列
- [ ] 产品正式命名

## License

MIT
