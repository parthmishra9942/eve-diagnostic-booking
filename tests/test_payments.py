from tests.conftest import API


async def _status(client, headers, booking_id):
    return (await client.get(f"{API}/bookings/{booking_id}", headers=headers)).json()["status"]


async def test_successful_payment_confirms_booking_via_webhook(client, user_headers, booking):
    res = await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    assert res.status_code == 201
    pay = res.json()
    assert pay["status"] == "SUCCESS" and pay["amount"] == 1500.0 and pay["transaction_id"].startswith("txn_")
    assert await _status(client, user_headers, booking["id"]) == "CONFIRMED"  # delivered by webhook


async def test_failed_payment_marks_booking_failed(client, user_headers, booking):
    res = await client.post(f"{API}/payments?simulate=failed", json={"booking_id": booking["id"]}, headers=user_headers)
    assert res.status_code == 201 and res.json()["status"] == "FAILED"
    assert await _status(client, user_headers, booking["id"]) == "FAILED"


async def test_booking_stays_pending_until_webhook_arrives(client, user_headers, booking, manual_webhooks):
    await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    assert await _status(client, user_headers, booking["id"]) == "PENDING"


async def test_default_mode_is_random_and_valid(client, user_headers, booking):
    res = await client.post(f"{API}/payments", json={"booking_id": booking["id"]}, headers=user_headers)
    assert res.status_code == 201 and res.json()["status"] in {"SUCCESS", "FAILED"}


async def test_payment_edge_cases(client, user_headers, other_headers, booking):
    assert (await client.post(f"{API}/payments", json={"booking_id": booking["id"]})).status_code == 401
    assert (await client.post(f"{API}/payments", json={"booking_id": 999}, headers=user_headers)).status_code == 404
    assert (await client.post(f"{API}/payments", json={"booking_id": booking["id"]}, headers=other_headers)).status_code == 403
    assert (await client.post(f"{API}/payments", json={}, headers=user_headers)).status_code == 422
    assert (await client.post(f"{API}/payments?simulate=bogus", json={"booking_id": booking["id"]}, headers=user_headers)).status_code == 422


async def test_cannot_pay_for_cancelled_or_already_paid_booking(client, user_headers, booking):
    await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    again = await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    assert again.status_code == 409  # already CONFIRMED
    assert (await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=user_headers)).status_code == 200
    cancelled = await client.post(f"{API}/payments", json={"booking_id": booking["id"]}, headers=user_headers)
    assert cancelled.status_code == 409


async def test_duplicate_success_blocked_before_webhook_lands(client, user_headers, booking, manual_webhooks):
    first = await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    assert first.status_code == 201
    second = await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    assert second.status_code == 409


async def test_failed_payment_can_be_retried_while_booking_pending(client, user_headers, booking, manual_webhooks):
    assert (await client.post(f"{API}/payments?simulate=failed", json={"booking_id": booking["id"]}, headers=user_headers)).status_code == 201
    retry = await client.post(f"{API}/payments?simulate=success", json={"booking_id": booking["id"]}, headers=user_headers)
    assert retry.status_code == 201
