from datetime import UTC, datetime, timedelta

from tests.conftest import API, future_iso


def _payload(catalog, when=None):
    return {
        "centre_id": catalog["centre"]["id"],
        "test_id": catalog["test"]["id"],
        "appointment_datetime": when or future_iso(),
    }


async def test_create_booking_locks_price_and_starts_pending(client, user_headers, staff_headers, catalog):
    res = await client.post(f"{API}/bookings", json=_payload(catalog), headers=user_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING" and body["amount"] == 1500.0

    # Staff changes the price afterwards: the booking keeps its locked-in amount.
    await client.put(
        f"{API}/centres/{catalog['centre']['id']}/tests/{catalog['test']['id']}", json={"price": 2500}, headers=staff_headers
    )
    again = await client.get(f"{API}/bookings/{body['id']}", headers=user_headers)
    assert again.json()["amount"] == 1500.0
    new = await client.post(f"{API}/bookings", json=_payload(catalog), headers=user_headers)
    assert new.json()["amount"] == 2500.0


async def test_past_or_present_appointment_rejected_with_422(client, user_headers, catalog):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    res = await client.post(f"{API}/bookings", json=_payload(catalog, past), headers=user_headers)
    assert res.status_code == 422
    assert "in the future" in res.json()["error"]["message"]
    garbage = await client.post(f"{API}/bookings", json=_payload(catalog, "tomorrow"), headers=user_headers)
    assert garbage.status_code == 422


async def test_centre_test_mismatch_is_400(client, user_headers, staff_headers, catalog):
    other_test = (await client.post(f"{API}/tests", json={"name": "MRI"}, headers=staff_headers)).json()
    res = await client.post(
        f"{API}/bookings", json={**_payload(catalog), "test_id": other_test["id"]}, headers=user_headers
    )
    assert res.status_code == 400
    assert "does not offer" in res.json()["error"]["message"]


async def test_unknown_centre_or_test_is_404(client, user_headers, catalog):
    assert (await client.post(f"{API}/bookings", json={**_payload(catalog), "centre_id": 999}, headers=user_headers)).status_code == 404
    assert (await client.post(f"{API}/bookings", json={**_payload(catalog), "test_id": 999}, headers=user_headers)).status_code == 404


async def test_booking_requires_authentication(client, catalog):
    assert (await client.post(f"{API}/bookings", json=_payload(catalog))).status_code == 401


async def test_non_existent_booking_is_404(client, user_headers):
    assert (await client.get(f"{API}/bookings/424242", headers=user_headers)).status_code == 404
    assert (await client.post(f"{API}/bookings/424242/cancel", headers=user_headers)).status_code == 404


async def test_authorization_isolation_between_users(client, user_headers, other_headers, booking):
    # Owner can read it.
    assert (await client.get(f"{API}/bookings/{booking['id']}", headers=user_headers)).status_code == 200
    # Another user gets 403 on read and on cancel; the booking is untouched.
    assert (await client.get(f"{API}/bookings/{booking['id']}", headers=other_headers)).status_code == 403
    assert (await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=other_headers)).status_code == 403
    assert (await client.get(f"{API}/bookings/{booking['id']}", headers=user_headers)).json()["status"] == "PENDING"
    # Listings only show your own bookings.
    assert (await client.get(f"{API}/bookings", headers=other_headers)).json() == {
        "items": [], "total": 0, "limit": 20, "offset": 0,
    }
    mine = (await client.get(f"{API}/bookings", headers=user_headers)).json()
    assert mine["total"] == 1 and mine["items"][0]["id"] == booking["id"]


async def test_cancel_lifecycle(client, user_headers, booking):
    cancelled = await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=user_headers)
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    again = await client.post(f"{API}/bookings/{booking['id']}/cancel", headers=user_headers)
    assert again.status_code == 409


async def test_list_filter_and_pagination(client, user_headers, catalog):
    for _ in range(3):
        await client.post(f"{API}/bookings", json=_payload(catalog), headers=user_headers)
    page = (await client.get(f"{API}/bookings", params={"limit": 2}, headers=user_headers)).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    first_id = page["items"][0]["id"]
    await client.post(f"{API}/bookings/{first_id}/cancel", headers=user_headers)
    cancelled = (await client.get(f"{API}/bookings", params={"status": "CANCELLED"}, headers=user_headers)).json()
    assert cancelled["total"] == 1
