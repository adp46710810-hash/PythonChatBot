from __future__ import annotations

import socket


class BouyomiClient:
    backend_name = "BouyomiChan"
    failure_hint = "is BouyomiChan running?"

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    def _make_header(
        self,
        *,
        command: int = 1,
        speed: int = -1,
        tone: int = -1,
        volume: int = -1,
        voice: int = 0,
        char_code: int = 0,
        msg_length: int = 0,
    ) -> bytes:
        b = b""
        b += int(command).to_bytes(2, "little", signed=True)
        b += int(speed).to_bytes(2, "little", signed=True)
        b += int(tone).to_bytes(2, "little", signed=True)
        b += int(volume).to_bytes(2, "little", signed=True)
        b += int(voice).to_bytes(2, "little", signed=True)
        b += int(char_code).to_bytes(1, "little", signed=True)
        b += int(msg_length).to_bytes(4, "little", signed=True)
        return b

    def speak(self, text: str) -> None:
        msg = text.encode("utf-8")
        header = self._make_header(msg_length=len(msg), char_code=0)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            s.connect((self.host, self.port))
            s.sendall(header)
            s.sendall(msg)
