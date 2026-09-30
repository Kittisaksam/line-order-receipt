import pytest

from arma.normalize import norm_key


def _attrs(norm, text):
    return {k: set(v) for k, v in norm.attributes(text).items() if v}


def test_clean_fixes_typos_and_spacing(norm):
    assert norm.clean("Toyotaกระบะท้าย Hirux ตัวเล้ก") == "toyota กระบะท้าย hilux เล็ก"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Toyota ท้ายดำเงา", {"brand": {"toyota"}, "model": {"travo"}, "part": {"ท้ายกระบะ"}, "color": {"ดำเงา"}}),
        ("R แดงกระจัง", {"model": {"raptor"}, "logo": {"r"}, "part": {"กระจังหน้า"}, "color": {"แดง"}}),
        ("Hirux แดง มือจับ", {"model": {"hilux"}, "part": {"มือจับท้าย"}, "color": {"แดง"}}),
        ("Type r กระจัง", {"model": {"civic type r"}, "part": {"กระจังหน้า"}}),
        ("พรบ ใส", {"part": {"พรบ"}, "color": {"ใสไม่มีลาย"}}),
    ],
)
def test_attributes(norm, text, expected):
    assert _attrs(norm, text) == expected


def test_longest_keyword_wins(norm):
    # "มือจับท้าย" ต้องไม่ถูกตีเป็น "ท้าย" (ท้ายกระบะ)
    assert _attrs(norm, "โลโก้มือจับท้าย 1 mm. TOYOTA HILUX REVO")["part"] == {"มือจับท้าย"}


def test_norm_key_is_order_independent(norm):
    assert norm_key(norm.attributes("ดำเงา toyota ท้ายรถ")) == norm_key(norm.attributes("Toyota ท้ายรถ ดำเงา"))


def test_landcruiser_defaults_to_black_gloss(norm):
    assert _attrs(norm, "landcruiser 1mm")["color"] == {"ดำเงา"}
    assert _attrs(norm, "land cruiser 1mm สีขาว")["color"] == {"ขาว"}
