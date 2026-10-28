from datetime import date

import pytest

from arma.parse_line import parse_file, parse_text

from .conftest import CHAT, ROOT, requires_data

SAMPLE = (
    '[LINE] ประวัติการแชท\r\n\r\n'
    "จันทร์ 04/05/2569\r\n"
    '10:54\tShopA\t"Yaris cross ดำเงา 15 \nToyota travo ดำเงา 20 \nพรบ amg 10 ชิ้น"\r\n'
    "10:55\tCustB\t[สติกเกอร์]\r\n"
    "20:06\t\t⁨ShopA⁩ เพิ่ม CustB เข้ากลุ่ม\r\n"
    "อังคาร 05/05/2569\r\n"
    "14:48\t⁨CustB⁩\tสั่งของ\r\n"
)


def test_parse_text_structure():
    df = parse_text(SAMPLE)
    assert len(df) == 4
    first = df.iloc[0]
    assert first.date == date(2026, 5, 4)  # พ.ศ. → ค.ศ.
    assert first.time == "10:54"
    assert first.text.split("\n") == ["Yaris cross ดำเงา 15 ", "Toyota travo ดำเงา 20 ", "พรบ amg 10 ชิ้น"]
    assert df.iloc[1].is_system  # สติกเกอร์
    assert df.iloc[2].is_system  # ผู้ส่งว่าง
    assert df.iloc[3].sender == "CustB"  # ลบอักขระมองไม่เห็น
    assert not df.iloc[3].is_system


@requires_data
def test_real_export_multiline_message_is_one_message():
    df = parse_file(CHAT, year=2026, month=5)
    assert set(d.month for d in df["date"]) == {5}
    hits = df[df["text"].str.startswith("Yaris cross ดำเงา 15") & df["text"].str.contains("\n")]
    assert len(hits) == 1
    lines = hits.iloc[0].text.split("\n")
    assert len(lines) == 3 and lines[2].strip() == "พรบ amg 10 ชิ้น"


SAMPLE_DOTTED = (
    "2026.10.02 วันศุกร์\n"
    "11:20 ShopA ตะแกรง Fj แดง 3 อัน\n"
    "กรอง  alphard มีรูปัก 6 อัน\n"
    "11:28 CustB สติกเกอร์\n"
    "13:43 ShopA ตะแกรง Fj ดำด้าน 5 อัน\n"
    "\n"
    "2026.10.03 วันเสาร์\n"
    "00:38 CustB รูป\n"
)


def test_parse_text_dotted_format():
    df = parse_text(SAMPLE_DOTTED)
    assert len(df) == 4
    first = df.iloc[0]
    assert first.date == date(2026, 10, 2)  # ค.ศ. อยู่แล้ว ไม่แปลง
    assert first.time == "11:20" and first.sender == "ShopA"
    assert first.text.split("\n") == ["ตะแกรง Fj แดง 3 อัน", "กรอง  alphard มีรูปัก 6 อัน"]
    assert df.iloc[2].text == "ตะแกรง Fj ดำด้าน 5 อัน"  # บรรทัดว่างไม่ต่อท้าย
    assert df.iloc[3].date == date(2026, 10, 3) and df.iloc[3].sender == "CustB"
    assert df.is_system.tolist() == [False, True, False, True]  # "สติกเกอร์" / "รูป" ไม่มีวงเล็บ


TAB_OCT = ROOT / "input" / "2569-10" / "line_export_1-7.txt"
DOTTED_OCT = ROOT / "data" / "[LINE]สั่งงานตัด อะคริลิค ฟิล์ม.txt"


@pytest.mark.skipif(not (TAB_OCT.exists() and DOTTED_OCT.exists()), reason="ไม่มีไฟล์ export ต.ค. 2569 ทั้งสองแบบ")
def test_dotted_export_matches_tab_export():
    cols = ["date", "time", "sender", "text"]
    tab = parse_file(TAB_OCT, end=date(2026, 10, 7))[cols]
    dotted = parse_file(DOTTED_OCT, end=date(2026, 10, 7))[cols]
    assert tab.to_dict("records") == dotted.to_dict("records")
