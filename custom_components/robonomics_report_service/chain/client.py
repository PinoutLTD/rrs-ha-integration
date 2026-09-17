"""Publishing a report to the chain: compose, sign, submit, confirm.

Inclusion in a block is not success: an extrinsic can be included and still
fail, which is what happens when a site publishes without a live subscription.
So the events of that block are read back and the result is checked.
"""

import asyncio
import logging

import aiohttp
from scalecodec.base import ScaleBytes

from .extrinsic import ExtrinsicBuilder, RuntimeInfo
from .keys import ROBONOMICS_SS58_FORMAT, Keypair
from .rpc import RobonomicsRpc, RpcError
from .storage import EVENTS_ITEM, EVENTS_PALLET, events_key

LOGGER = logging.getLogger(__name__)

EXTRINSIC_FAILED_EVENT = "ExtrinsicFailed"
EXTRINSIC_SUCCESS_EVENT = "ExtrinsicSuccess"


# Order of sp_runtime::transaction_validity::InvalidTransaction.
INVALID_TRANSACTION = (
    "Call",
    "Payment",
    "Future",
    "Stale",
    "BadProof",
    "AncientBirthBlock",
    "ExhaustsResources",
    "Custom",
    "BadMandatory",
    "MandatoryValidation",
    "BadSigner",
    "IndeterminateImplicit",
    "UnknownOrigin",
)

INVALID_EXPLANATIONS = {
    "Payment": (
        "the sending account does not exist on chain. RWS calls are free, but an "
        "account with a zero balance cannot sign anything: send it the "
        "existential deposit (0.000001 XRT) once"
    ),
    "Future": "the nonce is ahead of the account; another submission is pending",
    "Stale": "the nonce was already used; the same record was probably sent twice",
    "BadProof": "the signature does not verify; the runtime may have been upgraded",
    "AncientBirthBlock": "the transaction refers to a block the chain has forgotten",
    "ExhaustsResources": "the block is full; try again later",
}


def transaction_invalidity(raw: bytes) -> str | None:
    """Why the runtime would reject a transaction, or None if it is valid.

    `raw` is a SCALE-encoded TransactionValidity, as returned by
    TaggedTransactionQueue_validate_transaction.
    """

    if not raw or raw[0] == 0:
        return None
    if len(raw) >= 3 and raw[1] == 0:
        index = raw[2]
        name = INVALID_TRANSACTION[index] if index < len(INVALID_TRANSACTION) else str(index)
        if name == "Custom" and len(raw) >= 4:
            return f"Custom({raw[3]}): rejected by the runtime"
        return f"{name}: {INVALID_EXPLANATIONS.get(name, 'rejected by the runtime')}"
    if len(raw) >= 3 and raw[1] == 1:
        return f"Unknown({raw[2]}): the runtime could not validate the transaction"
    return "the runtime returned an unreadable validity"


def extrinsic_failure(records: list[dict], index: int) -> str | None:
    """Why the chain rejected our extrinsic, or None when it succeeded.

    Inclusion in a block says nothing about the call itself: a site without a
    live subscription gets its extrinsic included and refused.
    """

    ours = [
        record
        for record in records
        if record.get("extrinsic_idx") == index and record.get("module_id") == EVENTS_PALLET
    ]

    for record in ours:
        if record.get("event_id") == EXTRINSIC_FAILED_EVENT:
            return str(record.get("attributes"))

    if any(record.get("event_id") == EXTRINSIC_SUCCESS_EVENT for record in ours):
        return None
    # Neither outcome recorded: better to say so than to report success.
    return "the block holds no result for this extrinsic"


class ChainError(RuntimeError):
    pass


class ExtrinsicFailedError(ChainError):
    """The extrinsic reached a block and the chain rejected what it asked for."""


class RobonomicsClient:
    """Talks to one node; the caller decides when to move to another."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        url: str,
        timeout_seconds: int = 30,
        ss58_format: int = ROBONOMICS_SS58_FORMAT,
    ) -> None:
        self.session = session
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.ss58_format = ss58_format
        self._builder: ExtrinsicBuilder | None = None
        self._spec_version: int | None = None

    async def _runtime_info(self, rpc: RobonomicsRpc) -> RuntimeInfo:
        version = await rpc.request("state_getRuntimeVersion", [])
        return RuntimeInfo(
            metadata_hex=await rpc.request("state_getMetadata", []),
            spec_version=version["specVersion"],
            transaction_version=version["transactionVersion"],
            genesis_hash=await rpc.request("chain_getBlockHash", [0]),
        )

    async def _builder_for(self, rpc: RobonomicsRpc) -> ExtrinsicBuilder:
        """Parsing metadata is slow, so keep it until the runtime changes."""

        version = await rpc.request("state_getRuntimeVersion", [])
        if self._builder is None or self._spec_version != version["specVersion"]:
            LOGGER.debug("Loading runtime metadata for spec %s", version["specVersion"])
            runtime = await self._runtime_info(rpc)
            # Parsing metadata reads type registry files and takes seconds on a
            # Raspberry Pi: never on the event loop.
            self._builder = await asyncio.to_thread(ExtrinsicBuilder, runtime, self.ss58_format)
            self._spec_version = version["specVersion"]
        return self._builder

    async def _ensure_valid(self, rpc: RobonomicsRpc, extrinsic: str) -> None:
        """Ask the runtime whether it would accept the extrinsic, before sending.

        This is the check the transaction pool runs, reached through state_call,
        which public nodes allow. A rejected submission only says "Invalid
        Transaction"; this says why.
        """

        head = await rpc.request("chain_getFinalizedHead", [])
        # (TransactionSource::External, the extrinsic, the block to check at)
        data = "0x02" + extrinsic.removeprefix("0x") + head.removeprefix("0x")
        result = await rpc.request(
            "state_call", ["TaggedTransactionQueue_validate_transaction", data, head]
        )
        reason = transaction_invalidity(bytes.fromhex(result.removeprefix("0x")))
        if reason is not None:
            raise ExtrinsicFailedError(f"the chain would reject it — {reason}")

    async def record_datalog(
        self,
        keypair: Keypair,
        record: str,
        subscription_owner: str | None = None,
    ) -> str:
        """Publish one record; returns the hash of the block that holds it."""

        async with RobonomicsRpc(self.session, self.url, self.timeout_seconds) as rpc:
            builder = await self._builder_for(rpc)
            nonce = await rpc.request("system_accountNextIndex", [keypair.ss58_address])
            call = builder.record_datalog(record, subscription_owner)
            extrinsic = builder.create_signed_extrinsic(call, keypair, int(nonce))

            await self._ensure_valid(rpc, extrinsic)
            block_hash = await rpc.submit_and_watch(extrinsic)
            await self._check_result(rpc, builder, block_hash, extrinsic)
            return block_hash

    async def _check_result(
        self,
        rpc: RobonomicsRpc,
        builder: ExtrinsicBuilder,
        block_hash: str,
        extrinsic: str,
    ) -> None:
        index = await self._extrinsic_index(rpc, block_hash, extrinsic)
        if index is None:
            raise ChainError("the extrinsic is not in the block the node named")

        raw_events = await rpc.request("state_getStorage", [events_key(), block_hash])
        if raw_events is None:
            raise ChainError("the block carries no events to check the result with")

        events = builder.config.create_scale_object(
            builder.storage_value_type(EVENTS_PALLET, EVENTS_ITEM),
            metadata=builder.metadata,
            data=ScaleBytes(raw_events),
        )
        events.decode()

        failure = extrinsic_failure(events.value, index)
        if failure is not None:
            raise ExtrinsicFailedError(f"the chain rejected the call: {failure}")

    async def _extrinsic_index(
        self, rpc: RobonomicsRpc, block_hash: str, extrinsic: str
    ) -> int | None:
        block = await rpc.request("chain_getBlock", [block_hash])
        try:
            extrinsics = block["block"]["extrinsics"]
        except (TypeError, KeyError) as e:
            raise ChainError("the node returned a block without extrinsics") from e
        for index, included in enumerate(extrinsics):
            if included == extrinsic:
                return index
        return None


__all__ = [
    "ChainError",
    "ExtrinsicFailedError",
    "RobonomicsClient",
    "RpcError",
    "extrinsic_failure",
    "transaction_invalidity",
]
