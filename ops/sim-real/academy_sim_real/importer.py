"""Pin a connector release: start it in simulation and keep what it says about itself."""

import json
import tempfile
import time
from pathlib import Path

from academy.simreal import bindings, fdl

from .launch import running

# Everything a connector can serve is switched on, so every feature is pinned.
FULL = {
    "opentrons-flex": {
        "modules": list(bindings.FLEX_MODULES),
        "handoff": ["A1"],
    },
    "ur5e": {},
}


async def import_connector(key, installation, root=None, commit=None):
    """Write `connectors/<key>/` from a live simulated connector; return its manifest."""
    profile = bindings.profile(key)
    described = installation.describe(profile["package"])
    with tempfile.TemporaryDirectory(prefix=f"simreal-{key}-") as workdir:
        async with running(key, installation, workdir, options=FULL[key], pinned=False) as live:
            served, server = live.served, live.server
    target = Path(root or bindings.ROOT) / key
    target.mkdir(parents=True, exist_ok=True)
    for stale in target.glob("*.sila.xml"):
        stale.unlink()
    entries = []
    for identifier, xml in sorted(served.items()):
        feature = fdl.parse(xml)
        if feature["id"] != identifier:
            raise ValueError(f"{identifier} describes itself as {feature['id']}")
        originator, category, name, version = identifier.split("/")
        file = f"{name}.{version}.sila.xml"
        (target / file).write_text(xml)
        entries.append({"id": identifier, "sha256": feature["sha256"], "file": file})
    manifest = {
        "schema": bindings.SCHEMA,
        "key": key,
        "package": profile["package"],
        "package_version": described["package_version"],
        "source": {
            "repository": profile["repository"],
            # A revision given by hand is recorded as stated; nothing here can check it.
            "commit": described["commit"] or commit,
            "dirty": described["dirty"],
            "commit_stated": described["commit"] is None and commit is not None,
        },
        "server": {"type": server["type"], "version": server["version"]},
        "simulator": profile["simulator"],
        "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "features": entries,
    }
    (target / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    bindings.manifest.cache_clear()
    bindings.features.cache_clear()
    return manifest
