"""ขั้นที่ 3 — normalize ข้อความ + ดึงคุณลักษณะ (ใช้ร่วมกันทั้งฝั่ง LINE และฝั่ง products)"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

ATTRS = ("model", "brand", "part", "logo", "size", "style", "thickness", "category", "color")

Attrs = dict[str, frozenset[str]]

_THAI = "฀-๿"
_LATIN = "a-z0-9"
_INVISIBLE = re.compile("[⁨⁩​‌‍﻿]")


def _kw_regex(keyword: str) -> re.Pattern:
    if keyword.startswith("re:"):
        return re.compile(keyword[3:])
    pat = re.escape(keyword).replace(r"\ ", " ").replace(" ", r"\s*")
    if re.search(r"[a-z0-9]", keyword[:1]):
        pat = rf"(?<![{_LATIN}]){pat}"
    if re.search(r"[a-z0-9.]", keyword[-1:]):
        pat = rf"{pat}(?![{_LATIN}])"
    return re.compile(pat)


@dataclass
class Normalizer:
    cfg: dict
    _keywords: list[tuple[re.Pattern, str, str, int]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        kws = []
        for attr, values in self.cfg["vocab"].items():
            for canonical, words in values.items():
                for w in words:
                    w = str(w).lower()
                    length = len(w) if not w.startswith("re:") else len(w) - 3
                    kws.append((_kw_regex(w), attr, str(canonical), length))
        # คำยาวจับก่อน เพื่อไม่ให้คำสั้นไปจับในคำยาว ("ท้าย" ใน "มือจับท้าย")
        kws.sort(key=lambda k: -k[3])
        self._keywords = kws

    @classmethod
    def load(cls, path: Path) -> "Normalizer":
        return cls(yaml.safe_load(path.read_text("utf-8")))

    @cached_property
    def _typos(self) -> list[tuple[re.Pattern, str]]:
        items = sorted(self.cfg.get("typo", {}).items(), key=lambda kv: -len(kv[0]))
        return [(re.compile(k), v) for k, v in items]

    @cached_property
    def units(self) -> list[str]:
        return list(self.cfg.get("units", []))

    @cached_property
    def neutral_colors(self) -> frozenset[str]:
        return frozenset(self.cfg.get("neutral_colors", []))

    # ---------- ข้อความ ----------
    def clean(self, text: str) -> str:
        """lowercase, แก้คำผิด, เว้นวรรคระหว่างไทย/อังกฤษ, ตัดช่องว่างซ้ำ"""
        s = _INVISIBLE.sub("", text).lower()
        s = re.sub(rf"([{_THAI}])([{_LATIN}])", r"\1 \2", s)
        s = re.sub(rf"([{_LATIN}.])([{_THAI}])", r"\1 \2", s)
        for pat, repl in self._typos:
            s = pat.sub(repl, s)
        s = re.sub(rf"([{_THAI}])([{_LATIN}])", r"\1 \2", s)
        s = re.sub(rf"([{_LATIN}])([{_THAI}])", r"\1 \2", s)
        return re.sub(r"\s+", " ", s).strip()

    # ---------- คุณลักษณะ ----------
    def attributes(self, text: str, *, cleaned: bool = False, apply_rules: bool = True) -> Attrs:
        s = text if cleaned else self.clean(text)
        taken = [False] * len(s)
        found: dict[str, set[str]] = {a: set() for a in ATTRS}
        for pat, attr, canonical, _ in self._keywords:
            for m in pat.finditer(s):
                if m.end() == m.start() or any(taken[m.start() : m.end()]):
                    continue
                found[attr].add(canonical)
                for i in range(m.start(), m.end()):
                    taken[i] = True
        attrs = {a: frozenset(v) for a, v in found.items()}
        return self.apply_rules(attrs) if apply_rules else attrs

    def apply_rules(self, attrs: Attrs) -> Attrs:
        out = dict(attrs)
        for rule in self.cfg.get("rules", []):
            if all(_cond(out.get(a, frozenset()), c) for a, c in rule["when"].items()):
                for a, v in rule["set"].items():
                    out[a] = frozenset([v] if isinstance(v, str) else v)
        return out


def _cond(have: frozenset[str], cond) -> bool:
    if cond is None:
        return not have
    if cond == "*":
        return bool(have)
    options = cond if isinstance(cond, list) else [cond]
    if not have:
        return None in options
    return bool(have & {o for o in options if o is not None})


def merge(base: Attrs, override: Attrs, only: tuple[str, ...] | None = None) -> Attrs:
    """เติมค่าจาก base เฉพาะคุณลักษณะที่ override ไม่มี"""
    out = dict(override)
    for a in only or ATTRS:
        if not out.get(a) and base.get(a):
            out[a] = base[a]
    return out


def norm_key(attrs: Attrs) -> str:
    """คีย์สำหรับค้นใน aliases เช่น 'color=ดำเงา|model=travo|part=ท้ายกระบะ'"""
    parts = [f"{a}={'+'.join(sorted(v))}" for a, v in sorted(attrs.items()) if v]
    return "|".join(parts)


def attrs_to_str(attrs: Attrs) -> str:
    return ", ".join(f"{a}:{'/'.join(sorted(v))}" for a, v in attrs.items() if v)
