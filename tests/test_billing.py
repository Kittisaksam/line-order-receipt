from datetime import date, timedelta
from decimal import Decimal

import pytest

from arma.billing import BillingConfig, BillLine, assign_numbers, make_bills, read_counter, write_counter


def _lines(n, start=date(2026, 9, 1), step_days=1, price="125"):
    return [
        BillLine(start + timedelta(days=i * step_days), 10, f"P{i}", f"สินค้า {i}", Decimal(price))
        for i in range(n)
    ]


@pytest.mark.parametrize(("n", "bills"), [(1, 1), (10, 1), (11, 2), (25, 3)])
def test_by_max_lines(n, bills):
    result = make_bills(_lines(n), BillingConfig(mode="by_max_lines", max_lines_per_bill=10))
    assert len(result) == bills
    assert sum(len(b.lines) for b in result) == n


@pytest.mark.parametrize("n", [1, 10, 11, 60])
def test_single_mode_is_one_bill(n):
    assert len(make_bills(_lines(n), BillingConfig(mode="single"))) == 1


def test_by_period_from_first_order_with_max_lines():
    lines = _lines(4, step_days=3) + _lines(12, start=date(2026, 9, 20), step_days=0)
    cfg = BillingConfig(mode="by_period", period_days=7, period_anchor="first", max_lines_per_bill=10)
    assert [len(b.lines) for b in make_bills(lines, cfg)] == [3, 1, 10, 2]


def test_by_period_month_anchor_weeks():
    """ตัด 1–7, 8–14, 15–21, 22–28, 29–30 ; ไม่จำกัดจำนวนรายการ"""
    lines = _lines(30)  # 1–30 ก.ย. วันละรายการ
    cfg = BillingConfig(mode="by_period", period_days=7, period_anchor="month", max_lines_per_bill=0)
    bills = make_bills(lines, cfg)
    assert [len(b.lines) for b in bills] == [7, 7, 7, 7, 2]
    assert [b.date.day for b in bills] == [1, 8, 15, 22, 29]


def test_by_period_skips_empty_weeks():
    lines = _lines(1, start=date(2026, 9, 2)) + _lines(1, start=date(2026, 9, 29))
    cfg = BillingConfig(mode="by_period", period_anchor="month", max_lines_per_bill=0)
    assert len(make_bills(lines, cfg)) == 2


def test_bill_date_first_or_last_and_decimal_subtotal():
    first = make_bills(_lines(3, price="0.1"), BillingConfig())[0]
    assert first.date == date(2026, 9, 1)
    assert first.subtotal == Decimal("3.0")
    last = make_bills(_lines(3), BillingConfig(bill_date="last"))[0]
    assert last.date == date(2026, 9, 3)


@pytest.mark.parametrize("pid", ["SV-SHIPPING", "SV-DESIGN"])
def test_service_lines_show_dash(pid):
    ln = BillLine(date(2026, 6, 5), 1, pid, "ค่าบริการ", Decimal(85))
    assert ln.qty_display == "-" and ln.amount == 85


def test_merge_same_item():
    lines = _lines(1) + _lines(1)
    bills = make_bills(lines, BillingConfig(merge_same_item=True))
    assert len(bills[0].lines) == 1 and bills[0].lines[0].qty == 20


def test_numbering_and_dry_run(tmp_path):
    counter = tmp_path / "c.json"
    write_counter(counter, 317)
    bills = make_bills(_lines(11), BillingConfig(mode="by_max_lines"))
    assert assign_numbers(bills, read_counter(counter), dry_run=True) == 317
    assert [b.no for b in bills] == ["DRAFT-01", "DRAFT-02"]
    assert assign_numbers(bills, 317, dry_run=False) == 319
    assert [b.no for b in bills] == ["318", "319"]
