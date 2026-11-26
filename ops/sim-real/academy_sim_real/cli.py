"""Command line: pin connector releases, run Sim–Real plans in simulation and, after a
passed simulation, on the instruments' own connectors."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from academy.simreal import bindings

from .importer import import_connector
from .launch import LaunchError, installations


def main(argv=None):
    parser = argparse.ArgumentParser(prog="academy-sim-real", description=__doc__)
    parser.add_argument(
        "--connector",
        action="append",
        default=[],
        metavar="KEY=PYTHON[:SOURCE]",
        help="A connector's interpreter and source tree; else SIMREAL_<KEY>_PYTHON/_SOURCE",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    pin = commands.add_parser("import", help="Pin the features a simulated connector serves")
    pin.add_argument("key", choices=sorted(bindings.PROFILES))
    pin.add_argument(
        "--commit",
        help="Source revision, when the installation's source tree is not a git checkout",
    )
    build = commands.add_parser("compile", help="Compile a workflow into a plan")
    build.add_argument("workflow", type=Path)
    build.add_argument("--plan", type=Path, help="Write the plan here instead of stdout")
    run = commands.add_parser("run", help="Run a compiled plan on simulated connectors")
    run.add_argument("plan", type=Path)
    run.add_argument("--report", type=Path, help="Write the run report here instead of stdout")
    run.add_argument("--workdir", type=Path, help="Keep connector files and logs here")
    run.add_argument(
        "--real",
        action="append",
        default=[],
        metavar="DEVICE=HOST[:PORT]",
        help="After the simulation passes, run the plan on this instrument's connector",
    )
    run.add_argument(
        "--confirm",
        metavar="DIGEST",
        help="The first 12 characters of the plan digest, instead of typing them when asked",
    )
    args = parser.parse_args(argv)
    try:
        installed = installations(args.connector)
        if args.command == "import":
            if args.key not in installed:
                parser.error(f"Give --connector {args.key}=PYTHON[:SOURCE]")
            manifest = asyncio.run(
                import_connector(args.key, installed[args.key], commit=args.commit)
            )
            print(
                f"Pinned {manifest['package']} {manifest['package_version']}: "
                f"{len(manifest['features'])} features"
            )
            return 0
        if args.command == "compile":
            from academy.simreal import compiler

            plan = compiler.compile_workflow(
                compiler.Workflow.model_validate_json(args.workflow.read_text())
            )
            text = json.dumps(plan, indent=2)
            if args.plan:
                args.plan.write_text(text + "\n")
            else:
                print(text)
            for problem in plan["problems"]:
                print(f"problem: {problem['message']}", file=sys.stderr)
            return 0 if plan["valid"] else 1
        from .runner import instruments, run_plan, run_real

        plan = json.loads(args.plan.read_text())
        where = instruments(plan, args.real) if args.real else None
        report = asyncio.run(run_plan(plan, installed, workdir=args.workdir))
        if where and report["outcome"] != "passed":
            print(
                f"The simulation {report['outcome']}; nothing was sent to an instrument",
                file=sys.stderr,
            )
        elif where:
            key = plan["digest"][:12]
            print(f"Simulation passed: {len(plan['steps'])} commands, plan {key}", file=sys.stderr)
            for device, target in where.items():
                print(f"  {device} -> the instrument's connector at {target}", file=sys.stderr)
            typed = args.confirm
            if typed is None and sys.stdin.isatty():
                typed = input(f"Type {key} to send them to the instrument: ").strip()
            if typed != key:
                print("Not confirmed; nothing was sent to an instrument", file=sys.stderr)
                return 2
            report = asyncio.run(run_real(plan, where, report))
        text = json.dumps(report, indent=2)
        if args.report:
            args.report.write_text(text + "\n")
            print(f"{report['evidence']} {report['outcome']}: {args.report}")
        else:
            print(text)
        return 0 if report["outcome"] == "passed" else 1
    except (LaunchError, bindings.BindingError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
