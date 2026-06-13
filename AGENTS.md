# video_translator 项目指南

## 项目概述

video_translator 是一个 PySide6 桌面应用，面向有技术背景的个人用户，在 Apple Silicon（M5, 24GB）上将英文视频翻译为中文配音视频。定位为**管线编排器**——用户自带模型，软件只做编排。

目标硬件：MacBook Air M5，单次处理 ≤30 分钟视频。

## 用户画像

- 用户：Mr.ChouCj，个人项目，不以收入为目标
- 开发节奏：时间充裕，不限截止日期，质量优先于速度
- 沟通语言：中文（普通话）
- 技术水平：有技术背景，能理解 AI 模型、Python、命令行等概念
- 偏好：极简主义，拒绝复杂分层设计，追求开箱即用

## 关键技术决策及理由

| 决策 | 选择 | 为什么不选其他 |
|------|------|---------------|
| 桌面框架 | PySide6 | Qt 官方维护，LGPL 协议友好；不做 Electron/Web 路线，PySide 也可以做得好看 |
| ASR | mlx-whisper + large-v3-turbo | Apple Silicon 优化，其他 whisper 变体无 MPS 加速 |
| 翻译 | GLM API（默认）| 成本极低 ~$0.05/10min；同时支持 DeepSeek/OpenAI/DeepL/NLLB 本地 |
| TTS | CosyVoice（v1 主力） | Apache 2.0 开源，支持语速控制；不选 GPT-SoVITS（v2 再考虑声音克隆）；macOS 部署较复杂，见 `docs/cosyvoice-deployment-guide.md` |
| TTS 备选 | Edge-TTS | 云端免费，作为 OOM 降级方案；v1 当前实际主力 |
| TTS 本地备选 | sherpa-onnx + MeloTTS | `pip install sherpa-onnx` 一行安装，macOS 原生支持，离线运行；CosyVoice 部署失败时的优先替代 |
| 音视频引擎 | ffmpeg | 不内置，用户 brew install 自行安装 |
| 配置格式 | YAML + pydantic 校验 | 开发者友好，可读性好 |
| 分发 | pip install + Docker（v1） | v3.0 再做 dmg/pkg |
| 原声处理 | 完全替换为中文配音 | 不做双语声道或混合 |
| 字幕 | 硬字幕烧录（ffmpeg） | 字幕烧录到视频画面中 |
| GPU 加速 | 自动检测 MPS/Metal | 用户无感，不在界面暴露 GPU 开关 |
| 失败恢复 | v1 不做断点续传，失败从头重跑 | 简单可靠 |
| 视频长度 | 限 30 分钟（1800 秒） | v1 从 10 分钟放宽至 30 分钟；分段处理留到 v2.0 |

## 核心创新：语速自适应对齐算法

视频翻译最大难题是中文配音与英文画面的时间对齐。四层递进策略：
1. 源头控制：LLM 翻译时生成"口语化、时长接近原文"的译文
2. 合成微调：CosyVoice 语速参数控制
3. 后期对齐：静音填充 + 词间隙微裁剪（**v1 实现此层**）
4. 全局优化：整段话节奏平衡

v1 实现了第 3 层（居中静音填充 + rubberband 变速），v1.1 增强了第 1 层（翻译 prompt 时长约束）和第 2 层（Edge-TTS rate 参数），四层策略已有三层落地。

## 六阶段管线

```
音频提取(ffmpeg) → ASR(mlx-whisper) → 翻译(API) → TTS(CosyVoice) → 语速自适应 → 合成(ffmpeg)
```

输出三种产物：合成视频（硬字幕烧录）+ SRT 字幕 + 中文音频。

## 架构模式

- **Pipe-and-Filter** + **Strategy Pattern**
- 每个环节（ASR/翻译/TTS）独立可选、可替换
- ASR 和 TTS 顺序加载、顺序释放（ASR 完成后主动释放 MLX Metal 缓存：del + gc.collect() + mx.clear_cache()），峰值内存 ~7GB
- ASR 执行时后台预加载 TTS 模型

## 预设配置方案

| 方案名 | ASR | 翻译 | TTS | 内存 |
|--------|-----|------|-----|------|
| 高质量（默认） | large-v3-turbo | GLM API | CosyVoice | ~7GB |
| 均衡 | medium | DeepSeek | CosyVoice | ~5.5GB |
| 快速 | tiny | DeepSeek | Edge-TTS | ~0.5GB |
| 全离线 | medium | NLLB 本地 | CosyVoice | ~8GB |

## 分阶段交付

- **v1（MVP）：** ✅ 跑通完整管线，PySide6 UI + 翻译前校验 + 管线可视化 + 配置管理 + 错误恢复
- **v1.1（质量提升）：** ✅ ASR 专有名词/碎片段、翻译时长约束、rubberband 变速、Edge-TTS 语速控制、配置面板 UX 修补、字幕样式预设、abort 机制、内存阈值统一、DeepSeek 翻译后端、API Key 安全存储
- **v2.0（体验进阶）：** 断点续传+时长放宽、CosyVoice 声音克隆（已验证）、删除已保存方案UI精简配置面板
- **v3.0（差异化）：** 单句编辑重合成、多说话人识别（WhisperX）、多语言支持（日/韩/粤）、唇形同步、dmg/pkg 安装包、批量队列、产品正式命名

## BMad 工作流进度

使用 BMad Method 进行产品规划，模块：BMad Method。

### 1-analysis ✅ 已完成

- [x] 技术调研 → `_bmad-output/planning-artifacts/research/technical-english-to-chinese-video-translator-python-research-2026-04-28.md`
- [x] 头脑风暴 → `_bmad-output/brainstorming/brainstorming-session-2026-05-08-1430.md`（27 项产品决策）

### 2-planning ✅ 已完成

- [x] 产品技术规格 → `_bmad-output/planning-artifacts/product-technical-spec-2026-05-09.md`
- [x] PRD → `_bmad-output/planning-artifacts/prd.md`（46 条 FR + 19 条 NFR）
- [x] PRD v1.1 → `_bmad-output/planning-artifacts/prd-v1.1.md`（FR44~FR58，15 条新增）

### 3-solutioning ✅ 已完成

- [x] UX 设计 → `_bmad-output/planning-artifacts/ux-design-specification.md`
- [x] 架构设计 → `_bmad-output/planning-artifacts/architecture.md`
- [x] Epic/Story 拆分 → `_bmad-output/planning-artifacts/epics.md`
- [x] Epic/Story v1.1 拆分 → `_bmad-output/planning-artifacts/epics-v1.1.md`
- [x] 实施就绪检查 → `_bmad-output/planning-artifacts/implementation-readiness-report-2026-05-12.md`

### 4-implementation ✅ 已完成

当前进度详见 `_bmad-output/implementation-artifacts/sprint-status.yaml`

**v1（5 Epic，20 Story）：**

| Epic | 状态 | 说明 |
|------|------|------|
| Epic 1: 项目基础与配置管理 | ✅ done | 6 个 story 全部完成 |
| Epic 2: 桌面应用外壳与视频输入 | ✅ done | 3 个 story 全部完成 |
| Epic 3: 翻译前校验 | ✅ done | 2 个 story 全部完成 |
| Epic 4: 端到端翻译管线 | ✅ done | 4-1~4-7 全部完成，含 CosyVoice subprocess 桥 |
| Epic 5: 错误恢复与系统韧性 | ✅ done | 2 个 story 全部完成 |

**v1.1（5 Epic，13 Story）：**

| Epic | 状态 | 说明 |
|------|------|------|
| Epic 1-v1.1: ASR 质量提升 | ✅ done | 专有名词引导 + 碎片段合并 |
| Epic 2-v1.1: 翻译与 TTS 质量提升 | ✅ done | 时长约束 + rubberband + Edge-TTS rate + DeepSeek provider |
| Epic 3-v1.1: 配置面板 UX 修补 | ✅ done | 进度消息 + 预设追踪 + 引擎切换 + 资源预估 |
| Epic 4-v1.1: 字幕样式预设 | ✅ done | 3 种预设 + force_style 参数化 + 持久化 + UI |
| Epic 5-v1.1: 稳定性修复 | ✅ done | abort 机制 + 内存阈值统一 + API Key 安全 |

**度量：** v1+v1.1 共 33 Story，497 测试，全部 ruff+mypy+pytest 通过。

**下一步：** 决定进入 v2.0（长视频分段、单句编辑）或 v1.2（处理剩余可选债务 + 原 v1.1 路线图剩余项）。详见 `_bmad-output/implementation-artifacts/deferred-work.md`。

### 输入文档说明

PRD 由三份文档驱动：
1. **产品技术规格** — 头脑风暴 + 技术调研的整合版，含 25 章节和 9 个冲突决策
2. **头脑风暴** — 27 项产品决策，涵盖产品形态、技术选型、交互设计
3. **技术调研** — ~1200 行技术可行性分析

## 项目文件结构

```
video_translator/
├── _bmad-output/
│   ├── brainstorming/           # 头脑风暴产出
│   ├── planning-artifacts/      # PRD、规格、调研、架构、UX 设计
│   │   ├── prd.md               # 主 PRD 文档
│   │   ├── prd-v1.1.md          # v1.1 增量 PRD（FR44~FR58）
│   │   ├── architecture.md      # 架构设计
│   │   ├── ux-design-specification.md  # UX 设计规格
│   │   ├── epics.md             # Epic/Story 拆分
│   │   ├── epics-v1.1.md        # v1.1 Epic/Story 拆分
│   │   ├── implementation-readiness-report-2026-05-12.md
│   │   ├── product-technical-spec-2026-05-09.md
│   │   └── research/            # 技术调研
│   └── implementation-artifacts/ # 开发阶段产物（story 文件、sprint 状态、retro）
│       ├── sprint-status.yaml   # Sprint 进度跟踪（权威数据源）
│       ├── deferred-work.md     # 推迟到后续的已知问题
│       └── epic-*-retro-*.md    # Epic 回顾（v1: 5 个 + v1.1: 1 个整体回顾）
├── src/                         # 源代码
│   ├── asr/                     # ASR 引擎（mlx-whisper）
│   ├── translation/             # 翻译后端（GLM/DeepSeek/本地 NLLB）
│   ├── tts/                     # TTS 引擎（CosyVoice/Edge-TTS）
│   ├── composer/                # 音视频合成（ffmpeg）
│   ├── gui/                     # PySide6 UI 组件
│   ├── utils/                   # 工具函数
│   ├── config.py                # 配置管理（pydantic + YAML）
│   ├── models.py                # 数据模型
│   ├── pipeline.py              # 管线编排器
│   ├── validators.py            # 翻译前校验
│   ├── scheme_manager.py        # 配置方案管理
│   └── signals.py               # Qt 信号定义
├── models/                      # AI 模型文件（.gitignore）
│   └── asr/
│       └── whisper-medium-mlx/  # 已下载
├── tests/                       # 测试
├── scripts/                     # 辅助脚本
├── _bmad/                       # BMad 框架配置
│   ├── bmm/                     # BMad Method 模块
│   └── custom/                  # 自定义覆盖
├── main.py                      # 入口
├── pyproject.toml               # 项目配置
├── ruff.toml                    # Lint/Format 配置
├── config.yaml                  # 默认配置文件
└── Dockerfile                   # Docker 打包
```

## 注意事项

- 所有 BMad skill 建议在**新 context window** 中运行（先 `/clear` 再调用 skill）
- BMad skill 会自动读取 PRD 等输入文档，不依赖对话记忆
- 沟通使用中文，文档产出使用中文
- BMad 的 `on_complete` 和 workflow status file 都是可选定制点，当前留空是正常的
