import asyncio

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.models import Booking, Payment, WebhookEvent
from tests.conftest import API, signed_webhook

WEBHOOK = f"{API}/payments/webhook"


async def _pay(client, headers, booking_id, mode="success"):
    res = await client.post(f"{API}/payments?simulate={mode}", json={"booking_id": booking_id}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _counts():
    async with SessionLocal() as session:
        events = await session.scalar(select(func.count(WebhookEvent.id)))
        payments = await session.scalar(select(func.count(Payment.id)))
        bookings = await session.scalar(select(func.count(Booking.id)))
    return events, payments, bookings


async def _booking_status(client, headers, booking_id):
    return (await client.get(f"{API}/bookings/{booking_id}", headers=headers)).json()["status"]


async def test_webhook_confirms_booking_once_and_replays_are_noops(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"])
    body = signed_webhook(event_id="evt_1", booking_id=booking["id"], transaction_id=pay["transaction_id"])

    first = await client.post(WEBHOOK, json=body)
    assert first.status_code == 200
    assert first.json()["status"] == "processed" and first.json()["booking_status"] == "CONFIRMED"

    replays = [await client.post(WEBHOOK, json=body) for _ in range(3)]
    assert all(r.status_code == 200 for r in replays)
    assert all(r.json()["status"] == "already_processed" for r in replays)
    assert all(r.json()["booking_id"] == booking["id"] for r in replays)
    assert len({r.text for r in replays}) == 1  # byte-identical replay responses

    assert await _counts() == (1, 1, 1)  # one event, one payment, one booking


async def test_concurrent_duplicate_webhooks_are_applied_exactly_once(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"])
    body = signed_webhook(event_id="evt_race", booking_id=booking["id"], transaction_id=pay["transaction_id"])

    responses = await asyncio.gather(*[client.post(WEBHOOK, json=body) for _ in range(15)])

    assert all(r.status_code == 200 for r in responses)
    statuses = [r.json()["status"] for r in responses]
    assert statuses.count("processed") == 1
    assert statuses.count("already_processed") == 14
    duplicate_bodies = {r.text for r in responses if r.json()["status"] == "already_processed"}
    assert len(duplicate_bodies) == 1  # identical responses for every duplicate

    assert await _counts() == (1, 1, 1)  # zero duplicate DB entries
    assert await _booking_status(client, user_headers, booking["id"]) == "CONFIRMED"


async def test_confirmed_booking_never_regresses_to_failed(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"])
    ok = signed_webhook(event_id="evt_ok", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    assert (await client.post(WEBHOOK, json=ok)).json()["outcome"] == "APPLIED"

    late_failure = signed_webhook(
        event_id="evt_late_fail", booking_id=booking["id"], transaction_id=pay["transaction_id"], status="FAILED"
    )
    res = await client.post(WEBHOOK, json=late_failure)
    assert res.status_code == 200 and res.json()["outcome"] == "IGNORED"
    assert res.json()["booking_status"] == "CONFIRMED"

    another_success = signed_webhook(event_id="evt_ok_2", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    assert (await client.post(WEBHOOK, json=another_success)).json()["outcome"] == "IGNORED"
    assert await _booking_status(client, user_headers, booking["id"]) == "CONFIRMED"


async def test_failed_webhook_marks_booking_failed(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"], "failed")
    body = signed_webhook(event_id="evt_f", booking_id=booking["id"], transaction_id=pay["transaction_id"], status="FAILED")
    res = await client.post(WEBHOOK, json=body)
    assert res.json()["booking_status"] == "FAILED"
    # A late SUCCESS cannot resurrect a FAILED booking.
    late = signed_webhook(event_id="evt_f2", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    assert (await client.post(WEBHOOK, json=late)).json()["outcome"] == "IGNORED"
    assert await _booking_status(client, user_headers, booking["id"]) == "FAILED"


async def test_webhook_does_not_confirm_cancelled_booking(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"])
    await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=user_headers)
    body = signed_webhook(event_id="evt_c", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    res = await client.post(WEBHOOK, json=body)
    assert res.json()["outcome"] == "IGNORED" and res.json()["booking_status"] == "CANCELLED"


async def test_auto_dispatched_event_can_be_replayed_safely(client, user_headers, booking):
    pay = await _pay(client, user_headers, booking["id"])  # background webhook already confirmed it
    assert await _booking_status(client, user_headers, booking["id"]) == "CONFIRMED"
    replay = signed_webhook(
        event_id=f"evt_{pay['transaction_id']}", booking_id=booking["id"], transaction_id=pay["transaction_id"]
    )
    res = await client.post(WEBHOOK, json=replay)
    assert res.status_code == 200 and res.json()["status"] == "already_processed"
    assert await _counts() == (1, 1, 1)


async def test_invalid_signature_rejected_and_not_recorded(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"])
    body = signed_webhook(event_id="evt_bad", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    body["signature"] = "0" * 64
    assert (await client.post(WEBHOOK, json=body)).status_code == 401
    tampered = signed_webhook(event_id="evt_t", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    tampered["status"] = "FAILED"
    assert (await client.post(WEBHOOK, json=tampered)).status_code == 401
    assert (await _counts())[0] == 0
    assert await _booking_status(client, user_headers, booking["id"]) == "PENDING"


async def test_webhook_validation_and_lookup_errors(client, user_headers, booking, manual_webhooks):
    pay = await _pay(client, user_headers, booking["id"])
    unknown_booking = signed_webhook(event_id="e1", booking_id=9999, transaction_id=pay["transaction_id"])
    assert (await client.post(WEBHOOK, json=unknown_booking)).status_code == 404

    unknown_txn = signed_webhook(event_id="e2", booking_id=booking["id"], transaction_id="txn_nope")
    assert (await client.post(WEBHOOK, json=unknown_txn)).status_code == 404

    wrong_amount = signed_webhook(event_id="e3", booking_id=booking["id"], transaction_id=pay["transaction_id"], amount=1.0)
    assert (await client.post(WEBHOOK, json=wrong_amount)).status_code == 400

    invalid_status = signed_webhook(event_id="e4", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    invalid_status["status"] = "MAYBE"
    assert (await client.post(WEBHOOK, json=invalid_status)).status_code == 422
    assert (await client.post(WEBHOOK, json={"event_id": "x"})).status_code == 422

    # None of the rejected deliveries consumed an event id.
    assert (await _counts())[0] == 0
    ok = signed_webhook(event_id="e3", booking_id=booking["id"], transaction_id=pay["transaction_id"])
    assert (await client.post(WEBHOOK, json=ok)).json()["status"] == "processed"
