"""ขั้นที่ 1 — อ่านไฟล์ export แชท LINE (.txt) → DataFrame ข้อความ"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .thai_utils import be_to_ce

DAY_RE = re.compile(r"^(?:จันทร์|อังคาร|พุธ|พฤหัส|พฤหัสบดี|ศุกร์|เสาร์|อาทิตย์) (\d{2})/(\d{2})/(\d{4})$")
MSG_RE = re.compile(r"^(\d{2}):(\d{2})\t([^\t]*)\t(.*)$", re.S)
INVISIBLE = re.compile("[⁨⁩​‌‍﻿]")
SYSTEM_TEXTS = {"[สติกเกอร์]", "[รูป]", "[ไฟล์]", "[วิดีโอ]", "[ข้อความเสียง]", "[อัลบั้ม]"}
SYSTEM_PATTERNS = re.compile(r"ยกเลิกข้อความ|ลบข้อความ|เข้าร่วมกลุ่ม|ออกจากกลุ่ม")

COLUMNS = ["msg_id", "date", "time", "sender", "text", "is_system"]


def read_export(path: Path) -> str:
    # newline="" สำคัญ: ไม่ให้ Python แปลง \r\n → \n เพราะ \n เดี่ยวคือขึ้นบรรทัดภายในข้อความ
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def parse_text(raw: str) -> pd.DataFrame:
    rows: list[dict] = []
    current: date | None = None
    for line in raw.split("\r\n"):
        if m := DAY_RE.match(line):
            d, mth, y = (int(x) for x in m.groups())
            current = date(be_to_ce(y), mth, d)
            continue
        if current and (m := MSG_RE.match(line)):
            hh, mm, sender, text = m.groups()
            rows.append({"date": current, "time": f"{hh}:{mm}", "sender": sender, "text": text})
            continue
        if rows and line.strip():
            # บรรทัดที่ไม่ตรงรูปแบบ → ต่อท้ายข้อความก่อนหน้า
            rows[-1]["text"] += "\n" + line
    for i, r in enumerate(rows, start=1):
        r["msg_id"] = i
        r["sender"] = INVISIBLE.sub("", r["sender"]).strip()
        text = r["text"]
        if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
            text = text[1:-1].replace('""', '"')
        r["text"] = text.strip()
        r["is_system"] = (
            not r["sender"]
            or r["text"] in SYSTEM_TEXTS
            or bool(SYSTEM_PATTERNS.search(r["text"]))
        )
    return pd.DataFrame(rows, columns=COLUMNS)


def parse_file(path: Path, year: int | None = None, month: int | None = None,
               start: date | None = None, end: date | None = None) -> pd.DataFrame:
    """อ่านไฟล์และกรองเดือน (ค.ศ.) หรือช่วงวันที่ [start, end]"""
    df = parse_text(read_export(path))
    if year and month:
        df = df[[d.year == year and d.month == month for d in df["date"]]]
    if start:
        df = df[[d >= start for d in df["date"]]]
    if end:
        df = df[[d <= end for d in df["date"]]]
    return df.reset_index(drop=True)
