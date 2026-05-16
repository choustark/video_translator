class VideoTranslatorError(Exception):
    def __init__(self, message: str, stage: str = "", suggestion: str = "") -> None:
        self.stage = stage
        self.suggestion = suggestion
        super().__init__(message)


class ConfigError(VideoTranslatorError):
    pass


class ValidationError(VideoTranslatorError):
    pass


class PipelineError(VideoTranslatorError):
    pass
