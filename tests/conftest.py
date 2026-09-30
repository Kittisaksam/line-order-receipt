import shutil
from pathlib import Path

import pytest

from arma.build_master import build_products, build_seed_aliases, write_xlsx
from arma.config import Project
from arma.extract import Extractor
from arma.normalize import Normalizer

ROOT = Path(__file__).resolve().parents[1]
CHAT = ROOT / "data" / "[LINE] การแชทกลุ่ม สั่งงานตัด อะคริลิค ฟิล์ม.txt"
FIXTURES = ROOT / "tests" / "fixtures"
DOCX = ROOT / "ref_docs" / "ตารางราคากลาง.docx"

# แชท/ใบเสร็จ/ตารางราคาเป็นข้อมูลลูกค้าจริง ไม่อยู่ใน git → ข้าม test ที่ต้องใช้ ถ้าไม่มีไฟล์
requires_data = pytest.mark.skipif(
    not (CHAT.exists() and DOCX.exists() and any(FIXTURES.glob("*.csv"))),
    reason="ไม่มีข้อมูลจริง (data/, ref_docs/, tests/fixtures/*.csv) — ไม่ได้ commit เพราะเป็นข้อมูลลูกค้า",
)


@pytest.fixture(scope="session")
def norm() -> Normalizer:
    return Normalizer.load(ROOT / "master" / "normalize.yaml")


@pytest.fixture(scope="session")
def extractor(norm) -> Extractor:
    return Extractor(norm)


@pytest.fixture(scope="session")
def project(tmp_path_factory, norm) -> Project:
    """โปรเจกต์ชั่วคราว: master สร้างใหม่จาก docx (ไม่กระทบไฟล์จริงที่ผู้ใช้แก้ราคาไว้)"""
    root = tmp_path_factory.mktemp("arma")
    shutil.copytree(ROOT / "config", root / "config")
    shutil.copytree(ROOT / "templates", root / "templates")
    (root / "master").mkdir()
    shutil.copy(ROOT / "master" / "normalize.yaml", root / "master" / "normalize.yaml")
    products = build_products(DOCX, norm)
    write_xlsx(products, root / "master" / "products.xlsx", "products")
    write_xlsx(build_seed_aliases(products, norm), root / "master" / "aliases.xlsx", "aliases")
    return Project(root)
