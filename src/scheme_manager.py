from pathlib import Path

from src.config import AppConfig, load_config, save_config
from src.exceptions import ConfigError


class SchemeManager:
    def __init__(self, schemes_dir: Path) -> None:
        self._dir = schemes_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def _scheme_path(self, name: str) -> Path:
        return self._dir / f"{name}.yaml"

    @staticmethod
    def _strip_api_key(config: AppConfig) -> AppConfig:
        safe = config.model_copy(deep=True)
        safe.translation.api_key = ""
        return safe

    def save_scheme(self, name: str, config: AppConfig) -> None:
        save_config(self._strip_api_key(config), self._scheme_path(name))

    def list_schemes(self) -> list[str]:
        return sorted(p.stem for p in self._dir.glob("*.yaml"))

    def load_scheme(self, name: str) -> AppConfig:
        path = self._scheme_path(name)
        if not path.exists():
            raise ConfigError(
                f"方案不存在: '{name}'",
                stage="config",
                suggestion="请先保存方案或检查方案名称",
            )
        return load_config(path)

    def delete_scheme(self, name: str) -> None:
        path = self._scheme_path(name)
        if not path.exists():
            raise ConfigError(
                f"方案不存在: '{name}'",
                stage="config",
                suggestion="方案可能已被删除",
            )
        path.unlink()

    def export_scheme(self, name: str, target_path: Path) -> None:
        config = self.load_scheme(name)
        save_config(self._strip_api_key(config), target_path)

    def import_scheme(self, source_path: Path, name: str) -> None:
        if not source_path.exists():
            raise ConfigError(
                f"源文件不存在: {source_path}",
                stage="config",
                suggestion="请检查文件路径是否正确",
            )
        try:
            config = load_config(source_path)
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"导入方案失败: {e}",
                stage="config",
                suggestion="请确保文件是有效的 YAML 配置文件",
            ) from e
        save_config(self._strip_api_key(config), self._scheme_path(name))
