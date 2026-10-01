"""The test stand: a clean Home Assistant publishing to a development chain.

    scripts/stand.sh                      # everything, about 10 minutes
    scripts/stand.sh --skip-heartbeat     # without waiting 5 min for the first beat

What runs, all on this machine:
- a Robonomics development node (robonomics-interface's scripts/devchain.sh:
  the mainnet runtime, sudo and funded ED25519 dev accounts);
- a fake Pinata (stand/fake_pinata.py): pinning API and gateway;
- Home Assistant from PyPI, the release CI tests against, with a clean
  configuration and the integration already installed: its stored settings
  point at the public test mnemonics of tests/conftest.py.

The integration is told to use the dev chain and the fake Pinata through
RRS_STAND_* environment variables; nothing else in it is changed.

What is checked, by reading the chain and opening each report the way the
connector does (archive from the gateway, files decrypted with the
integrator's key):
1. a report sent on demand (an automation calls the service after start);
2. the entities check reports a sensor that is unavailable on purpose;
3. the daily heartbeat arrives, carrying the integration's version;
4. Home Assistant killed with SIGKILL and started again reports an unclean
   shutdown (host_health);
5. Home Assistant's log holds no error from the integration and no
   "Detected blocking call".

Everything lives under .stand/ (ignored by git); the chain binaries are kept
there between runs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from robonomicsinterface import Keypair, RobonomicsClient, decrypt_package

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "custom_components" / "robonomics_report_service"
WORK = ROOT / ".stand"

# The library release the integration pins; its dev chain script is used.
LIBRARY_TAG = "v3.0.0rc2"
LIBRARY_REPO = "https://github.com/airalab/robonomics-interface.git"

CHAIN_PORT = 19944
PINATA_PORT = 18080

# Public test mnemonics, the same as tests/conftest.py: not real sites.
SITE_SEED = "frozen woman pet meat entire question balcony wing echo excess adjust sleep"
RECIPIENT_SEED = "lens exchange drum inside current bullet include stamp purity decline absurd play"
SUDO = Keypair.from_uri("//Alice")  # the dev chain's sudo key
OWNER = Keypair.from_uri("//Bob")  # endowed on the dev chain: the subscription owner
XRT = 10**9

PROBE_ENTITY = "sensor.stand_probe"


def log(message: str) -> None:
    print(f"[stand {time.strftime('%H:%M:%S')}] {message}", flush=True)


# Processes


@dataclass
class Processes:
    running: list[tuple[str, subprocess.Popen]] = field(default_factory=list)

    def start(self, name: str, args: list[str], logfile: Path, **kwargs) -> subprocess.Popen:
        out = open(logfile, "ab")  # noqa: SIM115 - kept open for the process
        process = subprocess.Popen(
            args, stdout=out, stderr=subprocess.STDOUT, start_new_session=True, **kwargs
        )
        self.running.append((name, process))
        return process

    def stop(self, process: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
        if process.poll() is None:
            os.killpg(process.pid, sig)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def stop_all(self) -> None:
        for name, process in reversed(self.running):
            # The stand's Home Assistant is thrown away; a graceful stop only
            # risks a crash in Python's own shutdown, which macOS reports with
            # a "Python quit unexpectedly" dialog.
            self.stop(process, signal.SIGKILL if name == "home-assistant" else signal.SIGTERM)


def wait_for_port(port: int, timeout: float, process: subprocess.Popen, name: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} exited with {process.returncode}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise RuntimeError(f"{name} did not open port {port} in {timeout:.0f} s")


# The chain


def library_dir() -> Path:
    """robonomics-interface for its dev chain script: given, next door, or cloned."""

    given = os.environ.get("ROBONOMICS_INTERFACE_DIR")
    if given:
        return Path(given)
    neighbour = ROOT.parent / "robonomics-interface"
    if (neighbour / "scripts" / "devchain.sh").is_file():
        return neighbour
    clone = WORK / f"robonomics-interface-{LIBRARY_TAG}"
    if not clone.is_dir():
        log(f"cloning robonomics-interface {LIBRARY_TAG}")
        subprocess.run(
            ["git", "clone", "-q", "--depth", "1", "--branch", LIBRARY_TAG, LIBRARY_REPO, clone],
            check=True,
        )
    return clone


async def prepare_chain(client: RobonomicsClient, site: Keypair) -> None:
    """Fund the site, give the owner a subscription, put the site in it."""

    await client.balances.transfer_keep_alive(SUDO, site, 10 * XRT)
    set_oracle = await client.compose_call("RWS", "set_oracle", {"new": {"Id": SUDO.address}})
    await client.submit(await client.compose_call("Sudo", "sudo", {"call": set_oracle}), SUDO)
    subscription = await client.compose_call(
        "RWS",
        "set_subscription",
        {"target": OWNER.address, "subscription": {"Lifetime": {"tps": 10**9}}},
    )
    await client.submit(subscription, SUDO)
    await client.rws.set_devices(OWNER, [site])
    assert await client.rws.devices(OWNER) == [site.address]


# Home Assistant


CONFIGURATION = """\
homeassistant:
  name: Report Service stand
  time_zone: UTC
  unit_system: metric
  latitude: 34.7
  longitude: 33.0
  elevation: 0

recorder:
  commit_interval: 1

logger:
  default: warning

template:
  - sensor:
      - name: Stand probe
        unique_id: stand_probe
        state: "1"
        # Unavailable on purpose: the entities check must report it.
        availability: "{{ false }}"

automation:
  - alias: Stand report on demand
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      - delay: "00:00:20"
      - action: robonomics_report_service.send_problem_report
        data:
          type: installation_check
          summary: report on demand from the test stand
"""


def write_config(config: Path, site: Keypair, recipient: Keypair) -> None:
    """A clean configuration with the integration installed, as the setup form leaves it."""

    if config.exists():
        shutil.rmtree(config)
    storage = config / ".storage"
    storage.mkdir(parents=True)
    (config / "custom_components").mkdir()
    (config / "custom_components" / COMPONENT.name).symlink_to(COMPONENT)
    (config / "configuration.yaml").write_text(CONFIGURATION)

    # Version 1.1 of the store: Home Assistant fills in the newer fields itself.
    entries = {
        "version": 1,
        "minor_version": 1,
        "key": "core.config_entries",
        "data": {
            "entries": [
                {
                    "entry_id": "01STANDREPORTSERVICE000000",
                    "version": 1,
                    "domain": COMPONENT.name,
                    "title": "Robonomics Report Service",
                    "data": {"creds_configured": True},
                    "source": "user",
                    "unique_id": COMPONENT.name,
                }
            ]
        },
    }
    (storage / "core.config_entries").write_text(json.dumps(entries))

    # HTTP on localhost only, stored as already confirmed: from YAML it would be
    # a trial that Home Assistant reverts, restarting, after 5 minutes.
    http = {
        "server_host": ["127.0.0.1"],
        "server_port": 18123,
        "cors_allowed_origins": ["https://cast.home-assistant.io"],
        "login_attempts_threshold": -1,
        "ip_ban_enabled": True,
        "ssl_profile": "modern",
        "use_x_frame_options": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "error": None,
        "error_message": None,
    }
    (storage / "http").write_text(
        json.dumps(
            {
                "version": 2,
                "minor_version": 2,
                "key": "http",
                "data": {"stable": http, "pending": None, "yaml_migration_done": True},
            }
        )
    )

    creds = {
        "version": 6,
        "minor_version": 1,
        "key": f"{COMPONENT.name}.creds_storage",
        "data": {
            "problem_service_robonomics_address": recipient.address,
            "pinata_public": "stand-public",
            "pinata_secret": "stand-secret",
            "subscription_owner_robonomics_address": OWNER.address,
            "network": "polkadot",
            "sender_seed": SITE_SEED,
        },
    }
    (storage / f"{COMPONENT.name}.creds_storage").write_text(json.dumps(creds))


def start_home_assistant(procs: Processes, config: Path, logfile: Path) -> subprocess.Popen:
    env = dict(
        os.environ,
        RRS_STAND_ROBONOMICS_ENDPOINT=f"ws://127.0.0.1:{CHAIN_PORT}",
        RRS_STAND_PINATA_API=f"http://127.0.0.1:{PINATA_PORT}/",
    )
    # --skip-pip: the integration's requirements are installed in this
    # environment already (pyproject.toml mirrors manifest.json).
    return procs.start(
        "home-assistant",
        [sys.executable, "-m", "homeassistant", "--config", str(config), "--skip-pip"],
        logfile,
        env=env,
    )


# Reading what arrived


@dataclass
class Arrivals:
    seen: int = 0
    heartbeats: list[dict] = field(default_factory=list)
    issues: list[dict] = field(default_factory=list)

    def of_type(self, kind: str) -> list[dict]:
        return [issue for issue in self.issues if issue.get("type") == kind]


def open_report(cid: str, pinata_dir: Path, site: Keypair, recipient: Keypair) -> dict | None:
    """The issue of a report, decrypted as the connector does it."""

    with zipfile.ZipFile(BytesIO((pinata_dir / cid).read_bytes())) as archive:
        for name in archive.namelist():
            opened = json.loads(decrypt_package(archive.read(name), recipient, site.address))
            if opened["meta"]["orig_file_name"] == "issue_description.json":
                return json.loads(opened["payload"])
    return None


async def read_new(
    client: RobonomicsClient,
    arrivals: Arrivals,
    pinata_dir: Path,
    site: Keypair,
    recipient: Keypair,
) -> None:
    items = await client.datalog.items(site)
    for item in items[arrivals.seen :]:
        text = item.data.decode()
        if text.startswith("{"):
            payload = json.loads(text)
            if payload.get("t") == "hb":
                arrivals.heartbeats.append(payload)
                log(f"heartbeat: {payload}")
            continue
        issue = open_report(text, pinata_dir, site, recipient)
        if issue is not None:
            arrivals.issues.append(issue)
            log(f"report {text}: {issue.get('type')} — {issue.get('summary')}")
    arrivals.seen = len(items)


async def wait_until(what: str, timeout: float, check, poll) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await poll()
        if check():
            log(f"ok: {what}")
            return True
        await asyncio.sleep(3)
    log(f"FAILED: {what} (nothing in {timeout:.0f} s)")
    return False


def in_recovery_mode(logfile: Path) -> bool:
    """Recovery mode loads no integration: nothing would arrive, say why at once."""

    # Going into recovery mode restarts Home Assistant, which rotates the log.
    for path in (logfile, logfile.with_name(logfile.name + ".1")):
        if path.is_file() and "Activating recovery mode" in path.read_text(errors="replace"):
            return True
    return False


def log_problems(logfile: Path) -> list[str]:
    if not logfile.is_file():
        return [f"{logfile} is missing"]
    problems = []
    for line in logfile.read_text(errors="replace").splitlines():
        if "Detected blocking call" in line:
            problems.append(line)
        elif "ERROR" in line and COMPONENT.name in line:
            problems.append(line)
    return problems


# The run


async def run(args: argparse.Namespace) -> bool:
    WORK.mkdir(exist_ok=True)
    run_dir = WORK / "run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir()
    pinata_dir, config = run_dir / "pinata", run_dir / "config"

    site, recipient = Keypair.from_secret(SITE_SEED), Keypair.from_secret(RECIPIENT_SEED)
    procs = Processes()
    results: dict[str, bool] = {}
    try:
        library = library_dir()
        log(f"dev chain from {library}")
        chain = procs.start(
            "chain",
            ["bash", "scripts/devchain.sh"],
            run_dir / "chain.log",
            cwd=library,
            env=dict(os.environ, PORT=str(CHAIN_PORT), DEVCHAIN_DIR=str(WORK / "devchain")),
        )
        pinata = procs.start(
            "pinata",
            [
                sys.executable,
                str(ROOT / "stand" / "fake_pinata.py"),
                "--port",
                str(PINATA_PORT),
                "--dir",
                str(pinata_dir),
            ],
            run_dir / "pinata.log",
        )
        wait_for_port(PINATA_PORT, 30, pinata, "fake Pinata")
        wait_for_port(CHAIN_PORT, 600, chain, "dev chain")

        async with RobonomicsClient(
            f"ws://127.0.0.1:{CHAIN_PORT}", genesis_hash=None, require_healthy=False
        ) as client:
            await prepare_chain(client, site)
            log(f"site {site.address} is in the subscription of {OWNER.address}")

            write_config(config, site, recipient)
            ha_log = run_dir / "home-assistant.out"
            started = time.monotonic()
            ha = start_home_assistant(procs, config, ha_log)
            log("Home Assistant started")

            arrivals = Arrivals()

            async def poll() -> None:
                if ha.poll() is not None:
                    raise RuntimeError(f"Home Assistant exited with {ha.returncode}")
                if in_recovery_mode(config / "home-assistant.log"):
                    raise RuntimeError("Home Assistant started in recovery mode")
                await read_new(client, arrivals, pinata_dir, site, recipient)

            results["report on demand"] = await wait_until(
                "a report on demand arrived and decrypts",
                240,
                lambda: bool(arrivals.of_type("installation_check")),
                poll,
            )
            # The first entities check runs two minutes after start.
            results["unavailable entity"] = await wait_until(
                f"the entities check reported {PROBE_ENTITY}",
                max(60.0, 300 - (time.monotonic() - started)),
                lambda: any(
                    PROBE_ENTITY in json.dumps(i["details"])
                    for i in arrivals.of_type("entities_health_problems")
                ),
                poll,
            )
            if not args.skip_heartbeat:
                version = json.loads((COMPONENT / "manifest.json").read_text())["version"]
                results["heartbeat"] = await wait_until(
                    f"the heartbeat arrived with version {version}",
                    max(60.0, 420 - (time.monotonic() - started)),
                    lambda: any(b.get("v") == version for b in arrivals.heartbeats),
                    poll,
                )

            log("killing Home Assistant with SIGKILL")
            procs.stop(ha, signal.SIGKILL)
            ha = start_home_assistant(procs, config, ha_log)
            log("Home Assistant started again")
            results["unclean shutdown"] = await wait_until(
                "the unclean shutdown was reported",
                240,
                lambda: any("shutdown" in i["details"] for i in arrivals.of_type("host_health")),
                poll,
            )

        problems = log_problems(config / "home-assistant.log")
        for line in problems[:20]:
            log(f"log: {line}")
        results["clean log"] = not problems
    except Exception as e:  # noqa: BLE001 - reported, then the stand stops
        log(f"stand failed: {e!r}")
        results["stand ran"] = False
    finally:
        procs.stop_all()

    log("results:")
    for name, ok in results.items():
        log(f"  {'ok    ' if ok else 'FAILED'} {name}")
    if not all(results.values()):
        log(f"logs are in {run_dir}")
    return bool(results) and all(results.values())


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Report Service test stand.")
    parser.add_argument(
        "--skip-heartbeat", action="store_true", help="do not wait 5 min for the first heartbeat"
    )
    sys.exit(0 if asyncio.run(run(parser.parse_args())) else 1)


if __name__ == "__main__":
    main()
