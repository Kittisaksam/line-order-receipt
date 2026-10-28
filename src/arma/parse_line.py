"""ขั้นที่ 1 — อ่านไฟล์ export แชท LINE (.txt) → DataFrame ข้อความ"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from .thai_utils import be_to_ce

DAY_RE = re.compile(r"^(?:จันทร์|อังคาร|พุธ|พฤหัส|พฤหัสบดี|ศุกร์|เสาร์|อาทิตย์) (\d{2})/(\d{2})/(\d{4})$")
MSG_RE = re.compile(r"^(\d{2}):(\d{2})\t([^\t]*)\t(.*)$", re.S)
# รูปแบบ export อีกแบบ: หัววัน "2026.09.30 วันพุธ", ข้อความ "HH:MM ผู้ส่ง ข้อความ", ขึ้นบรรทัดด้วย \n
DAY_DOTTED_RE = re.compile(r"^(\d{4})\.(\d{2})\.(\d{2}) วัน\S+$")
MSG_SPACE_RE = re.compile(r"^(\d{2}):(\d{2}) (\S+) ?(.*)$", re.S)
DOTTED_DETECT = re.compile(r"^\d{4}\.\d{2}\.\d{2} วัน", re.M)
INVISIBLE = re.compile("[⁨⁩​‌‍﻿]")
_MEDIA = ("สติกเกอร์", "รูป", "ไฟล์", "วิดีโอ", "ข้อความเสียง", "อัลบั้ม")
# export แบบมีจุดไม่มีวงเล็บ: "รูป", "สติกเกอร์"
SYSTEM_TEXTS = {f"[{t}]" for t in _MEDIA} | set(_MEDIA)
SYSTEM_PATTERNS = re.compile(r"ยกเลิกข้อความ|ลบข้อความ|เข้าร่วมกลุ่ม|ออกจากกลุ่ม|เพิ่ม .+ เข้ากลุ่ม")

COLUMNS = ["msg_id", "date", "time", "sender", "text", "is_system"]


def read_export(path: Path) -> str:
    # newline="" สำคัญ: ไม่ให้ Python แปลง \r\n → \n เพราะ \n เดี่ยวคือขึ้นบรรทัดภายในข้อความ
    with open(path, encoding="utf-8-sig", newline="") as f:
        return f.read()


def parse_text(raw: str) -> pd.DataFrame:
    rows: list[dict] = []
    current: date | None = None
    # ตรวจรูปแบบครั้งเดียวต่อไฟล์ — กันบรรทัดต่อท้ายที่ขึ้นต้นด้วย "HH:MM " ถูกอ่านเป็นข้อความใหม่
    dotted = bool(DOTTED_DETECT.search(raw))
    if dotted:
        lines, day_re, msg_re = raw.replace("\r\n", "\n").split("\n"), DAY_DOTTED_RE, MSG_SPACE_RE
    else:
        lines, day_re, msg_re = raw.split("\r\n"), DAY_RE, MSG_RE
    for line in lines:
        if m := day_re.match(line):
            if dotted:
                y, mth, d = (int(x) for x in m.groups())
            else:
                d, mth, y = (int(x) for x in m.groups())
            current = date(be_to_ce(y), mth, d)
            continue
        if current and (m := msg_re.match(line)):
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
