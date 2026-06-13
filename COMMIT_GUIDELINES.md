# 提交规范 (Commit Guidelines)

本文档定义了 video_translator 项目的代码提交规范，确保提交历史清晰可追溯，与 Epic/Story 结构对齐。

## Epic 粒度提交规范

### Commit Message 格式

#### Story 实施过程中的提交

```bash
<type>(v<epic>-<story>): <简短描述>

主要修改:
- 第一点
- 第二点

Refs: v<epic>-<story> | Epic: <epic>-v<version>
```

**示例：**
```bash
feat(v2.0-1-3): 检查 Story 状态一致性

主要修改:
- 扫描所有 v1.0-v2.0 Story 文档
- 验证 Status 字段与 sprint-status.yaml 一致
- 为 v2.0-1-1 补充缺失的 Dev Agent Record 章节

Refs: v2.0-1-3 | Epic: 1-v2.0
```

#### Story 完成时的总结提交

```bash
feat(v<epic>-<story>): Story 完成总结 - <Story 标题>

Story: v<epic>-<story> | Status: done
Epic: <epic>-v<version> | Progress: <当前进度>/<总Story数> stories 完成

完成内容:
- 第一项主要工作
- 第二项主要工作
- 第三项主要工作

测试验证:
- 所有测试通过
- 代码质量检查通过
```

**示例：**
```bash
feat(v2.0-1-3): Story 完成总结 - 执行纪律

Story: v2.0-1-3 | Status: done
Epic: 1-v2.0 | Progress: 3/3 stories 完成

完成内容:
- 检查并修复所有 Story 状态不一致
- 建立 Epic 粒度提交规范
- 验证 Epic 1-v2.0 完整性

测试验证:
- 所有测试通过
- ruff/mypy 检查通过
```

### Commit Type 分类

| Type | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能或 Story 实施 | `feat(v2.0-1-1): 删除方案 UI` |
| `fix` | Bug 修复 | `fix(v2.0-1-2): Windows 测试失败` |
| `refactor` | 代码重构（不改变功能） | `refactor(v2.0-1-3): 提交规范优化` |
| `docs` | 文档更新 | `docs(v2.0-1-3): 更新 README` |
| `test` | 测试相关 | `test(v2.0-1-2): 添加平台测试` |
| `chore` | 构建/工具相关 | `chore: 更新依赖版本` |
| `perf` | 性能优化 | `perf(v2.0-2-1): 加速音频处理` |

### 提交组织最佳实践

#### 1. Epic 层面组织

**推荐方式：** 每个 Epic 的提交按 Story 顺序组织

```bash
# Epic 1-v2.0 提交历史
feat(v2.0-1-1): 删除方案 UI
feat(v2.0-1-1): Story 完成总结
feat(v2.0-1-2): 修复 Windows 测试
feat(v2.0-1-2): 添加许可证信息
feat(v2.0-1-2): Story 完成总结
feat(v2.0-1-3): 检查状态一致性
feat(v2.0-1-3): 建立提交规范
feat(v2.0-1-3): Story 完成总结
```

#### 2. Story 开始时的提交

**推荐：** 创建 Story 开始标记提交

```bash
feat(v2.0-1-3): 开始实施 - 执行纪律

主要任务:
- Story 状态一致性检查
- Epic 粒度提交规范建立
- Epic 完整性验证

Refs: v2.0-1-3 | Epic: 1-v2.0
```

#### 3. 实施过程中的提交

**推荐：** 按功能点或 AC 提交，包含 Story ID

```bash
# AC1: 检查 Story 状态一致性
feat(v2.0-1-3): 检查 Story 状态一致性

# AC2: 建立提交规范
feat(v2.0-1-3): 建立 Epic 粒度提交规范

# AC3: 验证 Epic 完整性
feat(v2.0-1-3): 验证 Epic 1-v2.0 完整性
```

#### 4. Story 完成时的总结提交

**必需：** 每个 Story 完成时必须包含总结提交

```bash
feat(v2.0-1-3): Story 完成总结 - 执行纪律

Story: v2.0-1-3 | Status: done
Epic: 1-v2.0 | Progress: 3/3 stories 完成

完成内容:
- ✅ 检查并修复所有 Story 状态不一致
- ✅ 建立 Epic 粒度提交规范
- ✅ 验证 Epic 1-v2.0 完整性
- ✅ 所有测试通过，无 regressions

测试验证:
- pytest: 68/68 tests passed
- ruff: 0 errors, 0 warnings
- mypy: 0 errors
```

### 提交历史查看

#### 查看 Epic 的所有提交

```bash
# 查看 Epic 1-v2.0 的所有提交
git log --oneline --grep="v2.0-1-\|1-v2.0\|Epic 1-v2.0"

# 查看 Epic 1-v2.0 的详细提交
git log --grep="v2.0-1-" --format="%h %s%n%b%n---%n"
```

#### 查看 Story 的所有提交

```bash
# 查看 Story v2.0-1-3 的所有提交
git log --oneline --grep="v2.0-1-3"

# 查看 Story v2.0-1-3 的详细提交
git log --grep="v2.0-1-3" --format="%h %s%n%b%n---%n"
```

### Commit Message 模板

#### 完整模板

```bash
<type>(v<epic>-<story>): <简短描述>

主要修改:
- <修改点1>
- <修改点2>
- <修改点3>

技术细节:
- <技术决策1>
- <技术决策2>

测试验证:
- <测试结果>
- <代码质量检查结果>

Refs: v<epic>-<story> | Epic: <epic>-v<version>
```

#### 简化模板（小型修改）

```bash
<type>(v<epic>-<story>): <简短描述>

Refs: v<epic>-<story> | Epic: <epic>-v<version>
```

### 与 Story 文档的对应关系

每个 Story 完成后，Story 文档应包含：

1. **Dev Agent Record** — 实施记录
2. **File List** — 修改的文件列表
3. **Change Log** — 变更日志
4. **Status** — 状态标记

这些章节应该与 git 提交历史对应，便于追溯。

### 最佳实践总结

1. **Epic 粒度**：提交按 Epic 组织，每个 Story 有清晰的开始和结束标记
2. **Story ID**：每个提交包含 Story ID，便于追溯
3. **总结提交**：Story 完成时包含总结提交，标记状态和进度
4. **清晰描述**：提交信息清晰描述修改内容和原因
5. **测试验证**：包含测试验证信息，确保质量

### 示例提交历史

```bash
# Epic 1-v2.0 完整提交历史示例

# Story v2.0-1-1: 删除方案 UI
feat(v2.0-1-1): 开始实施 - 删除方案 UI
feat(v2.0-1-1): 删除 config_panel.py scheme UI 代码
feat(v2.0-1-1): 删除 main_window.py 委托方法
feat(v2.0-1-1): 删除 scheme UI 测试文件
feat(v2.0-1-1): Story 完成总结 - 删除方案 UI

# Story v2.0-1-2: 修复 Windows 测试 + ChatTTS 许可证
feat(v2.0-1-2): 开始实施 - 修复 Windows 测试
feat(v2.0-1-2): 修复 platform_utils.py Windows 跨平台兼容性
feat(v2.0-1-2): 添加 ChatTTS 许可证信息
feat(v2.0-1-2): Story 完成总结 - 修复 Windows 测试

# Story v2.0-1-3: 执行纪律
feat(v2.0-1-3): 开始实施 - 执行纪律
feat(v2.0-1-3): 检查 Story 状态一致性
feat(v2.0-1-3): 建立 Epic 粒度提交规范
feat(v2.0-1-3): Story 完成总结 - 执行纪律

# Epic 1-v2.0 完成
chore: Epic 1-v2.0 全部完成，准备 Retrospective
```

## 与 BMad 工作流的集成

本提交规范与 BMad 工作流完全集成：

1. **Story 创建** → `bmad-create-story` 生成 Story 文档
2. **Story 实施** → 遵循本提交规范实施
3. **Story 完成** → 提交总结，标记状态为 done
4. **Epic Retrospective** → 基于 Epic 提交历史进行回顾

## 参考资料

- [Conventional Commits](https://www.conventionalcommits.org/)
- [BMad Method 工作流](../_bmad/)
- [Story 文档模板](../_bmad-output/implementation-artifacts/)
