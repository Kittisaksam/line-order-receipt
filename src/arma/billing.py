"""ขั้นที่ 6 — จัดบิลและเลขที่ใบเสร็จ"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

SHIPPING_ID = "SV-SHIPPING"
SERVICE_PREFIX = "SV-"


@dataclass
class BillLine:
    date: date
    qty: int
    product_id: str
    description: str
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return self.unit_price * self.qty

    @property
    def qty_display(self) -> str:
        return "-" if self.product_id.startswith(SERVICE_PREFIX) else f"{self.qty:,}"


@dataclass
class Bill:
    lines: list[BillLine]
    no: str = ""
    time: str = "18.00"
    date_rule: str = "first"  # first = วันที่ออเดอร์แรกในบิล (แบบใบเสร็จเดิม), last = ออเดอร์ล่าสุด

    @property
    def date(self) -> date:
        dates = [ln.date for ln in self.lines]
        return max(dates) if self.date_rule == "last" else min(dates)

    @property
    def subtotal(self) -> Decimal:
        return sum((ln.amount for ln in self.lines), Decimal(0))


@dataclass
class BillingConfig:
    mode: str = "single"
    max_lines_per_bill: int = 10   # 0 = ไม่จำกัด
    period_days: int = 7
    period_anchor: str = "month"   # month = ตัดตามวันที่ของเดือน (1–7, 8–14, …), first = นับจากออเดอร์แรกของรอบ
    bill_time: str = "18.00"
    bill_date: str = "first"
    merge_same_item: bool = False
    extra: dict = field(default_factory=dict)

    FIELDS = ("mode", "max_lines_per_bill", "period_days", "period_anchor", "bill_time", "bill_date", "merge_same_item")

    @classmethod
    def from_settings(cls, s: dict) -> "BillingConfig":
        known = {k: s[k] for k in cls.FIELDS if k in s}
        return cls(**known, extra={k: v for k, v in s.items() if k not in known})


def _merge_same(lines: list[BillLine]) -> list[BillLine]:
    merged: dict[tuple, BillLine] = {}
    for ln in lines:
        key = (ln.product_id, ln.unit_price, ln.description)
        if key in merged and ln.product_id != SHIPPING_ID:
            m = merged[key]
            merged[key] = BillLine(max(m.date, ln.date), m.qty + ln.qty, m.product_id, m.description, m.unit_price)
        else:
            merged[key if ln.product_id != SHIPPING_ID else (key, id(ln))] = ln
    return list(merged.values())


def _chunks(lines: list[BillLine], size: int) -> list[list[BillLine]]:
    if size <= 0:
        return [lines]
    return [lines[i : i + size] for i in range(0, len(lines), size)]


def _split_period(lines: list[BillLine], cfg: BillingConfig) -> list[list[BillLine]]:
    groups: list[list[BillLine]] = []
    key = start = None
    for ln in lines:
        if cfg.period_anchor == "month":
            # 1–7, 8–14, 15–21, 22–28, 29–สิ้นเดือน (ช่วงท้ายไม่ข้ามไปเดือนถัดไป)
            k = (ln.date.year, ln.date.month, (ln.date.day - 1) // cfg.period_days)
        else:
            if start is None or ln.date >= start + timedelta(days=cfg.period_days):
                start = ln.date
            k = start
        if k != key:
            groups.append([])
            key = k
        groups[-1].append(ln)
    return groups


def make_bills(lines: list[BillLine], cfg: BillingConfig) -> list[Bill]:
    lines = sorted(lines, key=lambda ln: ln.date)
    if not lines:
        return []
    if cfg.mode == "single":
        groups = [lines]
    elif cfg.mode == "by_max_lines":
        groups = _chunks(lines, cfg.max_lines_per_bill)
    elif cfg.mode == "by_period":
        groups = [c for g in _split_period(lines, cfg) for c in _chunks(g, cfg.max_lines_per_bill)]
    else:
        raise ValueError(f"billing.mode ไม่รู้จัก: {cfg.mode!r} (single | by_period | by_max_lines)")
    bills = []
    for g in groups:
        g = _merge_same(g) if cfg.merge_same_item else g
        bills.append(Bill(lines=g, time=cfg.bill_time, date_rule=cfg.bill_date))
    return bills


# ---------- เลขที่ใบเสร็จ ----------
def read_counter(path: Path) -> int:
    return int(json.loads(path.read_text("utf-8"))["last_no"])


def write_counter(path: Path, last_no: int) -> None:
    path.write_text(json.dumps({"last_no": last_no}) + "\n", "utf-8")


def assign_numbers(bills: list[Bill], last_no: int, dry_run: bool) -> int:
    """ใส่เลขที่ให้บิล คืนเลขล่าสุดใหม่ (dry-run ใช้ DRAFT-01.. และไม่เปลี่ยนเลข)"""
    for i, b in enumerate(bills, start=1):
        b.no = f"DRAFT-{i:02d}" if dry_run else str(last_no + i)
    return last_no if dry_run else last_no + len(bills)
