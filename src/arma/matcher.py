"""ขั้นที่ 4 — จับคู่บรรทัดสั่งของกับสินค้าใน products.xlsx"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz

from .normalize import ATTRS, Attrs, Normalizer, merge, norm_key
from .review import display_name

# น้ำหนักของแต่ละคุณลักษณะ
WEIGHT = {
    "model": 3.0, "part": 2.5, "logo": 2.0, "size": 1.5, "color": 1.5,
    "style": 1.0, "thickness": 1.0, "category": 1.0, "brand": 0.5,
}
# ข้อความไม่ได้ระบุ แต่สินค้ามี → ไม่หักคะแนน
NO_MISSING_PENALTY = {"brand", "category", "style"}
AMBIGUOUS_MARGIN = 0.6   # คะแนนห่างจากอันดับ 1 น้อยกว่านี้ = ผู้สมัครที่สูสี
MIN_MATCHED = 2.5        # คะแนนบวกขั้นต่ำ ต่ำกว่านี้ = not_found

# ค่าบริการที่ราคามาจากข้อความ: kind → product_id
FEE_PRODUCTS = {"shipping_fee": "SV-SHIPPING", "design_fee": "SV-DESIGN"}

MATCH_COLUMNS = [
    "norm_key", "context_used", "product_id", "receipt_name", "full_name", "unit_price", "amount",
    "status", "confidence", "candidates",
]


@dataclass
class Candidate:
    product_id: str
    score: float
    matched: float


@dataclass
class Matcher:
    products: pd.DataFrame
    norm: Normalizer
    aliases: dict[str, str] = field(default_factory=dict)
    history: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        p = self.products
        p = p[p["active"].astype(str).str.lower().isin(["true", "1", "yes", "y"])].copy()
        self.products = p.set_index("product_id", drop=False)
        self._attrs: dict[str, Attrs] = {}
        self._text: dict[str, str] = {}
        for r in self.products.itertuples(index=False):
            a = {k: frozenset(filter(None, str(getattr(r, k, "") or "").split("/"))) for k in ATTRS if k not in ("color", "category")}
            a["color"] = frozenset([r.color]) if isinstance(r.color, str) and r.color else frozenset()
            a["category"] = frozenset([r.category])
            self._attrs[r.product_id] = a
            self._text[r.product_id] = self.norm.clean(f"{r.receipt_name} {r.color or ''}")

    @classmethod
    def load(cls, products_path: Path, aliases_path: Path, history_path: Path, norm: Normalizer) -> "Matcher":
        products = pd.read_excel(products_path, dtype={"color": str}, keep_default_na=False)
        aliases: dict[str, str] = {}
        if aliases_path.exists():
            adf = pd.read_excel(aliases_path, dtype=str, keep_default_na=False)
            aliases = dict(zip(adf["alias_key"], adf["product_id"]))
        history: Counter = Counter()
        if history_path.exists():
            hdf = pd.read_csv(history_path, dtype={"product_id": str})
            history.update(hdf["product_id"])
        return cls(products, norm, aliases, history)

    # ---------- คะแนน ----------
    def score(self, text_attrs: Attrs, pid: str) -> tuple[float, float]:
        pa = self._attrs[pid]
        score = matched = 0.0
        for attr, w in WEIGHT.items():
            t, p = text_attrs.get(attr, frozenset()), pa.get(attr, frozenset())
            if t and p:
                if t & p:
                    score += w
                    matched += w
                    score -= 0.3 * w * len(t - p)
                else:
                    score -= 2 * w
            elif t:
                if attr == "color":
                    score -= w
                elif attr not in ("brand", "category"):
                    score -= 0.5 * w
            elif p:
                if attr == "color" and p <= self.norm.neutral_colors:
                    continue
                if attr not in NO_MISSING_PENALTY:
                    score -= 0.5 * w
        return score, matched

    def rank(self, text_attrs: Attrs, text: str) -> list[Candidate]:
        out = []
        for pid in self._attrs:
            if pid.startswith("SV-"):
                continue
            s, m = self.score(text_attrs, pid)
            s += 0.3 * fuzz.token_set_ratio(text, self._text[pid]) / 100
            out.append(Candidate(pid, round(s, 3), m))
        out.sort(key=lambda c: (-c.score, -self.history[c.product_id]))
        return out

    # ---------- ตัดสิน ----------
    def variants(self, clean: str, header: str, prev: str) -> list[tuple[str, str, Attrs]]:
        """ชุดคุณลักษณะที่เป็นไปได้: ข้อความเอง / + หัวข้อ / + ส่วนของบรรทัดก่อนหน้า"""
        raw = lambda s: self.norm.attributes(s, cleaned=True, apply_rules=False)  # noqa: E731
        own = raw(clean)
        out = [("", clean, self.norm.apply_rules(own))]
        base = own
        if header:
            base = merge(raw(header), own)
            out.append(("header", f"{header} {clean}", self.norm.apply_rules(base)))
        if prev:
            inherited = merge(raw(prev), base, only=("part", "logo", "size", "category"))
            if inherited != base:
                label = "header+prev" if header else "prev"
                out.append((label, f"{header} {prev} {clean}".strip(), self.norm.apply_rules(inherited)))
        return out

    def match_line(self, clean: str, header: str = "", prev: str = "") -> dict:
        best = None
        for label, text, attrs in self.variants(clean, header, prev):
            key = norm_key(attrs)
            if key and key in self.aliases and self.aliases[key] in self._attrs:
                return self._result(key, label, [Candidate(self.aliases[key], 99, 99)], "auto", 1.0)
            ranked = self.rank(attrs, text)
            # เลือกชุดที่คะแนนสูงสุด ถ้าเท่ากันให้ใช้ชุดที่มีบริบทมากกว่า
            if best is None or ranked[0].score >= best[2][0].score:
                best = (key, label, ranked)
        key, label, ranked = best
        top = ranked[0]
        if top.matched < MIN_MATCHED:
            return self._result(key, label, ranked[:3], "not_found", 0.0)
        close = [c for c in ranked if top.score - c.score < AMBIGUOUS_MARGIN]
        if len(close) == 1:
            margin = top.score - ranked[1].score if len(ranked) > 1 else 9
            return self._result(key, label, ranked[:3], "auto", round(min(1.0, 0.6 + margin / 10), 2))
        names = {self.products.at[c.product_id, "receipt_name"] for c in close}
        sizes = {frozenset(self._attrs[c.product_id]["size"]) for c in close}
        status = "need_info" if len(names) == 1 or len(sizes) > 1 else "ambiguous"
        return self._result(key, label, close[:3] if len(close) >= 3 else ranked[:3], status, 0.3)

    def _result(self, key, label, cands: list[Candidate], status: str, conf: float) -> dict:
        top = cands[0] if cands and status != "not_found" else None
        return {
            "norm_key": key,
            "context_used": label,
            "product_id": top.product_id if top else "",
            "status": status,
            "confidence": conf,
            "candidates": json.dumps([
                {"product_id": c.product_id, "name": self.display_name(c.product_id),
                 "price": float(self.products.at[c.product_id, "unit_price"]), "score": c.score}
                for c in cands
            ], ensure_ascii=False),
        }

    def display_name(self, pid: str) -> str:
        return display_name(self.products.loc[pid])

    @property
    def max_auto_qty(self) -> int:
        return int(self.norm.cfg.get("max_auto_qty", 100))

    # ---------- ทั้งตาราง ----------
    def match(self, lines: pd.DataFrame) -> pd.DataFrame:
        results = []
        for r in lines.itertuples(index=False):
            if r.kind in FEE_PRODUCTS:
                res = {"norm_key": "", "context_used": "", "product_id": FEE_PRODUCTS[r.kind], "status": "auto",
                       "confidence": 1.0, "candidates": "[]"}
            elif r.kind == "order":
                res = self.match_line(r.clean_text, r.header_text or "", r.prev_text or "")
            else:
                res = self.match_line(r.clean_text) if r.clean_text else {
                    "norm_key": "", "context_used": "", "product_id": "", "candidates": "[]"}
                res.update(status=r.kind, confidence=0.0)
            if res["status"] == "auto" and (r.qty or 0) > self.max_auto_qty and r.kind == "order":
                res.update(status="qty_check", confidence=0.3)
            pid = res["product_id"]
            if pid:
                price = r.fee if r.kind in FEE_PRODUCTS else float(self.products.at[pid, "unit_price"])
                suffix = getattr(r, "suffix", "") or ""
                res["receipt_name"] = " ".join(filter(None, [self.display_name(pid), suffix]))
                # ชื่อเต็มพร้อมสีเสมอ (ไม่สน print_color) ใช้ตรวจว่าเลือกสินค้าถูกตัว
                color = self.products.at[pid, "color"]
                full = f"{self.products.at[pid, 'receipt_name']} สี{color}" if color else self.products.at[pid, "receipt_name"]
                res["full_name"] = " ".join(filter(None, [full, suffix]))
                res["unit_price"] = price
                res["amount"] = price * (r.qty or 0)
            else:
                res.update(receipt_name="", full_name="", unit_price=None, amount=None)
            results.append(res)
        out = pd.concat([lines.reset_index(drop=True), pd.DataFrame(results, columns=MATCH_COLUMNS)], axis=1)
        return out
