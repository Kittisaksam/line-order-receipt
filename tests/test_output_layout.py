import json

from arma.cli import archive_previous
from arma.config import MonthOutput


def _finalized_month(tmp_path, finalized_at="2026-10-19T13:29:18"):
    out = MonthOutput(tmp_path / "output" / "2569-10")
    work = tmp_path / "work" / "2569-10"
    for folder, names in ((out.send, ["2026-10-19-arma-receipts-2569-10.pdf", "2026-10-19-arma-receipts-2569-10.docx"]),
                          (out.receipts, ["receipt_337.pdf", "receipt_337.docx"])):
        folder.mkdir(parents=True)
        for n in names:
            (folder / n).write_text(n)
    work.mkdir(parents=True)
    (work / "finalized.json").write_text(json.dumps({"bills": ["337"], "finalized_at": finalized_at}))
    (work / "finalized-review.csv").write_text("ชุดที่ออกบิล")
    (work / "review.csv").write_text("แก้แล้ว รอออกใหม่")
    return out, work


def test_archive_moves_previous_set(tmp_path):
    out, work = _finalized_month(tmp_path)
    dest = archive_previous(out, work)
    assert dest == out.archive / "2026-10-19"
    assert not any(out.send.iterdir()) and not any(out.receipts.iterdir())
    assert sorted(p.name for p in dest.iterdir()) == [
        "2026-10-19-arma-receipts-2569-10.docx", "2026-10-19-arma-receipts-2569-10.pdf",
        "finalized.json", "receipt_337.docx", "receipt_337.pdf", "review.csv",
    ]
    # review.csv ใน archive = ชุดที่ใช้ออกบิลเดิม ไม่ใช่ที่แก้ไว้รอออกใหม่
    assert (dest / "review.csv").read_text() == "ชุดที่ออกบิล"


def test_archive_same_day_gets_suffix(tmp_path):
    out, work = _finalized_month(tmp_path)
    (out.archive / "2026-10-19").mkdir(parents=True)
    assert archive_previous(out, work) == out.archive / "2026-10-19-2"


def test_archive_noop_when_never_finalized(tmp_path):
    assert archive_previous(MonthOutput(tmp_path / "out"), tmp_path / "work") is None
