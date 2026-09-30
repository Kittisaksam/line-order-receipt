"""ขั้นที่ 5 — สร้าง/อ่านไฟล์ตรวจทาน review.csv และเรียนรู้ alias"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from .thai_utils import fmt_date_th, parse_date_th

# utf-8-sig: ให้ Excel เปิดภาษาไทยได้ถูกต้อง
ENCODING = "utf-8-sig"

C_ID = "line_id"
C_DATE = "วันที่"
C_SENDER = "ผู้ส่ง"
C_TEXT = "ข้อความต้นฉบับ"
C_CTX = "บริบทที่ใช้"
C_QTY = "จำนวน"
C_STATUS = "สถานะ"
C_PRODUCT = "product_id"
C_NAME = "ชื่อสินค้า (อ้างอิง)"
C_SUFFIX = "ต่อท้ายชื่อ"
C_LIST_PRICE = "ราคาตามตาราง (อ้างอิง)"
C_PRICE = "ราคา (เว้นว่าง = ตามตาราง)"
C_OTHER = "ตัวเลือกอื่น"
C_CONFIRM = "ยืนยัน"
C_INCLUDE = "รวมในบิล (Y/N)"
C_NOTE = "หมายเหตุ"
C_KEY = "norm_key"
C_SUGGEST = "ระบบเลือก"
COLUMNS = [C_ID, C_DATE, C_SENDER, C_TEXT, C_CTX, C_QTY, C_STATUS, C_PRODUCT, C_NAME, C_SUFFIX, C_LIST_PRICE,
           C_PRICE, C_OTHER, C_CONFIRM, C_INCLUDE, C_NOTE, C_KEY, C_SUGGEST]

STATUS_ORDER = ["not_found", "file_order", "qty_missing", "qty_check", "ambiguous", "need_info", "claim", "auto"]
REVIEW_STATUSES = {"ambiguous", "need_info", "qty_check", "not_found", "file_order", "qty_missing"}
SERVICE_PREFIX = "SV-"  # ค่าบริการ: ราคาแปรผันตามข้อความ


def _active(products: pd.DataFrame) -> pd.DataFrame:
    return products[products["active"].astype(str).str.lower().isin(["true", "1", "yes", "y"])]


def _prints_color(r) -> bool:
    return str(r["print_color"]).lower() in ("true", "1") and bool(r["color"])


def display_name(r) -> str:
    """ชื่อที่พิมพ์ลงใบเสร็จ: receipt_name + 'สีxxx' (ถ้า print_color)"""
    return f"{r['receipt_name']} สี{r['color']}" if _prints_color(r) else str(r["receipt_name"])


def write_products_list(products: pd.DataFrame, path: Path) -> None:
    """รายการสินค้าสำหรับค้น product_id ตอนตรวจ review.csv"""
    df = _active(products)
    out = pd.DataFrame({
        "product_id": df["product_id"],
        "ชื่อในใบเสร็จ": [display_name(r) for _, r in df.iterrows()],
        "สี": df["color"],
        "ราคา": df["unit_price"],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(path, index=False, encoding=ENCODING)


def write_review(order_lines: pd.DataFrame, products: pd.DataFrame, path: Path) -> None:
    by_id = _active(products).set_index("product_id", drop=False)
    df = order_lines.copy()
    df["_order"] = [STATUS_ORDER.index(s) if s in STATUS_ORDER else 0 for s in df["status"]]
    df = df.sort_values(["_order", "date", "line_id"])

    rows = []
    for _, r in df.iterrows():
        status = r["status"]
        pid = r["product_id"] or ""
        known = pid in by_id.index
        others = [
            f"{c['product_id']} = {c['name']} ({c['price']:g})"
            for c in json.loads(r["candidates"] or "[]") if c["product_id"] != pid
        ]
        rows.append({
            C_ID: int(r["line_id"]),
            C_DATE: fmt_date_th(r["date"]),
            C_SENDER: r["sender"],
            C_TEXT: r["raw_line"] if r["kind"] == "order" else r["raw_message"],
            C_CTX: r.get("context_used") or "",
            C_QTY: int(r["qty"]) if pd.notna(r["qty"]) else "",
            C_STATUS: status,
            C_PRODUCT: pid,
            C_NAME: display_name(by_id.loc[pid]) if known else "",
            C_SUFFIX: r.get("suffix") or "",
            C_LIST_PRICE: f"{float(by_id.at[pid, 'unit_price']):g}" if known else "",
            # ค่าบริการราคาแปรผัน → ใส่ราคาจากข้อความไว้เลย
            C_PRICE: f"{float(r['unit_price']):g}" if pid.startswith(SERVICE_PREFIX) else "",
            C_OTHER: " / ".join(others[:3]),
            C_CONFIRM: "",
            C_INCLUDE: "N" if status == "claim" else ("Y" if status in ("auto", "ambiguous", "need_info", "qty_check") else ""),
            C_NOTE: "",
            C_KEY: r["norm_key"] or "",
            C_SUGGEST: pid,
        })
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=COLUMNS).to_csv(path, index=False, encoding=ENCODING)


@dataclass
class ConfirmedLine:
    date: date
    qty: int
    product_id: str
    unit_price: Decimal
    raw_text: str
    norm_key: str
    learn: bool  # คนแก้/ยืนยัน → เรียนรู้ alias
    suffix: str = ""  # ต่อท้ายชื่อในใบเสร็จ เช่น "กาวดำ", "EASY PASS"


class ReviewError(Exception):
    pass


def read_review(path: Path, products: pd.DataFrame, default_date: date) -> list[ConfirmedLine]:
    try:
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding=ENCODING)
    except UnicodeDecodeError:
        # Excel บน Windows อาจบันทึก CSV เป็น encoding ภาษาไทย (cp874) แทน UTF-8
        df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="cp874")
    missing = [c for c in (C_PRODUCT, C_QTY, C_STATUS, C_INCLUDE, C_CONFIRM) if c not in df.columns]
    if missing:
        raise ReviewError(f"review.csv ไม่มีคอลัมน์: {', '.join(missing)} (ห้ามแก้แถวหัวตาราง)")
    prices = {r["product_id"]: Decimal(str(r["unit_price"])) for _, r in products.iterrows()}
    problems: list[str] = []
    out: list[ConfirmedLine] = []
    for idx, row in df.iterrows():
        v = {k: str(val).strip() for k, val in row.items()}
        pid = v.get(C_PRODUCT, "")
        status = v.get(C_STATUS, "") or "manual"
        include = v.get(C_INCLUDE, "").upper()
        confirmed = bool(v.get(C_CONFIRM, ""))
        text = v.get(C_TEXT, "")
        if not any([pid, v.get(C_QTY), text, v.get(C_ID)]):
            continue  # แถวว่าง
        where = f"แถว {idx + 2} ({text[:30]!r})"
        if include == "N":
            continue
        if include != "Y":
            if status == "manual" and pid:
                include = "Y"
            else:
                problems.append(f"{where}: สถานะ {status} — ใส่ Y หรือ N ในช่อง 'รวมในบิล'")
                continue
        if status in REVIEW_STATUSES and not confirmed:
            problems.append(f"{where}: สถานะ {status} — ตรวจแล้วใส่ ✔ ในช่อง 'ยืนยัน'")
            continue
        if not pid or pid not in prices:
            problems.append(f"{where}: ยังไม่ได้เลือกสินค้า หรือสินค้าไม่อยู่ในรายการ")
            continue
        qty_raw = v.get(C_QTY, "")
        try:
            qty = int(float(qty_raw.replace(",", "")))
        except ValueError:
            problems.append(f"{where}: จำนวนไม่ถูกต้อง ({qty_raw!r})")
            continue
        if qty <= 0:
            problems.append(f"{where}: จำนวนต้องมากกว่า 0")
            continue
        price_raw = v.get(C_PRICE, "").replace(",", "")
        try:
            price = Decimal(price_raw) if price_raw else prices[pid]  # ผู้ใช้พิมพ์ราคาเอง / ค่าส่ง
        except InvalidOperation:
            problems.append(f"{where}: ราคาไม่ถูกต้อง ({price_raw!r})")
            continue
        try:
            d = parse_date_th(v[C_DATE]) if v.get(C_DATE) else default_date
        except ValueError:
            problems.append(f"{where}: วันที่ไม่ถูกต้อง ({v[C_DATE]!r}) ต้องเป็น dd/mm/yyyy")
            continue
        suggested = v.get(C_SUGGEST, "")
        out.append(ConfirmedLine(
            date=d, qty=qty, product_id=pid, unit_price=price, raw_text=text,
            norm_key=v.get(C_KEY, ""),
            learn=bool(v.get(C_KEY)) and not pid.startswith(SERVICE_PREFIX) and (status != "auto" or pid != suggested),
            suffix=v.get(C_SUFFIX, ""),
        ))
    if problems:
        raise ReviewError("\n".join(problems))
    return out


def learn_aliases(lines: list[ConfirmedLine], aliases_path: Path) -> int:
    """เพิ่ม/แก้ alias จากแถวที่คนยืนยัน (สำรองไฟล์เดิมก่อนเขียน) คืนจำนวนที่เปลี่ยน"""
    new = {ln.norm_key: ln for ln in lines if ln.learn}
    if not new:
        return 0
    if aliases_path.exists():
        df = pd.read_excel(aliases_path, dtype=str, keep_default_na=False)
        backup = aliases_path.with_name(f"{aliases_path.stem}.{datetime.now():%Y%m%d-%H%M%S}.bak.xlsx")
        shutil.copy2(aliases_path, backup)
    else:
        df = pd.DataFrame(columns=["alias_key", "product_id", "example_text", "source", "confirmed_at"])
    changed = 0
    today = date.today().isoformat()
    for key, ln in new.items():
        hit = df.index[df["alias_key"] == key]
        if len(hit) and df.at[hit[0], "product_id"] == ln.product_id:
            continue
        rec = {"alias_key": key, "product_id": ln.product_id, "example_text": ln.raw_text,
               "source": "review", "confirmed_at": today}
        if len(hit):
            for k, val in rec.items():
                df.at[hit[0], k] = val
        else:
            df = pd.concat([df, pd.DataFrame([rec])], ignore_index=True)
        changed += 1
    from .build_master import write_xlsx

    write_xlsx(df, aliases_path, "aliases")
    return changed


def append_history(lines: list[ConfirmedLine], history_path: Path, month: str) -> None:
    rows = pd.DataFrame([{"month": month, "date": ln.date.isoformat(), "product_id": ln.product_id,
                          "qty": ln.qty} for ln in lines])
    if history_path.exists():
        old = pd.read_csv(history_path, dtype=str)
        old = old[old["month"] != month]  # รันซ้ำเดือนเดิม → แทนที่
        rows = pd.concat([old, rows.astype(str)], ignore_index=True)
    rows.to_csv(history_path, index=False)
