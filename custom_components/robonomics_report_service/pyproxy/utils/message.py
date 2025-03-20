import typing as tp
import json


def format_msg_from_libp2p(message: dict) -> tp.Union[str, dict]:
    data = message["data"]
    return data


def format_msg_to_libp2p(data: str, protocol: str, server_peer_id: str, save_data: bool) -> str:
    try:
        json_obj = json.loads(data)
        message = {
            "protocol": protocol,
            "serverPeerId": server_peer_id,
            "save_data": save_data,
            "data": {"data": json_obj},
        }
    except json.decoder.JSONDecodeError:
        message = {"protocol": protocol, "serverPeerId": server_peer_id, "save_data": save_data, "data": {"data": data}}
    return json.dumps(message)


def format_msg_for_subscribing(protocols: list) -> str:
    msg = {"protocols_to_listen": protocols}
    return json.dumps(msg)

class InitialMessage:
    def __init__(self, msg: str):
        self._parse_msg(msg)

    def _parse_msg(self, msg):
        self.peer_id = msg["peerId"]
        self.multi_addressess = msg["multiAddresses"]