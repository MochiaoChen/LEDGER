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
    # OpenAI 兼容接口：DeepSeek / 通义千问(DashScope) / 智谱 / 本地 vLLM 均可
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
    llm_model: str = os.getenv("LLM_MODEL", "deepseek-chat")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    # live: 调用模型并写缓存；replay: 只读缓存（离线复现）；off: 不使用 LLM，仅走规则通道
    llm_mode: str = os.getenv("LLM_MODE", "live")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0"))
    llm_seed: int = int(os.getenv("LLM_SEED", "42"))
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "120"))
    cache_dir: str = os.getenv("LLM_CACHE_DIR", str(PROJECT_ROOT / ".cache" / "llm"))
    runs_dir: str = os.getenv("RUNS_DIR", str(PROJECT_ROOT / "runs"))

    def public(self) -> dict:
        """写入 manifest 的配置（隐去密钥）。"""
        data = asdict(self)
        data["llm_api_key"] = "***" if self.llm_api_key else ""
        return data

    @property
    def llm_enabled(self) -> bool:
        if self.llm_mode == "off":
            return False
        if self.llm_mode == "replay":
            return True
        return bool(self.llm_api_key)


def get_settings(**overrides) -> Settings:
    base = Settings()
    if not overrides:
        return base
    data = asdict(base)
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Settings(**data)
