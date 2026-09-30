"""คำสั่งรวม: uv run arma <คำสั่ง>"""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Optional

import pandas as pd
import typer

from . import backtest as bt
from . import pipeline
from .billing import BillingConfig, BillLine, assign_numbers, make_bills, read_counter, write_counter
from .build_master import build_products, build_seed_aliases, write_xlsx
from .config import Project
from .render_pdf import Renderer, merge_pdfs
from .review import (
    ReviewError, append_history, display_name, learn_aliases, read_review, write_products_list, write_review,
)
from .thai_utils import month_label, month_name_th, parse_month

app = typer.Typer(help="ARMA LASER: แปลงออเดอร์จาก LINE → ใบเสร็จรับเงิน PDF รายเดือน", no_args_is_help=True)

MonthArg = Annotated[str, typer.Argument(help="เดือน เช่น 2569-10 (พ.ศ.) หรือ 2026-10")]


def _load_products(project: Project) -> pd.DataFrame:
    return pd.read_excel(project.products_path, dtype={"color": str}, keep_default_na=False)


@app.command("build-master")
def build_master_cmd(
    docx: Annotated[Optional[Path], typer.Option(help="ไฟล์ตารางราคากลาง .docx")] = None,
    force: Annotated[bool, typer.Option("--force", help="เขียนทับ products.xlsx / aliases.xlsx ที่มีอยู่")] = False,
):
    """ขั้นที่ 0: ตารางราคากลาง.docx → master/products.xlsx (+ seed aliases.xlsx)"""
    project = Project.load()
    docx = docx or project.root / project.settings["paths"]["price_docx"]
    norm = pipeline.load_normalizer(project)
    if project.products_path.exists() and not force:
        typer.echo(f"มี {project.products_path} อยู่แล้ว (อาจแก้ราคาไว้) — ใช้ --force ถ้าต้องการสร้างใหม่")
        raise typer.Exit(1)
    products = build_products(docx, norm)
    write_xlsx(products, project.products_path, "products")
    typer.echo(f"✔ {project.products_path.relative_to(project.root)}: {len(products)} รายการ")
    if not project.aliases_path.exists() or force:
        aliases = build_seed_aliases(products, norm)
        write_xlsx(aliases, project.aliases_path, "aliases")
        typer.echo(f"✔ {project.aliases_path.relative_to(project.root)}: seed {len(aliases)} alias")
    typer.echo("→ เปิด products.xlsx ตรวจราคาก่อนใช้งานจริง")


@app.command()
def prepare(
    month: MonthArg,
    chat: Annotated[Optional[Path], typer.Option(help="ไฟล์ export แชท LINE (.txt)")] = None,
    force: Annotated[bool, typer.Option("--force", help="เขียนทับ review.csv ที่มีอยู่ (งานที่ตรวจไว้จะหาย)")] = False,
):
    """ขั้นที่ 1–5: parse + extract + match → work/<เดือน>/review.csv"""
    project = Project.load()
    year, mon = parse_month(month)
    label = month_label(month)
    work = project.work_dir(label)
    review_path = work / "review.csv"
    if review_path.exists() and not force:
        typer.echo(f"มี {review_path.relative_to(project.root)} อยู่แล้ว — ใช้ --force ถ้าต้องการสร้างใหม่ (งานที่ตรวจไว้จะหาย)")
        raise typer.Exit(1)
    chat_path = project.chat_path(label, chat)
    typer.echo(f"อ่านแชท: {chat_path}")
    messages, lines = pipeline.run(project, chat_path, year=year, month=mon)
    work.mkdir(parents=True, exist_ok=True)
    messages.to_parquet(work / "messages.parquet", index=False)
    lines.to_parquet(work / "order_lines.parquet", index=False)
    write_review(lines, _load_products(project), review_path)
    write_products_list(_load_products(project), work / "products.csv")

    counts = lines["status"].value_counts().to_dict()
    typer.echo(f"ข้อความเดือน {month_name_th(year, mon)}: {len(messages)} | รายการที่ดึงได้: {len(lines)}")
    for status, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {status:<12} {n}")
    typer.echo(f"✔ {review_path.relative_to(project.root)}  (รายการสินค้า: {(work / 'products.csv').relative_to(project.root)})")
    typer.echo("→ แถวที่สถานะไม่ใช่ auto: ใส่ product_id ที่ถูก + ใส่อะไรก็ได้ในช่อง 'ยืนยัน' (หรือ N ในช่อง 'รวมในบิล')")
    typer.echo(f"→ บันทึกเป็น CSV (UTF-8) แล้วรัน `uv run arma finalize {label}`")


def _build_bills(project: Project, year: int, mon: int, label: str):
    """อ่าน review.csv → (รายการที่ยืนยัน, บิลตาม settings)"""
    products = _load_products(project)
    last_day = date(year, mon, calendar.monthrange(year, mon)[1])
    confirmed = read_review(project.work_dir(label) / "review.csv", products, default_date=last_day)
    by_id = products.set_index("product_id", drop=False)
    lines = [
        BillLine(date=c.date, qty=c.qty, product_id=c.product_id,
                 description=" ".join(filter(None, [display_name(by_id.loc[c.product_id]), c.suffix])),
                 unit_price=c.unit_price)
        for c in confirmed
    ]
    return confirmed, make_bills(lines, BillingConfig.from_settings(project.settings.get("billing", {})))


def _render_month(project: Project, bills, year: int, mon: int, label: str, draft: bool, merged_name: str,
                  summary_name: str | None) -> tuple[Path, Path | None]:
    out_dir = project.output_dir(label)
    renderer = Renderer(project.templates_dir, project.settings)
    files = [renderer.render(b, out_dir / f"receipt_{b.no}.pdf", draft=draft) for b in bills]
    merged = merge_pdfs(files, out_dir / merged_name)
    summary = renderer.render_summary(bills, year, mon, out_dir / summary_name, draft=draft) if summary_name else None
    return merged, summary


@app.command()
def finalize(
    month: MonthArg,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="สร้าง PDF ร่าง (#DRAFT, ลายน้ำ) ไม่เปลี่ยนเลขที่/alias")] = False,
    force: Annotated[bool, typer.Option("--force", help="ออกบิลซ้ำแม้เดือนนี้เคย finalize แล้ว (จะได้เลขที่ใหม่)")] = False,
):
    """ขั้นที่ 5–7: อ่าน review.csv → เรียนรู้ alias → จัดบิล → PDF"""
    project = Project.load()
    year, mon = parse_month(month)
    label = month_label(month)
    review_path = project.work_dir(label) / "review.csv"
    done_path = project.work_dir(label) / "finalized.json"
    if not review_path.exists():
        typer.echo(f"ไม่พบ {review_path} — รัน `uv run arma prepare {label}` ก่อน")
        raise typer.Exit(1)
    if done_path.exists() and not dry_run and not force:
        done = json.loads(done_path.read_text("utf-8"))
        typer.echo(f"เดือนนี้ออกบิลไปแล้ว ({', '.join('#' + n for n in done['bills'])}) — ใช้ --force ถ้าต้องการออกใหม่")
        raise typer.Exit(1)

    try:
        confirmed, bills = _build_bills(project, year, mon, label)
    except ReviewError as e:
        typer.echo("ยังตรวจ review.csv ไม่ครบ:\n" + str(e))
        raise typer.Exit(1)
    if not bills:
        typer.echo("ไม่มีรายการที่รวมในบิล")
        raise typer.Exit(1)
    last_no = read_counter(project.counter_path)
    new_last = assign_numbers(bills, last_no, dry_run)

    today = date.today().isoformat()
    suffix = "-DRAFT" if dry_run else ""
    want_summary = project.settings.get("billing", {}).get("monthly_summary", False)
    merged, summary = _render_month(
        project, bills, year, mon, label, dry_run,
        merged_name=f"{today}-arma-receipts-{label}{suffix}.pdf",
        summary_name=f"{today}-arma-summary-{label}{suffix}.pdf" if want_summary else None,
    )

    if not dry_run:
        write_counter(project.counter_path, new_last)
        learned = learn_aliases(confirmed, project.aliases_path)
        append_history(confirmed, project.history_path, label)
        done_path.write_text(json.dumps({
            "bills": [b.no for b in bills], "finalized_at": datetime.now().isoformat(timespec="seconds"),
            "file": merged.name, "summary_file": summary.name if summary else None,
        }, ensure_ascii=False), "utf-8")
        typer.echo(f"เรียนรู้ alias ใหม่: {learned}")

    for b in bills:
        typer.echo(f"  #{b.no:<9} {b.date:%d/%m} {len(b.lines):>3} รายการ {b.subtotal:>12,.2f} บาท")
    total = sum(b.subtotal for b in bills)
    typer.echo(f"✔ {len(bills)} บิล, {len(confirmed)} รายการ, ยอดรวม {total:,.2f} บาท")
    typer.echo(f"✔ {merged.relative_to(project.root)}")
    if summary:
        typer.echo(f"✔ {summary.relative_to(project.root)} (ใบสรุปเดือน)")
    typer.echo("\nข้อความสำหรับส่ง LINE:\n" + lot_message(year, mon, [b.no for b in bills]))


@app.command()
def reprint(month: MonthArg):
    """พิมพ์ PDF ของเดือนที่ออกบิลแล้วใหม่ (เช่น หลังแก้หน้าตา template) โดยใช้เลขที่เดิม"""
    project = Project.load()
    year, mon = parse_month(month)
    label = month_label(month)
    done_path = project.work_dir(label) / "finalized.json"
    if not done_path.exists():
        typer.echo(f"เดือน {label} ยังไม่เคยออกบิล — ใช้ `uv run arma finalize {label}`")
        raise typer.Exit(1)
    done = json.loads(done_path.read_text("utf-8"))
    _, bills = _build_bills(project, year, mon, label)
    if len(bills) != len(done["bills"]):
        typer.echo(f"จำนวนบิลไม่ตรงกับที่ออกไว้ ({len(bills)} ≠ {len(done['bills'])}) — review.csv หรือ settings ถูกแก้หลังออกบิล")
        raise typer.Exit(1)
    for b, no in zip(bills, done["bills"]):
        b.no = no
    merged, summary = _render_month(project, bills, year, mon, label, False, done["file"], done.get("summary_file"))
    typer.echo(f"✔ พิมพ์ใหม่ {', '.join('#' + n for n in done['bills'])} → {merged.relative_to(project.root)}")
    if summary:
        typer.echo(f"✔ {summary.relative_to(project.root)} (ใบสรุปเดือน)")


def lot_message(year: int, mon: int, numbers: list[str]) -> str:
    return (
        f"*Lot เดือน{month_name_th(year, mon)}\n"
        f"รวมไฟล์ PDF ทั้งหมด {len(numbers)} บิล\n"
        + " ".join(f"#{n}" for n in numbers)
    )


@app.command()
def backtest(
    set_: Annotated[str, typer.Option("--set", help=f"ชุดเฉลย: {' | '.join(bt.SETS)}")] = "309-317",
    no_aliases: Annotated[bool, typer.Option("--no-aliases", help="ไม่ใช้ aliases.xlsx (วัดความสามารถของ rule ล้วน)")] = False,
    show: Annotated[bool, typer.Option("--show", help="แสดงรายการที่ไม่ตรง")] = False,
    chat: Annotated[Optional[Path], typer.Option(help="ไฟล์ export แชท LINE (.txt)")] = None,
):
    """วัดผลกับใบเสร็จเฉลย (#309–#317 หรือ #330–#336)"""
    if set_ not in bt.SETS:
        typer.echo(f"ไม่รู้จักชุดเฉลย {set_!r} — เลือกจาก {', '.join(bt.SETS)}")
        raise typer.Exit(1)
    fixture, (start, end) = bt.SETS[set_]
    project = Project.load()
    chat_path = chat or project.root / project.settings["paths"]["default_chat"]
    _, lines = pipeline.run(project, chat_path, start=start, end=end, use_aliases=not no_aliases)
    expected = bt.load_expected(project.root / "tests" / "fixtures" / fixture)
    result = bt.compare(lines, expected, pipeline.load_normalizer(project))
    typer.echo(f"ชุดเฉลย #{set_} (แชท {start:%d/%m}–{end:%d/%m})")
    typer.echo(result.summary())
    if show:
        d = result.detail
        with pd.option_context("display.width", 250, "display.max_colwidth", 70, "display.max_rows", 500):
            typer.echo(d[d["result"] != "correct"].to_string())


if __name__ == "__main__":
    app()
