# CosyVoice macOS Apple Silicon M5 部署指南

> 目标环境：macOS Apple Silicon M5 (24GB)，独立 conda 环境
> 最后更新：2026-05-22
> 状态：已部署验证
> 数据来源：CosyVoice main 分支 requirements.txt + README.md（2026-05-21 拉取）

---

## 一、前置条件

| 项目 | 要求 | 说明 |
|------|------|------|
| conda | miniconda 或 miniforge | `brew install --cask miniconda` |
| Python | 3.10（官方 README 明确要求） | 项目 venv 为 3.13，**不能混用** |
| 磁盘空间 | ~10GB（代码+依赖+模型） | 模型已有，主要装依赖 |
| Xcode CLI | `xcode-select --install` | 编译 C 扩展需要 |

---

## 二、安装步骤

### 2.1 安装 miniconda

```bash
brew install --cask miniconda
conda init zsh
source ~/.zshrc
conda --version
```

### 2.2 创建独立 conda 环境

```bash
conda create -n cosyvoice -y python=3.10
conda activate cosyvoice
python --version  # 必须 3.10.x
```

### 2.3 Clone CosyVoice 代码库

```bash
cd /Users/chou/work_space
git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git
cd CosyVoice

# 子模块 clone 失败时单独拉
git submodule update --init --recursive
```

### 2.4 安装依赖

requirements.txt 已做平台条件判断（2026-05-21 验证），**macOS 不需要手动修改**：

```
# TensorRT 三行已有 sys_platform == 'linux' 守卫，macOS 自动跳过
tensorrt-cu12==10.13.3.9; sys_platform == 'linux'

# onnxruntime 也已区分平台
onnxruntime-gpu==1.18.0; sys_platform == 'linux'
onnxruntime==1.18.0; sys_platform == 'darwin' or sys_platform == 'win32'

# deepspeed 也只装 linux
deepspeed==0.15.1; sys_platform == 'linux'
```

但有一个问题：`torch==2.3.1` 通过 `--extra-index-url https://download.pytorch.org/whl/cu121` 拉取 CUDA 版本，macOS 需要先装 MPS 版 PyTorch：

```bash
conda activate cosyvoice

# 第一步：先装 PyTorch MPS 版（覆盖 requirements.txt 中的 CUDA 版本）
# 2.4+ 对 Apple Silicon MPS 算子覆盖更好，减少 fallback 概率
pip install torch==2.4.1 torchaudio==2.4.1

# 第二步：装其余依赖（跳过已装的 torch/torchaudio）
pip install -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host=mirrors.aliyun.com

# 第三步：设置 MPS fallback（M 系列芯片建议默认开启）
export PYTORCH_ENABLE_MPS_FALLBACK=1
```

> **为什么先装 torch？** requirements.txt 开头有 `--extra-index-url https://download.pytorch.org/whl/cu121`，
> 如果不先装，pip 会尝试从这个 CUDA 仓库拉 torch，macOS 上会失败。先装好 MPS 版，后续 pip 会跳过。

### 2.5 验证安装

```bash
cd /Users/chou/open_project/CosyVoice

python -c "
import sys
sys.path.insert(0, 'third_party/Matcha-TTS')

from cosyvoice.cli.cosyvoice import CosyVoice
print('CosyVoice import 成功')
"
```

### 2.6 配置 PYTHONPATH

CosyVoice 依赖一个 third_party 子模块（Matcha-TTS）：

```bash
# 每次使用前执行（或写入 ~/.zshrc）
export PYTHONPATH=/Users/chou/open_project/CosyVoice/third_party/Matcha-TTS:/Users/chou/open_project/CosyVoice:$PYTHONPATH
```

> 注意：AcademiCodec 子模块已在 CosyVoice 较新版本中移除，当前不再需要。

### 2.7 测试推理

```bash
cd /Users/chou/open_project/CosyVoice

python -c "
import sys
sys.path.insert(0, 'third_party/Matcha-TTS')

from cosyvoice.cli.cosyvoice import CosyVoice
import torchaudio

# 使用已有模型
cosyvoice = CosyVoice('/Users/chou/work_space/video_translator/models/tts/CosyVoice-300M-SFT')
print('可用说话人:', cosyvoice.list_available_spks())

for i, result in enumerate(cosyvoice.inference_sft('你好，这是一个测试。', '中文女')):
    torchaudio.save(f'/tmp/cosyvoice_test_{i}.wav', result['tts_speech'], 22050)
    print(f'合成完成: /tmp/cosyvoice_test_{i}.wav')
"
```

---

## 三、M5 上可能遇到的问题

### 问题 1：PyTorch 安装失败（CUDA 版本冲突）

**症状：** `pip install -r requirements.txt` 时 torch 下载失败或安装 CUDA 版

**原因：** requirements.txt 指向 `--extra-index-url https://download.pytorch.org/whl/cu121`

**解决：** 2.4 步已处理——先装 `pip install torch==2.3.1 torchaudio==2.3.1`，再装其余依赖。

---

### 问题 2：PyTorch MPS 算子不支持

**症状：** `Output channels > 65536 not supported at the MPS device`

**原因：** PyTorch MPS 后端对部分算子有限制，CosyVoice 某些层可能触发

**解决：**
```bash
# 环境变量设置（运行前加）
export PYTORCH_ENABLE_MPS_FALLBACK=1

# 或代码中强制 CPU（慢但稳定）
# device = "cpu"
```

---

### 问题 3：submodule clone 失败

**症状：** `git submodule update` 网络超时

**原因：** AcademiCodec 和 Matcha-TTS 子模块可能被墙

**解决：**
```bash
# 配置 GitHub 代理
git config --global url."https://ghfast.top/https://github.com/".insteadOf "https://github.com/"
git submodule update --init --recursive
# 完成后恢复
git config --global --unset url."https://ghfast.top/https://github.com/".insteadOf
```

---

### 问题 4：内存不足

**M5 24GB 内存预算：**
- CosyVoice 300M-SFT 模型：~3GB
- PyTorch + 推理中间结果：~1-2GB
- macOS 系统占用：~5-6GB
- **余量：~12-14GB**

如果仍然 OOM，长文本分段处理即可。

---

### 问题 5：wetext / pynini 相关

**说明：** requirements.txt 中有 `wetext==0.0.4`（WeTextProcessing），用于中文文本规范化。
如果安装失败，CosyVoice 会自动跳过，不影响核心 TTS 功能，仅文本规范化效果稍差。

---

## 四、项目集成方式

CosyVoice 在独立 conda 环境（Python 3.10）中运行，项目（Python 3.13）通过 subprocess 桥接入：

### 已实现：subprocess 桥（scripts/cosyvoice_worker.py）

主进程（Python 3.13）通过 `subprocess.Popen` 调用 conda 环境下的 worker 脚本，使用 NDJSON 协议通信：

- **stdin** → JSON 批量输入（segments + model_path + speaker + speed）
- **stdout** ← NDJSON 逐段结果（每行一个 result/done/error）
- **stderr** ← worker 日志（供主进程诊断）

配置项在 `config.yaml` 的 `tts` 段：
```yaml
tts:
  conda_python_path: "/opt/homebrew/Caskroom/miniconda/base/envs/cosyvoice/bin/python"
  cosyvoice_source_path: "/Users/chou/open_project/CosyVoice"
```

失败时自动降级到 Edge-TTS（pipeline.py 已实现降级逻辑）。

### ~~方案 B：sys.path 注入（不可用）~~

Python 3.10（conda）编译的 C 扩展 .so 文件与 Python 3.13（项目 venv）ABI 不兼容，
import 时**必然报错** `ImportError: ... not a supported wheel`。此方案无法使用。

---

## 五、验证清单

- [ ] `conda activate cosyvoice` 成功
- [ ] `python --version` 输出 3.10.x
- [ ] `python -c "import torch; print(torch.backends.mps.is_available())"` 返回 True
- [ ] `from cosyvoice.cli.cosyvoice import CosyVoice` 无报错
- [ ] `CosyVoice('models/tts/CosyVoice-300M-SFT')` 加载成功
- [ ] `inference_sft('测试', '中文女')` 生成音频文件
- [ ] 音频文件可正常播放

---

## 六、回退方案

安装失败时：

1. **Edge-TTS**（已集成）— 云端免费，零安装，v1 当前主力
2. **sherpa-onnx + MeloTTS** — `pip install sherpa-onnx`，macOS arm64 原生支持，离线

---

_文档版本: 2026-05-21_
_requirements.txt 来源: https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/requirements.txt_
_README 来源: https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/README.md_
_API 来源: https://raw.githubusercontent.com/FunAudioLLM/CosyVoice/main/cosyvoice/cli/cosyvoice.py_
