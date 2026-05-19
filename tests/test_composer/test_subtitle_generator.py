from pathlib import Path

from src.composer.subtitle_generator import SubtitleGenerator
from src.models import SubtitleSegment


class TestFormatTimestamp:
    def test_zero(self) -> None:
        assert SubtitleGenerator._format_timestamp(0.0) == "00:00:00,000"

    def test_seconds_and_millis(self) -> None:
        assert SubtitleGenerator._format_timestamp(1.5) == "00:00:01,500"

    def test_minutes(self) -> None:
        assert SubtitleGenerator._format_timestamp(65.123) == "00:01:05,123"

    def test_hours(self) -> None:
        assert SubtitleGenerator._format_timestamp(3661.0) == "01:01:01,000"

    def test_rounds_millis(self) -> None:
        assert SubtitleGenerator._format_timestamp(1.9999) == "00:00:02,000"

    def test_exact_millis(self) -> None:
        assert SubtitleGenerator._format_timestamp(3.007) == "00:00:03,007"

    def test_large_value(self) -> None:
        result = SubtitleGenerator._format_timestamp(600.5)
        assert result == "00:10:00,500"


class TestGenerateSrt:
    def test_basic_generation(self, tmp_path: Path) -> None:
        segments = [
            SubtitleSegment(
                index=0, start_time=1.0, end_time=3.5,
                source_text="Hello world", translated_text="你好世界",
            ),
            SubtitleSegment(
                index=1, start_time=4.0, end_time=7.5,
                source_text="This is a test", translated_text="这是一个测试",
            ),
        ]
        gen = SubtitleGenerator()
        output = tmp_path / "test.srt"
        result = gen.generate_srt(segments, output)

        assert result == output
        content = output.read_text(encoding="utf-8")
        assert "1\n00:00:01,000 --> 00:00:03,500\n你好世界" in content
        assert "2\n00:00:04,000 --> 00:00:07,500\n这是一个测试" in content

    def test_index_is_one_based(self, tmp_path: Path) -> None:
        segments = [
            SubtitleSegment(
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hi", translated_text="嗨",
            ),
        ]
        gen = SubtitleGenerator()
        output = tmp_path / "test.srt"
        gen.generate_srt(segments, output)

        content = output.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        assert lines[0] == "1"

    def test_skips_empty_translated_text(self, tmp_path: Path) -> None:
        segments = [
            SubtitleSegment(
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hello", translated_text="你好",
            ),
            SubtitleSegment(
                index=1, start_time=1.0, end_time=2.0,
                source_text="Untranslated", translated_text="",
            ),
            SubtitleSegment(
                index=2, start_time=2.0, end_time=3.0,
                source_text="World", translated_text="世界",
            ),
        ]
        gen = SubtitleGenerator()
        output = tmp_path / "test.srt"
        gen.generate_srt(segments, output)

        content = output.read_text(encoding="utf-8")
        assert "1\n" in content
        assert "2\n" in content
        assert "Untranslated" not in content
        assert "世界" in content

    def test_empty_segments_produces_empty_file(self, tmp_path: Path) -> None:
        gen = SubtitleGenerator()
        output = tmp_path / "test.srt"
        gen.generate_srt([], output)

        content = output.read_text(encoding="utf-8")
        assert content == ""

    def test_all_empty_translated_produces_empty_file(self, tmp_path: Path) -> None:
        segments = [
            SubtitleSegment(
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hello", translated_text="",
            ),
        ]
        gen = SubtitleGenerator()
        output = tmp_path / "test.srt"
        gen.generate_srt(segments, output)

        content = output.read_text(encoding="utf-8")
        assert content == ""

    def test_utf8_encoding(self, tmp_path: Path) -> None:
        segments = [
            SubtitleSegment(
                index=0, start_time=0.0, end_time=1.0,
                source_text="Test", translated_text="测试中文编码",
            ),
        ]
        gen = SubtitleGenerator()
        output = tmp_path / "test.srt"
        gen.generate_srt(segments, output)

        content = output.read_text(encoding="utf-8")
        assert "测试中文编码" in content
