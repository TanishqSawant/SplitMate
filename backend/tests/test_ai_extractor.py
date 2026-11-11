
def test_ocr_preprocessing_uses_offline_fallback_when_gemini_unavailable():
    """Local OCR text is used by the offline fallback when Gemini is unavailable."""
    service = ReceiptExtractionService()
    img = Image.new("RGB", (100, 100), color="white")

    embedded_sample_text = (
        "Cafe Bistro\n"
        "Coffee 1 4.50\n"
        "Subtotal: 4.50\n"
        "Tax: 0.45\n"
        "Total: 4.95"
    )

    res = service.ocr_engine.process_receipt(
        image=img,
        embedded_text=embedded_sample_text,
    )

    assert res is not None
    assert res.is_fallback is True
    assert res.extraction_method == "regex_heuristic_fallback"
    assert res.merchant_name == "Cafe Bistro"
    assert res.final_total == Decimal("4.95")
    assert any("fallback" in w.lower() for w in res.warnings)
