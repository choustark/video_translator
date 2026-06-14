# 管线信号契约（Pipeline Signals Contract）

> 目标读者：项目维护者、回归代码的 Dev、调试 UI/pipeline 时序问题的工程师
> 最后更新：2026-06-14（v2.0-3-2 修复 D6-DEV-1）
> 状态：当前实现快照（v2.0），不包含未来规划
> 数据来源：代码快照 2026-06-14 / commit `d524bdd` + v2.0-3-2 修复

---

## 一、信号清单

`PipelineSignals`（`src/signals.py`）定义 7 个 PySide6 Signal，构成**管线 → UI 的单向通信总线**。

| # | 信号 | 签名 | 发送方 | 接收方 | 触发位置 |
|---|------|------|--------|--------|---------|
| 1 | `stage_started` | `(stage_name: str)` | `Pipeline` 后台线程 | `PipelineProgress._on_stage_started` | `pipeline.py:227`（`_start_stage`） |
| 2 | `stage_progress` | `(stage_name: str, progress: float)` | `Pipeline` 后台线程 | `PipelineProgress._on_stage_progress` | `pipeline.py:394, 456, 493, 532, 587, 610, 616, 624` |
| 3 | `stage_completed` | `(stage_name: str, duration: float)` | `Pipeline` 后台线程 | `PipelineProgress._on_stage_completed` | `pipeline.py:236`（`_complete_stage`） |
| 4 | `stage_failed` | `(stage_name: str, error: str)` | `Pipeline` 后台线程 | `MainWindow._on_stage_failed` + `PipelineProgress._on_stage_failed` | `pipeline.py:258`（`_fail_stage`） |
| 5 | `transcript_updated` | `(text: str)` | `Pipeline` 后台线程 | `TranscriptPanel._on_transcript_updated` | `pipeline.py:467`（ASR 后）, `503`（翻译后） |
| 6 | `pipeline_finished` | `()` | `Pipeline` 后台线程 | `MainWindow._on_pipeline_finished` + `PipelineProgress._on_pipeline_finished` | `pipeline.py:57, 175, 186, 196` |
| 7 | `tts_degraded` | `(original: str, fallback: str)` | `Pipeline` 后台线程 | `PipelineProgress._on_tts_degraded` | `pipeline.py:565`（TTS 三级降级） |

**进度参数约束：** `progress ∈ [0.0, 1.0]`，同阶段内**单调不减**（ETA 计算依赖此前提，见 `pipeline_progress.py:73`）。

**跨线程机制：** `Pipeline` 在后台 `threading.Thread` 中 emit，UI 在 PySide6 主线程接收，依赖 Qt 自动 `QueuedConnection`，不手动加锁（详见 `_bmad-output/project-context.md` 第 142 行）。

---

## 二、执行路径与 emit 序列

`Pipeline.process()` 主流程（`pipeline.py:86-197`）有三条主要执行路径，外加一条未捕获异常兜底路径。每条路径产生不同的 emit 序列。

### 2.1 成功路径

**触发条件：** 全部 6 个阶段（音频提取 → ASR → 翻译 → TTS → 语速自适应 → 合成）正常完成。

**emit 序列：**

```
[阶段 1: 音频提取]
  stage_started("音频提取")           @ pipeline.py:227
  stage_progress("音频提取", 0.x)     @ pipeline.py:394  ← 由 ffmpeg stderr 解析多次
  stage_completed("音频提取", dur)    @ pipeline.py:236

[阶段 2: ASR]
  stage_started("ASR")                @ 227
  stage_progress("ASR", 0.x)          @ 456  ← mlx-whisper 周期 timer 或 faster-whisper generator
  transcript_updated(full_text)       @ 467  ← ASR 完成后一次性更新字幕
  stage_completed("ASR", dur)         @ 236

[阶段 3: 翻译]
  stage_started("翻译")               @ 227
  stage_progress("翻译", 0.x)         @ 493
  transcript_updated(bilingual)       @ 503  ← 翻译完成后再次更新（双语对照）
  stage_completed("翻译", dur)        @ 236

[阶段 4: TTS]
  stage_started("TTS")                @ 227
  stage_progress("TTS", 0.x)          @ 532
  [可选] tts_degraded(orig, fb)       @ 565  ← 仅当 CosyVoice → ChatTTS → Edge-TTS 降级触发
  stage_completed("TTS", dur)         @ 236

[阶段 5: 语速自适应]
  stage_started("语速自适应")         @ 227
  stage_progress("语速自适应", 0.x)   @ 587
  stage_completed("语速自适应", dur)  @ 236

[阶段 6: 合成]
  stage_started("合成")               @ 227
  stage_progress("合成", 0.33)        @ 610
  stage_progress("合成", 0.67)        @ 616
  stage_progress("合成", 1.0)         @ 624
  stage_completed("合成", dur)        @ 236

[终态]
  pipeline_finished()                 @ 175
```

**关键观察：**
- 同一阶段内 `stage_started` 只 emit 一次（不变量 3）。
- `transcript_updated` 在 ASR 与翻译阶段各发一次，UI 用最新内容覆盖。
- `pipeline_finished` 永远是最后一个信号（不变量 1）。

### 2.2 阶段失败路径（`PipelineError`）

**触发条件：** 任意阶段抛出 `PipelineError`（业务异常，如 ffmpeg 失败、模型加载失败、ASR 抛错）。

**emit 序列：**

```
[阶段 N: 失败阶段]
  stage_started(stage)                @ 227
  [可能的 stage_progress 系列]
  ... 异常抛出 ...

[process() except 块, pipeline.py:178-187]
  stage_failed(stage, str(e))         @ 258  ← 经 _fail_stage() 调用
  pipeline_finished()                 @ 186
```

**关键不变量：** `stage_failed` 必须先于 `pipeline_finished`（不变量 2），UI 端 `_has_failure` 标志依赖此顺序（详见 §四.1）。

### 2.3 用户中止路径（abort）

**触发条件：** 用户点击"中止翻译"按钮，`Pipeline.abort()` 被调用 → `_abort_requested.set()` → 下一次 `_check_abort()` 抛 `PipelineError("用户中止")`。

**emit 序列：**

```
[阶段 N: 当前阶段]
  stage_started(stage)                @ 227
  [可能的 stage_progress 系列]

[abort 调用 → _abort_requested.set()]
  [子进程被 terminate / kill, pipeline.py:62-79]

[_check_abort 触发, pipeline.py:261-264]
  raise PipelineError("用户中止", stage=current_stage)

[process() except 块]
  stage_failed(current_stage, "用户中止")  @ 258
  pipeline_finished()                       @ 186

[UI 端]
  MainWindow._on_stage_failed:
    检查 self._pipeline._abort_requested.is_set() == True
    → 跳过 QMessageBox.critical（main_window.py:195-197）
  PipelineProgress._on_stage_failed:
    设置 _has_failure = True（pipeline_progress.py:93）
  PipelineProgress._on_pipeline_finished:
    显示 "管线执行失败"（因 _has_failure=True）
```

**关键契约：** abort 路径仍 emit `stage_failed`，只是 UI 端 `MainWindow` 通过 `_abort_requested.is_set()` 静默处理（不弹错误对话框），但 `PipelineProgress` 仍标记失败。这是**设计意图**——给用户视觉反馈"中止已生效"，但不显示烦人的错误弹窗。

### 2.4 未捕获异常路径（**已于 v2.0-3-2 修复**）

**触发条件：** `process()` 在外层 try 块之外抛异常（极罕见，理论上 `process()` 内部 86-197 行的双 except 已覆盖所有 Exception）。

**emit 序列（v2.0-3-2 修复后）：**

```
[_run_in_thread, pipeline.py:52-60]
  try:
      self.process(...)
  except Exception as e:
      logger.exception("管线 | 未捕获异常")
      self._fail_stage(self._current_stage, str(e))  @ 58  ← emit stage_failed
      self.signals.pipeline_finished.emit()           @ 59
```

**修复前（v2.0-3-2 之前）的偏差：**

修复前的 `_run_in_thread` except 块**只 emit `pipeline_finished`，不 emit `stage_failed`**，违反契约不变量 2（§三）。后果：
- `MainWindow._on_pipeline_finished` 会恢复 UI（按钮、`_pipeline=None`）✓ 正常
- `PipelineProgress._on_pipeline_finished` 因 `_has_failure=False`（始终未设置）会误显示"全部完成，总耗时 Xs" ✗ 不准确

**v2.0-3-2 修复方案（2026-06-14）：**

在 `_run_in_thread` 的 except 块中复用 `_fail_stage` 方法（line 253-259），传入 `self._current_stage`（在 `__init__` 已初始化为 `STAGE_NAMES[0]`="音频提取"，必为合法值）与 `str(e)`，保证不变量 2 成立。

**回归测试：** `tests/test_pipeline_uncaught_exception.py` 验证 emit 顺序。

---

## 三、不变量（Invariants）

以下 4 条不变量是 UI 端正确工作的前提，**任何代码改动不得破坏**。

### 不变量 1：`pipeline_finished` 永远是最后一个信号

**理由：** `MainWindow._on_pipeline_finished`（`main_window.py:183-191`）恢复按钮状态、清 `_pipeline = None`。若之后还有 emit，会导致 dangling reference。

**验证方法：** 任何路径下 grep `pipeline_finished.emit()` 后必须确认无后续 emit。

### 不变量 2：`stage_failed` 必须先于 `pipeline_finished`

**理由：** `PipelineProgress._on_pipeline_finished`（`pipeline_progress.py:95-105`）通过 `_has_failure` 标志决定显示"全部完成"还是"管线执行失败"，而 `_has_failure` 由 `_on_stage_failed` 设置。若顺序颠倒，UI 误显示成功。

**违反案例（历史）：** `_run_in_thread` 未捕获异常路径曾违反此不变量（§2.4），已于 v2.0-3-2 修复。

### 不变量 3：同一阶段内 `stage_started` 只 emit 一次

**理由：** `_on_stage_started`（`pipeline_progress.py:55-61`）覆写 `_stage_start_times[stage_name]`。若同一阶段多次 emit，ETA 计算的起点会被重置，导致 ETA 失真。

**当前实现保证：** `_start_stage()` 仅在 `process()` 的 `if "阶段名" not in completed_set:` 分支内调用，断点续传时跳过已完成阶段，因此每阶段至多一次。

### 不变量 4：`stage_progress` 的 `progress` 参数同阶段内单调不减

**理由：** `_on_stage_progress`（`pipeline_progress.py:63-76`）基于"elapsed / progress × (1 - progress)"计算 ETA。若 progress 回退，ETA 会出现负数或剧烈跳变。

**当前实现保证：**
- mlx-whisper：周期 timer 用 `min(ratio, 0.95)` + 完成时强制 1.0（v2.0-4-2）
- faster-whisper：generator-based，`i / total` 严格单调递增
- 音频提取：ffmpeg 解析 `time=` 字段，时间戳天然单调
- TTS / 翻译：`i / total` 严格递增
- 合成：硬编码 `0.33 → 0.67 → 1.0`

---

## 四、UI 消费契约

`MainWindow._connect_signals`（`main_window.py:121-136`）建立 9 个 connect 关系。

### 4.1 `PipelineProgress` 依赖

| 信号 | 方法 | 关键依赖 |
|------|------|---------|
| `stage_started` | `_on_stage_started` | 设置行状态为 running；记录 `_stage_start_times[stage]` |
| `stage_progress` | `_on_stage_progress` | 更新进度百分比 + ETA；依赖 `_stage_start_times` 已被 `_on_stage_started` 设置 |
| `stage_completed` | `_on_stage_completed` | 设置行状态为 completed；记录 `_stage_durations[stage]`（用于 §不变量2 失败提示） |
| `stage_failed` | `_on_stage_failed` | 设置行状态为 failed；设置 `_has_failure = True` |
| `pipeline_finished` | `_on_pipeline_finished` | 根据 `_has_failure` 显示"管线执行失败"或"全部完成，总耗时 Xs" |
| `tts_degraded` | `_on_tts_degraded` | 在 TTS 行显示警告标签（"已降级为 Edge-TTS"） |

**关键依赖链：** `_has_failure` 由 `_on_stage_failed` 写、由 `_on_pipeline_finished` 读。这是不变量 2 的实现层依据。

### 4.2 `MainWindow` 依赖

| 信号 | 方法 | 关键依赖 |
|------|------|---------|
| `pipeline_finished` | `_on_pipeline_finished` | 恢复按钮、清 `_pipeline = None`、`_translating = False` |
| `stage_failed` | `_on_stage_failed` | 通过 `_abort_requested.is_set()` 区分中止与失败；中止跳过弹窗，失败显示 `QMessageBox.critical` |

**关键判断：** `_on_stage_failed` 第 195 行：

```python
if self._pipeline is not None and self._pipeline._abort_requested.is_set():
    logger.info("用户中止，跳过失败弹窗 | stage=%s | error=%s", stage, error)
    return
```

注意此判断访问 `_pipeline._abort_requested`（私有字段）。这是契约的一部分：`Pipeline` 必须保留 `_abort_requested` 作为可读字段（不可改为 `_ __abort_requested` name-mangling 形式）。

### 4.3 `TranscriptPanel` 依赖

| 信号 | 方法 | 关键依赖 |
|------|------|---------|
| `transcript_updated` | `_on_transcript_updated` | 覆盖显示字幕文本（ASR 单语 → 翻译双语） |

**关键观察：** `transcript_updated` 在 ASR 与翻译阶段各发一次（§2.1），`TranscriptPanel` 用最新内容覆盖。

---

## 五、已知偏差与未来工作

### 5.1 已知偏差

> 截至 v2.0-3-2（2026-06-14），**无已知偏差**。原 D6-DEV-1（`_run_in_thread` 未捕获异常路径缺 `stage_failed`）已修复。

| ID | 描述 | 状态 | 修复 Story |
|----|------|------|-----------|
| ~~D6-DEV-1~~ | `_run_in_thread` 未捕获异常路径缺 `stage_failed`（§2.4） | ✅ 已修复 | v2.0-3-2（2026-06-14） |

### 5.2 未来工作（不在 v2.0 范围）

- v3.0 多说话人识别（D63）可能新增 `speaker_detected(speaker_id, segment_index)` 信号
- v3.0 单句编辑重合成（D62）可能新增 `resynthesis_started` / `resynthesis_finished` 信号
- 当前无信号 schema 版本化，未来若信号签名变更需考虑向后兼容

**新增信号的设计原则：**
1. 信号签名简单（≤3 参数，全部基本类型）
2. 文档化发送方 / 接收方 / 触发位置
3. 文档化与既有信号的顺序约束（如新增的信号必须在 `pipeline_finished` 之前）
4. 更新本契约文档

---

## 六、参考资料

- **当前实现：**
  - `src/signals.py`（PipelineSignals 定义，12 行 + docstring）
  - `src/pipeline.py:52-264`（emit 与状态管理）
  - `src/gui/main_window.py:121-202`（signal connect + handler）
  - `src/gui/pipeline_progress.py:55-111`（PipelineProgress handler）
  - `src/gui/transcript_panel.py:72`（TranscriptPanel handler）
- **规则来源：**
  - `_bmad-output/project-context.md:75-85`（PySide6 Signal 定义规则）
  - `_bmad-output/project-context.md:142`（跨线程 emit 依赖 QueuedConnection）
  - `_bmad-output/project-context.md:183`（回调只 emit 信号，不耗时操作）
- **相关 Story：**
  - v2.0-4-2（D22 ASR 进度回调实时化）——`stage_progress` 在 ASR 阶段的实现
  - v2.0-2-3（D23 Edge-TTS 重试）——`tts_degraded` 触发场景
  - v2.0-2-2（D61b 断点续传）——`completed_set` 跳过已完成阶段，保证不变量 3
