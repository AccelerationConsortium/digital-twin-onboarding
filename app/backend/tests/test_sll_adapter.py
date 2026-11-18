import pytest
from academy.sll_adapter import SllError, translate

PROGRAM = """
(* Two transfers out of the stock *)
ExperimentRoboticSamplePreparation[{
  Transfer[Source -> "stock", Destination -> "A1", Amount -> 250 Microliter],
  Transfer[Source -> "stock", Destination -> "A2", Amount -> 0.25 Milliliter]
}]
"""


def check(client, program, **extra):
    response = client.post(
        "/api/node/v1/adapters/sll/validate",
        json={"program": program, "source_volume": 5000, **extra},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_transfers_become_fresh_tip_pipetting_steps():
    units, actions, unsupported = translate(PROGRAM)
    assert units == [
        {"unit": 1, "source": "stock", "destination": "A1", "volume_ul": 250},
        {"unit": 2, "source": "stock", "destination": "A2", "volume_ul": 250},
    ]
    assert [a["kind"] for a in actions] == ["pickup", "aspirate", "dispense", "drop"] * 2
    assert unsupported == []


def test_a_valid_program_passes_the_simulator_rules(client):
    result = check(client, PROGRAM)
    assert result["valid"] and result["stops"] == [] and result["evidence"] == "synthetic"


def test_an_oversized_transfer_is_stopped_where_opentrons_would(client):
    big = 'Transfer[Source -> "stock", Destination -> "A1", Amount -> 1.5 Milliliter]'
    result = check(client, big)
    assert not result["valid"]
    assert result["stops"][0] == {
        "step": 2,
        "message": "Aspirates 1500 µL when the tip has room for 1000 µL",
    }
    assert not check(client, big.replace("1.5 Milliliter", "250 Microliter"), instrument="ot2")[
        "stops"
    ]


def test_unmodelled_operations_and_options_are_reported_not_guessed(client):
    program = """{
      Transfer[Source -> "stock", Destination -> "A1", Amount -> 100 Microliter,
               DispenseMix -> True],
      Incubate[Sample -> "A1", Temperature -> 37 Celsius]
    }"""
    with pytest.raises(SllError, match="Use Microliter or Milliliter, not Celsius"):
        translate(program)
    program = program.replace("37 Celsius", "37")
    result = check(client, program)
    assert not result["valid"]
    assert [u["message"] for u in result["unsupported"]] == [
        "Options not modelled and ignored: DispenseMix",
        "Incubate is not in this adapter yet",
    ]


@pytest.mark.parametrize(
    "program, message",
    [
        ('Transfer[Source -> "stock", Destination -> "B7", Amount -> 10 Microliter]', "B7"),
        ('Transfer[Source -> "stock", Amount -> 10 Microliter]', "needs Destination"),
        ('Transfer[Source -> "stock", Destination -> "A1", Amount -> 10]', "as a volume"),
        ('Transfer[Source -> "stock", Destination -> "A1"', "ends early"),
        ('RunScript["rm -rf /"]; Import["x"]', None),
        (
            'Transfer[Source -> Object[Sample, "id:1"], Destination -> "A1", '
            "Amount -> 10 Microliter]",
            "Source",
        ),
    ],
)
def test_malformed_programs_are_explained(client, program, message):
    result = check(client, program)
    assert not result["valid"]
    if message:
        text = (result["error"] or {}).get("message", "") + str(result["unsupported"])
        assert message in text


def test_nothing_in_a_program_is_evaluated(client):
    result = check(client, 'RunScript["rm -rf /"]; Import["/etc/passwd"]')
    assert [u["message"] for u in result["unsupported"]] == [
        "RunScript is not in this adapter yet",
        "Import is not in this adapter yet",
    ]
    assert result["actions"] == []
