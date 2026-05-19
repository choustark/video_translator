from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from src.config import TranslationConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.translation.glm_provider import GLMProvider


def _make_config(**overrides) -> TranslationConfig:
    defaults = {"engine": "glm", "api_key": "test-api-key"}
    defaults.update(overrides)
    return TranslationConfig(**defaults)


def _make_segments(*texts: str) -> list[SubtitleSegment]:
    return [
        SubtitleSegment(index=i, start_time=float(i), end_time=float(i + 1), source_text=t)
        for i, t in enumerate(texts)
    ]


def _mock_response(status_code: int = 200, content: str = "你好世界") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status.return_value = None
    resp.json.return_value = {
        "choices": [{"message": {"content": content}}],
    }
    resp.text = content
    return resp


def _make_500_response() -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 500
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Server Error", request=MagicMock(), response=resp,
    )
    return resp


def _make_provider(config: TranslationConfig, mock_client: MagicMock) -> GLMProvider:
    provider = GLMProvider(config)
    provider._client = mock_client
    return provider


class TestGLMProviderTranslate:
    def test_translates_single_segment(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _mock_response(content="你好世界")
        provider = _make_provider(_make_config(), mock_client)
        result = provider.translate(_make_segments("Hello world"))
        assert result[0].translated_text == "你好世界"

    def test_translates_multiple_segments(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            _mock_response(content="你好"),
            _mock_response(content="再见"),
        ]
        provider = _make_provider(_make_config(), mock_client)
        result = provider.translate(_make_segments("Hello", "Goodbye"))
        assert result[0].translated_text == "你好"
        assert result[1].translated_text == "再见"

    def test_skips_empty_source_text(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            _mock_response(content="你好"),
            _mock_response(content="再见"),
        ]
        provider = _make_provider(_make_config(), mock_client)
        result = provider.translate(_make_segments("Hello", "   ", "Goodbye"))
        assert result[0].translated_text == "你好"
        assert result[1].translated_text == ""
        assert result[2].translated_text == "再见"
        assert mock_client.post.call_count == 2

    def test_empty_segments_list(self) -> None:
        mock_client = MagicMock()
        provider = _make_provider(_make_config(), mock_client)
        result = provider.translate([])
        assert result == []
        mock_client.post.assert_not_called()

    def test_progress_callback_called(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            _mock_response(content="你好"),
            _mock_response(content="世界"),
        ]
        callbacks: list[ProgressEvent] = []
        provider = _make_provider(_make_config(), mock_client)
        provider.translate(_make_segments("Hello", "World"), callbacks.append)
        # 2 per-segment events + 1 final "翻译完成"
        assert len(callbacks) == 3
        assert callbacks[0].progress == pytest.approx(0.5)
        assert callbacks[0].message == "正在翻译 1/2"
        assert callbacks[1].progress == pytest.approx(1.0)
        assert callbacks[1].message == "正在翻译 2/2"
        assert callbacks[2].progress == 1.0
        assert callbacks[2].message == "翻译完成 2/2"

    def test_no_progress_callback_when_none(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _mock_response()
        provider = _make_provider(_make_config(), mock_client)
        result = provider.translate(_make_segments("Hello"), None)
        assert result[0].translated_text == "你好世界"

    def test_sends_correct_api_request(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _mock_response()
        provider = _make_provider(_make_config(api_key="my-secret-key"), mock_client)
        provider.translate(_make_segments("Hello world"))
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Bearer my-secret-key"
        body = call_kwargs.kwargs["json"]
        assert body["model"] == "glm-4-flash"
        assert body["temperature"] == 0.3
        assert body["messages"][1]["content"] == "Hello world"

    def test_empty_last_segment_progress_reaches_one(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _mock_response(content="你好")
        callbacks: list[ProgressEvent] = []
        provider = _make_provider(_make_config(), mock_client)
        provider.translate(_make_segments("Hello", "   "), callbacks.append)
        last = callbacks[-1]
        assert last.progress == 1.0
        assert "翻译完成" in last.message


class TestGLMProviderErrorHandling:
    def test_4xx_raises_pipeline_error(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.text = "Unauthorized"
        mock_client = MagicMock()
        mock_client.post.return_value = resp
        provider = _make_provider(_make_config(), mock_client)
        with pytest.raises(PipelineError, match="API 请求失败") as exc_info:
            provider.translate(_make_segments("Hello"))
        assert exc_info.value.stage == "翻译"
        assert "API Key" in exc_info.value.suggestion

    def test_5xx_retries_exhausted_raises_pipeline_error(self) -> None:
        mock_client = MagicMock()
        mock_client.post.return_value = _make_500_response()
        provider = _make_provider(_make_config(), mock_client)
        with pytest.raises(PipelineError, match="已重试 3 次") as exc_info:
            provider.translate(_make_segments("Hello"))
        assert exc_info.value.stage == "翻译"
        assert mock_client.post.call_count == 3

    def test_5xx_retries_then_succeeds(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            _make_500_response(),
            _make_500_response(),
            _mock_response(content="你好"),
        ]
        provider = _make_provider(_make_config(), mock_client)
        result = provider.translate(_make_segments("Hello"))
        assert result[0].translated_text == "你好"
        assert mock_client.post.call_count == 3

    def test_timeout_raises_pipeline_error(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.TimeoutException("timeout")
        provider = _make_provider(_make_config(), mock_client)
        with pytest.raises(PipelineError, match="已重试 3 次") as exc_info:
            provider.translate(_make_segments("Hello"))
        assert exc_info.value.stage == "翻译"

    def test_malformed_response_raises_pipeline_error(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {}
        mock_client = MagicMock()
        mock_client.post.return_value = resp
        provider = _make_provider(_make_config(), mock_client)
        with pytest.raises(PipelineError, match="返回格式异常") as exc_info:
            provider.translate(_make_segments("Hello"))
        assert exc_info.value.stage == "翻译"


class TestGLMProviderRetryProgress:
    def test_retry_progress_reported_on_5xx(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            _make_500_response(),
            _make_500_response(),
            _mock_response(content="你好"),
        ]
        callbacks: list[ProgressEvent] = []
        provider = _make_provider(_make_config(), mock_client)
        provider.translate(_make_segments("Hello"), callbacks.append)
        retry_events = [e for e in callbacks if "重试" in e.message]
        assert len(retry_events) == 2
        assert "1/3" in retry_events[0].message
        assert "2/3" in retry_events[1].message

    def test_retry_progress_reported_on_timeout(self) -> None:
        mock_client = MagicMock()
        mock_client.post.side_effect = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            _mock_response(content="你好"),
        ]
        callbacks: list[ProgressEvent] = []
        provider = _make_provider(_make_config(), mock_client)
        provider.translate(_make_segments("Hello"), callbacks.append)
        retry_events = [e for e in callbacks if "重试" in e.message]
        assert len(retry_events) == 2


class TestGLMProviderSecurity:
    def test_api_key_not_in_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.text = "Auth failed"
        mock_client = MagicMock()
        mock_client.post.return_value = resp
        provider = _make_provider(_make_config(api_key="super-secret-key-12345"), mock_client)

        with caplog.at_level(logging.ERROR, logger="video_translator"):
            try:
                provider.translate(_make_segments("Hello"))
            except PipelineError:
                pass

        for record in caplog.records:
            assert "super-secret-key-12345" not in record.message
