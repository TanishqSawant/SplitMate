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


def test_list_groups(client):
    client.post("/api/groups", json={"name": "Group A"})
    client.post("/api/groups", json={"name": "Group B"})

    response = client.get("/api/groups")
    assert response.status_code == 200
    groups = response.json()
    assert len(groups) >= 2
    names = [g["name"] for g in groups]
    assert "Group A" in names
    assert "Group B" in names


def test_update_group(client):
    create_resp = client.post("/api/groups", json={"name": "Original Group Name"})
    assert create_resp.status_code == 201
    group_id = create_resp.json()["id"]

    update_resp = client.put(f"/api/groups/{group_id}", json={"name": "Renamed Squad"})
    assert update_resp.status_code == 200
    assert update_resp.json()["name"] == "Renamed Squad"


def test_delete_group(client):
    create_resp = client.post("/api/groups", json={"name": "To Delete"})
    assert create_resp.status_code == 201
    group_id = create_resp.json()["id"]

    del_resp = client.delete(f"/api/groups/{group_id}")
    assert del_resp.status_code == 204

    # Verify group is gone
    get_resp = client.get(f"/api/groups/{group_id}")
    assert get_resp.status_code == 404


def test_remove_member(client):
    create_resp = client.post("/api/groups", json={"name": "Member Test Group"})
    group_id = create_resp.json()["id"]

    add_resp = client.post(
        f"/api/groups/{group_id}/members",
        json={"name": "Charlie", "email": "charlie@example.com"},
    )
    assert add_resp.status_code == 201
    member_id = add_resp.json()["id"]

    del_resp = client.delete(f"/api/groups/{group_id}/members/{member_id}")
    assert del_resp.status_code == 204

    # Verify member is gone
    list_resp = client.get(f"/api/groups/{group_id}/members")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 0

