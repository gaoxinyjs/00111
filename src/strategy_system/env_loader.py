from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv


@dataclass(frozen=True)
class StrategyEnvKeys:
    """Holds sensitive credentials loaded from the legacy .env file."""

    okx_api_key: Optional[str]
    okx_secret_key: Optional[str]
    okx_passphrase: Optional[str]
    deepseek_api_key: Optional[str]

    def as_dict(self) -> Dict[str, Optional[str]]:
        return asdict(self)


_ENV_LOADED = False


def _default_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def load_env_keys(env_path: Optional[Path | str] = None, force_reload: bool = False) -> StrategyEnvKeys:
    """
    Loads API credentials from the original project .env file.
    """

    global _ENV_LOADED
    env_file = Path(env_path) if env_path else _default_env_path()

    if (force_reload or not _ENV_LOADED) and env_file.exists():
        load_dotenv(env_file, override=False)
        _ENV_LOADED = True

    return StrategyEnvKeys(
        okx_api_key=os.getenv("OKX_API_KEY"),
        okx_secret_key=os.getenv("OKX_SECRET_KEY"),
        okx_passphrase=os.getenv("OKX_PASSPHRASE"),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY"),
    )
