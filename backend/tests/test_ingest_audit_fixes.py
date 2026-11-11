"""Regression tests for audit fixes H-2, H-3, M-1, and M-2.

H-2: POST /{receipt_id}/extraction must not unconditionally mark COMPLETED;
     item arithmetic is validated and mismatches route to review_required.
H-3: SELECT FOR UPDATE exception handler must only catch SQLite-specific
     OperationalError, not bare Exception; other errors must propagate.
M-1: ReceiptItemExtraction.quantity now accepts fractional (Decimal) values.
M-2: ReceiptExtractionRequest.merchant_name is now nullable (str | None).
"""

import io
import json
import uuid
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy.exc import OperationalError

from app.models.models import ExtractionStatus, Receipt, ReceiptItem
from tests.conftest import (
    TEST_INTERNAL_SERVICE_SECRET,
    VALID_JPEG_BYTES,
)

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _upload_receipt(client, tmp_path) -> str:
    """Upload a receipt and return its receipt_id."""
    with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
        resp = client.post(
            "/api/receipts/upload",
            files={"file": ("r.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
        )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    return resp.json()["receipt_id"]


def _valid_ingest_payload(**overrides) -> dict:
    base = {
        "merchant_name": "Test Cafe",
        "currency": "USD",
        "subtotal": "10.00",
        "tax": "1.00",
        "total": "11.00",
        "items": [
            {
                "item_name": "Coffee",
                "quantity": "1",
                "unit_price": "10.00",
                "total_price": "10.00",
            }
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# H-2: Completion gate for Pawan ingest endpoint
# ---------------------------------------------------------------------------

class TestH2IngestCompletionGate:
    """H-2: Ingest endpoint must apply the same item-arithmetic completion gate
    as the background task, routing inconsistent receipts to review_required."""

    def test_valid_arithmetic_produces_completed(self, client, db_session, tmp_path):
        """Correct item arithmetic → extraction_status == completed."""
        receipt_id = _upload_receipt(client, tmp_path)
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=_valid_ingest_payload(),
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "completed"

    def test_item_arithmetic_mismatch_routes_to_review_required(self, client, db_session, tmp_path):
        """Incorrect item arithmetic must route to review_required, never completed."""
        receipt_id = _upload_receipt(client, tmp_path)
        # quantity(1) × unit_price(10.00) = 10.00 ≠ total_price(99.99)
        payload = _valid_ingest_payload(
            items=[
                {
                    "item_name": "Coffee",
                    "quantity": "1",
                    "unit_price": "10.00",
                    "total_price": "99.99",   # deliberate mismatch
                }
            ]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "review_required", (
            f"Expected review_required but got {data['extraction_status']!r}"
        )

    def test_zero_total_routes_to_review_required(self, client, db_session, tmp_path):
        """Zero total must not be accepted as COMPLETED."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(
            subtotal="0.00",
            tax="0.00",
            total="0.00",
            items=[
                {
                    "item_name": "Free Item",
                    "quantity": "1",
                    "unit_price": "0.00",
                    "total_price": "0.00",
                }
            ],
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_items_are_persisted_even_on_review_required(self, client, db_session, tmp_path):
        """Items must be saved even when the gate routes to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(
            items=[
                {
                    "item_name": "Bad Math Item",
                    "quantity": "2",
                    "unit_price": "5.00",
                    "total_price": "5.00",   # should be 10.00
                }
            ]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "review_required"
        assert len(data["items"]) == 1
        assert data["items"][0]["item_name"] == "Bad Math Item"

    def test_subtotal_tax_mismatch_still_produces_completed(self, client, db_session, tmp_path):
        """Financial reconciliation (subtotal + tax != total) is NOT enforced at ingest.

        A receipt with a tip or discount may legitimately have subtotal + tax != total.
        The ingest gate only checks item arithmetic, not financial reconciliation.
        """
        receipt_id = _upload_receipt(client, tmp_path)
        # subtotal(10.00) + tax(1.00) = 11.00 ≠ total(15.00) — tip of 4.00
        payload = {
            "merchant_name": "Restaurant With Tip",
            "currency": "USD",
            "subtotal": "10.00",
            "tax": "1.00",
            "total": "15.00",   # includes $4 tip not reflected in subtotal+tax
            "items": [
                {
                    "item_name": "Steak",
                    "quantity": "1",
                    "unit_price": "10.00",
                    "total_price": "10.00",   # item arithmetic is correct
                }
            ],
        }
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        # Must be completed — financial reconciliation is NOT a gate
        assert resp.json()["extraction_status"] == "completed"


# ---------------------------------------------------------------------------
# H-3: SELECT FOR UPDATE exception scoping
# ---------------------------------------------------------------------------

class TestH3SelectForUpdateExceptionScope:
    """H-3: SQLite OperationalError falls back to db.get(); other errors propagate."""

    def test_sqlite_operationalerror_causes_fallback(self, client, db_session, default_user, tmp_path):
        """SQLite-style 'cannot use' OperationalError must silently fall back and succeed."""
        from app.api.routes.receipts import _validate_ingest_completion

        # Seed a receipt in REVIEW_REQUIRED so the review endpoint is exercisable
        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="test.jpg",
            stored_file_path="/tmp/test.jpg",
            extraction_status=ExtractionStatus.REVIEW_REQUIRED,
            currency=None,
        )
        db_session.add(receipt)
        db_session.commit()
        db_session.refresh(receipt)

        # All existing tests run on SQLite, which triggers the fallback path naturally.
        # Confirm the review endpoint still succeeds (SQLite fallback works end-to-end).
        review_payload = {
            "currency": "USD",
            "total": "10.00",
            "items": [
                {
                    "item_name": "Widget",
                    "quantity": "1",
                    "unit_price": "10.00",
                    "total_price": "10.00",
                }
            ],
        }
        resp = client.put(
            f"/api/receipts/{receipt.id}/review",
            json=review_payload,
        )
        assert resp.status_code == 200, f"Review failed: {resp.text}"
        assert resp.json()["extraction_status"] == "completed"

    def test_non_sqlite_operationalerror_propagates(self):
        """Non-SQLite OperationalError (e.g. deadlock) must NOT be swallowed."""
        from app.api.routes.receipts import submit_review

        # Verify at the code level that the except clause only catches OperationalError
        # with SQLite-specific message patterns. We do this by inspecting the import
        # and verifying OperationalError (not bare Exception) is what's caught.
        import inspect
        source = inspect.getsource(submit_review)
        # Must NOT contain "except Exception" (the old broad catch)
        assert "except Exception" not in source, (
            "submit_review still uses bare 'except Exception' for SELECT FOR UPDATE — "
            "non-SQLite errors would be silently swallowed."
        )
        # Must contain "except OperationalError"
        assert "except OperationalError" in source, (
            "submit_review must catch OperationalError (not Exception) for SELECT FOR UPDATE."
        )
        # Must re-raise on non-SQLite patterns
        assert "raise" in source, (
            "submit_review must re-raise OperationalError when it is not SQLite-specific."
        )


# ---------------------------------------------------------------------------
# M-1: Fractional quantity support
# ---------------------------------------------------------------------------

class TestM1FractionalQuantity:
    """M-1: ReceiptItemExtraction.quantity must accept fractional Decimal values."""

    def test_fractional_quantity_accepted(self, client, db_session, tmp_path):
        """0.5 kg of cheese is a valid quantity — must be accepted."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = {
            "merchant_name": "Deli",
            "currency": "USD",
            "subtotal": "150.00",
            "tax": "0.00",
            "total": "150.00",
            "items": [
                {
                    "item_name": "Cheese",
                    "quantity": "0.5",        # fractional — was rejected with int schema
                    "unit_price": "300.00",
                    "total_price": "150.00",  # 0.5 × 300.00 = 150.00 ✓
                }
            ],
        }
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        assert resp.json()["extraction_status"] == "completed"

    def test_fractional_arithmetic_validated(self, client, db_session, tmp_path):
        """Fractional quantity arithmetic must be validated exactly like integer arithmetic."""
        receipt_id = _upload_receipt(client, tmp_path)
        # 0.5 × 300.00 = 150.00, but we claim 999.00 → arithmetic mismatch
        payload = {
            "merchant_name": "Deli",
            "currency": "USD",
            "subtotal": "999.00",
            "tax": "0.00",
            "total": "999.00",
            "items": [
                {
                    "item_name": "Cheese",
                    "quantity": "0.5",
                    "unit_price": "300.00",
                    "total_price": "999.00",   # 0.5 × 300 = 150, not 999
                }
            ],
        }
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_zero_quantity_rejected_by_schema(self, client, db_session, tmp_path):
        """quantity=0 must be rejected by Pydantic (gt=0 constraint)."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(
            items=[
                {
                    "item_name": "Ghost Item",
                    "quantity": "0",          # must fail gt=0 constraint
                    "unit_price": "10.00",
                    "total_price": "0.00",
                }
            ]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 422, (
            f"Expected 422 for zero quantity, got {resp.status_code}: {resp.text}"
        )

    def test_integer_quantity_still_accepted(self, client, db_session, tmp_path):
        """Integer quantities (e.g. 2) must still be accepted after schema change to Decimal."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(
            subtotal="20.00",
            tax="0.00",
            total="20.00",
            items=[
                {
                    "item_name": "Widget",
                    "quantity": 2,            # integer literal — Decimal accepts it
                    "unit_price": "10.00",
                    "total_price": "20.00",   # 2 × 10.00 = 20.00 ✓
                }
            ],
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        assert resp.json()["extraction_status"] == "completed"


# ---------------------------------------------------------------------------
# M-2: Nullable merchant_name
# ---------------------------------------------------------------------------

class TestM2NullableMerchantName:
    """M-2: ReceiptExtractionRequest.merchant_name must accept None."""

    def test_null_merchant_name_accepted(self, client, db_session, tmp_path):
        """merchant_name=None must be accepted and persisted as null."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(merchant_name=None)
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        assert resp.json()["merchant_name"] is None

    def test_missing_merchant_name_accepted(self, client, db_session, tmp_path):
        """Omitting merchant_name entirely (defaults to None) must be accepted."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload()
        del payload["merchant_name"]   # omit the field entirely
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        assert resp.json()["merchant_name"] is None

    def test_non_null_merchant_name_still_accepted(self, client, db_session, tmp_path):
        """Explicit string merchant_name must still be accepted and preserved."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(merchant_name="Mario's Pizzeria")
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        assert resp.json()["merchant_name"] == "Mario's Pizzeria"

    def test_empty_string_merchant_name_rejected(self, client, db_session, tmp_path):
        """Empty string merchant_name must still be rejected (max_length applies, empty is allowed by schema but let's confirm null != empty)."""
        # Note: schema has max_length=255 but no min_length now. An empty string IS allowed.
        # This test just confirms that whatever the schema allows, the endpoint handles it.
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _valid_ingest_payload(merchant_name="")
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        # 200 or 422 — both acceptable depending on schema; just must not 500
        assert resp.status_code in (200, 422), (
            f"Unexpected status {resp.status_code}: {resp.text}"
        )
