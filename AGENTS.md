# video_translator 项目指南

## 项目概述

video_translator 是一个 PySide6 桌面应用，面向有技术背景的个人用户，在 Apple Silicon（M5, 24GB）上将英文视频翻译为中文配音视频。定位为**管线编排器**——用户自带模型，软件只做编排。

目标硬件：MacBook Air M5，单次处理 ≤10 分钟视频。

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
| TTS | CosyVoice（v1 主力） | Apache 2.0 开源，支持语速控制；不选 GPT-SoVITS（v2 再考虑声音克隆） |
| TTS 备选 | Edge-TTS | 云端免费，作为 OOM 降级方案 |
| 音视频引擎 | ffmpeg | 不内置，用户 brew install 自行安装 |
| 配置格式 | YAML + pydantic 校验 | 开发者友好，可读性好 |
| 分发 | pip install + Docker（v1） | v3.0 再做 dmg/pkg |
| 原声处理 | 完全替换为中文配音 | 不做双语声道或混合 |
| 字幕 | 硬字幕烧录（ffmpeg） | 字幕烧录到视频画面中 |
| GPU 加速 | 自动检测 MPS/Metal | 用户无感，不在界面暴露 GPU 开关 |
| 失败恢复 | v1 不做断点续传，失败从头重跑 | 简单可靠 |
| 视频长度 | v1 限 10 分钟 | 长视频分段处理留到 v2.0 |

## 核心创新：语速自适应对齐算法

视频翻译最大难题是中文配音与英文画面的时间对齐。四层递进策略：
1. 源头控制：LLM 翻译时生成"口语化、时长接近原文"的译文
2. 合成微调：CosyVoice 语速参数控制
3. 后期对齐：静音填充 + 词间隙微裁剪（**v1 实现此层**）
4. 全局优化：整段话节奏平衡

v1 用简单方案先跑通，不提前优化。

## 六阶段管线

```
音频提取(ffmpeg) → ASR(mlx-whisper) → 翻译(API) → TTS(CosyVoice) → 语速自适应 → 合成(ffmpeg)
```

输出三种产物：合成视频（硬字幕烧录）+ SRT 字幕 + 中文音频。

## 架构模式

- **Pipe-and-Filter** + **Strategy Pattern**
- 每个环节（ASR/翻译/TTS）独立可选、可替换
- ASR 和 TTS 顺序加载、顺序释放，峰值内存 ~8GB
- ASR 执行时后台预加载 TTS 模型

## 预设配置方案

| 方案名 | ASR | 翻译 | TTS | 内存 |
|--------|-----|------|-----|------|
| 高质量（默认） | large-v3-turbo | GLM API | CosyVoice | ~7GB |
| 均衡 | medium | DeepSeek | CosyVoice | ~5.5GB |
| 快速 | tiny | DeepSeek | Edge-TTS | ~0.5GB |
| 全离线 | medium | NLLB 本地 | CosyVoice | ~8GB |

## 分阶段交付

- **v1（MVP）：** 跑通完整管线，PySide6 UI + 翻译前校验 + 管线可视化 + 配置管理
- **v1.1（质量提升）：** 多翻译后端、断点续传、SRT 导入导出、内嵌播放器、字幕样式自定义
- **v2.0（体验进阶）：** 长视频分段、单句编辑重合成、多语言、唇形同步、多说话人识别
- **v3.0（差异化）：** GPT-SoVITS 声音克隆、dmg/pkg 安装包、批量队列、产品正式命名

## BMad 工作流进度

使用 BMad Method 进行产品规划，模块：BMad Method。

### 已完成

- [x] 技术调研 → `_bmad-output/planning-artifacts/research/technical-english-to-chinese-video-translator-python-research-2026-04-28.md`
- [x] 头脑风暴 → `_bmad-output/brainstorming/brainstorming-session-2026-05-08-1430.md`（27 项产品决策）
- [x] 产品技术规格 → `_bmad-output/planning-artifacts/product-technical-spec-2026-05-09.md`
- [x] PRD → `_bmad-output/planning-artifacts/prd.md`（46 条 FR + 19 条 NFR）

### 下一步

按 BMad 流程，PRD 完成后进入 3-solutioning 阶段：

```
当前: PRD ✅
  ↓
[CU] UX 设计 (bmad-create-ux-design) — 可选，对桌面应用有价值
  ↓
[CA] 架构设计 (bmad-create-architecture) — 必须
  ↓
[CE] Epic/Story 拆分 (bmad-create-epics-and-stories) — 必须
  ↓
[IR] 实施就绪检查 (bmad-check-implementation-readiness) — 必经门
  ↓
4-implementation 阶段（Sprint Planning → Dev Story → Code Review）
```

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
│   ├── planning-artifacts/      # PRD、规格、调研
│   │   ├── prd.md               # 主 PRD 文档
│   │   ├── product-technical-spec-2026-05-09.md
│   │   └── research/            # 技术调研
│   └── implementation-artifacts/ # 开发阶段产物（待创建）
├── _bmad/                       # BMad 框架配置
│   ├── bmm/                     # BMad Method 模块
│   ├── custom/                  # 自定义覆盖
│   └── scripts/                 # 解析脚本
└── .Codex/                     # Codex 配置
    └── skills/                  # BMad skills
```

## 注意事项

- 所有 BMad skill 建议在**新 context window** 中运行（先 `/clear` 再调用 skill）
- BMad skill 会自动读取 PRD 等输入文档，不依赖对话记忆
- 沟通使用中文，文档产出使用中文
- BMad 的 `on_complete` 和 workflow status file 都是可选定制点，当前留空是正常的
