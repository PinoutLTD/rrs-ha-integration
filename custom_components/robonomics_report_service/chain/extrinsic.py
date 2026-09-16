"""Building and signing the one extrinsic this integration sends.

A report is published as `Datalog.record(cid)`, wrapped in `RWS.call` when the
site publishes under an integrator's subscription. The encoding follows the
chain's own metadata rather than hard-coded indices, because a runtime upgrade
renumbers pallets.

The bytes are checked against substrate-interface in the tests: ed25519
signatures are deterministic, so "the same call, the same nonce, the same key"
must give the same extrinsic, byte for byte.
"""

from dataclasses import dataclass
from hashlib import blake2b

from scalecodec.base import RuntimeConfigurationObject, ScaleBytes
from scalecodec.type_registry import load_type_registry_preset

from .keys import ED25519, ROBONOMICS_SS58_FORMAT, Keypair

SUPPORTED_EXTRINSIC_VERSION = 4
# Longer payloads are signed as a hash, as every Substrate client does.
MAX_UNHASHED_PAYLOAD_BYTES = 256
IMMORTAL_ERA = "00"

# Which signed extensions contribute to the payload, and under which name.
# The chain lists them in its metadata; anything it does not list is skipped.
PAYLOAD_FIELDS = (
    ("CheckMortality", "era", "extrinsic"),
    ("CheckEra", "era", "extrinsic"),
    ("CheckNonce", "nonce", "extrinsic"),
    ("ChargeTransactionPayment", "tip", "extrinsic"),
    ("ChargeAssetTxPayment", "asset_id", "extrinsic"),
    ("CheckMetadataHash", "mode", "extrinsic"),
    ("CheckSpecVersion", "spec_version", "additional_signed"),
    ("CheckTxVersion", "transaction_version", "additional_signed"),
    ("CheckGenesis", "genesis_hash", "additional_signed"),
    ("CheckMortality", "block_hash", "additional_signed"),
    ("CheckEra", "block_hash", "additional_signed"),
    ("CheckMetadataHash", "metadata_hash", "additional_signed"),
)


class ExtrinsicError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeInfo:
    """What must be known about the chain before anything can be signed."""

    metadata_hex: str
    spec_version: int
    transaction_version: int
    genesis_hash: str


class ExtrinsicBuilder:
    """Composes calls and signs them against one runtime version."""

    def __init__(
        self, runtime: RuntimeInfo, ss58_format: int = ROBONOMICS_SS58_FORMAT
    ) -> None:
        self.runtime = runtime
        self.config = RuntimeConfigurationObject(
            ss58_format=ss58_format, implements_scale_info=True
        )
        self.config.update_type_registry(load_type_registry_preset(name="core"))

        self.metadata = self.config.create_scale_object(
            "MetadataVersioned", data=ScaleBytes(runtime.metadata_hex)
        )
        self.metadata.decode()
        self.config.add_portable_registry(self.metadata)
        self.config.set_active_spec_version_id(runtime.spec_version)

        version = self.metadata[1][1]["extrinsic"]["version"].value
        if version != SUPPORTED_EXTRINSIC_VERSION:
            raise ExtrinsicError(f"extrinsic version {version} is not supported")

    def compose_call(self, module: str, function: str, args: dict):
        call = self.config.create_scale_object("Call", metadata=self.metadata)
        call.encode(
            {"call_module": module, "call_function": function, "call_args": args}
        )
        return call

    def record_datalog(self, record: str, subscription_owner: str | None = None):
        """`Datalog.record`, wrapped in `RWS.call` when publishing on a subscription."""

        call = self.compose_call("Datalog", "record", {"record": record})
        if subscription_owner is None:
            return call
        return self.compose_call(
            "RWS",
            "call",
            {"subscription_id": subscription_owner, "call": call.value},
        )

    def signature_payload(self, call, nonce: int, tip: int = 0) -> bytes:
        """The bytes actually signed, hashed when they grow past the limit."""

        extensions = self.metadata.get_signed_extensions()
        payload = self.config.create_scale_object("ExtrinsicPayloadValue")
        payload.type_mapping = [["call", "CallBytes"]]
        for name, field, source in PAYLOAD_FIELDS:
            if name in extensions:
                payload.type_mapping.append([field, extensions[name][source]])

        payload.encode(
            {
                "call": str(call.data),
                "era": IMMORTAL_ERA,
                "nonce": nonce,
                "tip": tip,
                "spec_version": self.runtime.spec_version,
                "transaction_version": self.runtime.transaction_version,
                "genesis_hash": self.runtime.genesis_hash,
                # Immortal extrinsics carry the genesis hash here.
                "block_hash": self.runtime.genesis_hash,
                "asset_id": {"tip": tip, "asset_id": None},
                "metadata_hash": None,
                "mode": "Disabled",
            }
        )

        data = bytes(payload.data.data)
        if len(data) > MAX_UNHASHED_PAYLOAD_BYTES:
            return blake2b(data, digest_size=32).digest()
        return data

    def create_signed_extrinsic(
        self, call, keypair: Keypair, nonce: int, tip: int = 0
    ) -> str:
        """Sign a call and return the extrinsic ready for submission, as hex."""

        signature = keypair.sign(self.signature_payload(call, nonce, tip))

        extrinsic = self.config.create_scale_object("Extrinsic", metadata=self.metadata)
        extrinsic.encode(
            {
                "account_id": "0x" + keypair.public_key.hex(),
                "signature": "0x" + signature.hex(),
                "signature_version": ED25519,
                "call_function": call.value["call_function"],
                "call_module": call.value["call_module"],
                "call_args": call.value["call_args"],
                "nonce": nonce,
                "era": IMMORTAL_ERA,
                "tip": tip,
                "asset_id": {"tip": tip, "asset_id": None},
                "mode": "Disabled",
            }
        )
        return extrinsic.data.to_hex()
