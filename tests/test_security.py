from app.core.security import compute_webhook_signature, verify_webhook_signature


def test_signature_roundtrip_and_tamper_detection():
    fields = dict(event_id="e", booking_id=1, transaction_id="t", status="SUCCESS", amount=10.5)
    sig = compute_webhook_signature(**fields)
    assert verify_webhook_signature(signature=sig, **fields)
    assert not verify_webhook_signature(signature=sig, **{**fields, "amount": 10.51})
    assert not verify_webhook_signature(signature=sig, **{**fields, "status": "FAILED"})


def test_signature_is_amount_format_agnostic():
    base = dict(event_id="e", booking_id=1, transaction_id="t", status="SUCCESS")
    assert compute_webhook_signature(**base, amount=10) == compute_webhook_signature(**base, amount="10.00")
