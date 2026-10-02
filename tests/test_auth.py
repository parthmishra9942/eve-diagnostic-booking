from tests.conftest import API, PASSWORD, make_user

SIGNUP = {"email": "Alice@Example.com", "full_name": "Alice", "password": PASSWORD}


async def test_signup_login_me_flow(client):
    res = await client.post(f"{API}/auth/signup", json=SIGNUP)
    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "alice@example.com"  # normalised
    assert body["role"] == "USER"
    assert "password" not in body and "hashed_password" not in body

    login = await client.post(f"{API}/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    me = await client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


async def test_duplicate_signup_conflict(client):
    assert (await client.post(f"{API}/auth/signup", json=SIGNUP)).status_code == 201
    res = await client.post(f"{API}/auth/signup", json={**SIGNUP, "email": "alice@example.com"})
    assert res.status_code == 409


async def test_signup_cannot_self_assign_role(client):
    res = await client.post(f"{API}/auth/signup", json={**SIGNUP, "role": "ADMIN"})
    assert res.status_code == 201
    assert res.json()["role"] == "USER"


async def test_signup_validation(client):
    bad_email = await client.post(f"{API}/auth/signup", json={**SIGNUP, "email": "not-an-email"})
    assert bad_email.status_code == 422
    short = await client.post(f"{API}/auth/signup", json={**SIGNUP, "password": "a1"})
    assert short.status_code == 422
    weak = await client.post(f"{API}/auth/signup", json={**SIGNUP, "password": "onlyletters"})
    assert weak.status_code == 422
    assert "letter and one digit" in weak.json()["error"]["message"]


async def test_login_wrong_password_and_unknown_user(client):
    await client.post(f"{API}/auth/signup", json=SIGNUP)
    wrong = await client.post(f"{API}/auth/login", json={"email": "alice@example.com", "password": "Wrong1234"})
    unknown = await client.post(f"{API}/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]  # no user enumeration


async def test_protected_endpoints_require_valid_token(client):
    assert (await client.get(f"{API}/auth/me")).status_code == 401
    assert (await client.get(f"{API}/bookings")).status_code == 401
    bad = await client.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage"})
    assert bad.status_code == 401


async def test_password_is_hashed_with_bcrypt(client):
    from sqlalchemy import select

    from app.core.database import SessionLocal
    from app.models import User

    await client.post(f"{API}/auth/signup", json=SIGNUP)
    async with SessionLocal() as session:
        user = await session.scalar(select(User))
    assert user.hashed_password.startswith("$2") and user.hashed_password != PASSWORD


async def test_login_rate_limit(client):
    from app.core.rate_limit import limiter

    limiter.enabled = True
    limiter.reset()
    try:
        codes = [
            (await client.post(f"{API}/auth/login", json={"email": "x@example.com", "password": "Wrong1234"})).status_code
            for _ in range(7)
        ]
    finally:
        limiter.enabled = False
        limiter.reset()
    assert codes[:5] == [401] * 5
    assert 429 in codes[5:]


async def test_make_user_helper_creates_staff(client):
    headers = await make_user(client, "s@example.com")
    assert (await client.get(f"{API}/auth/me", headers=headers)).status_code == 200
