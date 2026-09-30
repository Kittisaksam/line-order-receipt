"""วันที่ไทย (พ.ศ.), รูปแบบตัวเลข, จำนวนเงินเป็นตัวอักษร"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

BE_OFFSET = 543

THAI_MONTHS = [
    "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def be_to_ce(year: int) -> int:
    return year - BE_OFFSET if year > 2400 else year


def ce_to_be(year: int) -> int:
    return year + BE_OFFSET if year < 2400 else year


def parse_month(month: str) -> tuple[int, int]:
    """'2569-10' หรือ '2026-10' → (2026, 10) เป็น ค.ศ."""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})", month.strip())
    if not m:
        raise ValueError(f"รูปแบบเดือนไม่ถูกต้อง: {month!r} (ต้องเป็น YYYY-MM เช่น 2569-10)")
    year, mon = int(m.group(1)), int(m.group(2))
    if not 1 <= mon <= 12:
        raise ValueError(f"เดือนไม่ถูกต้อง: {month!r}")
    return be_to_ce(year), mon


def month_label(month: str) -> str:
    """'2026-10' / '2569-10' → '2569-10' (ใช้เป็นชื่อโฟลเดอร์)"""
    y, m = parse_month(month)
    return f"{ce_to_be(y)}-{m:02d}"


def month_name_th(year_ce: int, month: int) -> str:
    return f"{THAI_MONTHS[month - 1]} {ce_to_be(year_ce)}"


def fmt_date_th(d: date) -> str:
    """date → 'dd/mm/พ.ศ.'"""
    return f"{d.day:02d}/{d.month:02d}/{ce_to_be(d.year)}"


def parse_date_th(text: str) -> date:
    """'dd/mm/yyyy' (พ.ศ. หรือ ค.ศ.) → date"""
    d, m, y = (int(x) for x in text.strip().split("/"))
    return date(be_to_ce(y), m, d)


def fmt_money(value: Decimal | int | float) -> str:
    """11985 → '11,985' ; 12.5 → '12.50'"""
    v = Decimal(str(value))
    if v == v.to_integral_value():
        return f"{int(v):,}"
    return f"{v:,.2f}"


def bahttext(value: Decimal | int | float) -> str:
    from pythainlp.util import bahttext as _bahttext

    return _bahttext(float(value))
