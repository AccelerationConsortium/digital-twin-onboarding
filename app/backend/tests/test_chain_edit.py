"""A transfer's waypoints can be taken from a draft layout, edited by hand and checked."""

from test_layout_refine import opened


def chain(client, catalog, step=3):
    response = client.post("/api/twins/layout/chain", json={**catalog["layout"], "step": step})
    assert response.status_code == 200, response.text
    return response.json()


def check(client, catalog, doc, step=3):
    body = {
        **catalog["layout"],
        "step": step,
        "reference": doc["reference"],
        "waypoints": [{k: w[k] for k in ("name", "degrees", "hold")} for w in doc["waypoints"]],
    }
    response = client.post("/api/twins/layout/chain/check", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_planned_waypoints_pass_their_own_check(client):
    catalog, _ = opened(client)
    doc = chain(client, catalog)
    assert doc["schema"] == "ur5e.action-chain/2" and 1 < len(doc["waypoints"]) <= 24
    result = check(client, catalog, doc)
    assert result["problem"] is None, result["problem"]
    assert result["clearance_m"] >= 0.01 and result["seconds"] > 5
    # The tool comes to both grasp points, and the path was run in the simulation.
    assert result["source_m"] <= 0.02 and result["target_m"] <= 0.02
    assert result["simulation"]["engine"] == "mujoco" and result["simulation"]["torque_ratio"] < 1
    assert len(result["frames"]) == len(result["joints"]) > 2
    # Nothing is stored.
    assert client.get("/api/twins").json()["version"] == catalog["version"]


def test_an_edit_that_hits_something_or_misses_the_grasp_says_so(client):
    catalog, _ = opened(client)
    doc = chain(client, catalog)
    # Folding the elbow through the bench.
    low = {**doc, "waypoints": [dict(w) for w in doc["waypoints"]]}
    low["waypoints"][0]["degrees"] = [0, 0, 150, 0, 0, 0]
    result = check(client, catalog, low)
    assert "would hit" in result["problem"] and result["simulation"] is None
    assert result["frames"]
    # Dropping the last waypoints never reaches the reader's tray.
    short = {**doc, "waypoints": doc["waypoints"][:2]}
    result = check(client, catalog, short)
    assert "grasp point" in result["problem"] and "Plate reader" in result["problem"]
    # A joint past its limit is named.
    far = {**doc, "waypoints": [dict(w) for w in doc["waypoints"]]}
    far["waypoints"][1]["degrees"] = [0, -90, 170, -90, -90, 0]
    assert "joint 3 is past" in check(client, catalog, far)["problem"]


def test_only_a_transfer_on_a_placed_layout_has_waypoints(client):
    catalog, _ = opened(client)
    wrong = client.post("/api/twins/layout/chain", json={**catalog["layout"], "step": 1})
    assert wrong.status_code == 422 and "not a transfer" in wrong.json()["detail"]["message"]
    empty = client.post(
        "/api/twins/layout/chain",
        json={"bench": catalog["layout"]["bench"], "placements": [], "step": 3},
    )
    assert empty.status_code == 422
