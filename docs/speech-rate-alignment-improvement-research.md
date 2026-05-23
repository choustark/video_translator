# 语速自适应对齐改进研究

> 生成日期：2026-05-23
> 上下文：v1 管线已跑通，当前对齐层仅实现第 3 层（后期对齐），本文档调研四层策略中未实现的改进方向。

---

## 目录

- [1. 当前实现现状](#1-当前实现现状)
- [2. 音频变速算法升级（第 3 层改进）](#2-音频变速算法升级第-3-层改进)
- [3. 翻译时长控制（第 1 层：源头控制）](#3-翻译时长控制第-1-层源头控制)
- [4. TTS 语速控制（第 2 层：合成微调）](#4-tts-语速控制第-2-层合成微调)
- [5. 行业竞品方案](#5-行业竞品方案)
- [6. 改进优先级与路线图](#6-改进优先级与路线图)
- [7. 参考文献](#7-参考文献)

---

## 1. 当前实现现状

### 1.1 四层策略总览

| 层 | 手段 | v1 状态 | 说明 |
|---|------|---------|------|
| 1. 源头控制 | LLM 翻译时生成口语化、时长接近的译文 | 部分 | 翻译 prompt 有引导但无显式时长约束 |
| 2. 合成微调 | TTS 引擎语速参数 | 未实现 | CosyVoice v1 无原生语速参数 |
| **3. 后期对齐** | **静音填充 + atempo 加速** | **已实现** | `src/composer/speed_adapter.py` |
| 4. 全局优化 | 整段话节奏平衡 | 未实现 | v2.0 范围 |

### 1.2 当前对齐逻辑

核心代码位于 `src/composer/speed_adapter.py`，`SpeedAdapter.align()` 方法：

```
对于每个 segment:
  target_duration = end_time - start_time   （英文原时间窗口）
  actual_duration = audio_duration           （TTS 中文音频实际时长）

  if actual < target:
      → _pad()    静音填充到 target 时长（ffmpeg apad）
  elif actual > target:
      speed_ratio = actual / target
      if ratio ≤ 1.5x:
          → _speed_up()  加速压缩到 target 时长（ffmpeg atempo）
      else:
          → _copy()      超过 1.5x 就跳过加速，保留原音频
  else:
      → _copy()      刚好相等，直接拷贝
```

三个关键阈值：

| 常量 | 值 | 含义 |
|------|-----|------|
| `_MAX_SPEED_RATIO` | 1.5 | 超过此比率不加速（超过 1.5x 语速明显不自然） |
| `_SINGLE_DEVIATION_THRESHOLD` | 0.15 | 单段对齐后偏差 >15% → 打 warning 日志 |
| `_GLOBAL_DEVIATION_THRESHOLD` | 0.10 | 全局总时长偏差 >10% → 打 warning 日志 |

### 1.3 当前局限

- `atempo` 本质是 WSOLA 算法，对语音质量不如专门的语音变速算法
- 偏差只报警不阻断，超 1.5x 直接放弃
- 翻译 prompt 未显式约束译文长度
- TTS 引擎无语速控制能力

---

## 2. 音频变速算法升级（第 3 层改进）

### 2.1 算法对比

当前使用的 `atempo` 本质是 **WSOLA（Waveform Similarity Overlap-Add）** 算法。WSOLA 对音乐效果好，但对语音不理想——尤其在 1.3x 以上会出现明显伪影。

| 算法 | 库 | 语音质量 | 速度 | 适用场景 | 备注 |
|------|-----|---------|------|---------|------|
| **ESOLA** (Epoch-Synchronous OLA) | `esolafast` (C) | 最高 | 极快（0.66s/12s 音频） | 专业语音变速 | ESOLA 论文基准测试：比 TD-PSOLA 快 100 倍且质量更好 |
| **TD-PSOLA / PICOLA** | `libsonic` (C) | 高 | 极快 | YouTube 播放加速 | YouTube 使用的就是 sonic/PICOLA |
| **Rubber Band** | `pyrubberband` / ffmpeg 内置 | 高 | 中等 | 通用音频 | ffmpeg 2022 年后原生支持 `rubberband` 滤镜 |
| **atempo**（当前） | ffmpeg 内置 | 中 | 快 | 通用音频 | WSOLA，对语音不如上面几个 |

### 2.2 关键发现

1. **Audacity 讨论结论**（GitHub #1524）：
   > "WSOLA works best for music and leaves much to be desired for speech. For speech, TD-PSOLA via sonic (which YouTube uses) is better. ESOLA is even better."

2. **ESOLA 论文基准**（arXiv:1801.06492）——12 秒语音 1.5x 变速：

   | 算法 | 耗时 |
   |------|------|
   | TD-PSOLA | 74.25s |
   | WSOLA (atempo) | 3.22s |
   | **ESOLA** | **0.66s** |

3. **pyvideotrans**（国内最活跃的开源视频翻译项目）**已经用 `pyrubberband` 替代了 atempo**，还保留了 ffmpeg 作为降级方案。

4. **ffmpeg 原生支持 rubberband 滤镜**（2022 年后），不需要额外的 Python 绑定：
   ```bash
   ffmpeg -i input.wav -filter:a "rubberband=tempo=1.3" output.wav
   ```

### 2.3 推荐路径

| 阶段 | 改动 | 风险 | 效果 |
|------|------|------|------|
| **v1.1** | `atempo` → `rubberband` | 极低（改 1 行 ffmpeg filter 字符串） | 变速质量显著提升 |
| **v2.0** | `rubberband` → ESOLA/sonic | 中（需编译 C 库） | 语音质量最高 |

### 2.4 rubberband 集成方式

**方案 A：ffmpeg 内置滤镜（推荐，零依赖）**

```python
# src/composer/speed_adapter.py _speed_up() 方法
# 当前：
"-filter:a", f"atempo={speed_ratio:.4f}",

# 改为：
"-filter:a", f"rubberband=tempo={speed_ratio:.4f}",
```

前提：ffmpeg 编译时需启用 rubberband 支持。macOS `brew install ffmpeg` 默认启用。

**方案 B：pyrubberband Python 库**

```python
import pyrubberband
import soundfile as sf

y, sr = sf.read("input.wav")
y_stretched = pyrubberband.time_stretch(y, sr, speed_ratio, rbargs={'--fine': '--fine'})
sf.write("output.wav", y_stretched, sr)
```

需额外安装：`pip install pyrubberband` + 系统安装 `rubberband` CLI。

---

## 3. 翻译时长控制（第 1 层：源头控制）

这是学术研究最密集的方向，统称 **"等距翻译（Isometric Translation）"**。

### 3.1 核心论文

| 论文 | 机构/会议 | 关键方法 | URL |
|------|----------|---------|-----|
| **VideoDubber** | 微软 / AAAI 2023 | MT 模型直接预测每个 token 的语音时长，控制生成长度 | https://speechresearch.github.io/videodubbing |
| **Isometric MT** | Amazon | 自学习等距 MT，翻译长度控制在源文本 ±10% 字符内 | https://assets.amazon.science/.../isometric-mt-neural-machine-translation-for-automatic-dubbing.pdf |
| **Duration-based Translation** | EMNLP 2025 | 音素计数预测器 + 迭代反馈循环，预测最佳翻译长度 | https://aclanthology.org/2025.emnlp-demos.37.pdf |
| **Joint Translation & Timing** | Amazon | 联合优化翻译质量 + 音素时长，55% 的等距提升 | https://ar5iv.labs.arxiv.org/html/2302.12979 |
| **LSST (Length-Sensitive ST)** | Interspeech 2025 | 生成短/中/长三个翻译候选，用时长的模型选最优 | https://arxiv.org/html/2506.00740v1 |
| **Dub-S2ST** | 2025 | 无文本端到端语音翻译 + 离散扩散时长控制 | https://arxiv.org/html/2505.20899v1 |
| **Target Factors for Dubbing** | IWSLT 2024 | 用 target factors 预测音素时长 + 辅助计数器 | https://ar5iv.labs.arxiv.org/html/2305.13204 |
| **Pause-Aware Dubbing** | IWSLT 2024 | LLM 后编辑 + VITS 语速控制 + 语音克隆 | https://aclanthology.org/pdf/iwslt/2024.iwslt-1.2.pdf |

### 3.2 可落地的技术方案

#### 方案 A：Prompt 注入时长约束（最简单，v1.1 可做）

在翻译 prompt 中加入显式时长约束：

```
将以下英文翻译为中文。要求：
1. 译文口语化，适合朗读配音
2. 原文朗读时长约 {duration} 秒，中文口语语速约 4 字/秒
3. 请控制译文在 {chars} 字左右（±2 字），以确保配音时长与原文接近
```

**优点**：零代码改动（仅改 prompt），立即生效。
**缺点**：LLM 不一定严格遵守字数约束，但对 ±15% 范围内的调整效果不错。

#### 方案 B：多候选翻译 + 时长预估选择（中等复杂度）

参考 LSST 论文：

1. 让 LLM 生成 3 个候选（短/中/长），分别标注字数
2. 用简单公式估算每个候选的 TTS 时长：`estimated = chars / 4.0`（秒）
3. 选择最接近目标时间窗口的候选
4. 如需更精确：可用音素时长模型（如 FastSpeech2 的 duration predictor）

**优点**：更精准的时长匹配。
**缺点**：翻译 API 调用成本 x3，但 GLM API 成本极低（~$0.05/10min）。

#### 方案 C：音素计数预测器（复杂，参考 Duration-based Translation）

训练一个轻量模型：

```
输入：源文本 + 目标时长
输出：目标翻译应有音素数
```

### 3.3 中文语速基准数据

| 指标 | 数值 | 来源 |
|------|------|------|
| 中文口语语速 | 3.5~4.5 字/秒（正常语速） | 行业通用 |
| 英→中长度比 | 中文比英文短 20~30%（按字符计） | IWSLT / Amazon 研究 |
| 等距容差 | ±10% 时长差对齐效果可接受 | Isometric MT (Amazon) |
| 等距合规定义 | 翻译长度在源文本 ±10% 字符范围内 | IWSLT 2022 Isometric Task |

---

## 4. TTS 语速控制（第 2 层：合成微调）

### 4.1 CosyVoice 语速控制能力

| 版本 | 语速控制能力 | 说明 |
|------|-------------|------|
| **CosyVoice 1.0**（当前） | 无原生语速参数 | subprocess 桥无 speed 参数传递 |
| **CosyVoice 2.0** | 支持 streaming，语速控制有限 | https://arxiv.org/html/2412.10117v1 |
| **Fun-CosyVoice 3.0** | 支持 SSML `<prosody rate="...">` | https://arxiv.org/html/2505.17589v1 |
| **阿里云 CosyVoice API** | 完整 SSML 支持（rate/pitch/volume/pause） | https://www.alibabacloud.com/help/en/model-studio/introduction-to-cosyvoice-ssml-markup-language |

### 4.2 Edge-TTS 语速控制

Edge-TTS 已原生支持 `rate` 参数，**零成本即可加上**：

```python
# 当前：
communicate = edge_tts.Communicate(text, voice)

# 加速 20%：
communicate = edge_tts.Communicate(text, voice, rate="+20%")

# 减速 30%：
communicate = edge_tts.Communicate(text, voice, rate="-30%")
```

支持范围：`rate="-50%"` 到 `rate="+100%"`。

### 4.3 升级路径

| 阶段 | 改动 | 工作量 |
|------|------|--------|
| **v1.1** | Edge-TTS 加 `rate` 参数 | 改几行代码 |
| **v1.1** | CosyVoice subprocess 桥传 speed 参数 | 改 worker 协议 |
| **v2.0** | 升级 CosyVoice 3.0，使用 SSML 语速控制 | 升级模型 + 改协议 |

---

## 5. 行业竞品方案

| 项目 | 对齐策略 | 变速技术 | TTS | Stars |
|------|---------|---------|-----|-------|
| **[pyvideotrans](https://github.com/jianchang512/pyvideotrans)** | rubberband 变速 + TTS 语速 + 多段裁切 | `pyrubberband` + ffmpeg 降级 | Edge-TTS / GPT-SoVITS / CosyVoice | ~12k |
| **[VideoLingo](https://github.com/Huanshere/VideoLingo)** | WhisperX 强制对齐 + 配音 | — | GPT-SoVITS / CosyVoice | ~8k |
| **[Auto-Synced-Translated-Dubs](https://github.com/ThioJoe/Auto-Synced-Translated-Dubs)** | rubberband/ffmpeg 双引擎 | `pyrubberband`（优先）+ `atempo`（降级） | Edge-TTS / XTTS | ~4k |
| **[KrillinAI](https://github.com/krillinai/KrillinAI)** | CosyVoice 声音克隆 + 对齐 | — | CosyVoice / 自定义 | ~3k |
| **[Linly-Dubbing](https://github.com/Kedreamix/Linly-Dubbing)** | GPT-SoVITS 声音克隆 + 唇形同步 | — | GPT-SoVITS / CosyVoice | ~3k |

### 5.1 pyvideotrans 的具体做法（最成熟的中文视频翻译方案）

`pyvideotrans` 的 `_rate.py` 模块实现了多层变速策略：

1. **首选 `pyrubberband`**：`pyrubberband.time_stretch(y, sr, speed_factor)`
2. **降级 ffmpeg atempo**：当 rubberband 不可用时自动降级
3. **还支持 PTS（Presentation Time Stamp）变速**：用于视频片段的时间拉伸

```python
# pyvideotrans/videotrans/util/help_ffmpeg.py
def change_speed_rubberband(input_path, out_file, target_duration):
    import pyrubberband as pyrb
    import soundfile as sf
    y, sr = sf.read(input_path)
    current_duration = int((len(y) / sr) * 1000)
    speed_factor = current_duration / target_duration
    y_stretched = pyrb.time_stretch(y, sr, speed_factor)
    sf.write(out_file, y_stretched, sr)
```

---

## 6. 改进优先级与路线图

### 6.1 优先级矩阵

| 优先级 | 改进 | 预期效果 | 工作量 | 风险 |
|--------|------|---------|--------|------|
| **P0** | atempo → rubberband | 变速语音质量显著提升 | 改 1 行 filter | 极低 |
| **P1** | Edge-TTS 加 `rate` 参数 | TTS 输出时长更接近目标 | 改几行代码 | 极低 |
| **P2** | 翻译 prompt 加时长约束 | 从源头减少对齐压力 | 改 prompt | 低 |
| **P3** | 多候选翻译 + 时长选择 | 更精准的时长匹配 | 中等 | 中 |
| **P4** | CosyVoice 3.0 SSML 语速 | TTS 原生语速控制 | 升级模型 | 高 |
| **P5** | 全局节奏优化（第 4 层） | 整段话节奏更自然 | 大工程 | 高 |

### 6.2 推荐实施顺序

```
v1.1 阶段（半天~1 天）：
  P0: rubberband 替换 atempo
  P1: Edge-TTS rate 参数
  P2: 翻译 prompt 时长约束

v1.1 后续（1~2 天）：
  P3: 多候选翻译 + 时长选择
  P4: CosyVoice subprocess 桥传 speed 参数

v2.0 阶段：
  ESOLA/sonic 替代 rubberband
  CosyVoice 3.0 SSML 语速
  全局节奏优化
```

### 6.3 效果预估

当前 v1 的典型对齐偏差分布（基于 10 分钟英文视频）：

- 约 30% 段落在 ±5% 以内（几乎无感）
- 约 40% 段落在 ±15% 以内（可接受）
- 约 20% 段落在 15%~30%（听感不自然）
- 约 10% 段落超过 30%（明显对不上）

实施 P0+P1+P2 后的预期改善：

- ±5% 以内：30% → **60%**
- 可接受范围：40% → **30%**
- 需要后期对齐的"重活"：30% → **10%**

---

## 7. 参考文献

### 论文

1. **VideoDubber** - Wu et al., "Machine Translation with Speech-Aware Length Control for Video Dubbing", AAAI 2023. https://speechresearch.github.io/videodubbing

2. **Isometric MT** - Lakew et al., "Isometric MT: Neural Machine Translation for Automatic Dubbing", Amazon. https://assets.amazon.science/bb/7f/0d5610424183b9678973f3c4e4f1/isometric-mt-neural-machine-translation-for-automatic-dubbing.pdf

3. **Duration-based Translation** - "End-to-End Multilingual Automatic Dubbing via Duration-based Translation", EMNLP 2025. https://aclanthology.org/2025.emnlp-demos.37.pdf

4. **Joint Translation & Timing** - Chronopoulou et al., "Jointly Optimizing Translations and Speech Timing to Improve Isochrony in Automatic Dubbing", 2023. https://ar5iv.labs.arxiv.org/html/2302.12979

5. **LSST** - Subramanian et al., "Length Aware Speech Translation for Video Dubbing", Interspeech 2025. https://arxiv.org/html/2506.00740v1

6. **Dub-S2ST** - Choi et al., "Textless Speech-to-Speech Translation for Seamless Dubbing", 2025. https://arxiv.org/html/2505.20899v1

7. **Target Factors for Dubbing** - Pal et al., "Improving Isochronous Machine Translation with Target Factors and Auxiliary Counters", IWSLT 2024. https://ar5iv.labs.arxiv.org/html/2305.13204

8. **Pause-Aware Dubbing** - "Pause-Aware Automatic Dubbing using LLM and Voice Cloning", IWSLT 2024. https://aclanthology.org/pdf/iwslt/2024.iwslt-1.2.pdf

9. **Length-Aware NMT** - "Length-Aware NMT and Adaptive Duration for Automatic Dubbing", IWSLT 2023. https://aclanthology.org/2023.iwslt-1.9.pdf

10. **ESOLA** - "Epoch-Synchronous Overlap-Add (ESOLA) for Time-Scale Modification of Speech", 2018. https://arxiv.org/pdf/1801.06492

### 竞赛/基准

11. **IWSLT 2024 Dubbing Track** - 英→中方向已有 baseline. https://iwslt.org/2024/dubbing

12. **IWSLT 2022 Isometric Translation Task** - 等距翻译评测标准定义. https://iwslt.org/2022/isometric

13. **Amazon IWSLT Auto-dub Task** - Baseline 代码和数据. https://github.com/amazon-science/iwslt-autodub-task

14. **Amazon Isometric SLT** - 等距翻译评测脚本. https://github.com/amazon-science/isometric-slt

### 开源项目

15. **pyvideotrans** - 视频翻译配音工具，已用 pyrubberband. https://github.com/jianchang512/pyvideotrans

16. **VideoLingo** - Netflix 级字幕+配音. https://github.com/Huanshere/VideoLingo

17. **Auto-Synced-Translated-Dubs** - rubberband/ffmpeg 双引擎. https://github.com/ThioJoe/Auto-Synced-Translated-Dubs

18. **KrillinAI** - AI 视频翻译配音. https://github.com/krillinai/KrillinAI

19. **Linly-Dubbing** - 多语言 AI 配音. https://github.com/Kedreamix/Linly-Dubbing

### 技术参考

20. **Audacity 算法讨论** - WSOLA vs PSOLA vs ESOLA for speech. https://github.com/audacity/audacity/discussions/1524

21. **Sox vs Rubberband 对比** - Justin Salamon 的听感评测. https://www.justinsalamon.com/news/sox-vs-rubberband-for-pitch-shifting-and-time-stretching

22. **CosyVoice 3.0** - FunAudioLLM. https://github.com/FunAudioLLM/CosyVoice

23. **阿里云 CosyVoice SSML** - 语速/音高/停顿控制. https://www.alibabacloud.com/help/en/model-studio/introduction-to-cosyvoice-ssml-markup-language
