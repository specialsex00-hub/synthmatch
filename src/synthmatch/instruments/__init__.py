"""楽器の設定ファイル（TOML）から Instrument を作る。"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from .base import Instrument, Preset

__all__ = ["Instrument", "Preset", "load_instrument", "slugify"]


def _types():
    from .demo import DemoInstrument
    from .hardware import HardwareInstrument
    from .vst import VSTInstrument

    return {"demo": DemoInstrument, "hardware": HardwareInstrument, "vst": VSTInstrument}


def load_instrument(path: str | Path) -> Instrument:
    path = Path(path)
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    kind = config.get("type", "")
    types = _types()
    if kind not in types:
        raise ValueError(f"{path}: type = '{kind}' は未対応です（{', '.join(types)}）")
    inst = types[kind](config, path.parent)
    inst.name = config.get("name", inst.name)
    return inst


def slugify(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", name).strip("_").lower() or "instrument"
