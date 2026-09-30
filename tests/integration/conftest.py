"""A clean Home Assistant with the integration installed, and the outside faked.

These tests run a real Home Assistant core (pytest-homeassistant-custom-component,
pinned to one HA release) and install the integration the way a person does:
through its setup form. Everything inside Home Assistant is real — the
recorder, the storage, the watchers, the report service, encryption, the
archive, the publishing queue. Only what lies outside is replaced:

- the chain: `FakeChain` takes the records a real node would put in a block;
- Pinata: `FakePinata` keeps the uploaded archives in memory, and the key
  check is answered by `aioclient_mock`.

A report can then be opened the way the connector opens it: find the CID in
the datalog, take the archive from "Pinata", decrypt it with the recipient's
key.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any

import pytest

pytest.importorskip(
    "pytest_homeassistant_custom_component",
    reason="needs a Home Assistant test harness: scripts/test-ha.sh",
)

from homeassistant import config_entries  # noqa: E402
from homeassistant.core import HomeAssistant  # noqa: E402
from homeassistant.data_entry_flow import FlowResultType  # noqa: E402
from robonomicsinterface import DatalogItem, Keypair, decrypt_package  # noqa: E402

from custom_components.robonomics_report_service import ipfs, robonomics  # noqa: E402
from custom_components.robonomics_report_service.const import DOMAIN  # noqa: E402

from ..conftest import RECIPIENT_SEED, SENDER_SEED  # noqa: E402

PINATA_PUBLIC = "test-public-key"
PINATA_SECRET = "test-secret-key"


@dataclass
class FakeChain:
    """What a node would put in blocks: every datalog record, in order."""

    records: list[tuple[str, str, str | None]] = field(default_factory=list)

    @property
    def datalog(self) -> FakeChain:
        return self

    async def record(
        self, keypair: Keypair, data: bytes | str, *, subscription_owner=None, **_: Any
    ) -> None:
        text = data.decode() if isinstance(data, bytes) else data
        self.records.append((keypair.address, text, subscription_owner))

    async def items(self, address: str, *, at: str | None = None) -> list[DatalogItem]:
        now_ms = int(time.time() * 1000)
        return [
            DatalogItem(index=i, timestamp_ms=now_ms, data=text.encode())
            for i, (sender, text, _) in enumerate(self.records)
            if sender == address
        ]

    async def close(self) -> None:
        pass

    def texts(self) -> list[str]:
        return [text for _, text, _ in self.records]

    def heartbeats(self) -> list[dict[str, Any]]:
        found = []
        for text in self.texts():
            try:
                payload = json.loads(text)
            except ValueError:
                continue
            if isinstance(payload, dict) and payload.get("t") == "hb":
                found.append(payload)
        return found

    def report_cids(self) -> list[str]:
        return [text for text in self.texts() if text.startswith("Qm")]


@dataclass
class FakePinata:
    """Pinata's pinning API as the integration uses it, kept in memory."""

    files: dict[str, bytes] = field(default_factory=dict)
    unpinned: list[str] = field(default_factory=list)

    def client(self, public: str, secret: str) -> FakePinata:
        assert (public, secret) == (PINATA_PUBLIC, PINATA_SECRET)
        return self

    def pin_file_to_ipfs(self, path: str, save_absolute_paths: bool = True) -> dict:
        with open(path, "rb") as file:
            data = file.read()
        cid = "Qm" + hashlib.sha256(data).hexdigest()[:44]
        self.files[cid] = data
        return {"IpfsHash": cid}

    def remove_pin_from_ipfs(self, cid: str) -> dict:
        self.unpinned.append(cid)
        self.files.pop(cid, None)
        return {"message": "OK"}


@dataclass
class OpenedReport:
    """A report as the connector sees it after decryption."""

    files: dict[str, str]

    @property
    def issue(self) -> dict[str, Any] | None:
        text = self.files.get("issue_description.json")
        return json.loads(text) if text is not None else None


def open_report(pinata: FakePinata, cid: str) -> OpenedReport:
    """Decrypt every file of an archive with the recipient's key."""

    sender = Keypair.from_secret(SENDER_SEED)
    recipient = Keypair.from_secret(RECIPIENT_SEED)
    files = {}
    with zipfile.ZipFile(io.BytesIO(pinata.files[cid])) as archive:
        for name in archive.namelist():
            opened = json.loads(decrypt_package(archive.read(name), recipient, sender.address))
            # The file's own name travels encrypted, next to its content.
            files[opened["meta"]["orig_file_name"]] = opened["payload"]
    return OpenedReport(files)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Load the integration from this repository, on a real recorder.

    The integration depends on the recorder; `recorder_mock` is the real one
    on an in-memory SQLite database. It has to come before `hass`.
    """

    yield


@pytest.fixture(autouse=True)
def no_real_wait_for_entities(monkeypatch):
    """The first entities check waits 15 s of real time for entities to load."""

    from custom_components.robonomics_report_service.error_watchers.watchers import (
        entities_checker,
    )

    real_sleep = entities_checker.asyncio.sleep

    async def sleep(seconds, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(entities_checker.asyncio, "sleep", sleep)


@pytest.fixture(name="chain")
def fixture_chain(monkeypatch) -> FakeChain:
    chain = FakeChain()
    monkeypatch.setattr(robonomics, "RobonomicsClient", lambda *args, **kwargs: chain)
    return chain


@pytest.fixture(name="pinata")
def fixture_pinata(monkeypatch, aioclient_mock) -> FakePinata:
    pinata = FakePinata()
    monkeypatch.setattr(ipfs, "PinataPy", pinata.client)
    aioclient_mock.get(ipfs.PINATA_TEST_AUTHENTICATION_URL, json={"message": "ok"})
    return pinata


async def install(hass: HomeAssistant, seed: str = SENDER_SEED) -> config_entries.ConfigEntry:
    """Go through the setup form as a person does."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "problem_service_robonomics_address": Keypair.from_secret(RECIPIENT_SEED).address,
            "pinata_public": PINATA_PUBLIC,
            "pinata_secret": PINATA_SECRET,
        },
    )
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "seed"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"sender_seed": seed}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


@pytest.fixture(name="installed")
async def fixture_installed(hass: HomeAssistant, chain: FakeChain, pinata: FakePinata):
    """The integration installed and running; removed again after the test."""

    entry = await install(hass)
    assert entry.state is config_entries.ConfigEntryState.LOADED
    yield entry
    if entry.state is config_entries.ConfigEntryState.LOADED:
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
