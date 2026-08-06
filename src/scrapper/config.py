import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from scrapper.models import Config

ENV_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


class MissingEnvVar(RuntimeError):
    """Konfiguracja odwołuje się do zmiennej środowiskowej, której nie ma."""


def _expand(value, env: Mapping[str, str]):
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            name = match.group(1)
            if name not in env:
                raise MissingEnvVar(f"Brak zmiennej środowiskowej: {name}")
            return env[name]

        return ENV_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _expand(v, env) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v, env) for v in value]
    return value


def load_config(path: Path, env: Mapping[str, str]) -> Config:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Config(**_expand(raw, env))
