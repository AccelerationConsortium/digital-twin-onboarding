import pytest
from academy.cloudlab import CLOUDLAB, CONTRACTS
from academy.cloudlab_anatomy import ANATOMY, anatomy, members


def test_every_drawn_stand_in_with_named_components_has_an_anatomy():
    drawn = {key for key, asset in CLOUDLAB.items() if asset["slug"]}
    assert {key for key in CLOUDLAB if anatomy(key)} == drawn
    # 15 cloud lab instruments and 27 Acceleration Consortium ones are drawn.
    assert sum(CLOUDLAB[key]["lab"] == "ecl" for key in drawn) == 15
    assert sum(CLOUDLAB[key]["lab"] == "ac" for key in drawn) == 27
    # An instrument drawn as an estimated box has nothing inside to show.
    assert anatomy("nmr") is None and anatomy("robotic-sample-preparation") is None
    assert set(ANATOMY) <= set(CONTRACTS["stand_ins"])


@pytest.mark.parametrize("slug", sorted(ANATOMY))
def test_a_component_belongs_to_one_numbered_part(slug):
    seen = {}
    for label, about, names, toward in ANATOMY[slug]:
        assert label and about.endswith(".")
        assert toward is None or len(toward) == 3
        for component in members(slug, names):
            assert component in CONTRACTS["stand_ins"][slug]["components"]
            assert component not in seen, (slug, component, seen.get(component), label)
            seen[component] = label
    assert 5 <= len(ANATOMY[slug]) <= 8


def test_a_name_ending_in_a_star_takes_every_component_it_starts():
    assert members("biorad_cfxopus", ["intake_vent_*"]) == ["intake_vent_left", "intake_vent_right"]
    with pytest.raises(ValueError, match="no component"):
        members("biorad_cfxopus", ["nowhere"])


def test_meet_the_instruments_serves_the_numbered_parts(client):
    found = client.get("/api/cloudlab/instruments").json()["instruments"]
    icp = next(i for i in found if i["id"] == "icp-ms")["anatomy"]
    assert icp["node_prefix"] == "shimadzu_icpms2030__"
    assert [p["n"] for p in icp["parts"]] == list(range(1, len(icp["parts"]) + 1))
    cones = next(p for p in icp["parts"] if p["label"] == "Cones")
    assert cones["components"] == ["sampling_cone", "skimmer_cone", "interface_flange"]
    gc = next(i for i in found if i["id"] == "gcms")["anatomy"]
    # Its model names its nodes after the 7890B, not after its slug.
    assert gc["node_prefix"] == "GC7890B__"
    assert next(i for i in found if i["id"] == "nmr")["anatomy"] is None
