from __future__ import annotations

import logging
from typing import Callable

import httpx
from tenacity import (
    RetryCallState,
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import CHARS_PER_SEC, TranslationConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.translation.base import TranslationProvider

logger = logging.getLogger("video_translator")

_API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"

_TRANSLATION_SYSTEM_PROMPT = (
    "你是一个专业的英译中翻译，专门用于视频配音字幕。\n"
    "翻译规则：\n"
    "1. 使用口语化的中文，适合朗读配音，避免书面语或生硬直译\n"
    "2. 译文长度应与原文相近——中文口语通常比英文短，尽量控制在原文长度的 80%-120%\n"
    "3. 保持原文的含义、语气和情感\n"
    "4. 只输出翻译结果，不要添加解释、注释、序号或引号"
)


class GLMProvider(TranslationProvider):
    def __init__(self, config: TranslationConfig) -> None:
        super().__init__(config)
        self._client: httpx.Client | None = None
        # Retry progress state — set by translate() before each segment
        self._progress_callback: Callable[[ProgressEvent], None] | None = None
        self._current_segment_idx: int = 0
        self._total_segments: int = 0

    @property
    def client(self) -> httpx.Client:
        """懒加载的 httpx.Client 实例，超时 30 秒。"""
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
        return self._client

    def translate(
        self,
        segments: list[SubtitleSegment],
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        """逐段翻译字幕，通过 httpx 调用 GLM API，使用 tenacity 进行 3 次重试。

        跳过 source_text 为空的片段。每翻译一段后通过 progress_callback 上报进度，
        重试时也会上报重试状态。

        Args:
            segments: 待翻译的字幕片段列表。
            progress_callback: 翻译进度回调，接收 ProgressEvent。

        Returns:
            翻译完成后的字幕片段列表，translated_text 已填充。

        Raises:
            PipelineError: API 调用失败（重试耗尽、4xx 错误、返回格式异常等）。
        """
        processable = [seg for seg in segments if seg.source_text.strip()]
        processable_total = len(processable)
        if not processable:
            return segments

        self._progress_callback = progress_callback
        self._total_segments = processable_total

        processed = 0
        for i, seg in enumerate(segments):
            if not seg.source_text.strip():
                continue
            self._current_segment_idx = processed
            processed += 1
            seg.translated_text = self._translate_segment(
                seg.source_text,
                seg.end_time - seg.start_time,
            )
            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        stage="翻译",
                        progress=processed / processable_total,
                        message=f"正在翻译 {processed}/{processable_total}",
                    )
                )

        skipped = len(segments) - processable_total
        summary = f"翻译完成 {processable_total}/{processable_total}"
        if skipped:
            summary += f"（跳过 {skipped} 段）"
        if progress_callback:
            progress_callback(
                ProgressEvent(
                    stage="翻译",
                    progress=1.0,
                    message=summary,
                )
            )

        return segments

    def _translate_segment(self, text: str, duration: float = 0.0) -> str:
        try:
            return self._do_api_call(text, duration)
        except RetryError as e:
            raise PipelineError(
                f"翻译 API 调用失败（已重试 3 次）: {e.last_attempt.exception()}",
                stage="翻译",
                suggestion="请检查网络连接或稍后重试",
            ) from e
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(
                f"翻译失败: {e}",
                stage="翻译",
                suggestion="请检查 API Key 和网络连接",
            ) from e

    def _retry_before_sleep(self, retry_state: RetryCallState) -> None:
        callback = self._progress_callback
        if callback is None:
            return
        attempt = retry_state.attempt_number
        callback(
            ProgressEvent(
                stage="翻译",
                progress=(self._current_segment_idx + 1) / self._total_segments,
                message=f"正在重试 ({attempt}/3)...",
            )
        )

    def _do_api_call(self, text: str, duration: float = 0.0) -> str:
        retrying = Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=1, max=10),
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.HTTPStatusError),
            ),
            before_sleep=self._retry_before_sleep,
        )
        return retrying(self._execute_api_request, text, duration)

    def _execute_api_request(self, text: str, duration: float = 0.0) -> str:
        user_content = text
        if duration > 0:
            target_chars = round(duration * CHARS_PER_SEC)
            user_content = (
                f"原文朗读时长约 {duration:.1f} 秒，"
                f"中文口语语速约 {CHARS_PER_SEC:.0f} 字/秒，"
                f"请控制译文在 {target_chars} 字左右。\n\n{text}"
            )
        response = self.client.post(
            _API_URL,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": [
                    {"role": "system", "content": _TRANSLATION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.3,
            },
        )

        if 400 <= response.status_code < 500:
            error_body = response.text[:200]
            logger.error(
                "翻译 | API 4xx | status=%d | body=%s",
                response.status_code,
                error_body,
            )
            raise PipelineError(
                f"翻译 API 请求失败 ({response.status_code}): {error_body}",
                stage="翻译",
                suggestion="请检查 API Key 是否正确",
            )

        response.raise_for_status()
        result = response.json()

        try:
            content: str = result["choices"][0]["message"]["content"]
            return content
        except (KeyError, IndexError) as e:
            raise PipelineError(
                f"翻译 API 返回格式异常: {e}",
                stage="翻译",
                suggestion="请检查 API 服务是否正常",
            ) from e
