"""The extrinsic must be byte-identical to what substrate-interface produced.

ed25519 signatures are deterministic, so "same call, same nonce, same key"
has exactly one correct answer. `tests/fixtures/extrinsic_vectors.json` holds
that answer, taken from the live Robonomics runtime through the stack we are
replacing, and `metadata.hex.gz` is the runtime metadata it was built against.
"""

import gzip
import json
from pathlib import Path

import pytest
from chain import Keypair
from chain.extrinsic import (
    MAX_UNHASHED_PAYLOAD_BYTES,
    ExtrinsicBuilder,
    RuntimeInfo,
)

FIXTURES = Path(__file__).parent / "fixtures"
VECTORS = json.loads((FIXTURES / "extrinsic_vectors.json").read_text("utf-8"))


@pytest.fixture(scope="module")
def runtime() -> RuntimeInfo:
    with gzip.open(FIXTURES / "metadata.hex.gz", "rt") as file:
        metadata_hex = file.read().strip()
    return RuntimeInfo(
        metadata_hex=metadata_hex,
        spec_version=VECTORS["spec_version"],
        transaction_version=VECTORS["transaction_version"],
        genesis_hash=VECTORS["genesis_hash"],
    )


@pytest.fixture(scope="module")
def builder(runtime: RuntimeInfo) -> ExtrinsicBuilder:
    return ExtrinsicBuilder(runtime)


@pytest.fixture(scope="module")
def keypair() -> Keypair:
    return Keypair.create_from_secret(VECTORS["mnemonic"])


def calls(builder: ExtrinsicBuilder) -> dict:
    return {
        "datalog_record": builder.record_datalog(VECTORS["cid"]),
        "rws_call": builder.record_datalog(
            VECTORS["cid"], VECTORS["subscription_owner"]
        ),
    }


@pytest.mark.parametrize("name", ["datalog_record", "rws_call"])
def test_call_bytes_match(builder, name: str) -> None:
    assert calls(builder)[name].data.to_hex() == VECTORS["calls"][name]


@pytest.mark.parametrize("vector", VECTORS["extrinsics"], ids=lambda v: v["call"])
def test_signed_extrinsic_matches_byte_for_byte(builder, keypair, vector) -> None:
    call = calls(builder)[vector["call"]]

    signed = builder.create_signed_extrinsic(call, keypair, nonce=vector["nonce"])

    assert signed == vector["hex"]


def test_report_payload_is_short_enough_to_sign_as_is(builder, keypair) -> None:
    # A report carries a CID, so its payload stays well under the limit and is
    # signed directly; the byte comparison above covers that path.
    call = calls(builder)["rws_call"]

    payload = builder.signature_payload(call, nonce=7)

    assert 0 < len(payload) <= MAX_UNHASHED_PAYLOAD_BYTES
    assert keypair.verify(payload, keypair.sign(payload))


def test_long_payload_is_signed_as_a_hash(builder, keypair) -> None:
    """Substrate hashes anything past 256 bytes; so must we."""

    call = builder.record_datalog("x" * 400, VECTORS["subscription_owner"])

    payload = builder.signature_payload(call, nonce=7)

    assert len(payload) == 32
    assert keypair.verify(payload, keypair.sign(payload))


def test_wrapping_in_a_subscription_changes_the_call(builder) -> None:
    plain = calls(builder)["datalog_record"]
    wrapped = calls(builder)["rws_call"]

    assert plain.value["call_module"] == "Datalog"
    assert wrapped.value["call_module"] == "RWS"
    assert wrapped.data.to_hex() != plain.data.to_hex()


def test_nonce_changes_the_signature(builder, keypair) -> None:
    call = calls(builder)["rws_call"]

    assert builder.create_signed_extrinsic(
        call, keypair, nonce=7
    ) != builder.create_signed_extrinsic(call, keypair, nonce=8)


def test_unknown_call_is_refused(builder) -> None:
    # Pallet names come from the metadata; a typo must not encode silently.
    with pytest.raises(ValueError, match="NoSuchPallet"):
        builder.compose_call("NoSuchPallet", "record", {"record": "x"})


def test_payload_limit_is_the_substrate_one() -> None:
    assert MAX_UNHASHED_PAYLOAD_BYTES == 256
