import base64
import importlib.util
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import pytest
from academy.chemlab import CHEMLAB
from academy.cloudlab import CLOUDLAB, CONTRACTS, LAYOUT
from academy.cloudlab_teaching import instruments
from academy.simple_twins import SIZE_BASES, TEMPLATES, TwinSpec, usda
from academy.simready import SIMREADY
from academy.workcell_models import catalog as workcell_catalog
from fastapi import HTTPException

WORKCELL = workcell_catalog()

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 32).decode()
SPEC = {
    "name": "Shaker incubator",
    "parts": [{"size": [0.4, 0.3, 0.4], "position": [0, 0.15, 0], "color": "#336699"}],
    "operations": ["load", "mix", "heat", "wait"],
    "container": {"vessel": "plate", "max_volume_ul": 2000},
    "resource": {"slots": 2},
    "consumables": [],
    "limits": {"min_temp_c": 20, "max_temp_c": 60, "max_duration_s": 900},
    "assumptions": "Scale estimated from a door handle; interior not visible.",
}
BOX = {"size": [0.1, 0.1, 0.1], "position": [0, 0.05, 0], "color": "#000000"}


UNKNOWN = {
    "library_id": "none",
    "alternatives": [],
    "maker": "",
    "model": "",
    "confidence": "low",
    "evidence": "No legible label.",
}
XPR = {
    "library_id": "chemlab:mt_xpr204e",
    "alternatives": ["chemlab:ohaus_px224e"],
    "maker": "METTLER TOLEDO",
    "model": "XPR204E",
    "confidence": "high",
    "evidence": "XPR204E badge on the terminal.",
}


def completed(spec, identification=UNKNOWN):
    text = json.dumps({"identification": identification, "twin": spec})
    return {
        "id": "resp_done",
        "status": "completed",
        "output": [{"type": "message", "content": [{"type": "output_text", "text": text}]}],
    }


class FakeAstra:
    available = True

    def __init__(self, polls=(), begin_error=None):
        self.polls = list(polls)
        self.begin_error = begin_error
        self.submitted = 0

    def begin(self, data):
        self.submitted += 1
        if self.begin_error:
            raise self.begin_error
        return "resp_abc123", {"id": "resp_abc123", "status": "queued"}

    def poll(self, response_id):
        assert response_id == "resp_abc123"
        return self.polls.pop(0)


def add(client, version, **source):
    twin_id = str(uuid4())
    response = client.post(
        "/api/twins", json={"expected_version": version, "id": twin_id, **source}
    )
    assert response.status_code == 200, response.text
    return twin_id, response.json()


def confirm(client, twin_id, version, spec):
    response = client.put(
        f"/api/twins/{twin_id}/confirm", json={"expected_version": version, "spec": spec}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_unconfigured_astra_fails_closed_and_templates_still_work(client):
    catalog = client.get("/api/twins").json()
    assert catalog["astra_available"] is False
    assert catalog["real_available"] is False
    image = {"expected_version": 0, "id": str(uuid4()), "image": PNG}
    assert client.post("/api/twins", json=image).status_code == 503
    twin_id, catalog = add(client, 0, template_id="heater")
    assert catalog["twins"][0]["spec"] == TEMPLATES["heater"]
    assert catalog["twins"][0]["confirmed"] is False
    assert client.get(f"/api/twins/{twin_id}/usd").status_code == 409


def test_photo_generation_polls_validates_and_is_never_replayed(client, app):
    fake = FakeAstra(polls=[{"status": "in_progress"}, completed(SPEC)])
    app.state.twins.provider = fake
    twin_id, catalog = add(client, 0, image=PNG, mime="image/png")
    twin = catalog["twins"][0]
    assert (twin["status"], twin["source"], twin["spec"]) == ("generating", "astra_image", None)
    version = catalog["version"]
    poll = f"/api/twins/{twin_id}/poll"
    assert client.post(poll, json={"expected_version": version}).json()["version"] == version
    catalog = client.post(poll, json={"expected_version": version}).json()
    assert catalog["twins"][0]["status"] == "draft"
    assert catalog["twins"][0]["spec"]["name"] == "Shaker incubator"
    assert catalog["twins"][0]["matches"] == []  # no library pick and no legible model
    assert fake.submitted == 1


def photo_twin(client, app, result):
    app.state.twins.provider = FakeAstra(polls=[result])
    twin_id, catalog = add(client, 0, image=PNG)
    catalog = client.post(
        f"/api/twins/{twin_id}/poll", json={"expected_version": catalog["version"]}
    ).json()
    return twin_id, catalog


def match(client, twin_id, version, collection, asset_id):
    return client.put(
        f"/api/twins/{twin_id}/match",
        json={"expected_version": version, "collection": collection, "asset_id": asset_id},
    )


def test_photo_identification_offers_verified_library_matches_to_replace_the_sketch(client, app):
    twin_id, catalog = photo_twin(client, app, completed(SPEC, XPR))
    twin = catalog["twins"][0]
    assert (twin["status"], twin["source"], twin["spec"]["name"]) == (
        "draft",
        "astra_image",
        "Shaker incubator",
    )
    assert twin["identification"] == XPR
    assert [(m["id"], m["suggested_by"], m["verified"]) for m in twin["matches"]] == [
        ("mt_xpr204e", "astra", True),
        ("ohaus_px224e", "astra", False),
    ]
    response = match(client, twin_id, catalog["version"], "chemlab", "mt_xpr204e")
    assert response.status_code == 200, response.text
    twin = response.json()["twins"][0]
    assert (twin["source"], twin["spec"]) == ("chemlab_asset", CHEMLAB["mt_xpr204e"]["spec"])
    assert twin["asset"]["attribution"] == CHEMLAB["mt_xpr204e"]["attribution"]
    assert twin["image_sha256"] and twin["confirmed"] is False
    catalog = confirm(client, twin_id, response.json()["version"], twin["spec"])
    assert match(client, twin_id, catalog["version"], "chemlab", "ohaus_px224e").status_code == 409


def test_model_read_off_the_label_finds_entries_astra_did_not_pick(client, app):
    read = {**UNKNOWN, "model": "5910 Ri", "confidence": "medium"}
    _, catalog = photo_twin(client, app, completed(SPEC, read))
    matches = catalog["twins"][0]["matches"]
    assert [(m["id"], m["suggested_by"], m["verified"]) for m in matches] == [
        ("eppendorf_5910ri", "label_text", True)
    ]


def test_only_offered_matches_can_replace_a_sketch(client, app):
    twin_id, catalog = photo_twin(client, app, completed(SPEC, XPR))
    for collection, asset_id in [("chemlab", "eppendorf_5910ri"), ("simready", "franka-fr3")]:
        response = match(client, twin_id, catalog["version"], collection, asset_id)
        assert response.status_code == 422
    assert client.get("/api/twins").json()["twins"][0]["source"] == "astra_image"


def test_a_failed_sketch_with_a_valid_identification_recovers_through_a_match(client, app):
    twin_id, catalog = photo_twin(client, app, completed({**SPEC, "parts": [BOX] * 5}, XPR))
    twin = catalog["twins"][0]
    assert (twin["status"], twin["spec"]) == ("failed", None)
    assert "library match" in twin["message"] and twin["matches"]
    response = match(client, twin_id, catalog["version"], "chemlab", "mt_xpr204e")
    assert response.status_code == 200 and response.json()["twins"][0]["status"] == "draft"


def test_identification_outside_the_library_is_rejected_not_matched(client, app):
    bogus = {**XPR, "library_id": "chemlab:not_listed", "alternatives": [], "model": ""}
    _, catalog = photo_twin(client, app, completed(SPEC, bogus))
    assert catalog["twins"][0]["matches"] == []


@pytest.mark.parametrize(
    "result",
    [
        completed(
            {**SPEC, "parts": [{"size": [9, 9, 9], "position": [0, 0, 0], "color": "#000000"}]}
        ),
        completed({**SPEC, "operations": ["load", "rm -rf"]}),
        completed({**SPEC, "parts": [BOX] * 5}),
        completed({**SPEC, "container": {"vessel": "none", "max_volume_ul": 0}}),
        {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
        },
        {"status": "failed"},
    ],
)
def test_out_of_bounds_or_refused_output_is_rejected(client, app, result):
    app.state.twins.provider = FakeAstra(polls=[result])
    twin_id, catalog = add(client, 0, image=PNG)
    catalog = client.post(
        f"/api/twins/{twin_id}/poll", json={"expected_version": catalog["version"]}
    ).json()
    assert catalog["twins"][0]["status"] == "failed"
    assert catalog["twins"][0]["spec"] is None


def test_unknown_submission_is_recorded_not_retried(client, app):
    fake = FakeAstra(begin_error=HTTPException(502, "Bedrock did not return a usable response."))
    app.state.twins.provider = fake
    _, catalog = add(client, 0, image=PNG)
    assert catalog["twins"][0]["status"] == "submission_unknown"
    assert fake.submitted == 1


def test_image_must_match_declared_type(client, app):
    app.state.twins.provider = FakeAstra()
    body = {"expected_version": 0, "id": str(uuid4()), "image": PNG, "mime": "image/jpeg"}
    assert client.post("/api/twins", json=body).status_code == 422


def build_cell(client):
    reader, catalog = add(client, 0, template_id="reader")
    heater, catalog = add(client, catalog["version"], template_id="heater")
    arm, catalog = add(client, catalog["version"], template_id="transfer-arm")
    for twin_id, key in [(reader, "reader"), (heater, "heater"), (arm, "transfer-arm")]:
        catalog = confirm(client, twin_id, catalog["version"], TEMPLATES[key])
    return reader, heater, arm, catalog


def test_multi_device_workflow_runs_on_mock_connectors(client):
    reader, heater, arm, catalog = build_cell(client)
    steps = [
        {"device_id": heater, "operation": "load"},
        {"device_id": heater, "operation": "heat", "value": 37},
        {"device_id": arm, "operation": "transfer", "source_id": heater, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    saved = client.put(
        "/api/twins/workflow", json={"expected_version": catalog["version"], "steps": steps}
    )
    assert saved.status_code == 200, saved.text
    run = client.post("/api/twins/workflow/run", json={"expected_version": saved.json()["version"]})
    assert run.status_code == 200, run.text
    result = run.json()["runs"][0]
    assert (result["evidence"], result["connector"]) == ("synthetic", "in_process_mock")
    assert [t["location"] for t in result["trace"]] == [heater, heater, reader, reader]
    assert result["trace"][-1]["measurement"]["temperature_c"] == 37
    stale = client.post(
        "/api/twins/workflow/run", json={"expected_version": saved.json()["version"]}
    )
    assert stale.status_code == 409


def test_invalid_handoffs_and_capability_edits_are_rejected(client):
    reader, heater, arm, catalog = build_cell(client)
    version = catalog["version"]
    for steps in [
        [{"device_id": reader, "operation": "heat", "value": 37}],
        [{"device_id": heater, "operation": "load"}, {"device_id": reader, "operation": "read"}],
        [
            {"device_id": heater, "operation": "load"},
            {"device_id": arm, "operation": "transfer", "source_id": reader, "target_id": heater},
        ],
    ]:
        response = client.put(
            "/api/twins/workflow", json={"expected_version": version, "steps": steps}
        )
        assert response.status_code == 422, steps
    steps = [
        {"device_id": heater, "operation": "load"},
        {"device_id": heater, "operation": "heat", "value": 50},
    ]
    version = client.put(
        "/api/twins/workflow", json={"expected_version": version, "steps": steps}
    ).json()["version"]
    no_heat = {**TEMPLATES["heater"], "operations": ["load", "wait"]}
    response = client.put(
        f"/api/twins/{heater}/confirm", json={"expected_version": version, "spec": no_heat}
    )
    assert response.status_code == 422
    assert (
        client.request(
            "DELETE", f"/api/twins/{heater}", json={"expected_version": version}
        ).status_code
        == 409
    )
    assert (
        client.request(
            "DELETE", f"/api/twins/{reader}", json={"expected_version": version}
        ).status_code
        == 200
    )


def test_real_connector_fails_closed(client):
    twin_id, catalog = add(client, 0, template_id="reader")
    response = client.put(
        f"/api/twins/{twin_id}/connector",
        json={"expected_version": catalog["version"], "mode": "real"},
    )
    assert response.status_code == 409
    assert "qualified physical connector" in response.json()["detail"]


def test_exports_are_self_contained_usd_and_valid_sila_xml(client):
    twin_id, catalog = add(client, 0, template_id="heater")
    confirm(client, twin_id, catalog["version"], {**TEMPLATES["heater"], "name": "Heater <&> 2"})
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert text.startswith("#usda 1.0") and "@" not in text and "references" not in text
    package = client.get(f"/api/twins/{twin_id}/sila").json()
    feature = ET.fromstring(package["files"]["Heater2Mock.sila.xml"])
    ns = {"s": "http://www.sila-standard.org"}
    assert feature.find("s:Identifier", ns).text == "Heater2Mock"
    commands = [c.find("s:Identifier", ns).text for c in feature.findall("s:Command", ns)]
    assert commands == ["Load", "Heat", "Wait"]
    assert package["evidence"] == "synthetic"


def test_simready_assets_are_pinned_attributed_one_box_specs():
    for asset in SIMREADY.values():
        assert TwinSpec.model_validate(asset["spec"]).model_dump(mode="json") == asset["spec"]
        assert len(asset["spec"]["parts"]) == 1
        assert asset["license"] == "CC-BY-4.0"
        assert len(asset["revision"]) == 40 and asset["revision"] in asset["url"]


def test_simready_asset_starts_an_attributed_twin_without_external_references(client):
    twin_id, catalog = add(client, 0, simready_id="forgecad-microplate-reader")
    twin = catalog["twins"][0]
    asset = SIMREADY["forgecad-microplate-reader"]
    assert catalog["simready"]["forgecad-microplate-reader"] == asset
    assert (twin["source"], twin["spec"], twin["confirmed"]) == (
        "simready_asset",
        asset["spec"],
        False,
    )
    assert twin["asset"]["url"] == asset["url"] and "spec" not in twin["asset"]
    confirm(client, twin_id, catalog["version"], twin["spec"])
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert asset["attribution"] in text and asset["url"] in text
    assert "@" not in text and "references" not in text and "payload" not in text
    readme = client.get(f"/api/twins/{twin_id}/sila").json()["files"]["README.md"]
    assert asset["attribution"] in readme


@pytest.mark.parametrize(
    "source",
    [
        {"simready_id": "not-in-catalog"},
        {"simready_id": "franka-fr3", "template_id": "heater"},
        {"simready_id": "franka-fr3", "image": PNG},
        {"chemlab_id": "not-in-catalog"},
        {"chemlab_id": "mt_xpr204e", "simready_id": "franka-fr3"},
        {"chemlab_id": "mt_xpr204e", "template_id": "heater"},
        {"cloudlab_id": "not-in-catalog"},
        {"cloudlab_id": "thermocycler", "chemlab_id": "mt_xpr204e"},
    ],
)
def test_simready_source_must_be_a_single_known_asset(client, source):
    response = client.post("/api/twins", json={"expected_version": 0, "id": str(uuid4()), **source})
    assert response.status_code == 422
    assert client.get("/api/twins").json()["twins"] == []


def test_simready_twins_run_a_workflow_on_mock_connectors(client):
    ids = {}
    catalog = {"version": 0}
    for key in ["forgecad-laboratory-incubator", "forgecad-microplate-reader", "franka-fr3"]:
        ids[key], catalog = add(client, catalog["version"], simready_id=key)
        catalog = confirm(client, ids[key], catalog["version"], SIMREADY[key]["spec"])
    incubator, reader, arm = ids.values()
    steps = [
        {"device_id": incubator, "operation": "load", "value": 200},
        {"device_id": incubator, "operation": "heat", "value": 37},
        {"device_id": arm, "operation": "transfer", "source_id": incubator, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    version = plan(client, catalog["version"], steps).json()["version"]
    run = client.post("/api/twins/workflow/run", json={"expected_version": version})
    assert run.status_code == 200, run.text
    assert run.json()["runs"][0]["trace"][-1]["measurement"]["temperature_c"] == 37


def test_chemlab_assets_are_pinned_non_commercial_one_box_specs():
    for asset in CHEMLAB.values():
        assert TwinSpec.model_validate(asset["spec"]).model_dump(mode="json") == asset["spec"]
        assert len(asset["spec"]["parts"]) == 1
        assert asset["license"] == "CC-BY-NC-4.0" and "CC-BY-NC-4.0" in asset["attribution"]
        assert "non-commercial" in asset["spec"]["assumptions"]
        assert len(asset["revision"]) == 40 and asset["revision"] in asset["url"]
    assert len(CHEMLAB) == 203 and sum(a["featured"] for a in CHEMLAB.values()) == 9
    balance = CHEMLAB["mt_xpr204e"]["spec"]["parts"][0]
    assert balance["size"] == [0.209, 0.339, 0.4604]  # Z-up catalog size, Y-up twin
    assert CHEMLAB["agilent_hplc1260"]["spec"]["operations"] == ["load", "read", "wait"]
    assert CHEMLAB["ika_rv10_digital_v"]["spec"]["operations"] == ["load", "heat", "wait"]


def test_cloudlab_entries_keep_published_capabilities_apart_from_stand_in_geometry():
    for asset in CLOUDLAB.values():
        assert TwinSpec.model_validate(asset["spec"]).model_dump(mode="json") == asset["spec"]
        assert len(asset["spec"]["parts"]) == 1
        if asset["lab"] == "ecl":
            assert asset["url"] == "https://www.emeraldcloudlab.com/instrumentation/"
        assumptions = asset["spec"]["assumptions"]
        assert asset["experiment"] in assumptions and "teaching defaults" in assumptions
        if asset["stand_in"]:
            assert asset["license"] == "CC-BY-NC-4.0" and asset["stand_in"] in assumptions
            assert "not this instrument's size" in assumptions
        elif asset["layout_model"]:
            assert asset["mesh"] is None and "not this instrument's size" in assumptions
        else:
            assert asset["mesh"] is None and "Academy estimate" in assumptions
    thermocycler = CLOUDLAB["thermocycler"]["spec"]
    assert thermocycler["limits"]["min_temp_c"] == 4 and thermocycler["limits"]["max_temp_c"] == 105
    assert thermocycler["container"] == {"vessel": "plate", "max_volume_ul": 100}
    # A published figure the twin schema cannot hold is cut, and the entry says so.
    nmr = CLOUDLAB["nmr"]["spec"]
    assert nmr["resource"]["slots"] == 96 and "96 of the 480" in nmr["assumptions"]
    gcms = CLOUDLAB["gcms"]["spec"]
    assert gcms["limits"]["max_temp_c"] == 120 and "above 120 °C" in gcms["assumptions"]


def load_script(name):
    path = Path(__file__).parents[3] / f"scripts/library-models/{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASES = ("datasheet: ", "manufacturer: ", "engineering_assumption: ", "estimate", "footprint: ")
# Contract fields and the twin fields they set.
TWIN_FIELDS = {
    "access": "access",
    "level_m": "level_m",
    "opening": "opening",
    "extends_m": "drawer_m",
}


def test_every_cloudlab_twin_carries_layout_geometry_with_its_basis():
    for asset_id, asset in CLOUDLAB.items():
        spec, basis = asset["spec"], asset["geometry_basis"]
        assert TwinSpec.model_validate(spec).model_dump(mode="json") == spec
        assert {"size", "access"} <= basis.keys(), asset_id
        for value in basis.values():
            assert value.startswith(BASES) or value == "unset", (asset_id, value)
            if value.startswith("datasheet: "):
                assert "https://" in value and value.endswith("read 2026-11-18")
        if spec["access"] == "front" and spec["level_m"] is None:
            assert basis["level_m"] == "unset"
        # Sourced figures are a comparable model's, never the cloud lab's own.
        if asset["layout_model"]:
            assert "not this instrument's size" in spec["assumptions"]
    for asset_id, (model, sourced) in LAYOUT.items():
        spec = CLOUDLAB[asset_id]["spec"]
        assert CLOUDLAB[asset_id]["layout_model"] == model and model in spec["assumptions"]
        width, depth, height = sourced["size"][0]
        assert spec["parts"][0]["size"] == [width, height, depth]  # Y-up twin box
        if "access" in sourced:
            assert spec["access"] == sourced["access"][0]


def test_stand_in_twins_take_their_contract_values_and_evidence():
    stand_ins = {k: a for k, a in CLOUDLAB.items() if a["stand_in"]}
    assert sum(a["lab"] == "ecl" for a in stand_ins.values()) == 15
    for asset_id, asset in stand_ins.items():
        slug = asset["slug"]
        found, spec = CONTRACTS["stand_ins"][slug], asset["spec"]
        assert asset["layout_model"] == asset["stand_in"]
        if "size" in found:
            width, depth, height = found["size"]["value"]
            assert spec["parts"][0]["size"] == [width, height, depth]
            assert asset["geometry_basis"]["size"].startswith(found["size"]["evidence"])
        for key, twin_key in TWIN_FIELDS.items():
            if key in found and twin_key in asset["geometry_basis"]:
                assert spec[twin_key] == found[key]["value"], (asset_id, key)
                assert found[key]["detail"] in asset["geometry_basis"][twin_key]
    # The reader's plate carrier comes out of the lower left of its front.
    reader = CLOUDLAB["plate-reader"]["spec"]
    assert reader["access"] == "front" and reader["opening"]["end"] < 0.5
    assert reader["level_m"] < 0.1 and reader["drawer_m"] == 0.185
    # A PCR plate goes into the block from above, where the contract places it.
    pcr = CLOUDLAB["thermocycler"]["spec"]
    assert pcr["access"] == "top" and [s["key"] for s in pcr["sites"]] == ["1"]
    assert 0 < pcr["level_m"] < pcr["parts"][0]["size"][1]
    # Samples that arrive by tubing give no loading face; it stays an Academy estimate.
    assert CLOUDLAB["lcms"]["geometry_basis"]["access"].startswith("estimate")


def test_pinned_contract_values_carry_no_dataset_text():
    allowed = {"size", "access", "level_m", "opening", "site", "extends_m", "port"}
    allowed |= {"parts", "joints", "components", "nodes", "mass_kg"}
    for slug, found in CONTRACTS["stand_ins"].items():
        assert found.keys() <= allowed, slug
        for key, item in found.items():
            if key == "nodes":
                # Model node names only: component ids to identifiers, nothing else.
                assert all(re.fullmatch(r"[a-z0-9_]+", c) for c in item)
                assert all(
                    re.fullmatch(r"[A-Za-z0-9_.-]+", n) for names in item.values() for n in names
                )
                continue
            if key == "port":
                assert re.fullmatch(r"[a-z0-9_]+", item)
                continue
            if key in {"parts", "components"}:
                assert all(re.fullmatch(r"[a-z0-9_]+", part) for part in item)
                continue
            if key == "joints":
                for name, joint in item.items():
                    assert name in found["parts"], (slug, name)
                    assert joint.keys() == {"type", "axis", "limits", "pivot", "evidence", "detail"}
                    assert joint["type"] in {"revolute", "prismatic"}
                    assert re.fullmatch(r"[a-z_]+", joint["detail"])
                    assert all(
                        isinstance(v, int | float) for v in [*joint["axis"], *joint["pivot"]]
                    )
                continue
            assert item["evidence"] in {"manufacturer", "engineering_assumption"}
            assert re.fullmatch(r"[a-z0-9_ ()]+", item["detail"]), (slug, item["detail"])
    assert CONTRACTS["license"] == "CC-BY-NC-4.0" and CONTRACTS["repo"] == "MBZUAI/ChemLab-Assets"


def test_a_drawn_stand_ins_documented_weight_reaches_the_overview_but_not_its_size_basis():
    found = {i["id"]: i for i in instruments()["instruments"]}
    washer = found["plate-washer"]["mass_kg"]
    assert washer["value"] == 16.5 and washer["range"] is None
    assert washer["basis"].startswith("manufacturer: ") and "BioTek 405 TS" in washer["basis"]
    # Where the documents give a range, the range is kept beside the value simulated.
    incubator = found["cell-incubator"]["mass_kg"]
    assert incubator["range"] == [107.0, 113.0]
    assert incubator["basis"].startswith("engineering_assumption: ")
    # A mass the dataset only assumed for simulation is not shown as the instrument's.
    assert CONTRACTS["stand_ins"]["agilent_gc8890b"].get("mass_kg") is None
    for item in found.values():
        assert "mass" not in item["geometry_basis"]
        if not item["stand_in"]:
            assert item["mass_kg"] is None


def test_contract_derivation_turns_the_asset_frame_into_the_twin_frame():
    """A drawer at the front left of a 0.4 m wide box, its nest 0.1 m up and 0.1 m from the front."""
    layout = load_script("chemlab_layout")
    manifest = {
        "manufacturer_dimensions_m": {"W_D_H": [0.4, 0.5, 0.3]},
        "world_origins_m": {"carrier": [-0.1, -0.15, 0.09]},
        "components": [
            {
                "id": "carrier",
                "parent": "root",
                "origin_m": [0, 0, 0],
                "geometry_evidence": "photo_estimate",
                "collisions": [{"shape": "box", "size_m": [0.1, 0.1, 0.02], "origin_m": [0, 0, 0]}],
            }
        ],
        "joint_definitions": {
            "carrier": {
                "type": "prismatic",
                "axis": [0, -1, 0],
                "limits_m": [0, 0.2],
                "range_evidence": "engineering_assumption",
            }
        },
    }
    layout.STAND_INS["test"] = (("W_D_H", (0, 1, 2)), "carrier", ("carrier", "front"))
    found = layout.derive(manifest, "test")
    assert found["size"] == {
        "value": [0.4, 0.5, 0.3],
        "evidence": "manufacturer",
        "detail": "manufacturer_dimensions_m",
    }
    assert found["access"]["value"] == "front"
    assert found["site"]["value"] == [-0.1, 0.15]  # +Y back becomes -z: toward the front
    assert found["level_m"] == {
        "value": 0.1,
        "evidence": "engineering_assumption",
        "detail": "photo_estimate",
    }
    assert found["extends_m"]["value"] == 0.2
    # The 0.1 m drawer spans 0.05 to 0.15 m from the left edge, rounded outward.
    opening = found["opening"]["value"]
    assert opening["face"] == "front"
    assert 0.123 <= opening["start"] <= 0.125 and 0.375 <= opening["end"] <= 0.377


def test_cloudlab_geometry_basis_reaches_the_twin_and_its_layout(client):
    pcr, catalog = add(client, 0, cloudlab_id="thermocycler")
    reader, catalog = add(client, catalog["version"], cloudlab_id="plate-reader")
    twins = {t["id"]: t for t in catalog["twins"]}
    for twin_id, asset_id in ((pcr, "thermocycler"), (reader, "plate-reader")):
        asset = twins[twin_id]["asset"]
        assert asset["geometry_basis"] == CLOUDLAB[asset_id]["geometry_basis"]
        assert asset["layout_model"] == CLOUDLAB[asset_id]["layout_model"]
        # The contract's positions are its author's estimates, so the twin is estimated.
        assert twins[twin_id]["size_basis"] == "estimated"
    for twin_id in (pcr, reader):
        catalog = confirm(client, twin_id, catalog["version"], twins[twin_id]["spec"])
    rows = [
        {"twin_id": pcr, "x": -0.4, "z": 0, "yaw": 0, "access": "top"},
        {"twin_id": reader, "x": 0.4, "z": 0, "yaw": 0, "access": "front"},
    ]
    body = {"bench": {"width": 2.0, "depth": 1.2}, "placements": rows}
    assert client.post("/api/twins/layout/preview", json=body).json()["size_basis"] == "estimated"
    catalog = client.put(
        f"/api/twins/{pcr}/size-check",
        json={"expected_version": catalog["version"], "checked": True},
    ).json()
    body["placements"] = rows[:1]
    assert client.post("/api/twins/layout/preview", json=body).json()["size_basis"] == "checked"
    # A layout reports its weakest twin, and a datasheet ranks between checked and catalogued.
    assert SIZE_BASES == ("checked", "datasheet", "catalogued", "estimated")
    # Moving where a plate goes in makes the geometry the learner's own.
    spec = {**twins[reader]["spec"], "level_m": 0.2}
    catalog = confirm(client, reader, catalog["version"], spec)
    assert next(t for t in catalog["twins"] if t["id"] == reader).get("size_edited") is True


def test_cloudlab_twin_sizes_stay_estimated_and_record_their_source(client):
    twin_id, catalog = add(client, 0, cloudlab_id="analytical-hplc")
    twin = catalog["twins"][0]
    asset = CLOUDLAB["analytical-hplc"]
    assert (twin["source"], twin["spec"], twin["size_basis"]) == (
        "cloudlab_asset",
        asset["spec"],
        "estimated",
    )
    assert twin["asset"]["stand_in"] == asset["stand_in"] and "spec" not in twin["asset"]
    assert twin["asset"]["mesh"] == asset["mesh"]
    confirm(client, twin_id, catalog["version"], twin["spec"])
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert asset["attribution"] in text and asset["url"] in text
    hits = client.get("/api/twins/library", params={"q": "thermocycler"}).json()["results"]
    assert ("cloudlab", "thermocycler") in {(r["collection"], r["id"]) for r in hits}


def test_library_search_ranks_name_matches_and_spans_both_collections(client):
    def search(q):
        response = client.get("/api/twins/library", params={"q": q})
        assert response.status_code == 200, response.text
        return response.json()

    from academy.workcell_models import catalog as workcell

    featured = search("")
    assert featured["size"] == len(CHEMLAB) + len(SIMREADY) + len(workcell()) + len(CLOUDLAB)
    assert {r["collection"] for r in featured["results"]} == {
        "workcell",
        "chemlab",
        "simready",
        "cloudlab",
    }
    # Instruments drawn with a full 3D model lead the featured list.
    assert [r["collection"] for r in featured["results"][: len(workcell())]] == ["workcell"] * len(
        workcell()
    )
    assert all(
        CHEMLAB[r["id"]]["featured"] for r in featured["results"] if r["collection"] == "chemlab"
    )
    assert [r["id"] for r in search("XPR204E")["results"]] == ["mt_xpr204e"]
    readers = search("plate reader")["results"]
    assert {(r["collection"], r["id"]) for r in readers} >= {
        ("simready", "forgecad-microplate-reader"),
        ("chemlab", "bmg_clariostarplus"),
    }
    assert search("no such instrument")["total"] == 0
    hit = search("XPR204E")["results"][0]
    assert hit["license"] == "CC-BY-NC-4.0" and hit["size_m"] == [0.209, 0.4604, 0.339]
    assert client.get("/api/twins/library", params={"q": "x" * 81}).status_code == 422


def test_model_library_pages_every_drawn_instrument_by_domain(client):
    def browse(**params):
        response = client.get("/api/twins/library/models", params=params)
        assert response.status_code == 200, response.text
        return response.json()

    everything = browse()
    drawn = (
        sum(1 for a in CHEMLAB.values() if a.get("mesh"))
        + sum(1 for a in CLOUDLAB.values() if a.get("mesh"))
        + len(workcell_catalog())
    )
    assert everything["size"] == everything["total"] == drawn
    assert sum(everything["domains"].values()) == drawn
    assert len(everything["results"]) == 24 and everything["results"][0]["collection"] == "workcell"
    seen = set()
    for offset in range(0, drawn, 24):
        seen.update(r["id"] for r in browse(offset=offset)["results"])
    assert len(seen) == drawn
    spectroscopy = browse(domain="Molecular Spectroscopy & Structure")
    assert spectroscopy["total"] == everything["domains"]["Molecular Spectroscopy & Structure"]
    assert {r["domain"] for r in spectroscopy["results"]} == {"Molecular Spectroscopy & Structure"}
    hit = browse(q="xpr204e")
    assert hit["total"] == 1 and hit["results"][0]["mesh"] == CHEMLAB["mt_xpr204e"]["mesh"]
    assert browse(collection="workcell")["total"] == len(workcell_catalog())
    assert (
        client.get("/api/twins/library/models", params={"collection": "simready"}).status_code
        == 422
    )


def test_workcell_model_twin_records_the_registered_model(client):
    from academy.workcell_assets import registry
    from academy.workcell_models import catalog

    registered = {a.id for a in registry().assets}
    for key, entry in catalog().items():
        assert entry["mesh"]["asset"] in registered
        twin_id, created = add(client, client.get("/api/twins").json()["version"], workcell_id=key)
        twin = next(t for t in created["twins"] if t["id"] == twin_id)
        assert twin["source"] == "workcell_asset" and twin["asset"]["mesh"] == entry["mesh"]
        assert twin["spec"] == entry["spec"]
    arm = catalog()["ur5e-2f140"]["spec"]
    assert arm["operations"] == ["transfer", "wait"]
    bad = {"expected_version": created["version"], "id": str(uuid4()), "workcell_id": "nope"}
    assert client.post("/api/twins", json=bad).status_code == 422


def test_chemlab_models_are_pinned_and_served_from_the_app_origin():
    from academy.chemlab import MODELS, REVISION

    assert MODELS["revision"] == REVISION and len(MODELS["models"]) >= 190
    for slug, model in MODELS["models"].items():
        mesh = CHEMLAB[slug]["mesh"]
        assert mesh["url"] == f"/library-models/chemlab/{slug}.glb"
        assert mesh["sha256"] == model["sha256"] and len(mesh["sha256"]) == 64
        assert 0 < model["bytes"] <= 16_000_000


def test_twins_saved_before_their_entry_had_a_model_are_drawn_with_it(app):
    service = app.state.twins
    asset = {k: v for k, v in CHEMLAB["mt_xpr204e"].items() if k not in {"spec", "mesh"}}
    twin = {"id": "old", "source": "chemlab_asset", "asset": {"id": "mt_xpr204e", **asset}}
    service.store.put("old-owner", service.key, {"version": 1, "twins": [twin]}, None)
    shown = service.catalog("old-owner")["twins"][0]
    assert shown["asset"]["mesh"] == CHEMLAB["mt_xpr204e"]["mesh"]
    assert "mesh" not in service.get("old-owner")["twins"][0]["asset"]


def test_chemlab_asset_starts_an_attributed_twin_without_external_references(client):
    twin_id, catalog = add(client, 0, chemlab_id="mt_xpr204e")
    twin = catalog["twins"][0]
    asset = CHEMLAB["mt_xpr204e"]
    assert "chemlab" not in catalog  # searched, never shipped with every catalog
    assert (twin["source"], twin["spec"], twin["confirmed"]) == (
        "chemlab_asset",
        asset["spec"],
        False,
    )
    assert twin["asset"]["url"] == asset["url"] and "spec" not in twin["asset"]
    confirm(client, twin_id, catalog["version"], twin["spec"])
    text = client.get(f"/api/twins/{twin_id}/usd").text
    assert asset["attribution"] in text and asset["url"] in text
    assert "@" not in text and "references" not in text and "payload" not in text
    readme = client.get(f"/api/twins/{twin_id}/sila").json()["files"]["README.md"]
    assert asset["attribution"] in readme


def test_chemlab_twins_run_a_workflow_on_mock_connectors(client):
    ids = {}
    catalog = {"version": 0}
    for key in ["ika_ks4000", "bmg_clariostarplus", "brooks_preciseflex_400"]:
        ids[key], catalog = add(client, catalog["version"], chemlab_id=key)
        catalog = confirm(client, ids[key], catalog["version"], CHEMLAB[key]["spec"])
    shaker, reader, arm = ids.values()
    steps = [
        {"device_id": shaker, "operation": "load", "value": 200},
        {"device_id": shaker, "operation": "heat", "value": 60},
        {"device_id": arm, "operation": "transfer", "source_id": shaker, "target_id": reader},
        {"device_id": reader, "operation": "read"},
    ]
    planned = plan(client, catalog["version"], steps)
    assert planned.status_code == 200, planned.text
    run = client.post(
        "/api/twins/workflow/run", json={"expected_version": planned.json()["version"]}
    )
    assert run.status_code == 200, run.text
    assert run.json()["runs"][0]["trace"][-1]["measurement"]["temperature_c"] == 60


def test_usda_is_deterministic():
    assert usda(TEMPLATES["reader"]) == usda(TEMPLATES["reader"])


def plan(client, version, steps):
    return client.put("/api/twins/workflow", json={"expected_version": version, "steps": steps})


@pytest.mark.parametrize(
    "layer, steps",
    [
        (
            "volume",
            lambda r, h, a: [
                {"device_id": h, "operation": "load", "value": 500},
                {"device_id": a, "operation": "transfer", "source_id": h, "target_id": r},
            ],
        ),
        (
            "constraint",
            lambda r, h, a: [
                {"device_id": h, "operation": "load", "value": 100},
                {"device_id": h, "operation": "heat", "value": 110},
            ],
        ),
        ("constraint", lambda r, h, a: [{"device_id": a, "operation": "wait", "value": 900}]),
        (
            "container",
            lambda r, h, a: [
                {"device_id": h, "operation": "load", "value": 100},
                {"device_id": a, "operation": "transfer", "source_id": h, "target_id": a},
            ],
        ),
    ],
)
def test_failures_are_attributed_to_a_twin_layer(client, layer, steps):
    reader, heater, arm, catalog = build_cell(client)
    response = plan(client, catalog["version"], steps(reader, heater, arm))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["layer"] == layer


def test_consumables_run_out_and_value_edits_need_no_residual(client):
    handler, catalog = add(client, 0, template_id="liquid-handler")
    spec = TEMPLATES["liquid-handler"]
    one_tip = {**spec, "consumables": [{**spec["consumables"][0], "stock": 1}]}
    catalog = confirm(client, handler, catalog["version"], spec)
    catalog = confirm(client, handler, catalog["version"], one_tip)
    assert catalog["twins"][0]["revision"] == 2
    steps = [
        {"device_id": handler, "operation": "load", "value": 100},
        {"device_id": handler, "operation": "mix", "value": 5},
        {"device_id": handler, "operation": "mix", "value": 5},
    ]
    response = plan(client, catalog["version"], steps)
    assert response.json()["detail"]["layer"] == "consumable"
    run = plan(client, catalog["version"], steps[:2]).json()
    run = client.post("/api/twins/workflow/run", json={"expected_version": run["version"]}).json()
    assert run["runs"][0]["trace"][-1]["consumables"][handler] == {"Pipette tips": 0}


def test_added_detail_requires_an_open_residual_which_it_then_resolves(client):
    reader, catalog = add(client, 0, template_id="reader")
    spec = TEMPLATES["reader"]
    catalog = confirm(client, reader, catalog["version"], spec)
    detailed = {**spec, "parts": [*spec["parts"], BOX]}
    path = f"/api/twins/{reader}/confirm"
    refused = client.put(path, json={"expected_version": catalog["version"], "spec": detailed})
    assert refused.status_code == 422 and "geometry" in refused.json()["detail"]
    catalog = client.post(
        f"/api/twins/{reader}/residuals",
        json={
            "expected_version": catalog["version"],
            "layer": "geometry",
            "step": 2,
            "predicted": "Arm reaches the plate nest",
            "observed": "Lid hinge blocks the arm",
            "note": "Measured on the real reader.",
        },
    ).json()
    residual = catalog["twins"][0]["residuals"][0]
    assert (residual["revision"], residual["resolved_in"], residual["evidence"]) == (
        1,
        None,
        "learner_observation",
    )
    catalog = confirm(client, reader, catalog["version"], detailed)
    twin = catalog["twins"][0]
    assert twin["revision"] == 2 and twin["residuals"][0]["resolved_in"] == 2
    assert len(twin["spec"]["parts"]) == 3


def test_owner_isolation_includes_assets_and_runnable_bundle(client, app):
    import io
    import zipfile

    from fastapi.testclient import TestClient

    twin_id, catalog = add(client, 0, template_id="heater")
    confirm(client, twin_id, catalog["version"], TEMPLATES["heater"])
    with TestClient(app) as other:
        assert other.get(f"/api/twins/{twin_id}/sila.zip").status_code == 401
        other.post("/api/auth/guest", json={"name": "Grace"})
        assert other.get("/api/twins").json()["twins"] == []
        for suffix in ("usd", "sila", "sila.zip"):
            assert other.get(f"/api/twins/{twin_id}/{suffix}").status_code == 404
    result = client.get(f"/api/twins/{twin_id}/sila.zip")
    assert result.status_code == 200
    with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
        assert "mock_sila.py" in archive.namelist()
        assert "mock_contract.py" in archive.namelist()
        manifest = json.loads(archive.read("workspace.json"))
        assert manifest["twins"][0]["id"] == twin_id


def test_bedrock_request_has_a_complete_strict_output_schema(monkeypatch):
    import httpx
    from academy.settings import Settings
    from academy.simple_twins import BedrockTwins, CreateTwin

    calls = []

    def request(method, url, **kwargs):
        assert (
            method == "POST"
            and url == "https://bedrock-mantle.us-west-2.api.aws/openai/v1/responses"
        )
        assert kwargs["headers"]["Authorization"] == "Bearer test-only"
        payload = kwargs["json"]
        assert payload["model"] == "openai.gpt-6-astra"
        assert payload["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")

        def strict(schema):
            if schema.get("type") == "object":
                assert schema["additionalProperties"] is False
                assert set(schema["required"]) == set(schema["properties"])
                for child in schema["properties"].values():
                    strict(child)
            if schema.get("type") == "array":
                strict(schema["items"])

        schema = payload["text"]["format"]["schema"]
        strict(schema)
        keys = schema["properties"]["identification"]["properties"]["library_id"]["enum"]
        assert "chemlab:mt_xpr204e" in keys and "simready:franka-fr3" in keys
        assert keys[-1] == "none" and len(keys) == len(CHEMLAB) + len(SIMREADY) + len(WORKCELL) + 1
        prompt = payload["input"][0]["content"][0]["text"]
        assert "chemlab:mt_xpr204e | METTLER TOLEDO XPR204E analytical balance" in prompt
        calls.append(payload)
        return httpx.Response(
            200,
            request=httpx.Request(method, url),
            json={"id": "resp_schema_test", "status": "queued"},
        )

    monkeypatch.setattr(httpx, "request", request)
    provider = BedrockTwins(Settings(twin_region="us-west-2", twin_api_key="test-only"))
    response_id, _ = provider.begin(CreateTwin(expected_version=0, id=uuid4(), image=PNG))
    assert response_id == "resp_schema_test" and len(calls) == 1


def test_saved_run_pins_specs_even_after_twin_revision(client):
    twin_id, catalog = add(client, 0, template_id="heater")
    catalog = confirm(client, twin_id, catalog["version"], TEMPLATES["heater"])
    catalog = plan(
        client, catalog["version"], [{"device_id": twin_id, "operation": "load", "value": 100}]
    ).json()
    catalog = client.post(
        "/api/twins/workflow/run", json={"expected_version": catalog["version"]}
    ).json()
    pinned = catalog["runs"][0]["twins"][0]
    revised = {**TEMPLATES["heater"], "name": "Revised heater"}
    catalog = confirm(client, twin_id, catalog["version"], revised)
    assert catalog["twins"][0]["spec"]["name"] == "Revised heater"
    assert catalog["runs"][0]["twins"][0] == pinned
    assert pinned["spec"]["name"] == "Heating station" and pinned["revision"] == 1


def test_no_two_routes_share_a_method_and_path(app):
    # FastAPI silently lets the first registration win; a shared path breaks one feature.
    seen = [(m, r.path) for r in app.routes for m in getattr(r, "methods", ()) or ()]
    assert len(seen) == len(set(seen)), sorted({x for x in seen if seen.count(x) > 1})


def test_meet_the_instruments_lists_every_cloud_lab_instrument(client):
    found = client.get("/api/cloudlab/instruments").json()
    assert len(found["instruments"]) == len(CLOUDLAB) and found["evidence"] == "synthetic"
    assert found["sections"][0] == "Transfers"
    hplc = next(i for i in found["instruments"] if i["id"] == "analytical-hplc")
    assert hplc["experiment"] == "ExperimentHPLC" and "48 HPLC vials" in hplc["published"]
    assert hplc["stand_in"] and hplc["mesh"]
    nmr = next(i for i in found["instruments"] if i["id"] == "nmr")
    assert nmr["mesh"] is None and "96 of the 480" in nmr["narrowed"]
