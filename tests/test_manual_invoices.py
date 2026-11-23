"""Ручные счета СБП: учёт, защита от двойного зачёта и сверка с провайдером."""

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from anonchat.db import Database
from anonchat.handlers.manual_invoices import verify_manual_invoice
from anonchat.payments import RollyPayError


def test_manual_invoice_lifecycle() -> None:
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            db = await Database(Path(directory) / "manual-invoices.db").start()
            try:
                invoice_id = await db.create_manual_invoice(
                    order_id="manual-1", created_by=100, user_id=200,
                    amount_rub=199, description="Тестовый счёт",
                )
                created = await db.get_manual_invoice(invoice_id)
                assert created["status"] == "creating"
                assert created["payment_id"] is None
                await db.attach_manual_invoice(invoice_id, "provider-1", "https://pay.example/1")
                await db.mark_manual_invoice_delivered(invoice_id)
                invoice = await db.get_manual_invoice(invoice_id)
                assert invoice["status"] == "awaiting_payment"
                assert invoice["delivered_at"] > 0
                assert invoice["user_id"] == 200 and invoice["created_by"] == 100
                assert await db.set_manual_invoice_status(invoice_id, "pending") is False
                assert await db.set_manual_invoice_status(invoice_id, "paid") is True
                assert await db.set_manual_invoice_status(invoice_id, "paid") is False
                assert await db.set_manual_invoice_status(invoice_id, "failed") is False
                assert (await db.get_manual_invoice(invoice_id))["status"] == "paid"
                assert (await db.manual_invoice_stats()) == {
                    "total": 1, "paid": 1, "unpaid": 0, "paid_rub": 199,
                }
                assert len(await db.list_manual_invoices(status="paid")) == 1
                assert len(await db.list_manual_invoices(status="unpaid")) == 0
            finally:
                await db.close()
    asyncio.run(scenario())


def test_manual_invoice_verifies_provider_identity_amount_and_currency() -> None:
    async def scenario():
        with tempfile.TemporaryDirectory() as directory:
            db = await Database(Path(directory) / "manual-invoices.db").start()
            try:
                invoice_id = await db.create_manual_invoice(
                    order_id="manual-secure", created_by=100, user_id=200,
                    amount_rub=349, description="Счёт для проверки",
                )
                await db.attach_manual_invoice(invoice_id, "provider-secure", "https://pay.example")
                invoice = await db.get_manual_invoice(invoice_id)
                remote = {
                    "payment_id": "provider-secure", "order_id": "manual-secure",
                    "currency": "RUB", "amount": "349.00", "status": "paid",
                }
                for altered in (
                    {"payment_id": "another"},
                    {"order_id": "another"},
                    {"currency": "XTR"},
                    {"amount": "350.00"},
                    {"amount": "NaN"},
                ):
                    with patch(
                        "anonchat.handlers.manual_invoices.get_payment",
                        new=AsyncMock(return_value={**remote, **altered}),
                    ):
                        try:
                            await verify_manual_invoice(SimpleNamespace(), db, invoice)
                        except RollyPayError:
                            pass
                        else:
                            raise AssertionError("Провайдер вернул несоответствующий платёж")
                    assert (await db.get_manual_invoice(invoice_id))["status"] == "awaiting_payment"
                with patch(
                    "anonchat.handlers.manual_invoices.get_payment",
                    new=AsyncMock(return_value=remote),
                ) as provider:
                    assert await verify_manual_invoice(SimpleNamespace(), db, invoice) == ("paid", True)
                    assert provider.await_count == 1
                invoice = await db.get_manual_invoice(invoice_id)
                assert await verify_manual_invoice(SimpleNamespace(), db, invoice) == ("paid", False)
            finally:
                await db.close()
    asyncio.run(scenario())


if __name__ == "__main__":
    test_manual_invoice_lifecycle()
    test_manual_invoice_verifies_provider_identity_amount_and_currency()
