from pathlib import Path

from lxml import etree

from sepa_fix import MODE_LINES, MODE_MINIMAL, fix_sepa

SAMPLE = (Path(__file__).parent / "data" / "sample_prinex_bldgnm.xml").read_bytes()


def test_original_has_bldgnm():
    assert b"<BldgNm>" in SAMPLE


def test_lines_mode_removes_bldgnm_and_keeps_amounts():
    out, rep = fix_sepa(SAMPLE, mode=MODE_LINES)
    assert rep.ok, rep.errors
    assert b"BldgNm" not in out
    assert rep.nb_txs == 2 and str(rep.ctrl_sum) == "1057.11"
    assert rep.removed_elements == {"BldgNm": 3}
    root = etree.fromstring(out)
    lines = [e.text for e in root.iter("{*}AdrLine")]
    assert "08010 BARCELONA" in lines           # CP completado, sin duplicar provincia
    assert any("D'URGELL" in l for l in lines)  # apóstrofo corregido


def test_minimal_mode():
    out, rep = fix_sepa(SAMPLE, mode=MODE_MINIMAL)
    assert rep.ok, rep.errors
    assert b"BldgNm" not in out and b"<StrtNm>" in out


def test_idempotent():
    out, _ = fix_sepa(SAMPLE)
    out2, rep2 = fix_sepa(out)
    assert rep2.ok and rep2.addresses_changed == 0


def test_tampered_ctrlsum_is_rejected():
    bad = SAMPLE.replace(b"<CtrlSum>1057.11</CtrlSum>", b"<CtrlSum>9999.99</CtrlSum>", 1)
    _, rep = fix_sepa(bad)
    assert not rep.ok


def test_not_xml():
    out, rep = fix_sepa(b"esto no es xml")
    assert out is None and not rep.ok
