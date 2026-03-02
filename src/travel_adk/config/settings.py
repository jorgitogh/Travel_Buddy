from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import find_dotenv, load_dotenv


@lru_cache(maxsize=1)
def load_environment() -> None:
    """
    Carga variables desde .env una sola vez sin sobrescribir el entorno actual.
    """
    project_env = Path(__file__).resolve().parents[3] / ".env"
    if project_env.exists():
        load_dotenv(project_env, override=False)
        return

    discovered = find_dotenv(usecwd=True)
    if discovered:
        load_dotenv(discovered, override=False)
