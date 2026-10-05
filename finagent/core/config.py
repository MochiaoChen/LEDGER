"""运行配置：全部来自环境变量（或 .env），便于评审在指定环境复现。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    runs_dir: str = os.getenv("RUNS_DIR", str(PROJECT_ROOT / "runs"))

    def public(self) -> dict:
        """写入 manifest 的配置。"""
        return asdict(self)


def get_settings(**overrides) -> Settings:
    base = Settings()
    if not overrides:
        return base
    data = asdict(base)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**data)
