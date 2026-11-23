import importlib.util
from pathlib import Path

from academy.cloudlab import CLOUDLAB, CONTRACTS, INSTRUMENTS
from academy.cloudlab_teaching import DOES, MOTION, instruments
from academy.cloudlab_workflow import INSTRUMENTS as WORKFLOW


def load_script(name):
    path = Path(__file__).parents[3] / f"scripts/library-models/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_instrument_teaches_its_purpose_and_steps_from_its_twin():
    assert DOES.keys() == CLOUDLAB.keys()
    for item in instruments()["instruments"]:
        spec = CLOUDLAB[item["id"]]["spec"]
        assert item["does"].endswith(".") and len(item["does"]) < 120
        assert [s["operation"] for s in item["steps"]] == spec["operations"]
        assert item["in_workflow"] == (item["id"] in WORKFLOW)
        # A twin that takes a reading can characterize or test; the rest prepare.
        assert item["stages"] in (["prepare"], ["characterize", "test"])
        if "read" not in item["operations"]:
            assert item["stages"] == ["prepare"]
    nmr = next(i for i in instruments()["instruments"] if i["id"] == "nmr")
    assert nmr["steps"][0]["says"] == "Put up to 96 tubes in, each up to 1.5 mL."
    assert nmr["motion"] is None and all(s["state"] is None for s in nmr["steps"])
    incubator = next(i for i in instruments()["instruments"] if i["id"] == "cell-incubator")
    heat = next(s for s in incubator["steps"] if s["operation"] == "heat")
    assert heat["says"] == "Set a temperature between 33 and 50 °C."


def test_states_move_only_the_stand_ins_own_joints_within_their_limits():
    for asset_id, (slug, parts, states) in MOTION.items():
        # The twin draws this stand-in, so its contract's joints are the ones that move.
        assert CLOUDLAB[asset_id]["slug"] == slug
        contract = CONTRACTS["stand_ins"][slug]
        assert parts.keys() <= set(contract["parts"]), asset_id
        assert 2 <= len(states) <= 3 and len(parts) <= 3, asset_id
        assert states[0][2] == {}, f"{asset_id} starts at rest"
        operations = CLOUDLAB[asset_id]["spec"]["operations"]
        for key, label, pose, says, shows in states:
            assert pose.keys() <= contract["joints"].keys(), (asset_id, key)
            assert all(0 <= v <= 1 for v in pose.values()), (asset_id, key)
            assert shows is None or shows in operations, (asset_id, key)
            assert says.endswith(".") and len(label) <= 20
        # Two states never show the same thing.
        poses = [tuple(sorted(pose.items())) for _, _, pose, _, _ in states]
        assert len(set(poses)) == len(poses), asset_id
        assert len({s[0] for s in states}) == len(states)


def test_the_view_moves_jointed_stand_ins_and_leaves_the_rest_still():
    found = {i["id"]: i for i in instruments()["instruments"]}
    moving = {k for k, i in found.items() if i["motion"]}
    # A model is drawn for one instrument only, so each jointed model moves one twin.
    assert moving == set(MOTION)
    assert len({MOTION[k][0] for k in moving}) == len(moving)
    assert len({k for k in moving if CLOUDLAB[k]["lab"] == "ecl"}) == 11
    assert len({k for k in moving if CLOUDLAB[k]["lab"] == "ac"}) == 10
    # Stand-ins whose contracts give no joints keep the plain view.
    for asset_id in ("analytical-hplc", "gcms"):
        slug = INSTRUMENTS[asset_id][-1]
        assert found[asset_id]["mesh"] and not CONTRACTS["stand_ins"][slug].get("joints")
    # Estimated boxes and photo sketches have no model to move.
    assert all(
        found[k]["motion"] is None and (found[k]["mesh"] or {"kind": "sketch"})["kind"] == "sketch"
        for k in found
        if not CLOUDLAB[k]["stand_in"]
    )
    incubator = found["cell-incubator"]["motion"]
    assert incubator["node_prefix"] == "eppendorf_cellxpertc170i__"
    door = incubator["joints"]["outer_door"]
    assert door["type"] == "revolute" and door["limits"] == [0.0, 1.745]
    # The door hinges at the front left of the 0.72 m wide cabinet.
    assert door["pivot"][0] < -0.3 and door["pivot"][1] < -0.25
    assert [p["moves"] for p in incubator["parts"]] == [True, True, False]
    load = next(s for s in found["cell-incubator"]["steps"] if s["operation"] == "load")
    assert load["state"] == "plate-in"


def test_motion_reads_pivots_and_limits_from_the_contract():
    layout = load_script("chemlab_layout")
    manifest = {
        "world_origins_m": {"lid": [0.0, 0.2, 0.4]},
        "components": [
            {"id": "body", "parent": "root", "origin_m": [0, 0, 0.1], "collisions": []},
            {"id": "lid", "parent": "body", "origin_m": [0, 0, 0], "collisions": []},
            {"id": "tray", "parent": "body", "origin_m": [0.1, -0.2, 0.05], "collisions": []},
        ],
        "joint_definitions": {
            "lid": {
                "type": "revolute",
                "axis": [-1, 0, 0],
                "limits_rad": [0, 1.2],
                "range_evidence": "engineering_assumption",
            },
            "tray": {
                "type": "prismatic",
                "axis": [0, -1, 0],
                "limits_m": [0, 0.15],
                "range_evidence": "manufacturer_datasheet",
            },
        },
    }
    layout.PARTS["test"] = ("lid", "tray", "body")
    found = layout.motion(manifest, "test")
    assert found["parts"] == ["lid", "tray", "body"]
    assert found["joints"]["lid"]["pivot"] == [0.0, 0.2, 0.4]  # the recorded world origin
    assert found["joints"]["tray"]["pivot"] == [0.1, -0.2, 0.15]  # else its parents' sum
    assert found["joints"]["tray"]["limits"] == [0, 0.15]
    assert found["joints"]["tray"]["evidence"] == "manufacturer"
    assert "body" not in found["joints"]


def test_meet_the_instruments_serves_what_each_twin_teaches(client):
    found = client.get("/api/cloudlab/instruments").json()["instruments"]
    reader = next(i for i in found if i["id"] == "plate-reader")
    assert reader["motion"]["states"][1] == {
        "id": "carrier-out",
        "label": "Carrier out",
        "pose": {"plate_carrier": 1},
        "says": "The carrier slides out of the lower left of the front for an arm to set "
        "a plate on it.",
        "shows": "load",
    }
    assert reader["motion"]["joints"]["plate_carrier"]["limits"] == [0.0, 0.185]


def test_every_instruments_starter_runs_on_its_own_twin():
    from academy.cloudlab_teaching import practise, starter

    for asset_id, asset in CLOUDLAB.items():
        steps = starter(asset["spec"])
        assert [s["operation"] for s in steps] == asset["spec"]["operations"]
        assert practise(asset_id, steps)["ok"], asset_id


def test_practice_checks_steps_against_one_twin(client):
    url = "/api/cloudlab/instruments/cell-incubator/check"
    found = client.post(url, json={"steps": [{"operation": "heat", "value": 37}]}).json()
    # With one instrument a sample is loaded, never moved in.
    assert found["error"] == {"step": 1, "message": "Step 1: load plate first", "layer": "state"}
    steps = [{"operation": "load", "value": 200, "slot": "3"}, {"operation": "heat", "value": 37}]
    found = client.post(url, json={"steps": steps}).json()
    assert found["ok"] and found["trace"][-1]["samples"]["plate"]["site"] == "3"
    assert "not the cloud lab's instrument specification" in found["statement"]
    hot = client.post(url, json={"steps": [steps[0], {"operation": "heat", "value": 60}]})
    assert hot.json()["error"]["step"] == 2  # above the incubator's 50 °C
    assert client.post(url, json={"steps": [{"operation": "transfer"}]}).status_code == 422
    missing = client.post("/api/cloudlab/instruments/nowhere/check", json={"steps": []})
    assert missing.status_code == 404
