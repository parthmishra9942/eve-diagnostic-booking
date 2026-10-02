from app.core.cache import cache
from tests.conftest import API


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.gets = 0

    async def get(self, key):
        self.gets += 1
        return self.store.get(key)

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def incr(self, key):
        self.store[key] = str(int(self.store.get(key, 0)) + 1)

    async def ping(self):
        return True


async def test_only_staff_can_create_centres(client, user_headers, staff_headers):
    payload = {"name": "Lab A", "location": "Bhopal"}
    assert (await client.post(f"{API}/centres", json=payload)).status_code == 401
    assert (await client.post(f"{API}/centres", json=payload, headers=user_headers)).status_code == 403
    created = await client.post(f"{API}/centres", json=payload, headers=staff_headers)
    assert created.status_code == 201
    assert created.json()["is_active"] is True
    assert (await client.post(f"{API}/centres", json=payload, headers=staff_headers)).status_code == 409


async def test_centre_search_and_pagination(client, staff_headers):
    for name, loc in [("Apollo Diagnostics", "Indore"), ("Apollo Labs", "Bhopal"), ("Metro Path", "Indore")]:
        await client.post(f"{API}/centres", json={"name": name, "location": loc}, headers=staff_headers)

    everything = (await client.get(f"{API}/centres")).json()
    assert everything["total"] == 3

    by_name = (await client.get(f"{API}/centres", params={"name": "apollo"})).json()
    assert {c["name"] for c in by_name["items"]} == {"Apollo Diagnostics", "Apollo Labs"}

    by_location = (await client.get(f"{API}/centres", params={"location": "indore"})).json()
    assert by_location["total"] == 2

    page = (await client.get(f"{API}/centres", params={"limit": 1, "offset": 1})).json()
    assert page["total"] == 3 and len(page["items"]) == 1 and page["offset"] == 1

    assert (await client.get(f"{API}/centres", params={"limit": 0})).status_code == 422
    # LIKE wildcards in user input are treated literally
    assert (await client.get(f"{API}/centres", params={"name": "%"})).json()["total"] == 0


async def test_centre_tests_listing_and_linking(client, staff_headers, catalog):
    centre_id = catalog["centre"]["id"]
    listing = await client.get(f"{API}/centres/{centre_id}/tests")
    assert listing.status_code == 200
    [entry] = listing.json()
    assert entry["price"] == 1500.0 and entry["turnaround_hours"] == 12 and entry["test"]["name"] == "CBC"

    dup = await client.post(
        f"{API}/centres/{centre_id}/tests", json={"test_id": catalog["test"]["id"], "price": 1}, headers=staff_headers
    )
    assert dup.status_code == 409
    missing = await client.post(f"{API}/centres/{centre_id}/tests", json={"test_id": 999, "price": 10}, headers=staff_headers)
    assert missing.status_code == 404
    bad_price = await client.post(f"{API}/centres/{centre_id}/tests", json={"test_id": 1, "price": -5}, headers=staff_headers)
    assert bad_price.status_code == 422
    assert (await client.get(f"{API}/centres/999/tests")).status_code == 404

    updated = await client.put(
        f"{API}/centres/{centre_id}/tests/{catalog['test']['id']}", json={"price": 1800}, headers=staff_headers
    )
    assert updated.status_code == 200 and updated.json()["price"] == 1800.0


async def test_tests_catalogue(client, staff_headers, user_headers):
    assert (await client.post(f"{API}/tests", json={"name": "X"}, headers=user_headers)).status_code == 403
    await client.post(f"{API}/tests", json={"name": "Lipid Profile", "category": "Biochemistry"}, headers=staff_headers)
    res = await client.get(f"{API}/tests", params={"category": "bio"})
    assert res.json()["total"] == 1


async def test_centre_list_is_cached_and_invalidated(client, staff_headers):
    fake = FakeRedis()
    orig_enabled = cache._enabled
    cache._enabled = True
    cache._client, cache._disabled_until = fake, 0.0
    try:
        await client.post(f"{API}/centres", json={"name": "Lab A", "location": "Indore"}, headers=staff_headers)
        first = (await client.get(f"{API}/centres")).json()
        assert any(k.startswith("centres:list:") for k in fake.store)  # populated
        second = (await client.get(f"{API}/centres")).json()
        assert first == second

        await client.post(f"{API}/centres", json={"name": "Lab B", "location": "Indore"}, headers=staff_headers)
        refreshed = (await client.get(f"{API}/centres")).json()
        assert refreshed["total"] == 2  # version bump invalidated the stale page
    finally:
        cache._client, cache._disabled_until = None, 0.0
        cache._enabled = orig_enabled


async def test_api_works_when_redis_is_unreachable(client, staff_headers):
    # conftest points REDIS_URL at a closed port
    cache._client, cache._disabled_until = None, 0.0
    await client.post(f"{API}/centres", json={"name": "Lab A", "location": "Indore"}, headers=staff_headers)
    res = await client.get(f"{API}/centres")
    assert res.status_code == 200 and res.json()["total"] == 1
    health = await client.get("/health")
    assert health.status_code == 200 and health.json()["cache"] is False
