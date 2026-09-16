"""Publishing a report to the chain: compose, sign, submit, confirm.

Inclusion in a block is not success: an extrinsic can be included and still
fail, which is what happens when a site publishes without a live subscription.
So the events of that block are read back and the result is checked.
"""

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


def extrinsic_failure(records: list[dict], index: int) -> str | None:
    """Why the chain rejected our extrinsic, or None when it succeeded.

    Inclusion in a block says nothing about the call itself: a site without a
    live subscription gets its extrinsic included and refused.
    """

    ours = [
        record
        for record in records
        if record.get("extrinsic_idx") == index
        and record.get("module_id") == EVENTS_PALLET
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
            self._builder = ExtrinsicBuilder(
                await self._runtime_info(rpc), self.ss58_format
            )
            self._spec_version = version["specVersion"]
        return self._builder

    async def record_datalog(
        self,
        keypair: Keypair,
        record: str,
        subscription_owner: str | None = None,
    ) -> str:
        """Publish one record; returns the hash of the block that holds it."""

        async with RobonomicsRpc(self.session, self.url, self.timeout_seconds) as rpc:
            builder = await self._builder_for(rpc)
            nonce = await rpc.request(
                "system_accountNextIndex", [keypair.ss58_address]
            )
            call = builder.record_datalog(record, subscription_owner)
            extrinsic = builder.create_signed_extrinsic(call, keypair, int(nonce))

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
]
