"""Tests for POST /api/receipts/extract and PUT /api/receipts/{id}/review endpoints.

Coverage:
- POST /extract: auth guard, file validation, 202 response contract, background task scheduling
- GET  /api/receipts/{id}: receipt_id key in response, status transitions
- PUT  /api/receipts/{id}/review: auth guard, status gate (409 if not review_required),
  field validation, item arithmetic, financial reconciliation, completed on success
"""

import io
import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.models import ExtractionStatus, Receipt, ReceiptItem
from tests.conftest import (
    VALID_JPEG_BYTES,
    VALID_PNG_BYTES,
    create_user_and_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_upload(filename: str = "receipt.jpg") -> dict:
    return {"file": (filename, io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}


def _seed_receipt(db, uploader_id, status: ExtractionStatus = ExtractionStatus.REVIEW_REQUIRED) -> Receipt:
    """Create and persist a Receipt directly in the test DB."""
    receipt = Receipt(
        uploader_id=uploader_id,
        original_filename="test_receipt.jpg",
        stored_file_path="/tmp/test_receipt.jpg",
        extraction_status=status,
        currency=None,
        warnings=json.dumps(["Requires human review: Currency is unknown."]),
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt


# ===========================================================================
# POST /api/receipts/extract
# ===========================================================================

class TestExtractEndpoint:

    def test_extract_requires_auth(self, unauth_client):
        """Unauthenticated upload must return 401."""
        resp = unauth_client.post(
            "/api/receipts/extract",
            files=_make_jpeg_upload(),
        )
        assert resp.status_code == 401

    def test_extract_returns_202_with_contract(self, client, tmp_path):
        """Authenticated upload returns 202 with receipt_id and extraction_status=pending."""
        with patch("app.api.routes.receipts.process_receipt_extraction_task") as mock_task:
            # BackgroundTasks wraps the callable — patch the function so it doesn't run
            with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
                resp = client.post(
                    "/api/receipts/extract",
                    files=_make_jpeg_upload(),
                )
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "receipt_id" in data, f"Missing receipt_id in {data}"
        assert data["extraction_status"] == "pending"
        # Must be a valid UUID
        uuid.UUID(data["receipt_id"])

    def test_extract_rejects_empty_file(self, client, tmp_path):
        """Empty file is rejected with 400."""
        with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
            resp = client.post(
                "/api/receipts/extract",
                files={"file": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
            )
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_extract_rejects_wrong_extension(self, client, tmp_path):
        """Disallowed extension is rejected with 400."""
        with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
            resp = client.post(
                "/api/receipts/extract",
                files={"file": ("receipt.exe", io.BytesIO(VALID_JPEG_BYTES), "application/octet-stream")},
            )
        assert resp.status_code == 400

    def test_extract_rejects_magic_byte_mismatch(self, client, tmp_path):
        """PNG bytes in a .jpg file are rejected (magic-byte mismatch)."""
        with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
            resp = client.post(
                "/api/receipts/extract",
                files={"file": ("receipt.jpg", io.BytesIO(VALID_PNG_BYTES), "image/jpeg")},
            )
        assert resp.status_code == 400
        assert "does not match" in resp.json()["detail"].lower()

    def test_extract_persists_receipt_as_pending(self, client, db_session, tmp_path):
        """Receipt row must exist in DB with status=pending after POST /extract."""
        with patch("app.api.routes.receipts.process_receipt_extraction_task"):
            with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
                resp = client.post(
                    "/api/receipts/extract",
                    files=_make_jpeg_upload(),
                )
        assert resp.status_code == 202
        receipt_id = uuid.UUID(resp.json()["receipt_id"])
        receipt = db_session.get(Receipt, receipt_id)
        assert receipt is not None
        assert receipt.extraction_status == ExtractionStatus.PENDING


# ===========================================================================
# GET /api/receipts/{receipt_id} — response contract
# ===========================================================================

class TestGetReceiptContract:

    def test_get_receipt_uses_receipt_id_key(self, client, db_session, tmp_path):
        """GET response must include receipt_id, not id."""
        with patch("app.api.routes.receipts.process_receipt_extraction_task"):
            with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
                post_resp = client.post(
                    "/api/receipts/extract",
                    files=_make_jpeg_upload(),
                )
        assert post_resp.status_code == 202
        receipt_id = post_resp.json()["receipt_id"]

        get_resp = client.get(f"/api/receipts/{receipt_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert "receipt_id" in data, f"receipt_id key missing from GET response: {list(data.keys())}"
        assert data["receipt_id"] == receipt_id
        assert "id" not in data, "id field should not be present in GET /api/receipts/{receipt_id} response"

    def test_get_receipt_returns_404_for_other_user(self, client, db_session, default_user, tmp_path):
        """Another user cannot access a receipt they did not upload."""
        _, other_client, _ = create_user_and_client(db_session, "other@example.com")
        with patch("app.api.routes.receipts.process_receipt_extraction_task"):
            with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
                post_resp = client.post(
                    "/api/receipts/extract",
                    files=_make_jpeg_upload(),
                )
        receipt_id = post_resp.json()["receipt_id"]
        get_resp = other_client.get(f"/api/receipts/{receipt_id}")
        assert get_resp.status_code == 404


# ===========================================================================
# PUT /api/receipts/{receipt_id}/review
# ===========================================================================

class TestReviewEndpoint:

    def _valid_review_body(self) -> dict:
        return {
            "currency": "USD",
            "total": "49.14",
            "subtotal": "45.50",
            "tax": "3.64",
            "items": [
                {
                    "item_name": "Margherita Pizza",
                    "quantity": "2",
                    "unit_price": "12.00",
                    "total_price": "24.00",
                },
                {
                    "item_name": "Garlic Bread",
                    "quantity": "1",
                    "unit_price": "21.50",
                    "total_price": "21.50",
                },
            ],
        }

    def test_review_requires_auth(self, unauth_client, db_session, default_user):
        receipt = _seed_receipt(db_session, default_user.id)
        resp = unauth_client.put(
            f"/api/receipts/{receipt.id}/review",
            json=self._valid_review_body(),
        )
        assert resp.status_code == 401

    def test_review_blocked_if_status_not_review_required(self, client, db_session, default_user):
        """PUT /review returns 409 if the receipt is not in review_required status."""
        receipt = _seed_receipt(db_session, default_user.id, status=ExtractionStatus.PENDING)
        resp = client.put(
            f"/api/receipts/{receipt.id}/review",
            json=self._valid_review_body(),
        )
        assert resp.status_code == 409
        assert "review_required" in resp.json()["detail"]

    def test_review_blocked_for_completed_receipt(self, client, db_session, default_user):
        receipt = _seed_receipt(db_session, default_user.id, status=ExtractionStatus.COMPLETED)
        resp = client.put(
            f"/api/receipts/{receipt.id}/review",
            json=self._valid_review_body(),
        )
        assert resp.status_code == 409

    def test_review_success_marks_completed(self, client, db_session, default_user):
        """Valid review submission transitions receipt to completed."""
        receipt = _seed_receipt(db_session, default_user.id)
        resp = client.put(
            f"/api/receipts/{receipt.id}/review",
            json=self._valid_review_body(),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "completed"
        assert data["is_user_reviewed"] is True
        assert data["currency"] == "USD"
        assert "receipt_id" in data

    def test_review_response_uses_receipt_id_key(self, client, db_session, default_user):
        """Review response must use receipt_id, not id."""
        receipt = _seed_receipt(db_session, default_user.id)
        resp = client.put(
            f"/api/receipts/{receipt.id}/review",
            json=self._valid_review_body(),
        )
        assert resp.status_code == 200
        assert "receipt_id" in resp.json()
        assert resp.json()["receipt_id"] == str(receipt.id)
        assert "id" not in resp.json(), "id field should not be present in review response"

    def test_review_rejects_invalid_currency(self, client, db_session, default_user):
        receipt = _seed_receipt(db_session, default_user.id)
        # 2-letter currency rejected by Pydantic schema validation with 422
        body = self._valid_review_body()
        body["currency"] = "XX"
        resp = client.put(f"/api/receipts/{receipt.id}/review", json=body)
        assert resp.status_code == 422

        # 3-character non-alpha currency rejected by route handler with 400
        body["currency"] = "123"
        resp = client.put(f"/api/receipts/{receipt.id}/review", json=body)
        assert resp.status_code == 400
        assert "currency" in resp.json()["detail"].lower()

    def test_review_rejects_nonpositive_total(self, client, db_session, default_user):
        receipt = _seed_receipt(db_session, default_user.id)
        body = self._valid_review_body()
        body["total"] = "0"
        resp = client.put(f"/api/receipts/{receipt.id}/review", json=body)
        assert resp.status_code in (400, 422)

    def test_review_rejects_item_arithmetic_mismatch(self, client, db_session, default_user):
        """Item where qty*unit_price disagrees with total_price by >0.05 is rejected."""
        receipt = _seed_receipt(db_session, default_user.id)
        body = self._valid_review_body()
        body["items"][0]["total_price"] = "99.99"  # deliberate mismatch
        resp = client.put(f"/api/receipts/{receipt.id}/review", json=body)
        assert resp.status_code == 400
        assert "arithmetic" in resp.json()["detail"].lower() or "total_price" in resp.json()["detail"].lower()

    def test_review_accepts_adjustments_differing_from_subtotal_plus_tax(self, client, db_session, default_user):
        """Review must NOT assume subtotal + tax = total; receipts with tips/discounts succeed."""
        receipt = _seed_receipt(db_session, default_user.id)
        body = self._valid_review_body()
        # Subtotal (45.50) + Tax (3.64) = 49.14, but total is 57.14 due to an $8 tip
        body["total"] = "57.14"
        resp = client.put(f"/api/receipts/{receipt.id}/review", json=body)
        assert resp.status_code == 200
        assert resp.json()["extraction_status"] == "completed"
        assert resp.json()["total"] == "57.14"

    def test_review_blocked_for_other_user(self, client, db_session, default_user):
        """Another user cannot review a receipt they don't own."""
        _, other_client, _ = create_user_and_client(db_session, "stranger@example.com")
        receipt = _seed_receipt(db_session, default_user.id)
        resp = other_client.put(
            f"/api/receipts/{receipt.id}/review",
            json=self._valid_review_body(),
        )
        assert resp.status_code == 404

    def test_review_accepts_fractional_quantity(self, client, db_session, default_user):
        """Fractional quantities (e.g. 0.5 kg of cheese) are accepted."""
        receipt = _seed_receipt(db_session, default_user.id)
        body = {
            "currency": "INR",
            "total": "150.00",
            "items": [
                {
                    "item_name": "Cheese",
                    "quantity": "0.5",        # fractional
                    "unit_price": "300.00",
                    "total_price": "150.00",
                }
            ],
        }
        resp = client.put(f"/api/receipts/{receipt.id}/review", json=body)
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "completed"


# ===========================================================================
# Background task unit tests (isolated from HTTP layer)
# ===========================================================================

class TestBackgroundExtractionTask:

    def test_task_marks_failed_on_extraction_error(self, db_session, default_user, tmp_path):
        """If ReceiptExtractionService raises ReceiptExtractionError, receipt → failed."""
        from app.api.routes.receipts import process_receipt_extraction_task
        from app.services.receipt_extractor.service import ReceiptExtractionError

        sample_file = tmp_path / "sample.jpg"
        sample_file.write_bytes(b"dummy image bytes")

        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="bad.jpg",
            stored_file_path=str(sample_file),
            extraction_status=ExtractionStatus.PENDING,
        )
        db_session.add(receipt)
        db_session.commit()
        db_session.refresh(receipt)

        # Override get_db_context to use the test session
        def _test_db_context():
            from contextlib import contextmanager
            @contextmanager
            def _ctx():
                yield db_session
            return _ctx()

        with patch("app.api.routes.receipts.get_db_context", side_effect=_test_db_context):
            with patch(
                "app.services.receipt_extractor.service.ReceiptExtractionService.extract_from_path",
                side_effect=ReceiptExtractionError("Corrupt data"),
            ):
                process_receipt_extraction_task(receipt.id, str(sample_file))

        db_session.refresh(receipt)
        assert receipt.extraction_status == ExtractionStatus.FAILED
        assert receipt.error_code == "EXTRACTION_ERROR"

    def test_task_marks_failed_when_file_missing_on_disk(self, db_session, default_user):
        """If the receipt file does not exist on disk, task marks failed with FILE_NOT_FOUND."""
        from app.api.routes.receipts import process_receipt_extraction_task

        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="ghost.jpg",
            stored_file_path="/nonexistent/ghost.jpg",
            extraction_status=ExtractionStatus.PENDING,
        )
        db_session.add(receipt)
        db_session.commit()
        db_session.refresh(receipt)

        def _test_db_context():
            from contextlib import contextmanager
            @contextmanager
            def _ctx():
                yield db_session
            return _ctx()

        with patch("app.api.routes.receipts.get_db_context", side_effect=_test_db_context):
            process_receipt_extraction_task(receipt.id, "/nonexistent/ghost.jpg")

        db_session.refresh(receipt)
        assert receipt.extraction_status == ExtractionStatus.FAILED
        assert receipt.error_code == "FILE_NOT_FOUND"

    def test_task_marks_failed_when_service_returns_failed_result(self, db_session, default_user, tmp_path):
        """When ReceiptExtractionService returns status='failed', receipt status → failed."""
        from app.api.routes.receipts import process_receipt_extraction_task
        from app.services.receipt_extractor.schemas import ReceiptExtractionResult

        sample_file = tmp_path / "sample.jpg"
        sample_file.write_bytes(b"dummy image bytes")

        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="test.jpg",
            stored_file_path=str(sample_file),
            extraction_status=ExtractionStatus.PENDING,
        )
        db_session.add(receipt)
        db_session.commit()
        db_session.refresh(receipt)

        failed_result = ReceiptExtractionResult(
            status="failed",
            error_code="MISSING_API_KEY",
            error_message="Gemini API key is not configured.",
            confidence=0.0,
            is_fallback=False,
            extraction_method="gemini_vision",
        )

        def _test_db_context():
            from contextlib import contextmanager
            @contextmanager
            def _ctx():
                yield db_session
            return _ctx()

        with patch("app.api.routes.receipts.get_db_context", side_effect=_test_db_context):
            with patch(
                "app.services.receipt_extractor.service.ReceiptExtractionService.extract_from_path",
                return_value=failed_result,
            ):
                process_receipt_extraction_task(receipt.id, str(sample_file))

        db_session.refresh(receipt)
        assert receipt.extraction_status == ExtractionStatus.FAILED
        assert receipt.error_code == "MISSING_API_KEY"
        assert "Gemini API key is not configured" in receipt.error_message

    def test_task_marks_review_required_when_service_returns_review_required(self, db_session, default_user, tmp_path):
        """When service returns review_required, receipt status → review_required and saves partial items."""
        from app.api.routes.receipts import process_receipt_extraction_task
        from app.services.receipt_extractor.schemas import ExtractedLineItem, ReceiptExtractionResult

        sample_file = tmp_path / "sample.jpg"
        sample_file.write_bytes(b"dummy image bytes")

        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="partial.jpg",
            stored_file_path=str(sample_file),
            extraction_status=ExtractionStatus.PENDING,
        )
        db_session.add(receipt)
        db_session.commit()
        db_session.refresh(receipt)

        review_result = ReceiptExtractionResult(
            document_type="receipt",
            status="review_required",
            merchant_name="Partial Cafe",
            currency="USD",
            subtotal=Decimal("20.00"),
            tax=Decimal("2.00"),
            final_total=Decimal("22.00"),
            confidence=0.70,
            items=[
                ExtractedLineItem(item_name="Tea", quantity=1, unit_price=Decimal("20.00"), total_price=Decimal("20.00"))
            ],
            uncertain_fields=["tax"],
        )

        def _test_db_context():
            from contextlib import contextmanager
            @contextmanager
            def _ctx():
                yield db_session
            return _ctx()

        with patch("app.api.routes.receipts.get_db_context", side_effect=_test_db_context):
            with patch(
                "app.services.receipt_extractor.service.ReceiptExtractionService.extract_from_path",
                return_value=review_result,
            ):
                process_receipt_extraction_task(receipt.id, str(sample_file))

        db_session.refresh(receipt)
        assert receipt.extraction_status == ExtractionStatus.REVIEW_REQUIRED
        assert receipt.merchant_name == "Partial Cafe"
        assert len(receipt.items) == 1
        assert receipt.items[0].item_name == "Tea"
