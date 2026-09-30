"""ขั้นที่ 8 (แผนข้อ 11) — วัดผลกับข้อมูลเฉลย: แชท 27/04–27/06/2569 เทียบใบเสร็จ #309–#317"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd

from .normalize import Normalizer

WINDOW = (date(2026, 4, 27), date(2026, 6, 27))

# ชุดเฉลย: ชื่อ → (ไฟล์ใน tests/fixtures, ช่วงวันที่ของแชทที่ใช้)
SETS = {
    "309-317": ("receipts_309_317.csv", WINDOW),
    "330-336": ("receipts_330_336.csv", (date(2026, 9, 1), date(2026, 9, 30))),
}


def canonical(name: str, norm: Normalizer) -> str:
    """ชื่อในใบเสร็จแบบหลวม: ไม่สนช่องว่าง, คำนำหน้า 'เลเซอร์คัทอะคริลิค', 'REVO', จุดหลัง mm"""
    s = norm.clean(name)
    s = s.replace("เลเซอร์คัทอะคริลิค", "").replace("revo", "").replace("mm.", "mm")
    s = re.sub(r"^\s*งาน", "", s)  # "งานออกแบบ…" / "ออกแบบ…" ใบเสร็จจริงเขียนทั้ง 2 แบบ
    return re.sub(r"\s+", "", s)


def strip_color(name: str) -> str:
    return re.sub(r"\s*สี\S+", "", name)


@dataclass
class BacktestResult:
    total: int
    found: int
    correct: int
    auto_lines: int       # รายการเฉลยที่ระบบจับคู่แบบ auto
    auto_correct: int
    predicted_lines: int
    detail: pd.DataFrame

    @property
    def recall(self) -> float:
        return self.found / self.total if self.total else 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.found if self.found else 0

    @property
    def auto_accuracy(self) -> float:
        return self.auto_correct / self.auto_lines if self.auto_lines else 0

    @property
    def auto_rate(self) -> float:
        return self.auto_lines / self.found if self.found else 0

    def summary(self) -> str:
        return (
            f"รายการในใบเสร็จเฉลย        : {self.total}\n"
            f"Extraction recall          : {self.found}/{self.total} = {self.recall:.0%}\n"
            f"เลือกสินค้าถูก (ทุกสถานะ)    : {self.correct}/{self.found} = {self.accuracy:.0%}\n"
            f"Match accuracy (auto)      : {self.auto_correct}/{self.auto_lines} = {self.auto_accuracy:.0%}\n"
            f"Auto rate                  : {self.auto_lines}/{self.found} = {self.auto_rate:.0%}\n"
            f"รายการในแชทที่ไม่อยู่ในเฉลย : {self.predicted_lines - self.found} (อาจออกบิลรอบอื่น — ดู --show)"
        )


def compare(predicted: pd.DataFrame, expected: pd.DataFrame, norm: Normalizer) -> BacktestResult:
    pred = predicted[predicted["kind"].isin(["order", "shipping_fee", "design_fee"])].copy()
    pred["qty_i"] = pred["qty"].fillna(0).astype(int)
    names = pred["full_name"] if "full_name" in pred else pred["receipt_name"]
    pred["canon"] = [canonical(n or "", norm) for n in names]
    pred["canon_nc"] = [canonical(strip_color(n or ""), norm) for n in names]
    used: set[int] = set()
    rows = []

    exp = expected.copy()
    exp["qty_i"] = [1 if q == "-" else int(q) for q in exp["qty"]]

    def same_name(p, e_desc: str) -> bool:
        e = canonical(e_desc, norm)
        has_color = bool(re.search(r"สี\S+", e_desc))
        return p.canon == e or (not has_color and p.canon_nc == e)

    # รอบ 1: จำนวนและชื่อตรง, รอบ 2: จำนวนตรงอย่างเดียว (ดึงเจอแต่เลือกสินค้าผิด)
    result = {}
    for pass_no in (1, 2):
        for i, e in exp.iterrows():
            if i in result:
                continue
            for j, p in pred.iterrows():
                if j in used or p.qty_i != e.qty_i:
                    continue
                # ค่าบริการ (จำนวน "-") ต้องจับคู่ด้วยชื่อเท่านั้น ไม่งั้นจะไปจับกับสินค้าจำนวน 1
                is_service = e.qty == "-" or p.kind != "order"
                if (pass_no == 1 or is_service) and not same_name(p, e.description):
                    continue
                used.add(j)
                result[i] = (j, pass_no == 1)
                break
    auto_lines = auto_correct = 0
    for i, e in exp.iterrows():
        j, ok = result.get(i, (None, False))
        p = pred.loc[j] if j is not None else None
        if p is not None and p.status == "auto":
            auto_lines += 1
            auto_correct += ok
        rows.append({
            "receipt_no": e.receipt_no, "qty": e.qty, "expected": e.description,
            "expected_price": e.unit_price,
            "chat_line": p.raw_line if p is not None else "",
            "predicted": p.receipt_name if p is not None else "",
            "predicted_price": p.unit_price if p is not None else None,
            "status": p.status if p is not None else "missing",
            "result": "correct" if ok else ("wrong" if p is not None else "missing"),
        })
    detail = pd.DataFrame(rows)
    # รายการที่ระบบดึงได้ แต่ไม่อยู่ในใบเสร็จเฉลย
    extra = pred[~pred.index.isin(used)]
    extra_rows = pd.DataFrame({
        "receipt_no": "", "qty": extra["qty_i"], "expected": "", "expected_price": None,
        "chat_line": extra["raw_line"], "predicted": extra["receipt_name"],
        "predicted_price": extra["unit_price"], "status": extra["status"], "result": "extra",
    })
    detail = pd.concat([detail, extra_rows], ignore_index=True)
    return BacktestResult(
        total=len(exp),
        found=len(result),
        correct=sum(ok for _, ok in result.values()),
        auto_lines=auto_lines,
        auto_correct=auto_correct,
        predicted_lines=len(pred),
        detail=detail,
    )


def load_expected(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"qty": str, "receipt_no": str})
