from uuid import uuid4

from academy.simple_twins import TEMPLATES
from fastapi.testclient import TestClient

INCUBATOR, READER, ARM = (str(uuid4()) for _ in range(3))
DEVICES = [
    {"id": INCUBATOR, "library": {"collection": "simready", "id": "forgecad-laboratory-incubator"}},
    {"id": READER, "library": {"collection": "simready", "id": "forgecad-microplate-reader"}},
    {"id": ARM, "spec": TEMPLATES["transfer-arm"]},
]
STEPS = [
    {"device_id": INCUBATOR, "operation": "load", "value": 200},
    {"device_id": INCUBATOR, "operation": "heat", "value": 37},
    {"device_id": ARM, "operation": "transfer", "source_id": INCUBATOR, "target_id": READER},
    {"device_id": READER, "operation": "read"},
]


def post(client, path, body):
    response = client.post(f"/api/node/v1/{path}", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_capabilities_describe_the_node_without_a_workspace(client):
    found = client.get("/api/node/v1/capabilities").json()
    assert found["version"] == "node/1"
    assert found["services"] == ["simulate", "validate", "replay", "assess"]
    assert found["library"]["simready"] >= 6 and found["evidence"] == "synthetic"


def test_simulate_runs_library_and_inline_devices_and_stores_nothing(client):
    result = post(client, "simulate", {"devices": DEVICES, "steps": STEPS})
    assert result["valid"] and result["error"] is None
    assert [t["operation"] for t in result["trace"]] == ["load", "heat", "transfer", "read"]
    assert result["trace"][-1]["measurement"]["temperature_c"] == 37
    assert client.get("/api/twins").json()["twins"] == []


def test_validate_names_the_failing_layer(client):
    too_much = [{**STEPS[0], "value": 5000}, *STEPS[1:]]
    result = post(client, "validate", {"devices": DEVICES, "steps": too_much})
    assert not result["valid"] and result["error"]["layer"] == "volume"
    out_of_range = [STEPS[0], {**STEPS[1], "value": 90}, *STEPS[2:]]
    assert (
        post(client, "validate", {"devices": DEVICES, "steps": out_of_range})["error"]["layer"]
        == "constraint"
    )
    skipped = [STEPS[0], STEPS[3]]
    assert (
        post(client, "validate", {"devices": DEVICES, "steps": skipped})["error"]["layer"]
        == "state"
    )


def test_bad_device_lists_are_rejected(client):
    unknown = [{"id": INCUBATOR, "library": {"collection": "simready", "id": "nope"}}]
    response = client.post("/api/node/v1/validate", json={"devices": unknown, "steps": STEPS[:1]})
    assert response.status_code == 422
    both = [{**DEVICES[2], "library": {"collection": "simready", "id": "franka-fr3"}}]
    assert (
        client.post("/api/node/v1/validate", json={"devices": both, "steps": STEPS}).status_code
        == 422
    )
    twice = [DEVICES[0], {**DEVICES[1], "id": INCUBATOR}]
    assert (
        client.post("/api/node/v1/validate", json={"devices": twice, "steps": STEPS}).status_code
        == 422
    )


def test_replay_reports_residuals_by_layer(client):
    observed = [
        {"step": 1, "volume_ul": 200.4},
        {"step": 2, "temperature_c": 33},
        {"step": 4, "location": READER},
    ]
    result = post(client, "replay", {"devices": DEVICES, "steps": STEPS, "observed": observed})
    assert result["valid"] and not result["matches"]
    assert result["residuals"] == [
        {
            "step": 2,
            "layer": "constraint",
            "field": "temperature_c",
            "predicted": 37,
            "observed": 33,
        }
    ]
    matching = [{"step": 2, "temperature_c": 36.5}]
    assert post(client, "replay", {"devices": DEVICES, "steps": STEPS, "observed": matching})[
        "matches"
    ]
    beyond = [{"step": 9, "volume_ul": 1}]
    response = client.post(
        "/api/node/v1/replay", json={"devices": DEVICES, "steps": STEPS, "observed": beyond}
    )
    assert response.status_code == 422


def test_assess_checks_a_signed_training_record(client):
    client.post("/api/cloudlab/training-sessions", json={"expected_version": 0})
    envelope = client.get("/api/cloudlab/qualifications/me").json()
    result = post(client, "assess", {"record": envelope})
    assert result["version"] == "node/1" and result["authentic"] and not result["complete"]


def test_the_opentrons_adapter_applies_simulator_rules(client):
    actions = [
        {"kind": "pickup"},
        {"kind": "aspirate", "well": "stock", "volume": 1000},
        {"kind": "aspirate", "well": "stock", "volume": 100},
        {"kind": "dispense", "well": "A1", "volume": 1000},
        {"kind": "drop"},
    ]
    result = post(
        client, "adapters/opentrons/validate", {"source_volume": 5000, "actions": actions}
    )
    assert not result["valid"] and result["stops"][0]["step"] == 3
    assert result["robot"] == "Flex"


def test_the_node_needs_a_signed_in_caller(app):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/node/v1/capabilities").status_code == 401
        assert (
            anonymous.post("/api/node/v1/simulate", json={"devices": DEVICES, "steps": STEPS})
        ).status_code == 401


def test_a_layout_adds_the_arm_path_check(client):
    reader, heater, arm = (str(uuid4()) for _ in range(3))
    devices = [
        {"id": reader, "spec": TEMPLATES["reader"]},
        {"id": heater, "spec": TEMPLATES["heater"]},
        {"id": arm, "spec": TEMPLATES["transfer-arm"]},
    ]
    steps = [
        {"device_id": heater, "operation": "load", "value": 150},
        {"device_id": arm, "operation": "transfer", "source_id": heater, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]

    def layout(reader_x):
        return {
            "bench": {"width": 3.0, "depth": 1.6},
            "placements": [
                {"twin_id": arm, "x": 0, "z": 0, "yaw": 0, "access": "top"},
                {"twin_id": heater, "x": -0.5, "z": 0.1, "yaw": 0, "access": "top"},
                {"twin_id": reader, "x": reader_x, "z": 0.1, "yaw": -90, "access": "front"},
            ],
        }

    placed = post(client, "simulate", {"devices": devices, "steps": steps, "layout": layout(0.8)})
    assert placed["valid"] and placed["trace"][1]["motion"]["clearance_m"] > 0
    far = post(client, "validate", {"devices": devices, "steps": steps, "layout": layout(1.25)})
    assert not far["valid"] and far["error"]["layer"] == "geometry"
    stranger = layout(0.8)
    stranger["placements"][0]["twin_id"] = str(uuid4())
    response = client.post(
        "/api/node/v1/validate", json={"devices": devices, "steps": steps, "layout": stranger}
    )
    assert response.status_code == 422
