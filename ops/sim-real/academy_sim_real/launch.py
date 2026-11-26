"""Start an installed instrument connector in its simulation mode on a loopback port, or
connect to the one already running on an instrument.

A connector is somebody else's program in its own Python environment, so a simulated one
runs as a child process. Before anything is sent to either, the runner checks over SiLA
that it says it is simulating, or that it says it is not, and that the features it serves
are the pinned ones.
"""

import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from academy.simreal import bindings, fdl
from sila.client import Client, ClientConfig

SERVICE = "org.silastandard/core/SiLAService/v1"
COMMAND_SECONDS = 600  # the longest one simulated command may take


class LaunchError(RuntimeError):
    """A connector could not be started or reached, or is not the pinned release in the
    mode that was asked for."""


@dataclass
class Installation:
    """Where one connector is installed: its interpreter and, when known, its source tree."""

    python: Path
    source: Path | None = None

    def describe(self, package):
        """Package version and source revision, as far as the installation can tell."""
        version = subprocess.run(
            [
                str(self.python),
                "-c",
                f"import importlib.metadata as m; print(m.version({package!r}))",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if version.returncode:
            raise LaunchError(f"{package} is not installed for {self.python}")
        found = {"package_version": version.stdout.strip(), "commit": None, "dirty": None}
        if self.source and (self.source / ".git").exists():

            def git(*args):
                return subprocess.run(
                    ["git", "-C", str(self.source), *args],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()

            found["commit"] = git("rev-parse", "HEAD") or None
            found["dirty"] = bool(git("status", "--porcelain", "--untracked-files=no"))
        return found


def installations(pairs=(), environ=None):
    """Connector installations from `key=python[:source]` pairs, else SIMREAL_<KEY>_PYTHON/_SOURCE."""
    environ = os.environ if environ is None else environ
    found = {}
    for key in bindings.PROFILES:
        name = key.upper().replace("-", "_")
        python = environ.get(f"SIMREAL_{name}_PYTHON")
        if python:
            source = environ.get(f"SIMREAL_{name}_SOURCE")
            found[key] = Installation(Path(python), Path(source) if source else None)
    for pair in pairs:
        key, _, rest = pair.partition("=")
        python, _, source = rest.partition(":")
        if key not in bindings.PROFILES or not python:
            raise LaunchError(f"Give connectors as key=python[:source]; got {pair}")
        found[key] = Installation(Path(python), Path(source) if source else None)
    for key, installation in found.items():
        if not installation.python.exists():
            raise LaunchError(f"No interpreter at {installation.python} for {key}")
    return found


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@dataclass
class Connector:
    """One running connector and a SiLA client connected to it."""

    key: str
    device: str
    port: int
    client: Client
    process: asyncio.subprocess.Process | None  # None for one this runner did not start
    log: Path | None
    served: dict = field(default_factory=dict)  # feature id -> Feature Definition XML
    server: dict = field(default_factory=dict)
    host: str = "127.0.0.1"
    _features: dict = field(default_factory=dict)

    async def feature(self, identifier):
        if identifier not in self._features:
            self._features[identifier] = await self.client.load_feature(identifier)
        return self._features[identifier]

    async def read(self, feature, name):
        return await (await self.feature(feature)).properties[name].read()

    async def execute(self, feature, command, arguments, timeout=COMMAND_SECONDS):
        """Run a command to its end and return its responses; a SiLA error is raised.

        An observable command first answers with a handle only, so its result is waited
        for: a command that fails while running fails here, not later.
        """
        answer = await (await self.feature(feature)).commands[command].execute(arguments)
        if not hasattr(answer, "get_responses"):
            return answer
        deadline = asyncio.get_running_loop().time() + timeout
        while not answer.done:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError(f"{command} did not finish within {timeout:g} s")
            await asyncio.sleep(0.02)
        return await answer.get_responses()


async def _served(client):
    service = await client.load_feature(SERVICE)
    found = {}
    for identifier in await service.properties["ImplementedFeatures"].read():
        answer = await service.commands["GetFeatureDefinition"].execute(
            {"FeatureIdentifier": identifier}
        )
        found[identifier] = answer["FeatureDefinition"]
    return found, {
        "name": await service.properties["ServerName"].read(),
        "type": await service.properties["ServerType"].read(),
        "version": await service.properties["ServerVersion"].read(),
    }


def drift(key, served):
    """How the features a connector serves differ from its pinned manifest; empty when equal.

    A simulated connector serves a subset when modules are left out, so a missing feature
    is not drift: a feature whose definition changed, or one never pinned, is.
    """
    pinned = {f["id"]: f["sha256"] for f in bindings.manifest(key)["features"]}
    problems = []
    for identifier, xml in served.items():
        if identifier not in pinned:
            problems.append(f"{identifier} is not in the pinned release")
        elif fdl.digest(xml) != pinned[identifier]:
            problems.append(f"{identifier} differs from the pinned release")
    return problems


async def _verified(connector, simulating, pinned):
    """The connector, once it reports the mode that was asked for and serves the pinned release."""
    profile = bindings.profile(connector.key)
    connector.served, connector.server = await _served(connector.client)
    probe = profile["simulating"]
    if probe["feature"] not in connector.served:
        raise LaunchError(
            f"The {profile['name']} connector does not serve {probe['feature']}, so it "
            f"cannot be shown to be {'simulating' if simulating else 'driving an instrument'}"
        )
    reported = await connector.read(probe["feature"], probe["property"])
    if simulating and reported is not True:
        raise LaunchError(
            f"The {profile['name']} connector does not report simulation; nothing was sent"
        )
    if not simulating and reported is not False:
        raise LaunchError(
            f"The {profile['name']} connector there reports simulation, not an instrument; "
            "nothing was sent"
        )
    if pinned:
        problems = drift(connector.key, connector.served)
        if problems:
            raise LaunchError(
                f"The {profile['name']} connector is not the pinned release: " + "; ".join(problems)
            )
    return connector


def address(key, text):
    """Host and port of a connector running on its instrument, from `host[:port]`."""
    profile = bindings.profile(key)
    if "real" not in profile:
        reason = bindings.NO_REAL.get(key, "no real run is bound for it")
        raise LaunchError(f"The {profile['name']} connector has no real run: {reason}")
    host, _, port = str(text).strip().rpartition(":")
    if not host:
        host, port = port, profile["real"]["port"]
    if not host or not str(port).isdigit() or not 0 < int(port) < 65536:
        raise LaunchError(f"Give an instrument's connector as host[:port]; got {text}")
    return host, int(port)


@contextlib.asynccontextmanager
async def attached(key, where, *, device=None, pinned=True):
    """The connector already running on an instrument, verified; left running on exit."""
    profile = bindings.profile(key)
    host, port = address(key, where)
    client = Client(ClientConfig(host, port, tls=False, default_timeout=120_000))
    try:
        try:
            await asyncio.wait_for(client.open(), timeout=20)
        except Exception as exc:  # whatever the client raises, nothing is there to command
            raise LaunchError(
                f"No {profile['name']} connector answers at {host}:{port}: {exc}"
            ) from exc
        yield await _verified(
            Connector(key, device or key, port, client, None, None, host=host), False, pinned
        )
    finally:
        with contextlib.suppress(Exception):
            await client.close()


@contextlib.asynccontextmanager
async def running(key, installation, workdir, *, device=None, options=None, pinned=True):
    """A connector started in simulation, verified, and stopped again on exit."""
    profile = bindings.profile(key)
    opts = bindings.options(key, options)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    files = bindings.launch_files(key, port, f"{profile['name']} (simulation)", opts)
    for name, content in files.items():
        text = json.dumps(content, indent=2).replace("{workdir}", str(workdir))
        (workdir / name).write_text(text)
    substitutions = {
        "python": str(installation.python),
        "bin": str(installation.python.parent),
        "config": str(workdir / "config.json"),
    }
    argv = [part.format(**substitutions) for part in profile["argv"]]
    log = workdir / "connector.log"
    with log.open("w") as stream:
        # A clean environment: the connector must not pick up this runner's packages.
        environment = {
            k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")
        }
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=stream,
            stderr=stream,
            cwd=workdir,
            env=environment,
            start_new_session=True,
        )
    client = Client(ClientConfig("127.0.0.1", port, tls=False, default_timeout=120_000))
    try:
        deadline = asyncio.get_running_loop().time() + profile["startup_seconds"]
        while True:
            if process.returncode is not None:
                raise LaunchError(
                    f"The {profile['name']} connector stopped while starting; see {log}"
                )
            with contextlib.suppress(OSError):
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            if asyncio.get_running_loop().time() > deadline:
                raise LaunchError(f"The {profile['name']} connector did not start; see {log}")
            await asyncio.sleep(0.25)
        await asyncio.wait_for(client.open(), timeout=60)
        yield await _verified(
            Connector(key, device or key, port, client, process, log), True, pinned
        )
    finally:
        with contextlib.suppress(Exception):
            await client.close()
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGINT if sys.platform != "win32" else signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
