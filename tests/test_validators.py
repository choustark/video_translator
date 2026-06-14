from __future__ import annotations

import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ASRConfig, TranslationConfig, TTSConfig
from src.exceptions import ValidationError
from src.validators import (
    ValidationResult,
    validate_all,
    validate_asr_model,
    validate_config_only,
    validate_disk_space,
    validate_ffmpeg,
    validate_memory,
    validate_translation_api,
    validate_tts_model,
    validate_video_duration,
    validate_video_format,
)

# ---------------------------------------------------------------------------
# validate_ffmpeg
# ---------------------------------------------------------------------------


class TestValidateFfmpeg:
    """validate_ffmpeg 测试：路径检测 + 版本解析。"""

    def test_passes_when_ffmpeg_exists_with_valid_version(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "ffmpeg version 6.0 Copyright (c) 2000-2023\n"
        with (
            patch("src.validators.shutil.which", return_value="/usr/local/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_result),
        ):
            validate_ffmpeg()

    def test_passes_with_ffmpeg_version_4(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "ffmpeg version 4.4.4 Copyright (c) 2000-2021\n"
        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_result),
        ):
            validate_ffmpeg()

    def test_fails_when_ffmpeg_not_found(self) -> None:
        with (
            patch("src.validators.shutil.which", return_value=None),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_ffmpeg()
        assert exc_info.value.stage == "ffmpeg"
        assert "brew install ffmpeg" in exc_info.value.suggestion

    def test_fails_when_version_too_low(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "ffmpeg version 3.4.12 Copyright (c) 2000-2021\n"
        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_ffmpeg()
        assert exc_info.value.stage == "ffmpeg"
        assert "升级" in exc_info.value.suggestion

    def test_fails_when_version_unparseable(self) -> None:
        mock_result = MagicMock()
        mock_result.stdout = "some random output without version\n"
        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_ffmpeg()
        assert "无法解析" in str(exc_info.value)

    def test_fails_when_subprocess_times_out(self) -> None:
        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "src.validators.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=5),
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_ffmpeg()
        assert exc_info.value.stage == "ffmpeg"

    def test_fails_when_subprocess_os_error(self) -> None:
        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "src.validators.subprocess.run",
                side_effect=OSError("无法执行 ffmpeg"),
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_ffmpeg()
        assert exc_info.value.stage == "ffmpeg"


# ---------------------------------------------------------------------------
# validate_asr_model
# ---------------------------------------------------------------------------


class TestValidateAsrModel:
    """validate_asr_model 测试：路径空值 + 存在性。"""

    def test_passes_when_model_exists(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "whisper-model"
        model_dir.mkdir()
        validate_asr_model(str(model_dir))

    def test_fails_when_model_path_empty(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_asr_model("")
        assert exc_info.value.stage == "asr"
        assert "未配置" in str(exc_info.value)

    def test_fails_when_model_path_not_exists(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_asr_model("/nonexistent/model/path")
        assert exc_info.value.stage == "asr"
        assert "不存在" in str(exc_info.value)

    def test_fails_when_model_path_is_file_not_dir(self, tmp_path: Path) -> None:
        model_file = tmp_path / "model.bin"
        model_file.write_text("fake model data")
        with pytest.raises(ValidationError) as exc_info:
            validate_asr_model(str(model_file))
        assert exc_info.value.stage == "asr"
        assert "不是目录" in str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_translation_api
# ---------------------------------------------------------------------------


class TestValidateTranslationApi:
    """validate_translation_api 测试：NLLB 跳过 + 空 Key + 网络请求 mock。"""

    def test_skips_for_nllb(self) -> None:
        validate_translation_api("nllb", "")

    def test_fails_for_empty_api_key(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_translation_api("glm", "")
        assert exc_info.value.stage == "translation"
        assert "未配置" in str(exc_info.value)

    def test_passes_for_valid_glm_key(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"choices":[]}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("src.validators.urllib.request.urlopen", return_value=mock_resp):
            validate_translation_api("glm", "valid-test-key")

    def test_passes_for_valid_deepseek_key(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"choices":[]}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("src.validators.urllib.request.urlopen", return_value=mock_resp):
            validate_translation_api("deepseek", "valid-test-key")

    def test_passes_for_valid_openai_key(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"choices":[]}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("src.validators.urllib.request.urlopen", return_value=mock_resp):
            validate_translation_api("openai", "valid-test-key")

    def test_passes_for_valid_deepl_key(self) -> None:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"translations":[]}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("src.validators.urllib.request.urlopen", return_value=mock_resp):
            validate_translation_api("deepl", "valid-test-key")

    def test_fails_for_401_response(self) -> None:
        err = urllib.error.HTTPError(
            url="https://example.com",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=None,  # type: ignore[arg-type]
        )
        with (
            patch("src.validators.urllib.request.urlopen", side_effect=err),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_translation_api("glm", "bad-key")
        assert exc_info.value.stage == "translation"
        assert "无效" in str(exc_info.value)

    def test_fails_for_403_response(self) -> None:
        err = urllib.error.HTTPError(
            url="https://example.com",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=None,  # type: ignore[arg-type]
        )
        with (
            patch("src.validators.urllib.request.urlopen", side_effect=err),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_translation_api("deepseek", "bad-key")
        assert "无效" in str(exc_info.value)

    def test_skips_on_network_timeout(self) -> None:
        with patch(
            "src.validators.urllib.request.urlopen",
            side_effect=TimeoutError("connection timed out"),
        ):
            validate_translation_api("glm", "some-key")

    def test_skips_on_url_error(self) -> None:
        with patch(
            "src.validators.urllib.request.urlopen",
            side_effect=urllib.error.URLError("no network"),
        ):
            validate_translation_api("glm", "some-key")

    def test_skips_on_500_server_error(self) -> None:
        err = urllib.error.HTTPError(
            url="https://example.com",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,  # type: ignore[arg-type]
        )
        with patch("src.validators.urllib.request.urlopen", side_effect=err):
            validate_translation_api("glm", "some-key")


# ---------------------------------------------------------------------------
# validate_tts_model
# ---------------------------------------------------------------------------


class TestValidateTtsModel:
    """validate_tts_model 测试：Edge-TTS 跳过 + CosyVoice 路径校验。"""

    def test_skips_for_edge_tts(self) -> None:
        validate_tts_model("edge-tts", "")

    def test_passes_for_cosyvoice_with_valid_path(self, tmp_path: Path) -> None:
        model_dir = tmp_path / "cosyvoice-model"
        model_dir.mkdir()
        validate_tts_model("cosyvoice", str(model_dir))

    def test_fails_for_cosyvoice_empty_path(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_tts_model("cosyvoice", "")
        assert exc_info.value.stage == "tts"
        assert "未配置" in str(exc_info.value)

    def test_fails_for_cosyvoice_nonexistent_path(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_tts_model("cosyvoice", "/nonexistent/cosyvoice")
        assert exc_info.value.stage == "tts"
        assert "不存在" in str(exc_info.value)

    def test_fails_for_cosyvoice_path_is_file_not_dir(self, tmp_path: Path) -> None:
        model_file = tmp_path / "cosyvoice.bin"
        model_file.write_text("fake model")
        with pytest.raises(ValidationError) as exc_info:
            validate_tts_model("cosyvoice", str(model_file))
        assert exc_info.value.stage == "tts"
        assert "不是目录" in str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_tts_reference_audio（D60 声音克隆）
# ---------------------------------------------------------------------------


class TestValidateTtsReferenceAudio:
    """validate_tts_reference_audio 测试：D60 参考音频校验。"""

    def test_skips_for_edge_tts(self, tmp_path: Path) -> None:
        from src.validators import validate_tts_reference_audio

        # Edge-TTS 即便设置了 reference_audio 也应跳过
        validate_tts_reference_audio("edge-tts", str(tmp_path / "ref.wav"))

    def test_skips_when_reference_audio_empty(self) -> None:
        from src.validators import validate_tts_reference_audio

        validate_tts_reference_audio("cosyvoice", "")

    def test_passes_for_valid_wav(self, tmp_path: Path) -> None:
        from src.validators import validate_tts_reference_audio

        ref = tmp_path / "voice.wav"
        ref.write_bytes(b"fake")
        validate_tts_reference_audio("cosyvoice", str(ref))

    def test_passes_for_mp3_and_flac(self, tmp_path: Path) -> None:
        from src.validators import validate_tts_reference_audio

        for suffix in (".mp3", ".flac"):
            ref = tmp_path / f"voice{suffix}"
            ref.write_bytes(b"fake")
            validate_tts_reference_audio("cosyvoice", str(ref))

    def test_fails_for_nonexistent_file(self, tmp_path: Path) -> None:
        from src.validators import validate_tts_reference_audio

        with pytest.raises(ValidationError) as exc_info:
            validate_tts_reference_audio("cosyvoice", str(tmp_path / "missing.wav"))
        assert exc_info.value.stage == "tts"
        assert "不存在" in str(exc_info.value)

    def test_fails_for_unsupported_suffix(self, tmp_path: Path) -> None:
        from src.validators import validate_tts_reference_audio

        ref = tmp_path / "voice.ogg"
        ref.write_bytes(b"fake")
        with pytest.raises(ValidationError) as exc_info:
            validate_tts_reference_audio("cosyvoice", str(ref))
        assert exc_info.value.stage == "tts"
        assert "不支持" in str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_video_format
# ---------------------------------------------------------------------------


class TestValidateVideoFormat:
    """validate_video_format 测试：允许列表 + 大小写不敏感。"""

    @pytest.mark.parametrize("suffix", [".mp4", ".mkv", ".mov", ".avi"])
    def test_passes_for_supported_formats(self, suffix: str) -> None:
        validate_video_format(Path(f"video{suffix}"))

    @pytest.mark.parametrize("suffix", [".MP4", ".MKV", ".MOV", ".AVI"])
    def test_passes_for_uppercase_formats(self, suffix: str) -> None:
        validate_video_format(Path(f"video{suffix}"))

    def test_fails_for_unsupported_format(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_video_format(Path("video.wmv"))
        assert exc_info.value.stage == "video"
        assert "不支持" in str(exc_info.value)

    def test_fails_for_no_extension(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            validate_video_format(Path("video"))
        assert exc_info.value.stage == "video"


# ---------------------------------------------------------------------------
# validate_video_duration
# ---------------------------------------------------------------------------


class TestValidateVideoDuration:
    """validate_video_duration 测试：ffprobe 输出解析 + 时长限制。"""

    def test_passes_for_short_video(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "120.5\n"
        with patch("src.validators.subprocess.run", return_value=mock_result):
            validate_video_duration(Path("video.mp4"))

    def test_passes_for_exactly_7200_seconds(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "7200.0\n"
        with patch("src.validators.subprocess.run", return_value=mock_result):
            validate_video_duration(Path("video.mp4"))

    def test_fails_for_over_7200_seconds(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "7201.0\n"
        with (
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_video_duration(Path("video.mp4"))
        assert exc_info.value.stage == "video"
        assert "超过" in str(exc_info.value)
        assert "2 小时" in str(exc_info.value)

    def test_fails_when_ffprobe_nonzero_exit(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        with (
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_video_duration(Path("video.mp4"))
        assert "无法获取" in str(exc_info.value)

    def test_fails_when_ffprobe_times_out(self) -> None:
        with (
            patch(
                "src.validators.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="ffprobe", timeout=10),
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_video_duration(Path("video.mp4"))
        assert "无法获取" in str(exc_info.value)

    def test_fails_when_duration_unparseable(self) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not-a-number\n"
        with (
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_video_duration(Path("video.mp4"))
        assert "无法解析" in str(exc_info.value)

    def test_fails_for_zero_duration(self) -> None:
        """零时长视频（duration=0.0）通常已损坏，应被校验拦截。"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "0.0\n"
        with (
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_video_duration(Path("video.mp4"))
        assert exc_info.value.stage == "video"
        assert "损坏" in str(exc_info.value)

    def test_fails_for_negative_duration(self) -> None:
        """负数时长属异常容器输出，与零时长共用同一拦截分支。"""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "-1.0\n"
        with (
            patch("src.validators.subprocess.run", return_value=mock_result),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_video_duration(Path("video.mp4"))
        assert exc_info.value.stage == "video"
        assert "损坏" in str(exc_info.value)


# ---------------------------------------------------------------------------
# validate_memory
# ---------------------------------------------------------------------------


class TestValidateMemory:
    """validate_memory 测试：psutil 可用内存阈值。"""

    def test_passes_when_sufficient_memory(self) -> None:
        mock_vm = MagicMock()
        mock_vm.available = int(4 * 1024**3)
        with patch("src.validators.psutil.virtual_memory", return_value=mock_vm):
            validate_memory(3.0)

    def test_fails_when_insufficient_memory(self) -> None:
        mock_vm = MagicMock()
        mock_vm.available = int(1 * 1024**3)
        with (
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_memory()
        assert exc_info.value.stage == "memory"
        assert "不足" in str(exc_info.value)

    def test_passes_with_custom_requirement(self) -> None:
        mock_vm = MagicMock()
        mock_vm.available = int(1.5 * 1024**3)
        with patch("src.validators.psutil.virtual_memory", return_value=mock_vm):
            validate_memory(requirement_gb=1.0)


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------


class TestValidationResult:
    """ValidationResult 数据类测试。"""

    def test_is_valid_when_no_errors(self) -> None:
        result = ValidationResult()
        assert result.is_valid is True

    def test_is_valid_false_with_errors(self) -> None:
        err = ValidationError("test error", stage="test")
        result = ValidationResult([err])
        assert result.is_valid is False

    def test_errors_list_empty_by_default(self) -> None:
        result = ValidationResult()
        assert result.errors == []


# ---------------------------------------------------------------------------
# validate_all
# ---------------------------------------------------------------------------


class TestValidateAll:
    """validate_all 批量校验测试：全部通过 + 多项失败收集。"""

    def _make_config(self) -> AppConfig:
        return AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="models/asr/test-model"),
            translation=TranslationConfig(engine="nllb"),
            tts=TTSConfig(engine="edge-tts", speed=1.0),
        )

    def test_all_pass(self, tmp_path: Path) -> None:
        config = self._make_config()
        video = tmp_path / "test.mp4"
        video.touch()

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.stdout = "ffmpeg version 6.0\n"
        mock_ffprobe = MagicMock()
        mock_ffprobe.returncode = 0
        mock_ffprobe.stdout = "120.0\n"
        mock_vm = MagicMock()
        mock_vm.available = int(8 * 1024**3)

        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", side_effect=[mock_ffmpeg, mock_ffprobe]),
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            patch("src.validators.Path.exists", return_value=True),
            patch("src.validators.Path.is_dir", return_value=True),
        ):
            result = validate_all(config, video, tmp_path)
        assert result.is_valid is True
        assert result.errors == []

    def test_collects_multiple_failures(self, tmp_path: Path) -> None:
        config = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path=""),
            translation=TranslationConfig(engine="glm", api_key=""),
            tts=TTSConfig(engine="cosyvoice", model_path="", speed=1.0),
        )
        video = tmp_path / "test.wmv"

        with (
            patch("src.validators.shutil.which", return_value=None),
            patch("src.validators.psutil.virtual_memory") as mock_vm,
        ):
            mock_vm.return_value.available = int(0.5 * 1024**3)
            result = validate_all(config, video, tmp_path)

        assert result.is_valid is False
        stages = {e.stage for e in result.errors}
        assert "ffmpeg" in stages
        assert "asr" in stages
        assert "translation" in stages
        assert "tts" in stages
        assert "video" in stages
        assert "memory" in stages

    def test_single_failure_does_not_block_others(self, tmp_path: Path) -> None:
        config = self._make_config()
        video = tmp_path / "test.mp4"
        video.touch()

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.stdout = "ffmpeg version 6.0\n"
        mock_ffprobe = MagicMock()
        mock_ffprobe.returncode = 0
        mock_ffprobe.stdout = "120.0\n"
        mock_vm = MagicMock()
        mock_vm.available = int(0.5 * 1024**3)

        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", side_effect=[mock_ffmpeg, mock_ffprobe]),
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            patch("src.validators.Path.exists", return_value=True),
            patch("src.validators.Path.is_dir", return_value=True),
        ):
            result = validate_all(config, video, tmp_path)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].stage == "memory"


# ---------------------------------------------------------------------------
# validate_config_only
# ---------------------------------------------------------------------------


class TestValidateConfigOnly:
    """validate_config_only 测试：仅配置项校验，不含视频相关检查。"""

    def _make_config(self) -> AppConfig:
        return AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="models/asr/test-model"),
            translation=TranslationConfig(engine="nllb"),
            tts=TTSConfig(engine="edge-tts", speed=1.0),
        )

    def test_all_pass(self) -> None:
        config = self._make_config()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.stdout = "ffmpeg version 6.0\n"
        mock_vm = MagicMock()
        mock_vm.available = int(8 * 1024**3)

        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_ffmpeg),
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            patch("src.validators.Path.exists", return_value=True),
            patch("src.validators.Path.is_dir", return_value=True),
        ):
            result = validate_config_only(config)
        assert result.is_valid is True
        assert result.errors == []

    def test_collects_multiple_config_failures(self) -> None:
        config = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path=""),
            translation=TranslationConfig(engine="glm", api_key=""),
            tts=TTSConfig(engine="cosyvoice", model_path="", speed=1.0),
        )
        with (
            patch("src.validators.shutil.which", return_value=None),
            patch("src.validators.psutil.virtual_memory") as mock_vm,
        ):
            mock_vm.return_value.available = int(0.5 * 1024**3)
            result = validate_config_only(config)

        assert result.is_valid is False
        stages = {e.stage for e in result.errors}
        assert "ffmpeg" in stages
        assert "asr" in stages
        assert "translation" in stages
        assert "tts" in stages
        assert "memory" in stages
        # validate_config_only 不应包含视频相关 stage
        assert "video" not in stages

    def test_no_video_checks_included(self) -> None:
        """验证 validate_config_only 不会触发视频校验（即便传入 config 也无法触发）。"""
        config = self._make_config()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.stdout = "ffmpeg version 6.0\n"
        mock_vm = MagicMock()
        mock_vm.available = int(8 * 1024**3)

        # 如果内部错误调用了 validate_video_format/duration，
        # 它们会因为 mock 不存在而报错
        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_ffmpeg),
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            patch("src.validators.Path.exists", return_value=True),
            patch("src.validators.Path.is_dir", return_value=True),
        ):
            result = validate_config_only(config)
        assert result.is_valid is True

    def test_single_config_failure_does_not_block_others(self) -> None:
        config = self._make_config()
        mock_ffmpeg = MagicMock()
        mock_ffmpeg.stdout = "ffmpeg version 6.0\n"
        mock_vm = MagicMock()
        mock_vm.available = int(0.5 * 1024**3)  # 仅内存不足

        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch("src.validators.subprocess.run", return_value=mock_ffmpeg),
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            patch("src.validators.Path.exists", return_value=True),
            patch("src.validators.Path.is_dir", return_value=True),
        ):
            result = validate_config_only(config)

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert result.errors[0].stage == "memory"


# ---------------------------------------------------------------------------
# validate_disk_space
# ---------------------------------------------------------------------------


class _DiskUsageStub:
    """shutil.disk_usage 返回值桩（total/used/free 三字段）。"""

    def __init__(self, free: int) -> None:
        self.total = free * 10
        self.used = free * 9
        self.free = free


class TestValidateDiskSpace:
    """validate_disk_space 测试：视频大小 × 3 估算 + 可用空间比对。"""

    def test_passes_when_space_sufficient(self, tmp_path: Path) -> None:
        """视频 100MB × 3 = 300MB 需求，可用 1GB 时通过。"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x" * (100 * 1024**2))

        with patch(
            "src.validators.shutil.disk_usage",
            return_value=_DiskUsageStub(int(1 * 1024**3)),
        ):
            validate_disk_space(video, tmp_path)

    def test_fails_when_space_insufficient(self, tmp_path: Path) -> None:
        """视频 100MB × 3 = 300MB 需求，可用 100MB 时拒绝。"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x" * (100 * 1024**2))

        with (
            patch(
                "src.validators.shutil.disk_usage",
                return_value=_DiskUsageStub(int(100 * 1024**2)),
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_disk_space(video, tmp_path)

        assert exc_info.value.stage == "disk"
        assert "磁盘空间不足" in str(exc_info.value)
        assert "300MB" in str(exc_info.value)

    def test_uses_three_times_multiplier(self, tmp_path: Path) -> None:
        """恰好 3× 时通过（边界：< 用于比较，等于视为够用）。"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x" * (50 * 1024**2))  # 50MB → required 150MB

        with patch(
            "src.validators.shutil.disk_usage",
            return_value=_DiskUsageStub(int(150 * 1024**2)),
        ):
            validate_disk_space(video, tmp_path)

    def test_fails_when_video_file_missing(self, tmp_path: Path) -> None:
        """视频文件不存在时，stat() 抛 OSError 转为 ValidationError。"""
        video = tmp_path / "missing.mp4"

        with pytest.raises(ValidationError) as exc_info:
            validate_disk_space(video, tmp_path)

        assert exc_info.value.stage == "disk"
        assert "无法读取视频文件大小" in str(exc_info.value)

    def test_fails_when_disk_usage_raises_oserror(self, tmp_path: Path) -> None:
        """shutil.disk_usage 抛 OSError（如目录权限不足）时转为 ValidationError。"""
        video = tmp_path / "test.mp4"
        video.write_bytes(b"x" * 1024)

        with (
            patch(
                "src.validators.shutil.disk_usage",
                side_effect=OSError("permission denied"),
            ),
            pytest.raises(ValidationError) as exc_info,
        ):
            validate_disk_space(video, tmp_path / "nonexistent")

        assert exc_info.value.stage == "disk"
        assert "无法获取磁盘信息" in str(exc_info.value)

    def test_zero_size_video_always_passes(self, tmp_path: Path) -> None:
        """视频大小为 0 时，required=0，任何磁盘都通过（边界场景）。"""
        video = tmp_path / "empty.mp4"
        video.touch()

        with patch(
            "src.validators.shutil.disk_usage",
            return_value=_DiskUsageStub(0),
        ):
            validate_disk_space(video, tmp_path)


# ---------------------------------------------------------------------------
# validate_all — disk 集成
# ---------------------------------------------------------------------------


class TestValidateAllDiskIntegration:
    """验证磁盘校验已纳入 validate_all 批量链。"""

    def test_disk_failure_collected_in_validate_all(self, tmp_path: Path) -> None:
        """视频大小 × 3 超过可用空间时，disk 错误出现在 errors 中。"""
        config = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="models/asr/test-model"),
            translation=TranslationConfig(engine="nllb"),
            tts=TTSConfig(engine="edge-tts", speed=1.0),
        )
        video = tmp_path / "big.mp4"
        video.write_bytes(b"x" * (100 * 1024**2))  # 100MB → required 300MB

        mock_ffmpeg = MagicMock()
        mock_ffmpeg.stdout = "ffmpeg version 6.0\n"
        mock_ffprobe = MagicMock()
        mock_ffprobe.returncode = 0
        mock_ffprobe.stdout = "120.0\n"
        mock_vm = MagicMock()
        mock_vm.available = int(8 * 1024**3)

        with (
            patch("src.validators.shutil.which", return_value="/usr/bin/ffmpeg"),
            patch(
                "src.validators.subprocess.run",
                side_effect=[mock_ffmpeg, mock_ffprobe],
            ),
            patch("src.validators.psutil.virtual_memory", return_value=mock_vm),
            patch("src.validators.Path.exists", return_value=True),
            patch("src.validators.Path.is_dir", return_value=True),
            patch(
                "src.validators.shutil.disk_usage",
                return_value=_DiskUsageStub(int(50 * 1024**2)),  # 仅 50MB 可用
            ),
        ):
            result = validate_all(config, video, tmp_path)

        assert result.is_valid is False
        stages = {e.stage for e in result.errors}
        assert "disk" in stages
