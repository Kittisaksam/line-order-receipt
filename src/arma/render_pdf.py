"""ขั้นที่ 7 — สร้าง PDF ใบเสร็จ (Jinja2 + WeasyPrint) และรวมเป็นไฟล์เดียวต่อเดือน"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfWriter

from .billing import Bill
from .thai_utils import bahttext, fmt_date_th, fmt_money, month_name_th


def _weasyprint():
    # macOS + Homebrew: ให้ WeasyPrint หา pango/cairo ใน /opt/homebrew/lib เจอ
    if sys.platform == "darwin" and "DYLD_FALLBACK_LIBRARY_PATH" not in os.environ:
        libs = [p for p in ("/opt/homebrew/lib", "/usr/local/lib") if Path(p).exists()]
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(libs)
    import weasyprint

    return weasyprint


def _font_css(templates_dir: Path, family: str) -> str:
    """ถ้ามีไฟล์ฟอนต์ใน templates/fonts ให้ใช้ (ไม่พึ่งฟอนต์ในเครื่อง)"""
    css = []
    for f in sorted((templates_dir / "fonts").glob("*.[ot]tf")):
        weight = 700 if "bold" in f.stem.lower() else 400
        style = "italic" if "italic" in f.stem.lower() else "normal"
        css.append(
            f'@font-face {{ font-family: "{family}"; src: url("{f.as_uri()}"); '
            f"font-weight: {weight}; font-style: {style}; }}"
        )
    css.append(f'body {{ font-family: "{family}", "Sarabun", "Noto Sans Thai", sans-serif; }}')
    return "\n".join(css)


class Renderer:
    def __init__(self, templates_dir: Path, settings: dict):
        self.templates_dir = templates_dir
        self.settings = settings
        env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html", "j2"]))
        self.template = env.get_template("receipt.html.j2")
        family = settings.get("pdf", {}).get("font_family", "Sarabun")
        self.css = (templates_dir / "receipt.css").read_text("utf-8") + "\n" + _font_css(templates_dir, family)

    def html(self, bill: Bill, draft: bool = False, summary: dict | None = None,
             rows: list[tuple[str, object]] | None = None) -> str:
        s = self.settings
        billing = s.get("billing", {})
        customer = s["customer"]
        return self.template.render(
            bill=bill,
            draft=draft,
            css=self.css,
            shop=s["shop"],
            customer=customer,
            ship_to=customer.get("ship_to") or customer,
            terms=billing.get("terms", "ครบกำหนดเมื่อได้รับ"),
            date_th=fmt_date_th(bill.date),
            fmt_date=fmt_date_th,
            money=fmt_money,
            summary=summary,
            rows=rows if rows is not None else [(bill.no, ln) for ln in bill.lines],
            baht_text=bahttext(bill.subtotal) if billing.get("print_bahttext") else "",
        )

    def render(self, bill: Bill, out: Path, draft: bool = False) -> Path:
        return self._write(self.html(bill, draft), out)

    def render_summary(self, bills: list[Bill], year: int, month: int, out: Path, draft: bool = False) -> Path:
        """ใบสรุปทั้งเดือน: รายการทุกบิลในตารางเดียว (ไม่ใช่ใบเสร็จ ไม่มีเลขที่ของตัวเอง)"""
        everything = Bill(lines=[ln for b in bills for ln in b.lines], time=bills[0].time, date_rule="last")
        numbers = [b.no for b in bills]
        covers = f"#{numbers[0]}" if len(numbers) == 1 else f"#{numbers[0]} – #{numbers[-1]}"
        summary = {
            "title": "ใบสรุปรายการประจำเดือน",
            "subtitle": f"เดือน{month_name_th(year, month)}",
            "covers": covers,
            "period": f"{fmt_date_th(min(b.date for b in bills))} – {fmt_date_th(everything.date)}",
            "bills": bills,
        }
        rows = [(b.no, ln) for b in bills for ln in b.lines]
        return self._write(self.html(everything, draft, summary=summary, rows=rows), out)

    def _write(self, html: str, out: Path) -> Path:
        wp = _weasyprint()
        out.parent.mkdir(parents=True, exist_ok=True)
        wp.HTML(string=html, base_url=str(self.templates_dir)).write_pdf(out)
        return out


def merge_pdfs(files: list[Path], out: Path) -> Path:
    writer = PdfWriter()
    for f in files:
        writer.append(str(f))
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        writer.write(fh)
    return out
