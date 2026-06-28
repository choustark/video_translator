# Deferred Work (v1 完成后清理)

> 最后更新: 2026-06-19 (调研登记 D65-D69 翻译质量提升候选，基于 Denzel 演讲译文样本 + 竞品/学术调研)
> 分类标准：v1.2 必做 / v1.2 可选 / v2.0+ / 已过期可丢弃

## Deferred from: code review of v2.0-3-1-d60-cosyvoice-voice-cloning (2026-06-14)

- [Defer] **AC2 措辞与 Dev Notes §2 矛盾** — AC2 说 reference_audio 加载失败"不整体崩溃"，但 Dev Notes §2 要求走降级链。实现正确（`sys.exit(1)` → 降级），AC2 措辞需在未来 spec 修订中更正。
- [Defer] **`_browse_reference_audio` 默认从 `Path.home()` 打开** — 首次使用时对话框从根目录打开，可能较慢。与既有 `_browse_directory` 模式一致，非新引入。

## Deferred from: Epic 1-v2.0 retro (2026-06-13)

- [Defer] **CI workflow `.github/workflows/{test,code-quality,nightly}.yml` 推迟到 v2.0 全部完成后处理** — Story v2.0-1-2 范围扩展引入，但未经真实 Windows runner 验证；Mr.ChouCj 决策（2026-06-13 retro）：v2.0 主线不依赖未验证 CI，待 Epic 2-4 全部完成后再启用跨平台 CI。文件已存在于 working tree，可在 v2.0 完成后直接 commit
- [Defer] **`src/scheme_manager.py` 已标 DEPRECATED** — Epic 1-v2.0 删除"已保存方案"UI 后，本底层模块成孤儿代码。已加文件头注释标记，未来恢复"自定义方案"功能可参考，否则可安全删除。详见 Epic 1-v2.0 retro
- [Defer] **v2.0-1-2 中 `CREATE_NEW_PROCESS_GROUP` 常量值 spec 文档需修正** — 实现使用正确值 `0x00000200`，但 Story spec 文档仍写错误的 `0x00000008`。下一个维护 platform_utils 的开发者读到 spec 会被误导
- [Defer] **v2.0-1-2 中 README 标注 ChatTTS 许可证类型需复核** — v1.2 retro A3 要求"注明 CC BY-NC 4.0"，但实际实现加的是 "MIT License"。两者矛盾，需确认 ChatTTS 真实许可证类型后统一文档

## Deferred from: code review (2026-06-05)

- [Defer] sprint-status.yaml 与功能改动混在同一批未提交改动中 — BMad 既有模式，sprint 状态更新和代码改动习惯性一起提交，后续可考虑分离
- [Defer] `tests/test_asr/test_faster_whisper_engine.py` 缺少空 proper_nouns 时 initial_prompt 的测试 — `test_mlx_whisper_engine.py` 已有等价覆盖（`_build_initial_prompt([])`），但 FasterWhisper 路径未覆盖此边界条件，虽然 `_build_initial_prompt` 已有 `if not nouns: return ""` guard

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
| D45 | ~~视频时长限制 10 分钟过短~~ | 用户反馈 | **已解决** — v1.1 放宽至 30 分钟；v2.0 进一步放宽至 2 小时（7200 秒）+ 新增磁盘空间校验 (2026-06-13，story v2.0-2-1) |
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
| ~~D59~~ | **ASR 专有名词 UI 配置入口** — 当前 `_DEFAULT_PROPER_NOUNS` 硬编码通用技术词汇（Claude Code、GPT-4、PySide6 等），不管视频内容如何都会被加入 initial_prompt，可能污染不相关内容的识别结果；且用户无法添加自己领域的专有名词（人名、地名、专业术语）。需在 ConfigPanel ASR 区块添加：(1) 多行文本框让用户输入自定义专有名词（逗号分隔）；(2) "使用默认技术词汇"复选框控制是否合并默认列表。配置层面新增 `asr.use_default_proper_nouns: bool = true` 字段 | 用户反馈 | **已解决** — `config_panel.py` 已实现专有名词 QTextEdit 输入框（行 220-225），支持逗号/换行/分号分隔解析（行 493-496），配置双向绑定（行 381/506） |

## v2.0（体验进阶）

> 重组日期: 2026-06-07
> PRD 路线图同步更新，四项核心功能 + 配套债务

---

### D60 — CosyVoice 声音克隆

| 属性 | 值 |
|------|-----|
| 来源 | Winston 架构评估 + 实测验证 (2026-06-05) |
| 复杂度 | 低（~100-150 行增量改动） |
| 依赖 | 无（复用现有 CosyVoice subprocess 桥） |

**背景：** PRD 路线图原规划 v3.0 使用 GPT-SoVITS 实现声音克隆。经架构评估发现 CosyVoice 已原生支持 zero-shot 声音克隆，无需引入新依赖。

**实测验证结果 (2026-06-05, M5, CosyVoice-300M-SFT)：**

| 模式 | API | 输出时长 | 推理耗时 | RTF | 额外输入 |
|------|-----|---------|---------|-----|---------|
| zero_shot | `inference_zero_shot(tts_text, prompt_text, prompt_wav)` | 7.3s | 25.5s | 3.4x | 需要参考文本 |
| **cross_lingual** ✓ | `inference_cross_lingual(tts_text, prompt_wav)` | 6.8s | 19.8s | 2.9x | 只要参考音频 |
| sft（基线） | `inference_sft(text, speaker)` | 6.7s | 16.7s | 2.5x | 无 |

**选定方案：`inference_cross_lingual`**

理由：
1. 不需要参考音频对应的英文文本（ASR 虽然已有，但少一个依赖更简单）
2. 英文参考音频 → 中文输出的跨语言场景正是 cross_lingual 的设计目标
3. 推理耗时仅比 sft 基线增加 ~20%，可接受
4. 质量经 Mr.ChouCj 主观验证，可接受

**注意：** 当前模型 `CosyVoice-300M-SFT` 可用，但 CosyVoice 官方 zero-shot 推荐使用 `CosyVoice-300M` 或 `CosyVoice2-0.5B`，后续可升级模型提升克隆质量。

**参考音频来源方案：**
- 首选：自动从 ASR 分段中选取（置信度最高、3-10s 的段），用户零操作
- 备选：用户手动上传参考音频文件（配置面板文件选择）

**代码影响清单：**

| 文件 | 改动 | 复杂度 |
|------|------|--------|
| `scripts/cosyvoice_worker.py` | 检测到 `reference_audio` 参数时走 `inference_cross_lingual` 而非 `inference_sft` | 低 |
| `src/config.py` → `TTSConfig` | 新增 `reference_audio: str = ""` 字段 | 低 |
| `src/tts/cosyvoice_engine.py` | 透传 `reference_audio` 参数到 worker stdin JSON | 低 |
| `src/gui/` 配置面板 | 新增"参考音频"文件选择控件 | 中 |
| `src/pipeline.py`（可选） | ASR 完成后自动选取最佳段作为参考音频 | 中 |

**不改动的部分：**
- 不新增 TTS 引擎（复用 CosyVoiceEngine）
- 不新增依赖（CosyVoice 已集成）
- 不改 subprocess 桥架构
- 不改 TTSEngine ABC 接口

---

### D61 — Per-stage 断点续传 + 时长放宽

| 属性 | 值 |
|------|-----|
| 来源 | 架构评估 (2026-06-07)，替代原"长视频分段"方案 |
| 复杂度 | 中低 |
| 依赖 | 无 |

**背景：** 原方案为"长视频分段处理"。经分析发现：(1) 管线每阶段已逐段流式处理，内存不随视频长度增长；(2) 分段会丢失翻译上下文、增加架构复杂度；(3) 真正的痛点是失败后从头重跑。因此改为 per-stage 断点续传。

**需求拆分（两部分独立）：**

#### D61a — 放宽时长限制（前置，极低复杂度）✅ 已解决 (2026-06-13, story v2.0-2-1)

将 `MAX_DURATION_SECONDS` 从 1800（30 分钟）放宽到 7200（2 小时），同步更新 `validators.py` 和 `video_drop_area.py`。需增加磁盘空间校验（2 小时视频中间产物约 1GB）。

| 文件 | 改动 |
|------|------|
| `src/gui/video_drop_area.py:28-29` | `MAX_DURATION_SECONDS = 7200` |
| `src/validators.py:21` | `_MAX_VIDEO_DURATION_SECONDS = 7200` |
| `src/validators.py` | 新增磁盘空间校验（估算：视频大小 × 3） |

#### D61b — Per-stage 断点续传（核心）

每个阶段完成后将中间状态持久化到 `.temp/` 目录。下次启动时检测到检查点文件，跳过已完成的阶段。

**现有架构优势（不需要改的部分）：**
- ✅ 失败时 `.temp/` 目录已保留（`_cleanup_temp` 只在成功时调用）
- ✅ 中间产物（WAV、TTS 音频段）已在 `.temp/{video_hash}/` 中
- ✅ 每阶段有 `_complete_stage()` — 天然的检查点写入时机

**检查点文件格式：** `.temp/{video_hash}/checkpoint.json`

```json
{
  "version": 1,
  "video_path": "/path/to/video.mp4",
  "video_size": 524288000,
  "config_hash": "sha256:abc123...",
  "completed_stages": ["音频提取", "ASR", "翻译"],
  "current_stage": "TTS",
  "audio_path": "audio.wav",
  "segments_path": "segments_checkpoint.json",
  "created_at": "2026-06-07T14:30:00",
  "updated_at": "2026-06-07T14:35:22"
}
```

**各阶段检查点内容：**

| 阶段完成后 | 持久化内容 | 大小估算 |
|-----------|-----------|---------|
| 音频提取 | `checkpoint.json`（记录 audio_path） | <1KB |
| ASR | `segments_checkpoint.json`（SubtitleSegment 列表，含 source_text） | ~50KB（2h 视频 ~500 段） |
| 翻译 | `segments_checkpoint.json`（更新 translated_text） | ~100KB |
| TTS | `segments_checkpoint.json`（更新 audio_path, audio_duration） | ~100KB + 音频文件（已在 .temp） |
| 语速自适应 | `segments_checkpoint.json`（更新对齐后路径） | ~100KB |
| 合成 | 删除检查点（管线完成） | 0 |

**代码影响清单：**

| 文件 | 改动 | 复杂度 |
|------|------|--------|
| `src/pipeline.py` | `_complete_stage()` 中写入检查点；`process()` 开头检测检查点并跳过已完成阶段；增加 `SubtitleSegment` ↔ JSON 序列化 | 中 |
| `src/models.py` | `SubtitleSegment` 增加 `to_dict()` / `from_dict()` 方法 | 低 |
| `src/gui/video_drop_area.py` | 检测到检查点时弹窗询问"检测到上次未完成的翻译，是否继续？" | 低 |
| `src/pipeline.py` | `_cleanup_temp()` 成功时删除检查点文件 | 低 |

**恢复逻辑（`process()` 入口）：**

```
1. 计算 temp_dir 路径（已有逻辑：output/.temp/{video_hash}/）
2. 检查 checkpoint.json 是否存在
3. 如果存在：
   a. 校验 video_path + video_size + config_hash 是否匹配
   b. 匹配 → 加载 segments_checkpoint.json，跳到 current_stage 继续执行
   c. 不匹配 → 删除旧检查点，从头开始
4. 如果不存在 → 正常流程
```

**不修改的部分：**
- 不改 TTSEngine / ASREngine 接口
- 不改信号机制
- 不改临时目录结构
- 不改 abort 机制（abort 后检查点自动保留，下次可续传）

---

### D64 — 删除"已保存方案"UI 区域

| 属性 | 值 |
|------|-----|
| 来源 | Sally UX 评审 (2026-06-07) |
| 复杂度 | 低（纯删除 ~215 行） |
| 依赖 | 无 |

**背景：** 配置面板顶部"已保存方案"下拉框 + 保存/删除/导入/导出四个按钮在个人项目中使用场景极少。配置管理由"预设方案"下拉框完全覆盖。

**改动方案：**

**删除的 UI 元素（config_panel.py）：**
- `_scheme_combo` 下拉框 + `_btn_save/delete/import/export_scheme` 四个按钮（行 172-191）
- 对应信号连接（行 341-345）
- 6 个方法：`refresh_schemes`、`_on_scheme_selected`、`_save_current_scheme`、`_delete_selected_scheme`、`_import_scheme`、`_export_scheme`（行 656-787）
- `_SCHEMES_DIR` 常量（行 96）、`_scheme_mgr` 初始化（行 114）、`import SchemeManager`（行 45）
- `refresh_schemes()` 调用（行 622）

**删除的桥接代码（main_window.py）：**
- `refresh_schemes()` 委托方法（行 343-345）

**删除的测试：**
- `tests/test_gui/test_config_panel_schemes.py`（~60 行）

**保留不动：**
- "预设方案"下拉框 + 恢复默认按钮 + 漂移检测
- `src/scheme_manager.py`（保留，未来可能复用）
- `tests/test_scheme_manager.py`（保留，SchemeManager 本身逻辑仍正确）

**净减 ~215 行，零风险纯删除。**

---

### D65-D69 — 翻译质量提升调研候选（v2.0 候选）

| 属性 | 值 |
|------|-----|
| 来源 | Mr.ChouCj 翻译样本评估 + 竞品调研 (2026-06-19) |
| 触发样本 | Denzel Washington Dillard University 毕业典礼演讲译文，发现 6+ 处问题（Court Theater → 法庭剧院、U-Haul 直译、第 100 行反义翻译、"扑通一声倒下"凭空多出、"宝贝""搞到"语气漂移等） |
| 调研依据 | HeyGen / Rask / Perso AI 工业实践 + VideoDubber / LSST / SSPO 学术研究 + subtitle-translator 开源工程实践 + Whisper: Courtside Edition NER+ASR 二转 |
| 状态 | **未实施，待 Mr.ChouCj 决策优先级** |

按 ROI（投入产出比）排序的 5 项候选：

#### D65 (P0) — 行数自检 + 批量拼接送翻译

| 属性 | 值 |
|------|-----|
| 复杂度 | 低（1 天） |
| ROI | 极高 |
| 解决的样本问题 | "扑通一声倒下"凭空多出一行 |

**做法（参考 subtitle-translator）：**
1. 把多段字幕用 `\n` 拼接成一段送 LLM 翻译，让模型看上下文，再按分隔符拆回来
2. 拆回来的行数必须等于原文行数，不等就报错重试（最多 N 次）
3. 上下文窗口：每次送当前行 + 前 N 行 + 后 N 行作为 context（推荐 70B+ 模型）

**代码影响：** `src/translation/` 现有 provider 链路重构为批量模式；新增行数校验逻辑

---

#### D66 (P0) — 翻译 prompt 加本土化 + 语气约束（few-shot）

| 属性 | 值 |
|------|-----|
| 复杂度 | 低（半天，纯 prompt 工程） |
| ROI | 高 |
| 解决的样本问题 | "宝贝""搞到"语气漂移、"带不走的东西别太在意"生硬直译 |

**做法：**
1. 翻译 prompt 中显式约束："使用成人演讲语气，避免'宝贝''搞到'等俚俗词"
2. 加 few-shot 示例（成功译文 + 失败译文各 2-3 个，标明为什么）
3. 加本土化指令：英语典故（U-Haul behind a hearse）→ 中文等价意象，而非直译

**代码影响：** `src/translation/{glm,deepseek,openai}_provider.py` 的 `_build_prompt()` 模板；prompt 文本可外置到 `src/translation/prompts/` 配置文件

---

#### D67 (P1) — ASR 二转 + LLM 自动专名提取

| 属性 | 值 |
|------|-----|
| 复杂度 | 中（2-3 天） |
| ROI | 中高 |
| 解决的样本问题 | Court Theater → 法庭剧院（专名误识别导致的下游错误） |
| 学术依据 | Whisper: Courtside Edition (ACL 2025)：NER agent + initial_prompt 二转，WER 相对降 17% |

**做法（参考 Whisper Courtside 流水线）：**
1. **第一遍** mlx-whisper 转写（现有逻辑）
2. **NER agent**（GLM-4）从一转结果识别人名、地名、机构名、术语
3. **归一化**到规范形式（拼写/大小写）
4. **拼接成自然句子**注入 mlx-whisper 的 `initial_prompt` 参数
5. **第二遍** mlx-whisper 重转写，专名准确率显著提升

**与现有 D46/D59 的关系：** D46/D59 是"用户手动填专名表"，D67 是"LLM 自动提取"，二者可叠加（用户表 + 自动提取合并去重）

**代码影响：**
- 新增 `src/asr/proper_noun_extractor.py`（LLM 调用）
- `src/asr/mlx_whisper_engine.py` 支持"二转"模式
- 性能权衡：双倍 ASR 时间，长视频可能要可选开关

---

#### D68 (P1) — LLM self-check 关键句复译

| 属性 | 值 |
|------|-----|
| 复杂度 | 中（2 天） |
| ROI | 中 |
| 解决的样本问题 | 第 100 行 "If you don't fail, you're not even trying" → 反义翻译 |
| 学术依据 | TEaR framework / SC (arxiv 2025)：翻译 → 评 → 精炼 |

**做法：**
1. 翻译完成后，开**新会话**（清空 history，避免锚定效应）
2. 让 LLM 对照原文逐句打分（准确度 1-5）
3. 分数 ≤ 3 的句子触发复译，要求"找出原文与译文的语义偏差并修正"
4. 警告（来自论文）：模型会过度纠错，仅对低分段触发复译而非全篇

**成本：** 双倍 token 消耗（翻译 + 评分）。建议按段计费可控。

**代码影响：** `src/translation/` 新增 verifier 模块；翻译流程从单次调用改为"翻译 + 抽查复译"两阶段

---

#### D69 (P2) — 多候选 length-aware 翻译 + 时长选优

| 属性 | 值 |
|------|-----|
| 复杂度 | 较高（3-4 天） |
| ROI | 中 |
| 解决的样本问题 | 整体时长对齐问题（v1.1 已部分解决，但仍有局部偏差） |
| 学术依据 | LSST (2025)：一次生成 short/normal/long 三候选 + duration model 估时长 + 选最优；VideoDubber (AAAI 2023)：token-level duration control |

**做法：**
1. LLM 一次生成 3 个候选译文（short / normal / long），每个标明预期时长
2. 用 duration model（按字数 × 平均语速估算，不实际合成）估每个候选时长
3. 选最贴近原文时长的候选进入下游 TTS
4. 避免在翻译时硬塞时长约束（会降质量）

**与 v1.1 现有方案的关系：** v1.1 的 D50 是"prompt 中加时长约束"（单一译文），D69 是"多候选 + 选优"——后者质量更高但成本翻倍

**代码影响：** 翻译 API 调用结构改写（一次调用返回多候选）；下游 TTS 接收"选定的译文"而非"唯一译文"

---

### v2.0 翻译质量提升实施建议

按 ROI 推荐顺序：
```
D65（行数自检，1天）──→ D66（prompt 约束，半天）
       │                         │
       └──── 解决 Denzel 样本 80% 问题 ────┘
                  │
            D67（ASR 二转，2-3天）── 治专名误识别
                  │
            D68（self-check，2天）── 治反义/严重错译
                  │
            D69（多候选时长，3-4天）── 提升对齐精度
```

**Mr.ChouCj 决策点：**
- 是否单独创建 v2.0 翻译质量 story 包？（vs 散落到现有 story）
- D65+D66 是否合并为一个 story（都是 prompt/批翻译层改动）？
- D67 是否在 v2.0 主线 vs 留到 v3.0？（双倍 ASR 时间是性能权衡）
- D69 是否值得做（与 v1.1 已实现的 D50 重叠度高）？

### v2.0 配套债务（从 v2.0+ 区块移入）

| # | 债务 | 来源 | 说明 |
|---|------|------|------|
| D7 | 无断点续传机制 | 4-1 review | **已并入 D61b** — per-stage 检查点即断点续传 |
| D6 | stage_failed 与 pipeline_finished 信号顺序无文档 | 4-1 review | 需在 v2.0 重构管线时一并规范 |

---

## v3.0

差异化功能，需在 v2.0 之后启动。用户已确认 D62/D63 归入此版本 (2026-06-13)。

### D62 — 单句编辑重合成

| 属性 | 值 |
|------|-----|
| 来源 | PRD v3.0 路线图 |
| 复杂度 | 中 |
| 依赖 | 无 |

**需求：** 用户可以在翻译完成后查看字幕面板，选中某一句修改译文，然后单独重新合成该句的音频和视频。无需重新跑整个管线。

**待设计项：**
- 字幕面板需支持：点击选中、编辑译文、触发"重合成此句"
- 重合成只跑 TTS + 语速自适应 + 局部合成（替换该段的音频和字幕）
- 需要保留中间产物（TTS 音频、对齐后音频）供重合成使用

**代码影响清单（预估）：**

| 文件 | 改动 | 复杂度 |
|------|------|--------|
| `src/gui/transcript_panel.py` | 可编辑模式 + "重合成"按钮 | 中 |
| `src/pipeline.py` | 新增 `resynthesize_segment()` 方法 | 中 |
| `src/composer/` | 局部音视频替换（而非全量合成） | 中 |
| 临时文件管理 | 重合成时保留中间产物 | 低 |

---

### D63 — 多说话人识别（WhisperX）

| 属性 | 值 |
|------|-----|
| 来源 | PRD v3.0 路线图 |
| 复杂度 | 中-高 |
| 依赖 | 无（与 D60 声音克隆协同：每说话人独立克隆） |

**需求：** 视频中有多位说话人时，区分不同说话人并为每人分配不同音色（TTS voice）或独立克隆声音。

**待设计项：**
- 说话人分离（Speaker Diarization）：WhisperX 或 pyannote.audio
- 与 ASR 集成：在识别文本的同时标注说话人 ID
- 与 TTS 协同：每个 speaker_id 映射到不同 voice 或不同 reference_audio
- UI 展示：字幕面板按说话人分色显示

**代码影响清单（预估）：**

| 文件 | 改动 | 复杂度 |
|------|------|--------|
| 新增 `src/asr/diarizer.py` | 说话人分离模块 | 高 |
| `src/models.py` | SubtitleSegment 新增 `speaker_id` 字段 | 低 |
| `src/tts/` | 按 speaker_id 选择不同 voice/reference | 中 |
| `src/gui/transcript_panel.py` | 按说话人分色显示 | 中 |
| `pyproject.toml` | 新增 `whisperx` 或 `pyannote.audio` 依赖 | 低 |

---

### 其他 v3.0+ 债务

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

## Deferred from: code review of v2.0-1-1-d64-remove-scheme-ui (2026-06-13)

- [Defer] `src/scheme_manager.py` 已是死代码，无生产代码引用 — AC4 要求保留以备未来复用
- [Defer] `tests/test_scheme_manager.py` 测试死代码 — AC4 要求保留
- [Defer] AC5 运行时验证待确认 — 需手动启动应用 + 运行 ruff/mypy/pytest

## Deferred from: code review of v2.0-1-2-fix-windows-test-and-license (2026-06-13)

- [Defer] Spec 常量 `0x00000008` 错误 — 实际 Windows API 值为 `0x00000200`，实现已使用正确值，spec 文档需修正
- [Defer] `README_zh.md` 缺少第三方依赖章节 — 需中文翻译同步

## Deferred from: code review of v2.0-2-1-d61a-relax-duration-limit (2026-06-13)

- [Defer] AC3 部分残留 — 2 处代码注释含 "30 分钟"（validators.py:21, video_drop_area.py:28），有意保留历史上下文
- [Defer] `output_dir` 硬编码为 `"output"`，不可配置 — 当前无用户配置输出目录需求
- [Defer] 测试中 video 和 output 目录混用（同 `tmp_path`）— 未覆盖不同卷场景

## Deferred from: code review of v2.0-2-3-d23-edgetts-retry (2026-06-14)

- [Defer] `Communicate()` 构造函数网络异常（aiohttp.ClientError/ssl.SSLError/TimeoutError）未被重试 — 当前仅重试 NoAudioReceived/WebSocketError，后续可扩展
- [Defer] `test_retry_uses_exponential_backoff` mock 覆盖所有策略函数 — 测试脆弱但实际重试行为由其他测试充分覆盖

## Deferred from: code review of v2.0-4-3-d6-signal-order-documentation (2026-06-14)

- [Defer] **contract doc 嵌入行号（`pipeline.py:227, 236...`）会随代码变更漂移** — 文档定位为"当前实现快照"，行号保质期短。后续 pipeline.py 改动时需同步更新。
- [Defer] **`transcript_updated` docstring "在 ASR 与翻译阶段各 emit 一次" 是脆性断言** — 若未来增加 emit 点，docstring 会成为谎言。建议改为描述性语言（如"管线过程中更新字幕文本"）。

## Deferred from: code review of v2.0-4-2-d22-asr-progress-realtime (2026-06-14)

- [Defer] **SubtitleSegment 格式化变更超出 story 范围** — `transcribe()` 中 `SubtitleSegment(...)` 从紧凑格式改为多行格式，属 ruff format 副作用，不影响功能。
- [Defer] **`if progress <= 0.0: continue` 是 dead code** — `time.monotonic()` 首次 wait 至少 2s 后才进入循环体，`ratio` 不可能 ≤0。防御性保留无害，可标注"理论不可达"。
- [Defer] **`test_progress_capped_at_95_percent` 未真正触及 0.95 cap 边界** — mock 参数使 max ratio=0.5，cap 未被测试到。后续可提高 audio_duration 重新验证。

## Deferred from: code review of v2.0-4-1-d29-zero-duration-validation (2026-06-14)

- [Defer] **格式化变更超出 story 范围** — ffprobe 参数列表（src/validators.py:277-285）、HTTPError 构造函数（tests/test_validators.py:191-240）、validate_all() 签名（src/validators.py:434-436）的纯格式化变更不属于 story spec 范围，增加 diff 噪音。可在后续统一格式化处理。
- [Defer] **极小正数时长不可拦截** — `1e-10` 等极小正值通过 `duration <= 0` 检查，但 spec 已明确"极短时长（<1s）校验"为 Story Boundary 除外项，且 ffprobe 不会对有效视频输出此值。后续 story 可考虑增加 min_duration 阈值。

## Deferred from: code review of v2.0-2-2-d61b-checkpoint-resume (2026-06-14)

- [Defer] `_compute_config_hash` 用 `default=str` 序列化 Path — 路径在不同机器/工作目录下可能 str 不同（相对 vs 绝对），导致同配置不同 hash — 需要 path-agnostic 重构
- [Defer] 检查点格式无版本消费 — `version: 1` 写入了但 `_load_checkpoint` 从未读取，未来跨版本兼容需补
- [Defer] 日志泄露绝对路径 — checkpoint/drop area 日志直接打印完整 temp_dir，可能含用户名 — 项目其他位置同风格，独立修复
- [Defer] `audio_path` 字段死代码 — 写入 checkpoint.json 但 `_load_checkpoint` 从不消费 — 可作未来调试用途保留
