"""A stand-in connector for launch tests: says whether it simulates, serves one odd feature."""

import asyncio
import json
import os
import sys

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila
from unitelabs.cdk.features.core.simulation_controller import SimulationControllerBase


class SimulationController(SimulationControllerBase):
    @sila.UnobservableCommand()
    async def start_simulation_mode(self) -> None:
        """Stay as configured."""

    @sila.UnobservableCommand()
    async def start_real_mode(self) -> None:
        """Stay as configured."""

    @sila.UnobservableProperty(name="SimulationMode")
    async def simulation_mode(self) -> bool:
        """Report the configured mode."""
        return os.environ.get("FAKE_SIMULATING", "1") == "1"


class Extra(sila.Feature):
    """A feature no release pinned."""

    def __init__(self):
        super().__init__(originator="org.example", category="test", version="1.0")

    @sila.UnobservableProperty()
    async def get_answer(self) -> int:
        """Return a number."""
        return 42


async def main():
    port = json.load(open(sys.argv[1]))["sila_server"]["port"]
    connector = Connector(
        ConnectorBaseConfig(
            sila_server=SiLAServerConfig(hostname="127.0.0.1", port=port, tls=False, name="Fake"),
            cloud_server_endpoint=None,
            discovery=None,
        )
    )
    connector.register(SimulationController())
    if os.environ.get("FAKE_EXTRA") == "1":
        connector.register(Extra())
    await connector.start()
    try:
        await connector.wait_for_termination()
    finally:
        await connector.stop()


asyncio.run(main())
