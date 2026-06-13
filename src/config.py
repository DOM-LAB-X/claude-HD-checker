import shutil
import sys
from pathlib import Path
from typing import List, Tuple

import yaml
from pydantic import BaseModel


class Config(BaseModel):
    timezone: str
    stores: List[str]
    zip_code: str
    schedule: dict
    delays: dict
    limits: dict
    alerts: dict
    watchlist_path: str
    db_path: str

    @property
    def between_products_sec(self) -> Tuple[float, float]:
        lo, hi = self.delays["between_products_sec"]
        return lo, hi

    @property
    def between_stores_sec(self) -> Tuple[float, float]:
        lo, hi = self.delays["between_stores_sec"]
        return lo, hi

    @property
    def max_retries_per_product(self) -> int:
        return self.limits["max_retries_per_product"]

    @property
    def schedule_times(self) -> List[str]:
        return self.schedule["times"]

    @property
    def jitter_minutes(self) -> int:
        return self.schedule["jitter_minutes"]


if getattr(sys, "frozen", False):
    # Running as a PyInstaller --onefile exe: __file__ paths point into a
    # temporary extraction folder, so user-editable files (config, watchlist,
    # database) must live next to the exe instead.
    PROJECT_ROOT = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent
    BUNDLE_DIR = PROJECT_ROOT


def _ensure_user_file(name: str) -> Path:
    """Copy a default template next to the exe on first run, if missing."""
    dest = PROJECT_ROOT / name
    if not dest.exists():
        default = BUNDLE_DIR / name
        if default.exists():
            shutil.copy(default, dest)
    return dest


def config_path() -> Path:
    return _ensure_user_file("config.yaml")


def load_config(path: str = None) -> Config:
    path = path or str(config_path())
    with open(path) as f:
        raw = yaml.safe_load(f)
    return Config(**raw)


def save_config(config: Config, path: str = None) -> None:
    path = path or str(config_path())
    with open(path, "w") as f:
        yaml.safe_dump(config.model_dump(), f, sort_keys=False)
