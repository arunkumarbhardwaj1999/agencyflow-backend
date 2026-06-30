from decimal import Decimal

from app.core.gst import compute_gst, resolve_place_of_supply, state_code_from_gstin


def test_state_code_from_gstin():
    assert state_code_from_gstin("27AAAAA0000A1Z5") == "27"
    assert state_code_from_gstin("29BBBBB1111B2Z6") == "29"
    assert state_code_from_gstin(None) is None
    assert state_code_from_gstin("99XXXXX0000X1Z9") is None  # invalid state code


def test_intra_state_splits_cgst_sgst():
    gst = compute_gst(Decimal("1000"), Decimal("0.18"), "27", "27")
    assert gst.tax_type == "cgst_sgst"
    assert gst.cgst == Decimal("90.00")
    assert gst.sgst == Decimal("90.00")
    assert gst.igst == Decimal("0.00")
    assert gst.total == Decimal("1180.00")


def test_inter_state_uses_igst():
    gst = compute_gst(Decimal("1000"), Decimal("0.18"), "27", "29")
    assert gst.tax_type == "igst"
    assert gst.igst == Decimal("180.00")
    assert gst.cgst == Decimal("0.00")
    assert gst.total == Decimal("1180.00")


def test_unknown_supplier_defaults_to_igst():
    gst = compute_gst(Decimal("500"), Decimal("0.18"), None, "27")
    assert gst.tax_type == "igst"
    assert gst.igst == Decimal("90.00")


def test_resolve_place_of_supply_priority():
    # explicit wins
    assert resolve_place_of_supply("07", "27AAAAA0000A1Z5", "27") == "07"
    # else client gstin
    assert resolve_place_of_supply(None, "29BBBBB1111B2Z6", "27") == "29"
    # else supplier state
    assert resolve_place_of_supply(None, None, "27") == "27"
