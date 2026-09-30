"""ตำแหน่งไฟล์ของโปรเจกต์ และการโหลด settings.yaml"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml


# settings.yaml มีข้อมูลลูกค้าจริงและไม่ถูก commit — ถ้าไม่มี ใช้ไฟล์ตัวอย่าง
SETTINGS_FILES = ("settings.yaml", "settings.example.yaml")


def find_root(start: Path | None = None) -> Path:
    """หาโฟลเดอร์โปรเจกต์: $ARMA_HOME หรือไล่ขึ้นไปจนเจอ config/settings.yaml"""
    if env := os.environ.get("ARMA_HOME"):
        return Path(env).resolve()
    here = (start or Path.cwd()).resolve()
    for p in (here, *here.parents):
        if any((p / "config" / name).exists() for name in SETTINGS_FILES):
            return p
    return here


@dataclass
class Project:
    root: Path

    @classmethod
    def load(cls, root: Path | None = None) -> "Project":
        return cls(root or find_root())

    @cached_property
    def settings(self) -> dict:
        for name in SETTINGS_FILES:
            path = self.root / "config" / name
            if path.exists():
                return yaml.safe_load(path.read_text("utf-8"))
        raise FileNotFoundError("ไม่พบ config/settings.yaml — คัดลอกจาก config/settings.example.yaml")

    # --- paths ---
    @property
    def counter_path(self) -> Path:
        return self.root / "config" / "receipt_counter.json"

    @property
    def master_dir(self) -> Path:
        return self.root / "master"

    @property
    def products_path(self) -> Path:
        return self.master_dir / "products.xlsx"

    @property
    def aliases_path(self) -> Path:
        return self.master_dir / "aliases.xlsx"

    @property
    def history_path(self) -> Path:
        return self.master_dir / "history.csv"

    @property
    def normalize_path(self) -> Path:
        return self.master_dir / "normalize.yaml"

    @property
    def templates_dir(self) -> Path:
        return self.root / "templates"

    def input_dir(self, month: str) -> Path:
        return self.root / "input" / month

    def work_dir(self, month: str) -> Path:
        return self.root / "work" / month

    def output_dir(self, month: str) -> Path:
        return self.root / "output" / month

    def chat_path(self, month: str, override: Path | None = None) -> Path:
        if override:
            return override
        monthly = self.input_dir(month) / "line_export.txt"
        if monthly.exists():
            return monthly
        return self.root / self.settings["paths"]["default_chat"]
