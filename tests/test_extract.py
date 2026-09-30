from datetime import date

import pandas as pd
import pytest


@pytest.mark.parametrize(
    ("line", "qty"),
    [
        ("Hirux แดง 4มือจับ", 4),
        ("Type r กระจัง 8 ใช้ก่อน 5", 8),
        ("- โลโก้ Hilux ท้ายรถ 1 มิล สีขาว 10 ชิ้นใช้ก่อน 6", 10),
        ("มือเปิดกระบะท้ายโควเมื่ยม 1 mm 10 ชุด", 10),
        ("Rangerท้าย33cm 3Dปริ้น  4ชุด", 4),
        ("Gr กระจังหน้า yaris cross 10 ตัวเล้ก", 10),
        ("สั่งโลโก้ โตโยต้ากระบะท้าย สีขาว 10 ชิ้นใช้ก่อนเที่ยง 5 ชุด", 10),
        ("ปรินต์ Easy Pass หนึ่งชุด 200 บาท", 1),
        ("Hirux 65-70", None),
        ("S1  1", 1),
    ],
)
def test_split_qty(extractor, line, qty):
    assert extractor.split_qty(line)[1] == qty


def test_split_qty_removes_quantity_text(extractor):
    text, qty = extractor.split_qty("Hirux แดง 4มือจับ")
    assert (text, qty) == ("hilux แดง มือจับ", 4)


def test_split_items_two_sizes_in_one_line(extractor):
    assert extractor.split_items("กระจังหน้าfortuner ใหญ่ 5 เล็ก 5") == [
        ("กระจังหน้า fortuner ใหญ่", 5),
        ("กระจังหน้า fortuner เล็ก", 5),
    ]


def _messages(*texts, sender="A"):
    return pd.DataFrame([
        {"msg_id": i, "date": date(2026, 6, 24), "time": "11:12", "sender": sender, "text": t,
         "is_system": t.startswith("[")}
        for i, t in enumerate(texts, start=1)
    ])


def test_context_header_is_carried_to_following_lines(extractor):
    lines = extractor.extract(_messages("Gr ตัวใหย่ \nกระจังหน้า yaris ativ 10  ชิ้น\n               Toyota travo 10 ชิ้น"))
    assert list(lines["qty"]) == [10, 10]
    assert set(lines["header_text"]) == {"gr ใหญ่"}
    assert lines.iloc[1]["prev_text"] == "กระจังหน้า yaris ativ"


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("มีค่าส่ง 85 บาท ครับ", "shipping_fee"),
        ("ส่งตัว N เคลมลูกค้าหน่อยจ้า", "claim"),
        ("@ลูกค้า รบกวนเคลียร์บิลให้พี่หน่อยครับ", None),
        ("อัพเดทราคาใหม่ Toyota 170-180", None),
        ("ครับ", None),
        ("Yaris cross ดำเงา 15", "order"),
    ],
)
def test_classify(extractor, text, kind):
    lines = extractor.extract(_messages(text))
    assert (lines.iloc[0]["kind"] if len(lines) else None) == kind


def test_file_order_after_attachment(extractor):
    lines = extractor.extract(_messages("[ไฟล์]", "[รูป]", "สั่งตัด 3 ชุดนี้"))
    assert list(lines["kind"]) == ["file_order"]


def test_design_fee_uses_amount_and_subject(extractor):
    lines = extractor.extract(_messages("สั่งปรินต์ Easy Pass 200 บาท", "สั่งออกแบบตะแกรงค่าทำไฟล์ 2000 บาท"))
    assert list(lines["kind"]) == ["design_fee", "design_fee"]
    assert list(lines["fee"]) == [200, 2000]
    assert list(lines["suffix"]) == ["EASY PASS", "ตะแกรง"]


def test_note_phrase_goes_to_suffix(extractor):
    lines = extractor.extract(_messages("Toyotaท้ายรถ สีขาว กาวดำ 1 ชุด"))
    assert lines.iloc[0]["suffix"] == "กาวดำ"
    assert lines.iloc[0]["qty"] == 1


def _timed(*items, sender="A"):
    return pd.DataFrame([
        {"msg_id": i, "date": date(2026, 9, 19), "time": t, "sender": sender, "text": text, "is_system": False}
        for i, (t, text) in enumerate(items, start=1)
    ])


def test_quantity_in_following_message(extractor):
    lines = extractor.extract(_timed(("13:47", "Toyota 1 มิล \nLandcruiser 3 มิล"), ("13:47", "สั่งหนึ่งชุด")))
    assert list(lines["kind"]) == ["order", "order"]
    assert list(lines["qty"]) == [1, 1]
    assert list(lines["raw_line"]) == ["Toyota 1 มิล", "Landcruiser 3 มิล"]


def test_following_message_too_late_keeps_qty_missing(extractor):
    lines = extractor.extract(_timed(("13:00", "Toyota 1 มิล \nLandcruiser 3 มิล"), ("15:00", "สั่งหนึ่งชุด")))
    assert list(lines["kind"]) == ["qty_missing"]
