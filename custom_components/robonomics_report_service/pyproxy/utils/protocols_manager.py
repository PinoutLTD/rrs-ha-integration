from dataclasses import dataclass, field
import typing as tp


@dataclass
class ProtocolsManager:
    protocols: tp.Dict[str, tp.Dict[tp.Callable, str]] = field(default_factory=dict)

    def add_protocol(self, protocol, callback):
        self.protocols[protocol] = callback

    def remove_protocol(self, protocol):
        self.protocols.pop(protocol, None)

    def get_protocols(self) -> list:
        return list(self.protocols.keys())

    def remove_all_protocols(self):
        self.protocols = {}


@dataclass
class Callback:
    callback_function: tp.Callable
    callback_type: str


class CallbackTypes:
    AsyncType = "async"
    SyncType = "sync"
