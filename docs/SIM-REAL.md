# Sim–Real: workflows on the real connectors in simulation

Status: implemented and run locally against the Opentrons Flex and UR5e connectors in
their simulation modes. Not deployed. No physical instrument was contacted.

A Sim–Real run sends a workflow to the same connector programs that drive the
instruments, started in their own simulation mode. Nothing imitates a connector: the
commands, parameter limits and errors are the connector's.

## Parts

| Part | Where | What it does |
|---|---|---|
| Connector bindings | `academy/simreal/bindings.py`, `academy/simreal/connectors/<key>/` | How each connector starts in simulation, how it shows it is simulating, and the Feature Definitions of one pinned release with their SHA-256 |
| Feature reader | `academy/simreal/fdl.py` | Parses SiLA 2 Feature Definitions and checks arguments against their types and constraints |
| World model | `academy/simreal/world.py` | Where every plate is across instruments, what each deck ledger records, and what each connector should report back |
| Motion | `academy/simreal/motion.py` | Cuts a planned transfer into the arm connector's waypoint chains, ending at the grasp points |
| Compiler | `academy/simreal/compiler.py` | Workflow → plan of concrete SiLA calls, with problems named instead of raised |
| Routes | `academy/simreal/api.py` (`/api/sim-real/v1`) | Connector catalog, example, compile, kept run reports |
| Runner | `ops/sim-real` | Starts connectors as child processes, runs a plan, reads every connector back after every command |
| Page | `app/frontend/src/SimReal.tsx` (`#/sim-real`) | Its own sidebar section |

The web application and Lambda import no SiLA SDK and start nothing. Connectors need their
own Python environments (the Flex simulator needs `opentrons`), so runs happen where they
are installed.

## Running

```sh
cd ops/sim-real && uv sync
export SIMREAL_OPENTRONS_FLEX_PYTHON=/path/to/flex-env/bin/python
export SIMREAL_UR5E_PYTHON=/path/to/ur5e-env/bin/python
uv run academy-sim-real compile workflow.json --plan plan.json
uv run academy-sim-real run plan.json --report report.json
uv run pytest            # end-to-end tests are skipped without the two interpreters
```

`academy-sim-real import <key>` pins a connector release from a live simulated connector.
Give `SIMREAL_<KEY>_SOURCE` (a git checkout) so the manifest records the commit, or
`--commit` when the source tree is not one.

## Fail-closed rules

- A connector that does not report simulation over SiLA receives no command.
- A served Feature Definition that differs from the pinned one, or was never pinned, stops
  the run before it starts. A subset (modules left out) is not drift.
- A plan carries a digest over its devices, pinned feature digests, layout and commands;
  the runner and the report check both refuse a plan that no longer matches it.
- A workflow may not send arm motion, gripper or simulation-switch commands itself.
- Nothing is retried. A refused effect, a connector error or a readback difference ends
  the run at that command.

## Transfers

A `transfer` step becomes: travel to the source, lower, `SetSimulatedObject` (simulation
only), `GripPlate`, lift–carry–lower, `ReleasePlate`, retreat. Around it, a Flex is told
through its own `DeckHandoffController`: `ReleaseLabware` once the plate is away,
`RegisterLabware` once it is set down. Slots the arm touches become handoff slots of the
simulated Flex, and plates that start on a Flex start in its deck ledger.

## What it does not establish

- The arm simulator interpolates joints; collision clearance comes from the bench planner
  (capsule links, box instruments, nominal DH), not from the connector.
- The plate gripper is simulated in the UR5e connector; no hardware is chosen.
- The Flex connector's simulator attaches a gripper but no pipettes, so pipetting commands
  fail with `PipetteNotAttachedError`.
- Opentrons' module simulator lets a Heater-Shaker shake with its latch open and open its
  latch while shaking; the world model keeps those two rules itself.
- The world model tracks plate custody, not liquids, temperatures or chemistry.
- Timing: the arm's simulator runs faster than the clock; its own reported duration is
  kept as `device_s`. Other commands have only the time waited.
