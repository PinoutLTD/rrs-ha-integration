"""A fake Pinata for the test stand: the pinning API the integration uses, and a gateway.

    python stand/fake_pinata.py --port 18080 --dir .stand/pinata

- GET  /data/testAuthentication  — any key is valid;
- POST /pinning/pinFileToIPFS    — keeps the file, answers with its CID;
- DELETE /pinning/unpin/<cid>    — forgets it; 404 NOT_PINNED when unknown;
- GET  /ipfs/<cid>               — the file back, as a gateway serves it.

CIDs are real CIDv0 (base58 of the SHA-256 multihash of the bytes), so they
look to anything downstream like the ones Pinata gives. Standard library only.
"""

import argparse
import email.parser
import email.policy
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def cid_v0(data: bytes) -> str:
    multihash = b"\x12\x20" + hashlib.sha256(data).digest()
    number = int.from_bytes(multihash, "big")
    encoded = ""
    while number:
        number, rest = divmod(number, 58)
        encoded = BASE58[rest] + encoded
    return encoded


def multipart_files(content_type: str, body: bytes) -> list[bytes]:
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    return [
        part.get_payload(decode=True)
        for part in message.iter_parts()
        if part.get_filename() is not None
    ]


class Handler(BaseHTTPRequestHandler):
    store: Path

    def _answer(self, status: int, payload: dict | bytes) -> None:
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/octet-stream" if isinstance(payload, bytes) else "application/json",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/data/testAuthentication":
            self._answer(
                200, {"message": "Congratulations! You are communicating with the fake Pinata"}
            )
        elif self.path.startswith("/ipfs/"):
            path = self.store / self.path.removeprefix("/ipfs/").strip("/")
            if path.is_file():
                self._answer(200, path.read_bytes())
            else:
                self._answer(404, {"error": "not found"})
        elif self.path == "/pins":
            self._answer(200, {"pins": sorted(p.name for p in self.store.iterdir())})
        else:
            self._answer(404, {"error": "unknown path"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/pinning/pinFileToIPFS":
            self._answer(404, {"error": "unknown path"})
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        files = multipart_files(self.headers.get("Content-Type", ""), body)
        if len(files) != 1:
            self._answer(400, {"error": f"expected one file, got {len(files)}"})
            return
        cid = cid_v0(files[0])
        (self.store / cid).write_bytes(files[0])
        self._answer(200, {"IpfsHash": cid, "PinSize": len(files[0]), "Timestamp": ""})

    def do_DELETE(self) -> None:  # noqa: N802
        cid = self.path.removeprefix("/pinning/unpin/").strip("/")
        path = self.store / cid
        if not self.path.startswith("/pinning/unpin/") or not path.is_file():
            self._answer(404, {"error": {"reason": "NOT_PINNED"}})
            return
        path.unlink()
        self.send_response(200)
        self.send_header("Content-Length", "2")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        print(f"fake pinata: {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--dir", type=Path, required=True)
    args = parser.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    Handler.store = args.dir
    print(f"fake pinata on http://127.0.0.1:{args.port}/, files in {args.dir}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
