from pathlib import Path

import pytest

from src.config import get_preset, save_config
from src.exceptions import ConfigError
from src.scheme_manager import SchemeManager


@pytest.fixture
def schemes_dir(tmp_path: Path) -> Path:
    d = tmp_path / "schemes"
    d.mkdir()
    return d


@pytest.fixture
def manager(schemes_dir: Path) -> SchemeManager:
    return SchemeManager(schemes_dir)


class TestSchemeManagerSaveAndLoad:
    def test_save_creates_yaml_file(self, manager: SchemeManager, schemes_dir: Path) -> None:
        config = get_preset("high_quality")
        manager.save_scheme("my_scheme", config)

        assert (schemes_dir / "my_scheme.yaml").exists()

    def test_load_returns_saved_config(self, manager: SchemeManager) -> None:
        config = get_preset("fast")
        manager.save_scheme("fast_scheme", config)

        loaded = manager.load_scheme("fast_scheme")
        assert loaded.asr.engine == "mlx-whisper"
        assert loaded.translation.engine == "deepseek"

    def test_load_nonexistent_raises(self, manager: SchemeManager) -> None:
        with pytest.raises(ConfigError, match="方案不存在"):
            manager.load_scheme("no_such_scheme")

    def test_save_overwrites_existing(self, manager: SchemeManager) -> None:
        config1 = get_preset("high_quality")
        config2 = get_preset("offline")
        manager.save_scheme("test", config1)
        manager.save_scheme("test", config2)

        loaded = manager.load_scheme("test")
        assert loaded.translation.engine == "nllb"

    def test_save_strips_api_key(self, manager: SchemeManager) -> None:
        config = get_preset("high_quality")
        config.translation.api_key = "secret-key-123"
        manager.save_scheme("safe_scheme", config)

        loaded = manager.load_scheme("safe_scheme")
        assert loaded.translation.api_key == ""


class TestSchemeManagerList:
    def test_list_empty(self, manager: SchemeManager) -> None:
        assert manager.list_schemes() == []

    def test_list_returns_scheme_names(self, manager: SchemeManager) -> None:
        manager.save_scheme("alpha", get_preset("high_quality"))
        manager.save_scheme("beta", get_preset("fast"))

        names = manager.list_schemes()
        assert sorted(names) == ["alpha", "beta"]

    def test_list_ignores_non_yaml(self, manager: SchemeManager, schemes_dir: Path) -> None:
        (schemes_dir / "readme.txt").write_text("not a scheme")
        manager.save_scheme("real", get_preset("high_quality"))

        assert manager.list_schemes() == ["real"]


class TestSchemeManagerDelete:
    def test_delete_removes_file(self, manager: SchemeManager, schemes_dir: Path) -> None:
        manager.save_scheme("to_delete", get_preset("high_quality"))
        manager.delete_scheme("to_delete")

        assert not (schemes_dir / "to_delete.yaml").exists()
        assert manager.list_schemes() == []

    def test_delete_nonexistent_raises(self, manager: SchemeManager) -> None:
        with pytest.raises(ConfigError, match="方案不存在"):
            manager.delete_scheme("ghost")


class TestSchemeManagerExport:
    def test_export_copies_file(self, manager: SchemeManager, tmp_path: Path) -> None:
        manager.save_scheme("exportable", get_preset("balanced"))
        target = tmp_path / "exported.yaml"

        manager.export_scheme("exportable", target)

        assert target.exists()

    def test_export_nonexistent_raises(self, manager: SchemeManager, tmp_path: Path) -> None:
        target = tmp_path / "out.yaml"
        with pytest.raises(ConfigError, match="方案不存在"):
            manager.export_scheme("ghost", target)

    def test_export_strips_api_key(self, manager: SchemeManager, tmp_path: Path) -> None:
        config = get_preset("high_quality")
        config.translation.api_key = "top-secret"
        manager.save_scheme("leaky", config)
        target = tmp_path / "leaked.yaml"

        manager.export_scheme("leaky", target)

        from src.config import load_config as load_yaml

        exported = load_yaml(target)
        assert exported.translation.api_key == ""


class TestSchemeManagerImport:
    def test_import_valid_yaml(self, manager: SchemeManager, tmp_path: Path) -> None:
        config = get_preset("fast")
        config.translation.api_key = "should-be-stripped"
        src = tmp_path / "incoming.yaml"
        save_config(config, src)

        manager.import_scheme(src, "imported")

        loaded = manager.load_scheme("imported")
        assert loaded.translation.engine == "deepseek"
        assert loaded.translation.api_key == ""

    def test_import_invalid_yaml_raises(self, manager: SchemeManager, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(":: not valid yaml {{{", encoding="utf-8")

        with pytest.raises(ConfigError):
            manager.import_scheme(bad, "bad_scheme")

    def test_import_nonexistent_source_raises(self, manager: SchemeManager, tmp_path: Path) -> None:
        src = tmp_path / "missing.yaml"
        with pytest.raises(ConfigError):
            manager.import_scheme(src, "missing")


class TestSchemeManagerAutoCreateDir:
    def test_auto_creates_directory(self, tmp_path: Path) -> None:
        schemes_dir = tmp_path / "new_dir" / "schemes"
        assert not schemes_dir.exists()

        SchemeManager(schemes_dir)
        assert schemes_dir.exists()
