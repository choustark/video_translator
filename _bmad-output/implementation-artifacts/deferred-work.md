# Deferred Work (v1 完成后清理)

> 最后更新: 2026-05-30 (v1.1 retro + 语速滑块评估 + 复制功能需求)
> 分类标准：v1.2 必做 / v1.2 可选 / v2.0+ / 已过期可丢弃

---

## v1.1 必做

这些项影响用户体验或存在真实风险，应在 v1.1 首批解决。

| # | 债务 | 来源 | 影响 |
|---|------|------|------|
| ~~D1~~ | **closeEvent 不处理运行中 Pipeline** — daemon 线程被终止时 ffmpeg 子进程变孤儿、临时文件残留，需 abort 机制 | 4-1 review | **已解决** (2026-05-23)：`_abort_requested` → `threading.Event`；四个长阶段 progress callback 中 `_check_abort()` 检查；UI "中止翻译"按钮；`abort()` terminate→wait→kill 子进程 + 清理 temp；VideoDropArea 翻译中状态联动 |
| D30 | **跳段进度消息偏差（4-3/4-4/4-5 共享）** — 跳过段时消息"正在处理 {i+1}/{total}"与实际处理数不一致 | 4-3/4-4/4-5 review | 进度显示不准 |
| D26 | **内存阈值不一致** — validators validate_memory 默认 2GB vs ASR 引擎需 6GB，需统一为单一配置源 | 4-2 review | 校验通过但 ASR OOM |
| D3 | ~~`_OUTPUT_DIR` 相对路径依赖 CWD~~ | 4-1 review | **已解决** — 统一改为 `_PROJECT_ROOT / "output"` / `_PROJECT_ROOT / "logs"` (2026-05-22) |
| D32 | **预设标签不跟随手动修改** — 用户改配置后 combo 仍显示旧预设名，造成误导 | UX 评审 | 用户误导 |
| D33 | **ASR/TTS 引擎类型被预设锁死** — `_collect_config()` 硬编码读取引擎字段，用户无法在 UI 切换 | UX 评审 | 用户无法切换引擎 |
| D14 | **ffmpeg/memory 汇总标签 tooltip** — 配置面板缺少资源预估提示 | 3-2 review | 用户不知资源需求 |
| D43 | **字幕样式不可配置** — 字体大小、颜色、边框等硬编码在 ffmpeg_wrapper.py，用户无法在 UI 调整字幕外观 | 用户反馈 | 字幕与原视频硬字幕重叠时无法调整 |
| D46 | **ASR 专有名词误识别** — mlx-whisper 将 "Claude Code" 误识别为 "quad code"，导致翻译输出"四维码/四轴飞行器"等严重偏离原意。需：(1) whisper `initial_prompt` 参数引导识别；(2) 后处理专有名词替换表（用户可配置） | 用户实测 | 翻译质量严重受损，直接影响产品可信度 |
| D47 | **ASR 碎片段导致字幕重复/不可读** — mlx-whisper 输出大量短片段（490 条中 20 条 <0.5s、183 条间隙 <0.1s），翻译逐碎片处理产生独立字幕"代码。""工具们。"等。需：ASR 后处理合并相邻短片段（<1s 的段合并到前一条），翻译前按语义边界重新分段 | 用户实测 | 字幕碎片化、重复、不可读，与"字幕重复"用户反馈直接相关 |
| D48 | **P0: 音频变速 atempo → rubberband** — `speed_adapter.py` 的 `_speed_up()` 使用 ffmpeg `atempo`（WSOLA 算法），对语音质量不理想（1.3x 以上有明显伪影）。改为 ffmpeg 内置 `rubberband` 滤镜，语音变速质量显著提升。改动量：1 行 filter 字符串。需验证 macOS `brew install ffmpeg` 默认启用 rubberband 支持 | 架构研究 (2026-05-23) | 变速语音质量差，直接影响配音自然度 |
| D49 | **P1: Edge-TTS 加 rate 参数** — `edge_tts.Communicate()` 原生支持 `rate` 参数（如 `rate="+20%"`、`rate="-30%"`），可在 TTS 合成阶段就控制语速，使输出音频时长更接近目标时间窗口。当前 `EdgeTTSEngine` 未使用此参数 | 架构研究 (2026-05-23) | TTS 输出时长偏差大，加重后期对齐负担 |
| D50 | **P2: 翻译 prompt 加时长约束** — 翻译 prompt 中未显式约束译文长度，导致中文译文与英文原文时长差距大。需在 prompt 中注入目标时长信息：如"原文朗读时长约 {duration} 秒，中文口语语速约 4 字/秒，请控制译文在 {chars} 字左右"。对应论文方案：Isometric Translation / Duration-based Translation | 架构研究 (2026-05-23) | 从源头减少对齐压力，提升整体管线质量 |
| ~~D51~~ | **API Key 明文存储在 config.yaml** — `TranslationConfig.api_key` 明文写入 YAML 文件，可能被误提交到 git（已发生过一次）。需迁移到 `.env` 文件（已在 `.gitignore` 中），加载优先级：`.env` > 环境变量 > config.yaml（降级兜底）。GUI 保存时 api_key 写 `.env`，`save_config()` 自动排除 `api_key`。**已解决** (2026-05-23)：新增 `save_api_key_to_env()`、`_load_dotenv()`；`load_config` 合并 .env；`save_config` 排除 api_key；`ConfigPanel._do_save` 写 .env；新增 `python-dotenv` 依赖；477 tests passed | Code Review (2026-05-23) | 安全问题，API Key 泄露风险 |
| ~~D53~~ | **DeepSeekProvider 仅存根** — `translate()` 抛 `NotImplementedError`，"balanced"/"fast" 预设实际不可用 | 用户需求 | **已解决** (2026-05-23)：完整实现，DeepSeek OpenAI 兼容 API + tenacity 3 次重试 + 时长约束翻译 + 模型默认值 `deepseek-chat` 自动覆盖 `glm-4-flash` + 18 个测试 |
| ~~D52~~ | **`requires-python>=3.11` 与实际目标 (>=3.13) 不一致** — 项目目标 MacBook Air M5 出厂 macOS 26 / Python 3.13，`audioop-lts`（pydub 在 3.13 的依赖）要求 >=3.13。`requires-python>=3.11` 导致 uv lock 解析失败。**已解决** (2026-05-23)：`requires-python` → `>=3.13`；新增 `audioop-lts>=0.2.2` 显式依赖；mypy `python_version` → 3.13 | Code Review (2026-05-23) | 依赖管理，uv sync 报错 |
| ~~D54~~ | **P1: 翻译视频节奏断续** — 实测静音占比 54% vs 原始 4.7%。v1 对齐层设计为尾部填充（Story 4-5 设计决策），合成层按时间轴 concat。v1.1 FR51+FR52+FR54 已全部实现（ASR 碎片合并、翻译时长约束、Edge-TTS 语速控制），上游偏差已收敛，但用户实测节奏问题依然存在，证实问题在填充策略本身。**已解决** (2026-05-23)：`_pad()` 改为 `adelay={ms}|{ms},apad=whole_dur={target}` 滤镜链，静音前后 50/50 居中分布 | 用户实测 (2026-05-23) | 翻译视频节奏断续，直接影响观看体验 |

## v1.1 可选

改善体验但不阻塞功能。

| # | 债务 | 来源 | 影响 |
|---|------|------|------|
| D4 | AC8 措辞偏差 — spec 说抛异常，实现用 Result | 4-1 review | 文档不一致 |
| D5 | subprocess stderr 积累风险 — capture_output 对大视频可能内存占用大 | 4-1 review | v1 限 10 分钟可接受 |
| D22 | 进度回调为转录完成后模拟非实时 | 4-2 review | 进度条跳跃 |
| D25 | `_ASR_MEMORY_REQUIREMENT_GB` 硬编码 6.0 — 不同模型需不同阈值 | 4-2 review | 灵活性差 |
| D28 | httpx.Client 未显式关闭 | 4-3 review | 资源泄漏（v1 非实际） |
| D23 | edge-tts 无重试机制 | 4-4 review | 网络波动导致失败 |
| D34 | RuntimeError 捕获范围广（含 NotImplementedError） | 5-1 review R1 | CosyVoice 完整实现后缩小 |
| D35 | TTS 降级时 speed 参数跨引擎透传未校验 | 5-1 review R2 | 不同引擎可能用不同刻度 |
| D36 | OSError 未纳入降级 except 子句 | 5-1 review R2 | 磁盘满/权限错误罕见 |
| D38 | failure 测试未覆盖 PipelineError 路径 temp 保留 | 5-2 review | 测试覆盖缺口 |
| D39 | mock 链重复（8 个 patch）可抽共享 helper | 5-2 review | 测试维护成本 |
| D40 | `_cleanup_temp` OSError 恢复路径未测试 | 5-2 review | 边界场景 |
| D41 | stage 1/3+/4/5 失败时 temp 保留未测试 | 5-2 review | 测试覆盖缺口 |
| D42 | self.signals 防御性 None 检查缺失 | 5-1 review R2 | Pipeline 总以有效 Signals 构造 |
| D37 | ~~CosyVoice 存根总触发降级~~ | 5-1 review R1 | **已解决** — subprocess 桥完整实现 (2026-05-22) |
| D44 | ~~ASR 模型内存未主动释放~~ | 用户反馈 | **已解决** — ASR 完成后 del result + gc.collect() + mx.clear_cache() (2026-05-22) |
| D45 | ~~视频时长限制 10 分钟过短~~ | 用户反馈 | **已解决** — 放宽至 30 分钟（1800 秒），同步更新 validators/video_drop_area (2026-05-22) |
| D31 | validate_all 的 globals() 字符串查找脆弱 | 3-1 review | 重命名可能 KeyError |
| D29 | 零时长视频（duration=0.0）会通过校验 | 3-1 review | 损坏视频未拦截 |
| D27 | validate_ffmpeg 应使用解析后的 ffmpeg_path | 3-1 review | 功能无影响 |

## v1.2 必做

> 代码评审日期: 2026-05-30
> 评审结论：6 项全部可行，D20→D57 为依赖链，其余独立。
> 建议实现顺序：D55 → D2 → D20 → D57 → D58 → D56

---

### D55 — 删除语速滑块（FR9 废弃）

| 属性 | 值 |
|------|-----|
| 来源 | Winston 架构评估 (2026-05-30) |
| 复杂度 | 低（删除为主） |
| 依赖 | 无 |

**评审结论：可以删除。** Edge-TTS 的 `_compute_rate()` (`edge_tts_engine.py:91-101`) 会根据目标时长为每句话动态计算最优 rate，用户手调的 `speed` 作为 `base_rate_str` 叠加后会和自动计算互相干扰，实际效果微乎其微。三层自动化（翻译时长约束 + rate 自适应 + rubberband）已覆盖。

**代码影响清单：**

| 文件 | 行号 | 改动 |
|------|------|------|
| `gui/main_window.py` | 96-111 | 删除 speed_label、speed_slider、speed_value_label、speed_row |
| `gui/main_window.py` | 152-154 | 删除两处 speed slider 信号连接 |
| `gui/main_window.py` | 258-272 | 删除 `_on_right_speed_changed`、`_on_left_speed_changed` |
| `gui/config_panel.py` | 270-279 | 删除 speed_slider、speed_label、speed_row |
| `gui/config_panel.py` | 341 | 删除 `_on_speed_changed` 信号连接 |
| `gui/config_panel.py` | 349-351 | 删除 `_on_speed_changed` 方法 |
| `gui/config_panel.py` | 375,399-400,413 | `_fill_from_config` 中移除 speed 相关 blockSignals + setValue |
| `gui/config_panel.py` | 457 | `_matches_preset` 移除 speed 比对 |
| `gui/config_panel.py` | 519 | `_collect_config` 中 speed 改为硬编码 `1.0` |
| `gui/main_window.py` | 289 | `_setup_tab_order` 中 QSlider 类型白名单——如无其他 slider 可移除 |
| `config.py` | 61 | `TTSConfig.speed` 字段保留默认 1.0，注释注明"不再暴露给 UI" |

**同步更新：** PRD FR9 标记废弃；UX 规格移除语速控件描述。

---

### D2 — 音频提取阶段实时进度反馈

| 属性 | 值 |
|------|-----|
| 来源 | 4-1 review |
| 复杂度 | 低（单方法改造） |
| 依赖 | 无 |

**评审结论：改动集中在 `pipeline.py:_extract_audio` 一个方法。** 将 `subprocess.run(capture_output=True)` 改为 `subprocess.Popen` + 实时解析 ffmpeg stderr 中的 `time=HH:MM:SS.ms` 行，通过 `progress_callback` 推送到 UI。`video_drop_area.py` 已有 `get_duration()` 获取视频时长作为进度分母。

**代码影响清单：**

| 文件 | 行号 | 改动 |
|------|------|------|
| `pipeline.py` | 215-218 | `subprocess.run` → `Popen` + stderr 逐行解析 + `_check_abort()` 集成 |
| `pipeline.py` | 201 | `_extract_audio` 签名添加 `progress_callback` 参数 |

**实现要点：**
- 解析 ffmpeg stderr 中的 `time=` 行，提取当前处理时间戳
- 需要视频总时长（`FFmpegWrapper.get_video_duration()` 或从 `video_drop_area` 传入）
- 进度回调中调用 `_check_abort()` 支持用户中止
- `Popen` 进程注册到 `_active_processes` 列表以支持 abort kill

---

### D20 — FasterWhisperEngine 实现

| 属性 | 值 |
|------|-----|
| 来源 | 用户需求 (2026-05-30) |
| 复杂度 | 中 |
| 依赖 | 无（但 D57 依赖它） |
| 前置 | D57（Windows 跨平台）**依赖本项完成** |

**评审结论：底层基础已就绪，只需实现 `transcribe()`。** 工厂 (`asr/__init__.py:22-24`)、config Literal (`config.py:43`)、GUI 下拉框 (`config_panel.py:79-82`)、pyproject.toml docker 组 (`pyproject.toml:26`) 均已注册。核心工作：加载 CTranslate2 模型 → 调用 `model.transcribe()` → 转换为 `SubtitleSegment` 列表，参考 `MLXWhisperEngine` 的进度回调模式。

**代码影响清单：**

| 文件 | 改动 |
|------|------|
| `asr/faster_whisper_engine.py` | 完整实现 `transcribe()`：模型加载、推理、结果转换 |
| `pyproject.toml` | `faster-whisper>=1.0` 从 optional-dependencies 移到主依赖（或加 import guard 保持可选） |

**注意：** 暂不需要平台自动检测（那是 D57 的工作）。macOS 继续用 mlx-whisper，faster-whisper 面向 Docker/Linux/Windows。

---

### D57 — 跨平台支持（Windows）

| 属性 | 值 |
|------|-----|
| 来源 | 用户需求 (2026-05-30) |
| 复杂度 | 中-高（影响面广但每处改动小） |
| 依赖 | **D20**（没有跨平台 ASR 引擎，Windows 管线无法运行） |

**评审结论：六项具体改造，每项独立可控。** 好消息：路径处理全部使用 `pathlib.Path`（已跨平台），ffmpeg 检测用 `shutil.which`（已跨平台），`sys.platform` 尚未使用（不需要重构现有逻辑分支）。

**代码影响清单（按严重度排序）：**

| # | 位置 | 问题 | 严重度 |
|---|------|------|--------|
| 1 | `pyproject.toml:18` | `mlx-whisper>=0.4` 无条件依赖，Windows 安装即失败 | **阻断** |
| 2 | `main_window.py:277` | `subprocess.run(["open", ...])` 是 macOS 专有命令 | 中 |
| 3 | `cosyvoice_engine.py:154` | `PYTHONPATH` 拼接用 `:` 硬编码，Windows 需 `;`（改用 `os.pathsep`） | 中 |
| 4 | `cosyvoice_engine.py:65` | `start_new_session=True` Windows 语义不同，需 `CREATE_NEW_PROCESS_GROUP` | 低 |
| 5 | `pipeline.py:228` | `brew install ffmpeg` 提示信息需平台化 | 低 |
| 6 | 全局 | 所有 `import mlx_whisper` 需包裹 `try/except` 或平台判断 | 中 |

**实现要点：**
- pyproject.toml: `mlx-whisper` 标记 `sys_platform == "darwin"`；`faster-whisper` 标记 `sys_platform != "darwin"` 或无条件（CTranslate2 跨平台）
- CosyVoice worker 在 Windows 上不可用（conda 环境隔离），导入时给出提示，降级到 ChatTTS/Edge-TTS
- 平台检测统一放在一个工具函数中（如 `src/platform_utils.py`），避免散落各处

---

### D58 — ChatTTS 引擎支持

| 属性 | 值 |
|------|-----|
| 来源 | 用户需求 (2026-05-30) |
| 复杂度 | 中 |
| 依赖 | 无 |

**评审结论：实现可行，注意语速参数验证和模型下载体验。** ChatTTS `infer()` 有 `speed` 参数（默认 1.0）可控制语速，但取值范围和中文效果需实测。模型首次运行自动下载约 2GB，需进度提示。内存方面 ChatTTS 和 CosyVoice 不能同时加载。

**代码影响清单：**

| 文件 | 改动 |
|------|------|
| 新建 `tts/chattts_engine.py` | 实现 `TTSEngine` ABC：模型加载、`synthesize()`、语速控制 |
| `tts/__init__.py:21-24` | 工厂注册 `chattts` |
| `config.py:58` | `TTSConfig.engine` Literal 添加 `"chattts"` |
| `config_panel.py:83-86` | `_TTS_ENGINE_DISPLAY` 添加 `"chattts": "ChatTTS"` |
| `pipeline.py:330-356` | 降级链更新：CosyVoice → ChatTTS → Edge-TTS |

**待验证项：**
- ChatTTS `speed` 参数取值范围和中文效果实测
- 模型下载进度能否通过回调报告
- 内存峰值（与 CosyVoice 2GB+ 对比）

---

### D56 — ASR/翻译结果一键复制

| 属性 | 值 |
|------|-----|
| 来源 | 用户需求 (2026-05-30) |
| 复杂度 | 中 |
| 依赖 | 无 |

**评审结论：发现设计问题需一并修复。** 当前 `transcript_updated` 信号在翻译阶段会**覆盖** ASR 文本（`pipeline.py:267` emit 原文 → `pipeline.py:303` emit 双语覆盖），ASR 原文在 UI 上消失，无法复制。缓存方案见实现要点。

**代码影响清单：**

| 文件 | 行号 | 改动 |
|------|------|------|
| `gui/transcript_panel.py` | 全文 | 缓存 `_asr_text` + `_translation_text` 两份数据；顶部加"复制原文""复制译文"按钮；使用 `QApplication.clipboard()` |
| `pipeline.py` | 267,303 | 可选：拆分信号为 `asr_transcript_ready` + `translation_ready`（或保留现有信号加 stage 参数） |

**实现要点（最小方案，不改信号层）：**
- TranscriptPanel 内维护 `_asr_text: str` 和 `_translation_text: str`
- `_on_transcript_updated` 根据当前管线阶段判断是 ASR 还是翻译结果，分别缓存
- 顶部 toolbar 加两个 QPushButton："复制原文" / "复制译文"
- 使用 `QApplication.clipboard().setText()` 写入系统剪贴板
- 管线完成后（`pipeline_finished`）按钮保持可用

---

## v1.2 实现顺序

```
D55（删滑块）──→ D2（音频进度）──→ D20（FasterWhisper）──→ D57（Windows）
                                                              │
                    D58（ChatTTS）──→ D56（复制功能）←────────┘
```

- **D55 最先**：纯删除，验证 v1.2 方向，0 风险
- **D2 其次**：单方法改造，改动面最小
- **D20→D57 依赖链**：先做跨平台 ASR 引擎，再做平台适配
- **D58→D56 并行链**：ChatTTS 独立实现；D56 放最后避免同一文件（transcript_panel + pipeline）反复修改

---

## v1.2 可选

从 v1.1 可选遗留的低影响项。

| # | 债务 | 来源 | 影响 |
|---|------|------|------|
| D22 | 进度回调为转录完成后模拟非实时 | 4-2 review | 进度条跳跃 |
| D23 | edge-tts 无重试机制 | 4-4 review | 网络波动导致失败 |
| D29 | 零时长视频（duration=0.0）会通过校验 | 3-1 review | 损坏视频未拦截 |
| D30 | 跳段进度消息偏差（4-3/4-4/4-5 共享）— v1.1 部分修复，可能仍有边界情况 | 4-3/4-4/4-5 review | 进度显示不准 |
| D59 | **ASR 专有名词 UI 配置入口** — 当前 `_DEFAULT_PROPER_NOUNS` 硬编码通用技术词汇（Claude Code、GPT-4、PySide6 等），不管视频内容如何都会被加入 initial_prompt，可能污染不相关内容的识别结果；且用户无法添加自己领域的专有名词（人名、地名、专业术语）。需在 ConfigPanel ASR 区块添加：(1) 多行文本框让用户输入自定义专有名词（逗号分隔）；(2) "使用默认技术词汇"复选框控制是否合并默认列表。配置层面新增 `asr.use_default_proper_nouns: bool = true` 字段 | 用户反馈 | 专有名词识别不准，影响翻译质量；用户无法自定义领域词汇 |

## v2.0+

需要架构变更或大量工作，v1.2 不做。

| # | 债务 | 来源 |
|---|------|------|
| D7 | 无 cancel/abort 机制 — v2.0 断点续传时实现 | 4-1 review |
| D6 | stage_failed 与 pipeline_finished 信号顺序无文档 | 4-1 review |
| D11 | `mx.synchronize()` 无超时保护 — MLX 不提供超时参数，v1 串行管线 GPU 挂起概率极低 | 4-2 review (2026-05-22) |
| D21 | Docker 无 CLI/headless 模式 | 1-6 review |
| D24 | `__file__` 在 frozen/zipimport 中为 None — v3 dmg/pkg 时处理 | 2-3 review |
| D19 | 容器以 root 运行 — Dockerfile 缺 USER 指令 | 1-6 review |
| D18 | CosyVoice 未在 Docker 镜像中安装（subprocess 桥需 conda 环境，Docker 内不可用） | 1-6 review |
| AC1 | 异常捕获范围依赖模型加载时机 — 已通过 subprocess 桥确认，worker 异常通过 ImportError 传播 | 5-1 review R1 |

### TTS 本地方案

CosyVoice 已通过 subprocess 桥集成（2026-05-22），使用独立 conda 环境 Python 3.10
与项目 Python 3.13 隔离，详见 `scripts/cosyvoice_worker.py` 和
`src/tts/cosyvoice_engine.py`。部署指南见 `docs/cosyvoice-deployment-guide.md`。

以下为备选替代方案（CosyVoice 部署失败时）：

| 方案 | 安装方式 | 中文质量 | macOS 原生 | 离线 | 推荐度 |
|------|---------|---------|-----------|------|--------|
| **sherpa-onnx + MeloTTS** | `pip install sherpa-onnx` | ⭐⭐⭐ | ✅ arm64 | ✅ | ⭐⭐⭐⭐⭐ |
| MeloTTS 原版 | `pip install melo-tts` | ⭐⭐⭐⭐ | ⚠️ MPS bug | ✅ | ⭐⭐⭐ |
| ChatTTS | `pip install ChatTTS` | ⭐⭐⭐⭐ | ✅ | ✅ | ⭐⭐⭐ |

**推荐：sherpa-onnx** — 一行安装、macOS arm64 原生支持、内置 MeloTTS 中文模型、纯 CPU 推理零 GPU 依赖。
如果 CosyVoice 部署失败或兼容问题无法解决，优先切换到 sherpa-onnx。

## 已过期 / 可丢弃

以下债务已被后续 Story 解决、或属于已知设计决策不需要修复。

| # | 债务 | 来源 | 原因 |
|---|------|------|------|
| — | 全局 QSS 通过 qApp.setStyleSheet() 设置 | 2-1 review | 项目已统一此模式，v1 无跨模块隔离需求 |
| — | QSettings 测试替换 _settings | 2-1 review | 低风险，测试模式已稳定 |
| — | 测试访问 `_config_panel._asr_path_input` 双重私有属性 | 2-1 review | 项目已建立的测试模式 |
| — | QSS 色值硬编码与 constants.py 解耦 | 2-1 review | QSS 不支持 Python 常量引用，设计决策 |
| — | `restoreState()` 未来 toolbar/dock 兼容 | 2-1 review | v1 无此类组件 |
| — | `findChildren(QWidget)` 不保证视觉顺序 | 2-1 review | 创建顺序与视觉一致 |
| — | `get_config()` 静默回退到预设 | 2-1 review | 属于 ConfigPanel 设计 |
| — | `CONFIG_PATH = Path("config.yaml")` 相对 CWD | 2-1 review | 已在 D3 统一处理 |
| — | apt 系统包未锁定版本 | 1-6 review | Debian stable 变更缓慢 |
| — | models/ 排除但 config.yaml 引用 model_path | 1-6 review | 预期行为，volume 挂载 |
| — | entrypoint 无模型下载或配置校验 | 1-6 review | 用户自带模型 |
| — | 空 api_key/model_path 通过 pydantic 校验 | 1-6 review | Epic 3 已处理运行时校验 |
| — | MainWindow 突破 ConfigPanel 封装 | 2-3 review | 已文档化的跨 Story 模式 |
| — | `_load_qss` 全局设置 QSS | 2-3 review | Story 2-1 遗留，项目已统一 |
| — | 测试用 MagicMock 模拟 QDropEvent | 2-3 review | 真实构造 segfault，项目模式 |
| — | 无 HEALTHCHECK 指令 | 2-3 review | v1 单容器运行 |
| — | .env.example 被 .dockerignore 排除 | 2-3 review | 面向开发者，Docker 用 env |
| — | 未知引擎静默跳过 | 3-1 review | pydantic Literal 已约束 |
| — | 显式 gc.collect() 代码异味 | 4-2 review | mlx-whisper 内存行为所需 |
| — | psutil 模块级导入 vs 延迟导入不一致 | 4-2 review | pyproject.toml 已声明 |
| — | _report_progress @staticmethod 限制子类覆盖 | 4-2 review | v1 仅一个引擎 |
| — | AC5 文本与 Task note 矛盾 | 4-2 review | 实现正确，编辑性 |
| — | _run_asr 局部 import ProgressEvent | 4-2 review | 遵循延迟导入模式 |
| — | _preload_check_tts 方法名微瑕 | 4-2 review | 命名不影响功能 |
| — | 全部段 source_text 为空时无 progress | 4-3 review | ASR 输出不可能全空 |
| — | config.yaml 翻译引擎 nllb→glm 变更 | 5-1 review R2 | 不影响功能 |

## Deferred from: code review of v1.2-2-1 (2026-05-30)

| # | 债务 | 来源 | 影响 |
|---|------|------|------|
| D2-CR1 | **`_read_ffmpeg_progress` 超时依赖 stderr 输出** — 超时检查在 stderr 循环内部，若 ffmpeg 无输出则永不触发（实际总会输出，风险极低） | 2.2-1 review | 极端情况下超时失效 |
| D2-CR2 | **abort 竞态导致错误消息不精确** — 主线程 `abort()` terminate 进程先于后台线程 `_check_abort()` 触发时，抛出"音频提取失败"而非"用户中止"，清理正确仅消息不准 | 2.2-1 review | 用户体验轻微偏差 |
| — | 降级时 progress 可能回退 | 5-1 review R1 | 预存问题，非本次引入 |
