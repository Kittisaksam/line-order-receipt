"""ขั้นที่ 2 — จัดประเภทข้อความ แยกบรรทัดสั่งของ และดึงจำนวน"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cached_property

import pandas as pd

from .normalize import Normalizer

ATTACHMENTS = {"[ไฟล์]", "[รูป]", "[อัลบั้ม]"}

COLUMNS = [
    "line_id", "msg_id", "date", "time", "sender", "kind", "raw_message", "raw_line",
    "clean_text", "header_text", "prev_text", "qty", "fee", "suffix",
]
FOLLOWUP_MINUTES = 10  # ข้อความที่มีแต่จำนวน ต้องตามมาภายในกี่นาที จึงนับเป็นจำนวนของข้อความก่อนหน้า


@dataclass
class Extractor:
    norm: Normalizer

    @cached_property
    def cfg(self) -> dict:
        return self.norm.cfg

    @cached_property
    def _protect(self) -> re.Pattern:
        return re.compile("|".join(f"(?:{p})" for p in self.cfg.get("protect", [])))

    @cached_property
    def _drop(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.cfg.get("drop_phrases", [])]

    @cached_property
    def _qty(self) -> re.Pattern:
        units = "|".join(re.escape(u) for u in sorted(self.norm.units, key=len, reverse=True))
        return re.compile(rf"(?<![\d.])(\d+)(?![\d.])\s*({units})?")

    @cached_property
    def _shipping(self) -> re.Pattern:
        return re.compile(self.cfg["shipping_fee"])

    @cached_property
    def _design(self) -> tuple[re.Pattern, re.Pattern] | None:
        d = self.cfg.get("design_fee")
        return (re.compile(d["markers"]), re.compile(d["amount"])) if d else None

    @cached_property
    def _notes(self) -> list[re.Pattern]:
        return [re.compile(p) for p in self.cfg.get("note_phrases", [])]

    def notes(self, line: str) -> str:
        """วลีที่ต้องพิมพ์ต่อท้ายชื่อในใบเสร็จ เช่น 'กาวดำ'"""
        s = self.norm.clean(line)
        return " ".join(m.group(0) for pat in self._notes for m in pat.finditer(s))

    def design_subject(self, text: str) -> str:
        """'สั่งปรินต์ Easy Pass 200 บาท' → 'EASY PASS'"""
        markers, amount = self._design
        s = amount.sub(" ", text)
        s = markers.sub(" ", s)
        s = re.sub(r"^\s*สั่ง|หนึ่ง\s*(?:ชุด|ชิ้น|อัน)|\d+\s*(?:ชุด|ชิ้น|อัน)|ครับ|ค่ะ|นะ", " ", s)
        return re.sub(r"\s+", " ", s).strip().upper()

    @cached_property
    def _thai_num(self) -> re.Pattern | None:
        nums = self.cfg.get("thai_numbers") or {}
        if not nums:
            return None
        units = "|".join(re.escape(u) for u in self.norm.units)
        return re.compile(rf"({'|'.join(map(re.escape, nums))})\s*(?=(?:{units}))")

    @cached_property
    def _multi_attrs(self) -> dict[str, str]:
        """คำที่ใช้แยก 1 บรรทัดเป็นหลายรายการ เช่น 'fortuner ใหญ่ 5 เล็ก 5' (ขนาด/สี)"""
        vocab = self.cfg["vocab"]
        return {w: attr for attr in ("size", "color") for canon in vocab[attr] for w in [canon]}

    # ---------- บรรทัดเดียว ----------
    def _prepare(self, line: str) -> str:
        s = self.norm.clean(line)
        for pat in self._drop:
            s = pat.sub(" ", s)
        if self._thai_num:
            nums = self.cfg["thai_numbers"]
            s = self._thai_num.sub(lambda m: f"{nums[m.group(1)]} ", s)
        return re.sub(r"\s+", " ", s).strip()

    def _qty_candidates(self, s: str) -> list[re.Match]:
        protected = [m.span() for m in self._protect.finditer(s)]
        return [
            m for m in self._qty.finditer(s)
            if not any(a < m.end(1) and m.start(1) < b for a, b in protected)
        ]

    def split_qty(self, line: str) -> tuple[str, int | None]:
        """คืน (ข้อความที่ normalize แล้วโดยตัดจำนวนออก, จำนวน)"""
        s = self._prepare(line)
        cands = self._qty_candidates(s)
        if not cands:
            return s, None
        chosen = next((m for m in cands if m.group(2)), cands[-1])
        rest = (s[: chosen.start()] + " " + s[chosen.end():]).strip()
        return re.sub(r"\s+", " ", rest), int(chosen.group(1))

    def split_items(self, line: str) -> list[tuple[str, int | None]]:
        """เหมือน split_qty แต่แยก 'xxx ใหญ่ 5 เล็ก 5' เป็น 2 รายการ"""
        s = self._prepare(line)
        cands = self._qty_candidates(s)
        if len(cands) >= 2:
            words = []
            for m in cands:
                w = re.search(r"(\S+)\s*$", s[: m.start()])
                words.append(w)
            kinds = {self._multi_attrs.get(w.group(1)) if w else None for w in words}
            distinct = len({w.group(1) for w in words if w}) == len(cands)
            if None not in kinds and len(kinds) == 1 and distinct:
                prefix = s[: words[0].start(1)].strip()
                return [(f"{prefix} {w.group(1)}", int(m.group(1))) for w, m in zip(words, cands)]
        return [self.split_qty(line)]

    def product_word_kinds(self, text: str) -> int:
        """จำนวนชนิดคุณลักษณะสินค้า (ไม่นับสี) ที่พบในข้อความ"""
        attrs = self.norm.attributes(text, apply_rules=False)
        return len({a for a, v in attrs.items() if v and a != "color"})

    def has_product_words(self, text: str) -> bool:
        return self.product_word_kinds(text) > 0

    # ---------- ทั้งข้อความ ----------
    def classify(self, text: str, prev_text: str | None) -> str:
        if any(m.lower() in text.lower() for m in self.cfg.get("non_order_markers", [])):
            return "other"
        if self._shipping.search(text):
            return "shipping_fee"
        if self._design and self._design[0].search(text) and self._design[1].search(text):
            return "design_fee"
        if any(m in text for m in self.cfg.get("claim_markers", [])):
            return "claim"
        if re.search(r"สั่งตัด|ชุดนี้|อันนี้|ตามไฟล์|ตามรูป", text) and prev_text in ATTACHMENTS:
            return "file_order"
        if re.search(r"\d", text):
            if self.has_product_words(text):
                return "order"
            units = "|".join(map(re.escape, self.norm.units))
            if re.search(rf"\d\s*(?:{units})", text):
                return "order"
            return "other"
        return "qty_missing" if self.product_word_kinds(text) >= 2 else "other"

    def _followup_qty(self, text: str) -> int | None:
        """ข้อความที่มีแต่จำนวน ไม่มีชื่อสินค้า เช่น 'สั่งหนึ่งชุด' → 1"""
        s = self._prepare(text)
        cands = self._qty_candidates(s)
        if len(cands) != 1:
            return None
        rest = s[: cands[0].start()] + s[cands[0].end():]
        return None if self.has_product_words(rest) else int(cands[0].group(1))

    def extract(self, messages: pd.DataFrame) -> pd.DataFrame:
        rows: list[dict] = []
        prev_by_sender: dict[str, str] = {}
        # ผู้ส่ง → (แถว qty_missing, ข้อความ, [(บรรทัดดิบ, บรรทัด clean)]) รอจำนวนจากข้อความถัดไป
        pending: dict[str, tuple[dict, object, list[tuple[str, str]]]] = {}

        def add(msg, kind, raw_line="", clean="", qty=None, header="", prev="", fee=None, suffix=""):
            row = {
                "msg_id": msg.msg_id, "date": msg.date, "time": msg.time, "sender": msg.sender,
                "kind": kind, "raw_message": msg.text, "raw_line": raw_line or msg.text,
                "clean_text": clean, "header_text": header, "prev_text": prev, "qty": qty, "fee": fee,
                "suffix": suffix,
            }
            rows.append(row)
            return row

        def minutes(t: str) -> int:
            hh, mm = t.split(":")
            return int(hh) * 60 + int(mm)

        for msg in messages.itertuples(index=False):
            prev = prev_by_sender.get(msg.sender)
            prev_by_sender[msg.sender] = msg.text
            if msg.is_system:
                continue
            waiting = pending.pop(msg.sender, None)
            if waiting:
                row, first, items = waiting
                qty = None
                if first.date == msg.date and 0 <= minutes(msg.time) - minutes(first.time) <= FOLLOWUP_MINUTES:
                    qty = self._followup_qty(msg.text)
                if qty is not None:
                    rows.remove(row)
                    prev_line = ""
                    for raw, clean in items:
                        add(first, "order", raw_line=raw, clean=clean, qty=qty, prev=prev_line,
                            suffix=self.notes(raw))
                        prev_line = clean
                    continue
            kind = self.classify(msg.text, prev)
            if kind == "other":
                continue
            if kind == "shipping_fee":
                fee = float(self._shipping.search(msg.text).group(1))
                add(msg, kind, clean="ค่าส่ง", qty=1, fee=fee)
                continue
            if kind == "design_fee":
                fee = float(self._design[1].search(msg.text).group(1).replace(",", ""))
                add(msg, kind, clean="ค่าออกแบบ", qty=1, fee=fee, suffix=self.design_subject(msg.text))
                continue
            if kind in ("claim", "file_order", "qty_missing"):
                clean, qty = self.split_qty(msg.text.replace("\n", " "))
                row = add(msg, kind, clean=clean, qty=qty)
                if kind == "qty_missing":
                    items = [(ln.strip(), self._prepare(ln)) for ln in msg.text.split("\n") if ln.strip()]
                    pending[msg.sender] = (row, msg, items)
                continue

            headers: list[tuple[str, str]] = []
            prev_line = ""
            for raw in msg.text.split("\n"):
                if not raw.strip():
                    continue
                for clean, qty in self.split_items(raw):
                    if qty is None:
                        if clean and self.has_product_words(clean):
                            headers.append((raw.strip(), clean))
                        continue
                    add(msg, "order", raw_line=raw.strip(), clean=clean, qty=qty,
                        header=" ".join(c for _, c in headers), prev=prev_line, suffix=self.notes(raw))
                    prev_line = clean
            header_text = " ".join(c for _, c in headers)
            if not prev_line and headers and (
                self.product_word_kinds(header_text) >= 2 or msg.text.lstrip().startswith("สั่ง")
            ):
                # มีคำสินค้าแต่ไม่มีจำนวนเลยทั้งข้อความ → ให้คนตรวจ ไม่ทิ้งเงียบๆ
                # (ถ้าข้อความถัดไปบอกจำนวน จะถูกแทนด้วยรายการทีละบรรทัด)
                row = add(msg, "qty_missing", clean=header_text)
                pending[msg.sender] = (row, msg, headers)

        df = pd.DataFrame(rows, columns=COLUMNS)
        df["line_id"] = range(1, len(df) + 1)
        return df
