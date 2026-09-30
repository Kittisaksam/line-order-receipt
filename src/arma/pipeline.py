"""รวมขั้นที่ 1–4: แชท → order_lines ที่จับคู่สินค้าแล้ว"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from .config import Project
from .extract import Extractor
from .matcher import Matcher
from .normalize import Normalizer
from .parse_line import parse_file


def load_normalizer(project: Project) -> Normalizer:
    return Normalizer.load(project.normalize_path)


def load_matcher(project: Project, norm: Normalizer, use_aliases: bool = True) -> Matcher:
    if not project.products_path.exists():
        raise FileNotFoundError(f"ไม่พบ {project.products_path} — รัน `uv run arma build-master` ก่อน")
    aliases = project.aliases_path if use_aliases else Path("/nonexistent")
    return Matcher.load(project.products_path, aliases, project.history_path, norm)


def run(project: Project, chat: Path, *, year: int | None = None, month: int | None = None,
        start: date | None = None, end: date | None = None,
        use_aliases: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """คืน (messages, order_lines)"""
    norm = load_normalizer(project)
    messages = parse_file(chat, year=year, month=month, start=start, end=end)
    lines = Extractor(norm).extract(messages)
    matched = load_matcher(project, norm, use_aliases).match(lines)
    return messages, matched
