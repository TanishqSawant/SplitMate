"""PostgreSQL concurrency and query compilation tests for PayPal payments."""

import os
import threading
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.models.models import Base, ExpenseGroup, GroupMember, Expense, Payment, PaymentStatus
from app.services.paypal_service import PayPalService


def test_postgresql_dialect_generates_for_update():
    """Verify that SQLAlchemy compiles .with_for_update() into a native SQL 'FOR UPDATE' clause."""
    test_id = uuid.uuid4()
    query = select(Payment).where(Payment.id == test_id).with_for_update()
    compiled_sql = str(query.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE" in compiled_sql
    assert "payments" in compiled_sql


@pytest.mark.skipif(
    not os.getenv("TEST_POSTGRESQL_URL"),
    reason="TEST_POSTGRESQL_URL environment variable not set; skipping live PostgreSQL concurrency test."
)
def test_live_postgres_concurrent_capture_lock():
    """Live PostgreSQL integration test: verifies row-level locking serializes concurrent captures.

    Only executed when a real PostgreSQL instance is supplied via TEST_POSTGRESQL_URL.
    """
    pg_url = os.environ["TEST_POSTGRESQL_URL"]
    engine = create_engine(pg_url)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)

    # Setup payment
    session1 = Session()
    group = ExpenseGroup(name="PG Concurrency Test Group")
    session1.add(group)
    session1.commit()

    member = GroupMember(group_id=group.id, name="Bob", email="bob@example.com")
    session1.add(member)
    session1.commit()

    expense = Expense(group_id=group.id, total_amount=20.00, currency="USD")
    session1.add(expense)
    session1.commit()

    payment = Payment(
        expense_id=expense.id,
        member_id=member.id,
        amount=20.00,
        currency="USD",
        status=PaymentStatus.ORDER_CREATED,
        paypal_order_id="PG-CONC-ORDER-1",
    )
    session1.add(payment)
    session1.commit()
    payment_id = payment.id
    session1.close()

    results = []
    lock = threading.Lock()

    def _attempt_capture(worker_id: int):
        worker_session = Session()
        try:
            # Query with row-level lock
            p = (
                worker_session.query(Payment)
                .filter(Payment.id == payment_id)
                .with_for_update()
                .first()
            )
            if p.status == PaymentStatus.CAPTURED:
                with lock:
                    results.append((worker_id, "ALREADY_CAPTURED"))
                worker_session.rollback()
                return

            if p.status == PaymentStatus.ORDER_CREATED:
                # Simulate work
                import time
                time.sleep(0.1)
                p.status = PaymentStatus.CAPTURED
                p.paypal_capture_id = f"CAP-WORKER-{worker_id}"
                worker_session.commit()
                with lock:
                    results.append((worker_id, "CAPTURED"))
        except Exception as e:
            worker_session.rollback()
            with lock:
                results.append((worker_id, str(e)))
        finally:
            worker_session.close()

    t1 = threading.Thread(target=_attempt_capture, args=(1,))
    t2 = threading.Thread(target=_attempt_capture, args=(2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # One worker must capture, and the other must see ALREADY_CAPTURED
    statuses = [r[1] for r in results]
    assert "CAPTURED" in statuses
    assert "ALREADY_CAPTURED" in statuses
    assert len(statuses) == 2

