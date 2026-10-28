# arma — ออเดอร์จาก LINE → ใบเสร็จรับเงิน PDF รายเดือน (ARMA LASER)

แผนการออกแบบ: [2026-09-30-line-order-to-receipt-plan.md](2026-09-30-line-order-to-receipt-plan.md)

## ติดตั้ง

ต้องมี [uv](https://docs.astral.sh/uv/) และ pango (สำหรับ WeasyPrint)

```bash
brew install pango   # macOS
uv sync
cp config/settings.example.yaml config/settings.yaml   # แล้วแก้ข้อมูลร้าน/ลูกค้าจริง
```

ข้อมูลธุรกิจจริงไม่อยู่ใน git (ดู `.gitignore`): `data/` (แชท LINE), `ref_docs/` (ตารางราคา, ใบเสร็จตัวอย่าง),
`config/settings.yaml`, `master/products.xlsx`, `master/aliases.xlsx`, `master/history.csv`, `tests/fixtures/*.csv`
— ต้องวางไฟล์เหล่านี้เองในเครื่อง (test ที่ต้องใช้ข้อมูลจริงจะถูกข้ามถ้าไม่มีไฟล์)

## ใช้งานทุกเดือน

```bash
# 0) ครั้งแรกเท่านั้น: ตารางราคากลาง.docx → master/products.xlsx (แล้วเปิดตรวจราคา)
uv run arma build-master

# 1) วางไฟล์ export แชทใหม่ (ถ้าไม่วาง จะใช้ไฟล์ใน data/ ตาม config/settings.yaml)
mkdir -p input/2569-10
cp ~/Downloads/"[LINE] การแชทกลุ่ม สั่งงานตัด อะคริลิค ฟิล์ม.txt" input/2569-10/line_export.txt

# 2) Parse + แยกออเดอร์ + จับคู่สินค้า → work/2569-10/review.csv (+ products.csv ไว้ค้น product_id)
uv run arma prepare 2569-10

# 3) เปิด review.csv (Excel/Numbers/Google Sheets) แล้วดูคอลัมน์ "สถานะ":
#    - ไม่ใช่ auto → ใส่ product_id ที่ถูก (ดูจาก "ตัวเลือกอื่น" หรือ products.csv) แล้วใส่อะไรก็ได้ในช่อง "ยืนยัน"
#    - ไม่คิดเงิน → ใส่ N ในช่อง "รวมในบิล (Y/N)"
#    - ราคาพิเศษ → ใส่ในช่อง "ราคา (เว้นว่าง = ตามตาราง)"
#    - เพิ่มแถวเองได้ (ออเดอร์ทางโทรศัพท์/สั่งเป็นไฟล์): ใส่ วันที่ (dd/mm/2569) ข้อความ จำนวน product_id
#    - บันทึกกลับเป็น CSV UTF-8 และห้ามแก้แถวหัวตาราง

# 4) ดูร่างก่อน (เลข #DRAFT + ลายน้ำ, ไม่เปลี่ยนเลขที่/alias) → output/2569-10/drafts/
uv run arma finalize 2569-10 --dry-run

# 5) ออกบิลจริง: เลขที่รันต่อจาก config/receipt_counter.json, เรียนรู้ alias ใหม่
uv run arma finalize 2569-10
# → output/2569-10/1-send/YYYY-MM-DD-arma-receipts-2569-10.pdf + ข้อความสรุป Lot สำหรับส่ง LINE
#   ทุก PDF มี .docx คู่กัน ให้ admin แก้ใน Word ได้
#   — แก้ใน Word ไม่ย้อนกลับเข้าระบบ ถ้าแก้รายการ/ราคา ให้แก้ review.csv ด้วยแล้ว `uv run arma reprint 2569-10`
```

## โครงสร้าง output

```
output/<เดือน>/
├── 1-send/       ใบเสร็จรวม + ใบสรุปเดือน (.pdf + .docx) ← ไฟล์ที่ส่งลูกค้า
├── 2-receipts/   receipt_<เลขที่>.pdf/.docx แยกทีละบิล
├── 3-review/     รายการที่ไม่แน่ใจ ให้ admin ตรวจ (.pdf/.docx/.md)
├── drafts/       ผลจาก --dry-run
└── archive/<วันที่>/  ชุดเดิมที่ถูกแทน — `finalize --force` ย้ายให้อัตโนมัติ (พร้อม review.csv + finalized.json ของชุดนั้น)
```

## วัดผล / ทดสอบ

```bash
uv run arma backtest          # เทียบแชท 27/04–27/06/2569 กับใบเสร็จ #309–#317
uv run arma backtest --no-aliases --show
uv run pytest
```

## ไฟล์ที่แก้ได้โดยไม่ต้องแก้โค้ด

| ไฟล์ | ใช้ทำอะไร |
|---|---|
| `config/settings.yaml` | ข้อมูลร้าน/ลูกค้า, โหมดแบ่งบิล (`single` / `by_period` / `by_max_lines`), ฟอนต์ |
| `config/receipt_counter.json` | เลขที่ใบเสร็จล่าสุด |
| `master/products.xlsx` | ราคาและชื่อสินค้าที่พิมพ์ลงใบเสร็จ (`active=False` เพื่อปิดสินค้า) |
| `master/aliases.xlsx` | คำเรียกที่ยืนยันแล้ว → สินค้า (ระบบเพิ่มให้เองตอน finalize) |
| `master/normalize.yaml` | คำสะกดผิด, คำพ้อง, กฎเติมค่า, วลีที่ตัดทิ้ง |
| `templates/receipt.html.j2`, `receipt.css` | หน้าตาใบเสร็จ |

ฟอนต์ Sarabun ใน `templates/fonts/` ใช้สัญญาอนุญาต SIL Open Font License
