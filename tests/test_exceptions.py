from src.exceptions import ConfigError, PipelineError, ValidationError, VideoTranslatorError


class TestVideoTranslatorError:
    def test_basic_message(self) -> None:
        err = VideoTranslatorError("something went wrong")
        assert str(err) == "something went wrong"
        assert err.stage == ""
        assert err.suggestion == ""

    def test_with_stage_and_suggestion(self) -> None:
        err = VideoTranslatorError("error", stage="ASR", suggestion="检查模型路径")
        assert err.stage == "ASR"
        assert err.suggestion == "检查模型路径"


class TestConfigError:
    def test_is_subclass(self) -> None:
        assert issubclass(ConfigError, VideoTranslatorError)

    def test_create(self) -> None:
        err = ConfigError("配置文件格式错误", stage="config", suggestion="检查 YAML 缩进")
        assert isinstance(err, VideoTranslatorError)
        assert err.suggestion == "检查 YAML 缩进"


class TestValidationError:
    def test_is_subclass(self) -> None:
        assert issubclass(ValidationError, VideoTranslatorError)


class TestPipelineError:
    def test_is_subclass(self) -> None:
        assert issubclass(PipelineError, VideoTranslatorError)

    def test_with_cause(self) -> None:
        err = PipelineError("模型加载失败", stage="TTS", suggestion="尝试 Edge-TTS")
        assert err.stage == "TTS"
