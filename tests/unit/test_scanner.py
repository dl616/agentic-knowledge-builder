"""scanner.py 的单元测试：验证识别器的判断逻辑。"""
from __future__ import annotations

from pke.scanner import _is_mono, scan


def test_is_mono_detects_monospace_fonts():
    assert _is_mono("Cour") is True
    assert _is_mono("Courier New") is True
    assert _is_mono("Consolas") is True
    assert _is_mono("Times New Roman") is False
    assert _is_mono("SimSun") is False


def test_scan_detects_pdf_with_code(sample_pdf_path):
    result = scan(sample_pdf_path)
    assert result.file_type == "pdf"
    assert result.parser == "pdf"
    assert result.features["has_code"] is True
    assert result.features["is_scanned"] is False


def test_scan_routes_markdown(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# hi\n")
    result = scan(p)
    assert result.file_type == "markdown"
