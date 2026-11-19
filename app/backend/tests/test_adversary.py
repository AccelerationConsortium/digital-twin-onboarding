"""Adaptive stress testing: a cross-entropy search for a workflow's likeliest failure."""

import itertools
import json

import pytest
from academy import adversary, arm_simulation, endurance, examples
from academy.mock_contract import PlanError

needs_mujoco = pytest.mark.skipif(not arm_simulation.available(), reason="MuJoCo not installed")
# Drift wide enough that the plate reader can reach the gripper's transit path, but only
# past about 2.5σ: a few cycles in a thousand.
ROUGH = {**endurance.NOISE, "drift_mm": 10}


@pytest.fixture(scope="module")
def cell():
    counter = itertools.count()
    twins, steps, layout = examples.build(
        examples.EXAMPLES["flex-reader"], lambda: f"twin-{next(counter)}"
    )
    return {t["id"]: t for t in twins}, layout, steps


@pytest.fixture(scope="module")
def rough(cell):
    twins, layout, steps = cell
    return adversary.adversary(twins, layout, steps, budget=120, noise=ROUGH, seconds=600)


def test_the_search_space_has_a_dimension_per_perturbation_in_units_of_sigma(cell):
    twins, layout, steps = cell
    transfers = endurance.nominal(twins, layout, steps)
    arms = {t["actor_id"] for t in transfers}
    dims = adversary.dimensions(twins, layout, transfers, arms, endurance.NOISE)
    # Two instruments drift in x, z and yaw; the transfer has pick and place errors in x
    # and z, a labware mass and an arm speed.
    assert len(dims) == 2 * 3 + 6
    z = [0.0] * len(dims)
    z[0], z[-2], z[-1] = 1.5, -2.0, 9.0  # 9σ is cut at 3σ, as in the endurance run
    drift, moves = adversary.perturb(dims, z, layout, transfers, arms)
    first = dims[0]["twin_id"]
    assert drift[first] == pytest.approx((1.5 * 0.002, 0.0, 0.0))
    assert moves[0]["mass"] == pytest.approx(0.8) and moves[0]["speed"] == pytest.approx(1.3)
    assert moves[0]["pick"] == [0.0, 0.0]
    # A zero σ takes a perturbation out of the search.
    still = {**endurance.NOISE, "drift_deg": 0, "speed_pct": 0}
    assert len(adversary.dimensions(twins, layout, transfers, arms, still)) == len(dims) - 3


@needs_mujoco
def test_the_search_finds_a_rare_failure_far_sooner_than_monte_carlo(cell, rough):
    twins, layout, steps = cell
    assert rough["synthetic"] and rough["nominal_ok"] and rough["next"] is None
    assert rough["simulated"] >= 120
    (found, *_) = rough["failures"]
    assert found["mode"] == "collision" and found["message"].startswith("Step 3: the ")
    # Plain Monte Carlo at the same spread sees no failure in 100 cycles...
    mc = endurance.stress(twins, layout, steps, cycles=100, noise=ROUGH, seconds=600)
    assert all(r["ok"] for r in mc["results"])
    # ...while the search reaches one within a few dozen and puts it near 3σ out.
    assert found["first_found_at"] <= 60
    assert 2.0 < found["distance_sigma"] < 4.0
    assert found["monte_carlo_cycles"] > 100
    assert found["probability"] == pytest.approx(1 / found["monte_carlo_cycles"], rel=0.01)
    assert found["log_likelihood"] == pytest.approx(-0.5 * found["distance_sigma"] ** 2, abs=0.01)
    # The plate reader drifting toward the arm carries most of the distance.
    top = found["drivers"][0]
    assert top["kind"] == "drift_x" and top["label"].startswith("Plate reader")
    assert top["share"] > 0.4 and top["value"] == pytest.approx(top["sigma"] * 10, abs=0.06)
    reader = next(d for d in found["perturbation"]["drift"] if d["twin_id"] == top["twin_id"])
    assert reader["dx_mm"] == pytest.approx(top["value"], abs=0.02)


@needs_mujoco
def test_a_found_failure_replays_the_same_cycle(cell, rough):
    twins, layout, steps = cell
    found = rough["failures"][0]
    again = adversary.replay(twins, layout, steps, found["sigma"], noise=ROUGH)
    assert again["synthetic"] and not again["record"]["ok"]
    assert again["record"]["failures"][0]["message"] == found["message"]
    assert again["drift"] == found["perturbation"]["drift"]
    assert again["moves"] == found["perturbation"]["moves"]
    (motion,) = again["motions"]
    assert len(motion["frames"]) == len(motion["joints"]) > 10
    with pytest.raises(PlanError, match="start the search again"):
        adversary.replay(twins, layout, steps, found["sigma"][:-1], noise=ROUGH)


@needs_mujoco
def test_a_seed_repeats_the_search_and_chunks_resume_it_exactly(cell):
    twins, layout, steps = cell

    def search(state=None, seed=4, seconds=600):
        return adversary.adversary(
            twins,
            layout,
            steps,
            budget=30,
            population=8,
            state=state,
            seed=seed,
            noise=ROUGH,
            seconds=seconds,
        )

    whole = search()
    assert whole["next"] is None and whole == search()
    assert search(seed=5)["closest"] != whole["closest"]
    # With no time per chunk every chunk still runs one cycle, then hands back its state.
    chunks, state = 0, None
    while True:
        chunk = search(state=state, seconds=0)
        chunks += 1
        if chunk["next"] is None:
            break
        state = json.loads(json.dumps(chunk["next"]))  # as the client sends it back
        assert chunk["simulated"] == chunks + 1
    assert chunks == whole["simulated"] - 1
    assert {k: v for k, v in chunk.items()} == whole
    # A state from other settings is refused.
    with pytest.raises(PlanError, match="settings changed"):
        adversary.adversary(twins, layout, steps, budget=30, population=8, state=state)


@needs_mujoco
def test_without_a_failure_it_reports_the_closest_approach(cell):
    twins, layout, steps = cell
    run = adversary.adversary(twins, layout, steps, budget=40, population=8, seconds=600)
    assert run["failures"] == []
    families = {c["family"] for c in run["closest"]}
    assert families == set(adversary.FAMILIES)
    for near in run["closest"]:
        assert 0 < near["margin_left"] <= 1 and near["distance_sigma"] >= 0
        assert len(near["sigma"]) == len(run["dimensions"])
    collision = next(c for c in run["closest"] if c["family"] == "collision")
    assert collision["clearance_m"] > arm_simulation.SAFETY


def test_without_mujoco_the_search_says_why(cell, monkeypatch):
    monkeypatch.setattr(arm_simulation, "mujoco", None)
    twins, layout, steps = cell
    with pytest.raises(PlanError, match="need the MuJoCo simulation"):
        adversary.adversary(twins, layout, steps)


@needs_mujoco
def test_the_api_searches_the_owners_saved_workflow_only(client, app, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(endurance, "CHUNK_SECONDS", 0)  # one cycle per chunk

    opened = client.put("/api/twins/examples/flex-reader", json={"expected_version": 0})
    layout = opened.json()["layout"]
    url = "/api/twins/layout/endurance/adversary"
    body = {**layout, "budget": 20, "population": 8, "seed": 2, "noise": {"drift_mm": 10}}
    response = client.post(url, json=body)
    assert response.status_code == 200, response.text
    chunk = response.json()
    assert chunk["synthetic"] and chunk["engine"]["engine"] == "mujoco"
    assert chunk["noise"]["drift_mm"] == 10 and len(chunk["dimensions"]) == 12
    assert chunk["simulated"] == 2 and chunk["next"]
    resumed = client.post(url, json={**body, "state": chunk["next"]})
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["simulated"] == 3
    # Changed settings make the state stale, and a tampered one is refused.
    stale = client.post(url, json={**body, "seed": 3, "state": chunk["next"]})
    assert stale.status_code == 422 and "start the search again" in stale.text
    broken = {**chunk["next"], "gaussians": {"collision": {"mean": [1e9], "std": [1]}}}
    assert client.post(url, json={**body, "state": broken}).status_code == 422
    garbled = {**chunk["next"], "pending": {"cycles": "x", "done": []}}
    assert client.post(url, json={**body, "state": garbled}).status_code == 422
    sigma = [0.0] * 12
    replayed = client.post(
        f"{url}/replay", json={**layout, "sigma": sigma, "noise": {"drift_mm": 10}}
    )
    assert replayed.status_code == 200 and replayed.json()["record"]["ok"]
    # Bounds are enforced before any simulation runs.
    for bad in ({"budget": 50_000}, {"budget": 5}, {"population": 2}, {"population": 500}):
        assert client.post(url, json={**body, **bad}).status_code == 422
    assert client.post(f"{url}/replay", json={**layout, "sigma": [4.0] * 12}).status_code == 422
    assert client.post(f"{url}/replay", json={**layout, "sigma": [0.0] * 3}).status_code == 422
    with TestClient(app) as other:
        other.post("/api/auth/guest", json={"name": "Grace"})
        # Another learner's instruments are not found, and an empty bench is refused.
        assert other.post(url, json=body).status_code == 404
        empty = {"bench": layout["bench"], "placements": [], "budget": 20}
        assert other.post(url, json=empty).status_code == 409
