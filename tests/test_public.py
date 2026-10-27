from fastapi.testclient import TestClient
import pytest
from app.api import create_app
from app.domain import Parcel, ParcelState, EventType, InvalidTransition, apply_event

def test_domain_lifecycle():
    p = Parcel(id="pcl_1", merchant_ref="m1", cod_amount_piastres=100, address_text="Cairo")
    assert p.state == ParcelState.CREATED
    assert p.attempts == 0

    p_out = apply_event(p, EventType.DISPATCH)
    assert p_out.state == ParcelState.OUT_FOR_DELIVERY
    assert p_out.attempts == 1

    p_fail = apply_event(p_out, EventType.FAIL)
    assert p_fail.state == ParcelState.FAILED_ATTEMPT

    p_out2 = apply_event(p_fail, EventType.DISPATCH)
    assert p_out2.attempts == 2

    p_delivered = apply_event(p_out2, EventType.DELIVER)
    assert p_delivered.state == ParcelState.DELIVERED

    with pytest.raises(InvalidTransition):
        apply_event(p_delivered, EventType.FAIL)

def test_api_create_and_get():
    client = TestClient(create_app())
    res = client.post("/v1/parcels", json={
        "merchant_ref": "REF-001",
        "cod_amount_piastres": 5000,
        "address_text": "123 Street"
    })
    assert res.status_code == 201
    assert "Location" in res.headers
    data = res.json()
    assert data["merchant_ref"] == "REF-001"
    assert data["state"] == "created"
    assert data["id"].startswith("pcl_")

    get_res = client.get(f"/v1/parcels/{data['id']}")
    assert get_res.status_code == 200
    assert get_res.json() == data

def test_api_duplicate_merchant_ref():
    client = TestClient(create_app())
    body = {"merchant_ref": "REF-DUP", "cod_amount_piastres": 1000, "address_text": "Street"}
    res1 = client.post("/v1/parcels", json=body)
    assert res1.status_code == 201

    res2 = client.post("/v1/parcels", json=body)
    assert res2.status_code == 409
    assert res2.headers["content-type"] == "application/problem+json"

def test_api_invalid_event():
    client = TestClient(create_app())
    res = client.post("/v1/parcels", json={
        "merchant_ref": "REF-EVT",
        "cod_amount_piastres": 100,
        "address_text": "Street"
    })
    p_id = res.json()["id"]

    # created + deliver is forbidden
    bad_evt = client.post(f"/v1/parcels/{p_id}/events", json={"type": "deliver"})
    assert bad_evt.status_code == 409
    assert bad_evt.headers["content-type"] == "application/problem+json"

def test_api_pagination():
    client = TestClient(create_app())
    for i in range(25):
        client.post("/v1/parcels", json={
            "merchant_ref": f"REF-PAGE-{i}",
            "cod_amount_piastres": i * 10,
            "address_text": "Street"
        })

    page1 = client.get("/v1/parcels?limit=10").json()
    assert len(page1["items"]) == 10
    assert page1["next_cursor"] is not None

    page2 = client.get(f"/v1/parcels?limit=10&cursor={page1['next_cursor']}").json()
    assert len(page2["items"]) == 10
    assert page2["next_cursor"] is not None

    page3 = client.get(f"/v1/parcels?limit=10&cursor={page2['next_cursor']}").json()
    assert len(page3["items"]) == 5
    assert page3["next_cursor"] is None