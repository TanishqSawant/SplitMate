"""Tests for the groups API."""


def test_create_group(client):
    response = client.post("/api/groups", json={"name": "Dinner Group"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Dinner Group"
    assert "id" in data
    assert "created_at" in data


def test_create_group_empty_name(client):
    response = client.post("/api/groups", json={"name": ""})
    assert response.status_code == 422  # validation error


def test_get_group(client):
    # Create
    create_resp = client.post("/api/groups", json={"name": "Test Group"})
    group_id = create_resp.json()["id"]

    # Retrieve
    response = client.get(f"/api/groups/{group_id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Group"


def test_get_group_not_found(client):
    response = client.get("/api/groups/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_add_member(client):
    # Create group
    create_resp = client.post("/api/groups", json={"name": "Test Group"})
    group_id = create_resp.json()["id"]

    # Add member
    response = client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Tanishq", "email": "tanishq@example.com"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Tanishq"
    assert data["email"] == "tanishq@example.com"
    assert data["group_id"] == group_id


def test_add_member_invalid_email(client):
    create_resp = client.post("/api/groups", json={"name": "Test Group"})
    group_id = create_resp.json()["id"]

    response = client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Tanishq", "email": "not-an-email"},
    )
    assert response.status_code == 422


def test_list_members(client):
    # Create group with two members
    create_resp = client.post("/api/groups", json={"name": "Test Group"})
    group_id = create_resp.json()["id"]

    client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Alice", "email": "alice@example.com"},
    )
    client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Bob", "email": "bob@example.com"},
    )

    response = client.get(f"/api/groups/{group_id}/members")
    assert response.status_code == 200
    members = response.json()
    assert len(members) == 2
    names = {m["name"] for m in members}
    assert names == {"Alice", "Bob"}

