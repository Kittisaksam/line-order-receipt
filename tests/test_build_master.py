from arma.build_master import build_products

from .conftest import DOCX, requires_data


@requires_data
def test_service_products(norm):
    products = build_products(DOCX, norm).set_index("product_id")
    for pid in ("SV-SHIPPING", "SV-DESIGN", "SV-CLAIM"):
        assert products.at[pid, "category"] == "service"
    assert products.at["SV-CLAIM", "receipt_name"] == "งานเคลม"
