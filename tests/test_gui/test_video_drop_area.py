from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import Signal

from src.gui.video_drop_area import SUPPORTED_FORMATS, VideoDropArea

# ==================== 辅助函数 ====================


def _make_mime_with_urls(file_path: str) -> MagicMock:
    """创建 mock QMimeData，hasUrls() 返回 True，urls() 返回指定文件"""
    mime = MagicMock()
    mime.hasUrls.return_value = True
    url_mock = MagicMock()
    url_mock.toLocalFile.return_value = file_path
    mime.urls.return_value = [url_mock]
    return mime


def _make_mime_without_urls() -> MagicMock:
    """创建 mock QMimeData，hasUrls() 返回 False"""
    mime = MagicMock()
    mime.hasUrls.return_value = False
    return mime


def _make_mock_drag_enter(file_path: str) -> MagicMock:
    """创建 mock QDragEnterEvent，携带文件 URL"""
    event = MagicMock()
    event.mimeData.return_value = _make_mime_with_urls(file_path)
    return event


def _make_mock_drop(file_path: str) -> MagicMock:
    """创建 mock QDropEvent，携带文件 URL"""
    event = MagicMock()
    event.mimeData.return_value = _make_mime_with_urls(file_path)
    return event


def _make_mock_drag_enter_no_urls() -> MagicMock:
    """创建 mock QDragEnterEvent，不含文件 URL"""
    event = MagicMock()
    event.mimeData.return_value = _make_mime_without_urls()
    return event


def _mock_ffprobe(duration: float) -> ExitStack:
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = f"{duration}\n"
    mock_result.stderr = ""

    stack = ExitStack()
    stack.enter_context(patch.object(Path, "is_file", return_value=True))
    stack.enter_context(patch("subprocess.run", return_value=mock_result))
    stack.enter_context(patch("shutil.which", return_value="/usr/local/bin/ffprobe"))
    return stack


# ==================== AC1: 空闲状态测试 ====================


class TestVideoDropAreaCreation:
    """组件创建和空闲状态测试"""

    def test_create_success(self, qapp) -> None:
        """组件创建成功，video_path 和 video_info 初始为 None"""
        area = VideoDropArea()
        assert area is not None
        assert area.video_path is None
        assert area.video_info is None

    def test_idle_hint_text(self, qapp) -> None:
        """空闲状态下提示文字正确"""
        area = VideoDropArea()
        assert area._hint_label.text() == "拖入视频文件到此处"

    def test_accepts_drops(self, qapp) -> None:
        """组件接受拖放"""
        area = VideoDropArea()
        assert area.acceptDrops() is True

    def test_minimum_height(self, qapp) -> None:
        area = VideoDropArea()
        assert area.minimumHeight() == 220

    def test_info_label_hidden_initially(self, qapp) -> None:
        area = VideoDropArea()
        assert area._info_label.isHidden() is True

    def test_select_file_button_exists(self, qapp) -> None:
        area = VideoDropArea()
        assert area._select_file_btn.objectName() == "textButton"
        assert area._select_file_btn.text() == "选择文件"
        assert area._select_file_btn.isHidden() is False


# ==================== AC2/AC6: 拖入悬停测试 ====================


class TestDragEnterEvent:
    """拖入事件测试"""

    def test_accepts_video_file_urls(self, qapp) -> None:
        """拖入视频文件时接受事件，进入 hover 状态"""
        area = VideoDropArea()
        event = _make_mock_drag_enter("/test/video.mp4")
        area.dragEnterEvent(event)

        event.acceptProposedAction.assert_called_once()
        assert "释放以添加视频" in area._hint_label.text()

    def test_rejects_non_file_mime(self, qapp) -> None:
        """非文件 MIME 类型直接拒绝，保持 idle 状态"""
        area = VideoDropArea()
        event = _make_mock_drag_enter_no_urls()
        area.dragEnterEvent(event)

        event.ignore.assert_called_once()
        assert area._hint_label.text() == "拖入视频文件到此处"


# ==================== AC6: 拖离恢复测试 ====================


class TestDragLeaveEvent:
    """拖离事件测试"""

    def test_leave_restores_idle_when_never_loaded(self, qapp) -> None:
        """从未加载过文件时，拖离恢复 idle 状态"""
        area = VideoDropArea()
        # 先进入 hover
        area.dragEnterEvent(_make_mock_drag_enter("/test/video.mp4"))
        assert "释放以添加视频" in area._hint_label.text()

        # 离开
        area.dragLeaveEvent(MagicMock())
        assert area._hint_label.text() == "拖入视频文件到此处"

    def test_leave_restores_loaded_after_successful_drop(self, qapp) -> None:
        """已加载文件后拖离，恢复到 loaded 状态"""
        with _mock_ffprobe(120.0):
            area = VideoDropArea()
            # 成功加载视频
            area.dropEvent(_make_mock_drop("/test/video.mp4"))
            assert area.video_path is not None

            # 再次拖入进入 hover
            area.dragEnterEvent(_make_mock_drag_enter("/test/another.mp4"))
            assert "释放以添加视频" in area._hint_label.text()

            # 离开 → 恢复到 loaded 状态（显示之前加载的文件）
            area.dragLeaveEvent(MagicMock())
            assert area._hint_label.text() == "video.mp4"
            assert area._info_label.isHidden() is False


# ==================== AC4: 格式校验测试 ====================


class TestDropEventFormatValidation:
    """格式校验测试 — 仅接受 mp4、mkv、mov、avi"""

    @pytest.mark.parametrize(
        "file_path,suffix",
        [
            ("/test/video.mp4", ".mp4"),
            ("/test/video.mkv", ".mkv"),
            ("/test/video.mov", ".mov"),
            ("/test/video.avi", ".avi"),
        ],
    )
    def test_supported_formats_in_whitelist(self, file_path, suffix) -> None:
        """支持的格式在 SUPPORTED_FORMATS 白名单中"""
        assert suffix in SUPPORTED_FORMATS

    @pytest.mark.parametrize(
        "file_path",
        [
            "/test/video.txt",
            "/test/video.jpg",
            "/test/video.png",
            "/test/video.pdf",
        ],
    )
    def test_rejects_unsupported_formats(self, qapp, file_path) -> None:
        """不支持的格式触发 error 状态"""
        area = VideoDropArea()
        area.dropEvent(_make_mock_drop(file_path))

        assert "不支持的视频格式" in area._hint_label.text()
        # 错误状态下 video_path 不变（仍为 None）
        assert area.video_path is None


# ==================== AC5: 时长校验测试 ====================


class TestDropEventDurationValidation:
    """时长校验测试 — 超过 10 分钟拒绝"""

    def test_rejects_duration_exceeds_limit(self, qapp) -> None:
        """超过 600 秒的视频触发 error 状态"""
        with _mock_ffprobe(700.0):
            area = VideoDropArea()
            area.dropEvent(_make_mock_drop("/test/video.mp4"))

            assert "视频时长超过 10 分钟" in area._hint_label.text()
            assert area.video_path is None

    def test_accepts_duration_at_limit(self, qapp) -> None:
        """恰好 600 秒的视频接受"""
        with _mock_ffprobe(600.0):
            area = VideoDropArea()
            area.dropEvent(_make_mock_drop("/test/video.mp4"))

            assert area.video_path is not None
            assert area.video_info is not None
            assert area.video_info["duration"] == "10:00"

    def test_accepts_duration_under_limit(self, qapp) -> None:
        """600 秒以内的视频正常加载"""
        with _mock_ffprobe(30.5):
            area = VideoDropArea()
            area.dropEvent(_make_mock_drop("/test/video.mp4"))

            assert area.video_path == Path("/test/video.mp4")
            assert area.video_info is not None
            assert area.video_info["duration"] == "00:30"


# ==================== AC3: 成功加载测试 ====================


class TestDropEventSuccess:
    """成功加载视频后的状态和信号测试"""

    def test_loaded_state_after_successful_drop(self, qapp) -> None:
        """成功加载后切换到 loaded 状态，显示文件信息"""
        with _mock_ffprobe(125.0):
            area = VideoDropArea()
            area.dropEvent(_make_mock_drop("/test/my_video.MKV"))

            assert area._hint_label.text() == "my_video.MKV"
            assert area._info_label.text() == "02:05 | MKV"
            assert area._info_label.isHidden() is False
            assert area.video_path == Path("/test/my_video.MKV")

    def test_video_loaded_signal_emitted(self, qapp) -> None:
        """成功加载后 video_loaded 信号 emit，携带正确路径"""
        with _mock_ffprobe(60.0):
            area = VideoDropArea()
            received: list = []
            area.video_loaded.connect(lambda p: received.append(p))

            area.dropEvent(_make_mock_drop("/test/video.mp4"))

            assert len(received) == 1
            assert received[0] == Path("/test/video.mp4")

    def test_format_uppercase_in_loaded_state(self, qapp) -> None:
        """格式后缀转为大写显示"""
        with _mock_ffprobe(10.0):
            area = VideoDropArea()
            area.dropEvent(_make_mock_drop("/test/video.MoV"))

            assert area._info_label.text() == "00:10 | MOV"

    def test_reload_replaces_previous_file(self, qapp) -> None:
        """重新拖入新文件会替换之前加载的文件"""
        with _mock_ffprobe(30.0):
            area = VideoDropArea()
            # 第一次加载
            area.dropEvent(_make_mock_drop("/test/first.mp4"))
            assert area.video_path == Path("/test/first.mp4")

            # 第二次加载 — 替换
            area.dropEvent(_make_mock_drop("/test/second.mkv"))
            assert area.video_path == Path("/test/second.mkv")
            assert area._hint_label.text() == "second.mkv"


# ==================== AC7: ffprobe 时长提取测试 ====================


class TestFfprobeDurationExtraction:
    """ffprobe 时长提取方法测试"""

    def test_parses_duration_output_correctly(self, qapp) -> None:
        """正确解析 ffprobe stdout 中的时长数字"""
        with _mock_ffprobe(123.456):
            duration = VideoDropArea._get_video_duration(Path("/test/video.mp4"))
            assert duration == 123.456

    def test_raises_when_ffprobe_not_found(self, qapp) -> None:
        """ffprobe 不可用时抛出 FileNotFoundError"""
        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="ffprobe 未找到"):
                VideoDropArea._get_video_duration(Path("/test/video.mp4"))

    def test_raises_on_nonzero_returncode(self, qapp) -> None:
        """ffprobe 返回非零退出码时抛出 RuntimeError"""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Invalid data found"

        with patch("subprocess.run", return_value=mock_result), patch(
            "shutil.which", return_value="/usr/local/bin/ffprobe"
        ):
            with pytest.raises(RuntimeError, match="ffprobe 失败"):
                VideoDropArea._get_video_duration(Path("/test/video.mp4"))

    def test_format_duration_mm_ss(self) -> None:
        """秒数转 mm:ss 格式正确"""
        assert VideoDropArea._format_duration(0) == "00:00"
        assert VideoDropArea._format_duration(65) == "01:05"
        assert VideoDropArea._format_duration(3661) == "61:01"
        assert VideoDropArea._format_duration(599.9) == "09:59"


# ==================== dropEvent 错误路径测试 ====================


class TestDropEventErrorPaths:
    """dropEvent 各种错误路径测试"""

    def test_ffprobe_unavailable_shows_error(self, qapp) -> None:
        with (
            patch.object(Path, "is_file", return_value=True),
            patch("shutil.which", return_value=None),
        ):
            area = VideoDropArea()
            area.dropEvent(_make_mock_drop("/test/video.mp4"))

            assert "ffprobe 未找到" in area._hint_label.text()
            assert area.video_path is None

    def test_drop_without_urls_ignored(self, qapp) -> None:
        """没有 URL 的 drop 事件被忽略，保持 idle"""
        area = VideoDropArea()
        event = MagicMock()
        event.mimeData.return_value = _make_mime_without_urls()
        area.dropEvent(event)

        assert area.video_path is None
        assert area._hint_label.text() == "拖入视频文件到此处"


# ==================== 信号定义测试 ====================


class TestVideoDropAreaSignalDefinition:
    """验证 Signal 在类体中正确定义（PySide6 规则）"""

    def test_video_loaded_signal_exists(self, qapp) -> None:
        assert hasattr(VideoDropArea, "video_loaded")
        assert isinstance(VideoDropArea.video_loaded, Signal)


# ==================== 文件选择测试 ====================


class TestSelectFile:
    def test_select_file_opens_dialog(self, qapp) -> None:
        area = VideoDropArea()
        with patch("src.gui.video_drop_area.QFileDialog.getOpenFileName") as mock_dialog:
            mock_dialog.return_value = ("", "")
            area._on_select_file()
            mock_dialog.assert_called_once()

    def test_select_file_cancelled_does_nothing(self, qapp) -> None:
        area = VideoDropArea()
        with (
            patch("src.gui.video_drop_area.QFileDialog.getOpenFileName", return_value=("", "")),
        ):
            area._on_select_file()
        assert area.video_path is None

    def test_select_file_valid_video_loads(self, qapp) -> None:
        area = VideoDropArea()
        with (
            patch("src.gui.video_drop_area.QFileDialog.getOpenFileName") as mock_dialog,
            patch.object(Path, "is_file", return_value=True),
            patch("shutil.which", return_value="/usr/local/bin/ffprobe"),
            patch("subprocess.run") as mock_run,
        ):
            mock_dialog.return_value = ("/test/video.mp4", "")
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "120.0\n"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            area._on_select_file()

        assert area.video_path == Path("/test/video.mp4")
        assert area._hint_label.text() == "video.mp4"

    def test_select_file_nonexistent_shows_error(self, qapp) -> None:
        area = VideoDropArea()
        with (
            patch("src.gui.video_drop_area.QFileDialog.getOpenFileName") as mock_dialog,
            patch.object(Path, "is_file", return_value=False),
        ):
            mock_dialog.return_value = ("/nonexistent/video.mp4", "")
            area._on_select_file()

        assert area.video_path is None
        assert "不存在" in area._hint_label.text()
