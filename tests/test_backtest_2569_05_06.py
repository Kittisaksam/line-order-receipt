"""เทียบกับใบเสร็จจริง #309–#317 (แผนข้อ 11) — เป้าหมาย: recall ≥ 90%, auto accuracy ≥ 90%, auto rate ≥ 60%"""

import pytest

from arma import backtest as bt
from arma import pipeline

from .conftest import CHAT, FIXTURES, requires_data

pytestmark = requires_data


@pytest.fixture(scope="module", params=[True, False], ids=["with-aliases", "rules-only"])
def result(request, project):
    _, lines = pipeline.run(project, CHAT, start=bt.WINDOW[0], end=bt.WINDOW[1], use_aliases=request.param)
    return bt.compare(lines, bt.load_expected(FIXTURES / "receipts_309_317.csv"), pipeline.load_normalizer(project))


def test_backtest_targets(result):
    print("\n" + result.summary())
    assert result.total == 74
    assert result.recall >= 0.90
    assert result.auto_accuracy >= 0.90
    assert result.auto_rate >= 0.60


def test_backtest_2569_09_targets(project):
    """เทียบแชท ก.ย. 2569 กับ #330–#336 (5 รายการในเฉลยไม่มีในแชท จึงตั้งเป้า recall ที่ 85%)"""
    fixture, (start, end) = bt.SETS["330-336"]
    _, lines = pipeline.run(project, CHAT, start=start, end=end, use_aliases=False)
    result = bt.compare(lines, bt.load_expected(FIXTURES / fixture), pipeline.load_normalizer(project))
    print("\n" + result.summary())
    assert result.total == 57
    assert result.recall >= 0.85
    assert result.auto_accuracy >= 0.90


def test_end_to_end_pdf(project, tmp_path):
    """review.csv → อ่านกลับ → จัดบิล → PDF ได้จริง"""
    import pandas as pd

    from arma.billing import BillingConfig, BillLine, make_bills
    from arma.render_pdf import Renderer
    from arma.review import display_name, read_review, write_review

    _, lines = pipeline.run(project, CHAT, year=2026, month=5)
    products = pd.read_excel(project.products_path, dtype={"color": str}, keep_default_na=False)
    auto = lines[lines["status"] == "auto"]
    path = tmp_path / "review.csv"
    write_review(auto, products, path)
    confirmed = read_review(path, products, default_date=auto["date"].max())
    assert len(confirmed) == len(auto)

    by_id = products.set_index("product_id", drop=False)
    bills = make_bills(
        [BillLine(c.date, c.qty, c.product_id, display_name(by_id.loc[c.product_id]), c.unit_price) for c in confirmed],
        BillingConfig(mode="by_max_lines"),
    )
    bills[0].no = "TEST"
    pdf = Renderer(project.templates_dir, project.settings).render(bills[0], tmp_path / "r.pdf", draft=True)
    assert pdf.read_bytes().startswith(b"%PDF")
