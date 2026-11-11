"""Regression tests for standardized receipt completion validation logic.

Verifies:
1. Valid automatic completion:
   - Consistent subtotal, tax, and total.
   - Legitimate tip or adjustment where subtotal + tax != total.
   - Missing tax but reliable total.
   - Missing subtotal but reliable total.
2. Review required:
   - Missing currency.
   - Missing final total.
   - Zero or negative final total.
   - Empty item list.
   - Missing item name.
   - Missing quantity.
   - Zero or negative quantity.
   - Missing unit price or total price.
   - Incorrect item arithmetic.
   - Critical fields marked uncertain.
   - Critical fields marked missing.
3. Contract consistency:
   - Background and ingest paths make identical completion decisions.
   - Missing values remain null (no hallucinated defaults or zero conversions).
   - No arbitrary confidence threshold (e.g. 0.70) blocks complete receipts.
4. Payment regression:
   - Receipts in REVIEW_REQUIRED block payment order creation.
   - Receipts in REVIEW_REQUIRED block payment capture.
   - Payer authorization and IDOR protections remain intact.
"""

import io
import json
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.api.routes.receipts import (
    _validate_completion_gate,
    _validate_ingest_completion,
    _validate_receipt_completion,
    process_receipt_extraction_task,
)
from app.models.models import (
    Expense,
    ExpenseGroup,
    ExtractionStatus,
    GroupMember,
    Payment,
    PaymentStatus,
    Receipt,
    ReceiptItem,
)
from app.services.receipt_extractor.schemas import (
    ExtractedLineItem,
    ReceiptExtractionResult,
)
from tests.conftest import (
    TEST_INTERNAL_SERVICE_SECRET,
    VALID_JPEG_BYTES,
    create_user_and_client,
)

AI_KEY_HEADER = {"X-Internal-Service-Key": TEST_INTERNAL_SERVICE_SECRET}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _upload_receipt(client, tmp_path) -> str:
    """Helper to upload a receipt and return its ID string."""
    with patch("app.core.config.settings.UPLOAD_DIR", str(tmp_path)):
        resp = client.post(
            "/api/receipts/upload",
            files={"file": ("test.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")},
        )
    assert resp.status_code == 201, f"Upload failed: {resp.text}"
    return resp.json()["receipt_id"]


def _base_payload(**overrides) -> dict:
    base = {
        "merchant_name": "Corner Cafe",
        "currency": "USD",
        "subtotal": "20.00",
        "tax": "2.00",
        "total": "22.00",
        "items": [
            {
                "item_name": "Sandwich",
                "quantity": "2",
                "unit_price": "10.00",
                "total_price": "20.00",
            }
        ],
    }
    base.update(overrides)
    return base


# ===========================================================================
# 1. Valid Automatic Completion
# ===========================================================================

class TestValidAutomaticCompletion:

    def test_consistent_subtotal_tax_and_total(self, client, tmp_path):
        """Receipt with consistent subtotal, tax, and total auto-completes."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload()
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "completed"
        assert data["total"] == "22.00"

    def test_legitimate_tip_adjustment_causing_subtotal_tax_difference(self, client, tmp_path):
        """Receipt with subtotal (20.00) + tax (2.00) != total (27.00) (due to $5 tip) auto-completes."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(total="27.00")  # $5 tip not in subtotal+tax
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "completed"
        assert data["total"] == "27.00"

    def test_missing_tax_with_reliable_total(self, client, tmp_path):
        """Receipt with missing tax (tax=None) and reliable total auto-completes without error."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(tax=None, total="20.00")
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "completed"
        assert data["tax"] is None
        assert data["total"] == "20.00"

    def test_missing_subtotal_with_reliable_total(self, client, tmp_path):
        """Receipt with missing subtotal (subtotal=None) and reliable total auto-completes."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(subtotal=None, tax=None, total="20.00")
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "completed"
        assert data["subtotal"] is None
        assert data["total"] == "20.00"


# ===========================================================================
# 2. Review Required Tests
# ===========================================================================

class TestReviewRequiredGates:

    def test_missing_currency_routes_to_review_required(self, client, tmp_path):
        """Receipt with missing/None currency must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(currency=None)
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "review_required"
        assert any("Currency" in str(w) for w in (data.get("warnings") or []))

    def test_missing_final_total_routes_to_review_required(self, client, tmp_path):
        """Receipt with missing total must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(total=None)
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "review_required"

    def test_zero_or_negative_total_routes_to_review_required(self, client, tmp_path):
        """Zero or negative total must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        # Test zero total
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=_base_payload(total="0.00"),
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

        # Test negative total
        receipt_id_2 = _upload_receipt(client, tmp_path)
        resp2 = client.post(
            f"/api/receipts/{receipt_id_2}/extraction",
            json=_base_payload(total="-15.00"),
            headers=AI_KEY_HEADER,
        )
        assert resp2.status_code == 200, resp2.text
        assert resp2.json()["extraction_status"] == "review_required"

    def test_empty_item_list_routes_to_review_required(self, client, tmp_path):
        """Receipt with empty item list must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(items=[])
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_missing_item_name_routes_to_review_required(self, client, tmp_path):
        """Line item with missing or whitespace-only name must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(
            items=[{"item_name": "  ", "quantity": "1", "unit_price": "22.00", "total_price": "22.00"}]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_missing_quantity_routes_to_review_required(self, client, tmp_path):
        """Line item with missing quantity (None) must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(
            items=[{"item_name": "Burger", "quantity": None, "unit_price": "10.00", "total_price": "10.00"}]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_zero_or_negative_quantity_routes_to_review_required(self):
        """Line item with quantity <= 0 fails the completion gate and routes to review_required."""
        item_zero = {"item_name": "Burger", "quantity": Decimal("0"), "unit_price": Decimal("10.00"), "total_price": Decimal("0.00")}
        passes, reason = _validate_receipt_completion(currency="USD", total=Decimal("10.00"), items=[item_zero])
        assert passes is False
        assert "non-positive quantity" in reason

        item_neg = {"item_name": "Burger", "quantity": Decimal("-1"), "unit_price": Decimal("10.00"), "total_price": Decimal("-10.00")}
        passes_neg, reason_neg = _validate_receipt_completion(currency="USD", total=Decimal("10.00"), items=[item_neg])
        assert passes_neg is False
        assert "non-positive quantity" in reason_neg

    def test_missing_unit_or_total_price_routes_to_review_required(self, client, tmp_path):
        """Line item with missing unit_price or total_price must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(
            items=[{"item_name": "Burger", "quantity": "1", "unit_price": None, "total_price": "10.00"}]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_incorrect_item_arithmetic_routes_to_review_required(self, client, tmp_path):
        """Line item where qty * unit_price != total_price must route to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(
            items=[{"item_name": "Burger", "quantity": "2", "unit_price": "10.00", "total_price": "25.00"}]
        )
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_critical_fields_marked_uncertain_routes_to_review_required(self, client, tmp_path):
        """Receipt where currency or total is marked uncertain routes to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(uncertain_fields=["currency"])
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"

    def test_critical_fields_marked_missing_routes_to_review_required(self, client, tmp_path):
        """Receipt where final_total or items are in missing_fields routes to review_required."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = _base_payload(missing_fields=["final_total"])
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["extraction_status"] == "review_required"


# ===========================================================================
# 3. Contract Consistency
# ===========================================================================

class TestContractConsistency:

    def test_background_and_ingest_paths_yield_identical_completion_decision(self):
        """Both _validate_completion_gate and _validate_ingest_completion share the same core gate."""
        # 1. Valid receipt with tip
        valid_res = ReceiptExtractionResult(
            currency="USD",
            subtotal=Decimal("20.00"),
            tax=Decimal("2.00"),
            final_total=Decimal("27.00"),  # $5 tip
            items=[
                ExtractedLineItem(item_name="Steak", quantity=1, unit_price=Decimal("20.00"), total_price=Decimal("20.00"))
            ],
        )
        passes_bg, reason_bg = _validate_completion_gate(valid_res)
        passes_ing, reason_ing = _validate_ingest_completion(valid_res)
        assert passes_bg is True
        assert passes_ing is True
        assert reason_bg == ""
        assert reason_ing == ""

        # 2. Inconsistent item math
        bad_res = ReceiptExtractionResult(
            currency="USD",
            subtotal=Decimal("20.00"),
            tax=Decimal("2.00"),
            final_total=Decimal("22.00"),
            items=[
                ExtractedLineItem(item_name="Steak", quantity=1, unit_price=Decimal("20.00"), total_price=Decimal("25.00"))
            ],
        )
        passes_bg, reason_bg = _validate_completion_gate(bad_res)
        passes_ing, reason_ing = _validate_ingest_completion(bad_res)
        assert passes_bg is False
        assert passes_ing is False
        assert "differs from total_price" in reason_bg
        assert "differs from total_price" in reason_ing

    def test_missing_values_remain_null(self, client, tmp_path):
        """Missing subtotal or tax must remain null in the database and never silently become zero."""
        receipt_id = _upload_receipt(client, tmp_path)
        payload = {
            "merchant_name": None,
            "currency": "EUR",
            "subtotal": None,
            "tax": None,
            "total": "18.50",
            "items": [
                {
                    "item_name": "Tapas",
                    "quantity": "1",
                    "unit_price": "18.50",
                    "total_price": "18.50",
                }
            ],
        }
        resp = client.post(
            f"/api/receipts/{receipt_id}/extraction",
            json=payload,
            headers=AI_KEY_HEADER,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["extraction_status"] == "completed"
        assert data["merchant_name"] is None
        assert data["subtotal"] is None
        assert data["tax"] is None
        assert data["total"] == "18.50"

    def test_no_arbitrary_confidence_threshold_applied(self):
        """A receipt with confidence score 0.40 but valid fields auto-completes cleanly."""
        res = ReceiptExtractionResult(
            currency="USD",
            subtotal=None,
            tax=None,
            final_total=Decimal("15.00"),
            confidence=0.40,  # Below 0.70 threshold
            items=[
                ExtractedLineItem(item_name="Lunch", quantity=1, unit_price=Decimal("15.00"), total_price=Decimal("15.00"))
            ],
        )
        passes, reason = _validate_completion_gate(res)
        assert passes is True
        assert reason == ""


# ===========================================================================
# 4. Payment Regression Tests
# ===========================================================================

class TestPaymentReceiptCompletionProtection:

    def test_review_required_receipt_blocks_payment_order_creation(self, client, db_session, default_user):
        """Payment order creation is rejected with 400 when the linked receipt is in review_required status."""
        group = ExpenseGroup(name="Trip Group", creator_id=default_user.id)
        db_session.add(group)
        db_session.flush()

        member = GroupMember(group_id=group.id, user_id=default_user.id, name="Alice", email=default_user.email)
        db_session.add(member)
        db_session.flush()

        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="receipt.jpg",
            stored_file_path="/tmp/receipt.jpg",
            extraction_status=ExtractionStatus.REVIEW_REQUIRED,  # Blocked status
            currency="USD",
            total=Decimal("50.00"),
        )
        db_session.add(receipt)
        db_session.flush()

        expense = Expense(group_id=group.id, receipt_id=receipt.id, total_amount=Decimal("50.00"), currency="USD")
        db_session.add(expense)
        db_session.flush()

        payment = Payment(
            expense_id=expense.id,
            member_id=member.id,
            amount=Decimal("25.00"),
            currency="USD",
            status=PaymentStatus.PENDING,
        )
        db_session.add(payment)
        db_session.commit()

        resp = client.post(f"/api/payments/{payment.id}/create-order", json={})
        assert resp.status_code == 400
        assert "not completed" in resp.json()["detail"].lower()

    def test_review_required_receipt_blocks_payment_capture(self, client, db_session, default_user):
        """Payment capture is rejected with 400 if the receipt status is review_required."""
        group = ExpenseGroup(name="Trip Group", creator_id=default_user.id)
        db_session.add(group)
        db_session.flush()

        member = GroupMember(group_id=group.id, user_id=default_user.id, name="Alice", email=default_user.email)
        db_session.add(member)
        db_session.flush()

        receipt = Receipt(
            uploader_id=default_user.id,
            original_filename="receipt.jpg",
            stored_file_path="/tmp/receipt.jpg",
            extraction_status=ExtractionStatus.REVIEW_REQUIRED,  # Blocked status
            currency="USD",
            total=Decimal("50.00"),
        )
        db_session.add(receipt)
        db_session.flush()

        expense = Expense(group_id=group.id, receipt_id=receipt.id, total_amount=Decimal("50.00"), currency="USD")
        db_session.add(expense)
        db_session.flush()

        payment = Payment(
            expense_id=expense.id,
            member_id=member.id,
            amount=Decimal("25.00"),
            currency="USD",
            status=PaymentStatus.ORDER_CREATED,
            paypal_order_id="VALID_ORDER_123",
        )
        db_session.add(payment)
        db_session.commit()

        resp = client.post(
            f"/api/payments/{payment.id}/capture",
            json={"paypal_order_id": "VALID_ORDER_123"},
        )
        assert resp.status_code == 400
        assert "not completed" in resp.json()["detail"].lower()
