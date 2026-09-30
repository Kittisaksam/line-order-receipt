from datetime import date

from arma.parse_line import parse_file, parse_text

from .conftest import CHAT, requires_data

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
