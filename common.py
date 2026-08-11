"""Protocolo compartilhado entre server.py e client.py."""

import hashlib
import struct


DEFAULT_VIDEO_PORT = 5000
DEFAULT_CONTROL_PORT = 5001


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def send_line(sock, text: str) -> None:
    sock.sendall((text + "\n").encode("utf-8"))


def recv_line(sock) -> str:
    chars = bytearray()
    while True:
        c = sock.recv(1)
        if not c or c == b"\n":
            break
        chars.extend(c)
    return chars.decode("utf-8")


def recvn(sock, n: int):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock, data: bytes) -> None:
    sock.sendall(struct.pack(">I", len(data)) + data)


def recv_frame(sock):
    header = recvn(sock, 4)
    if not header:
        return None
    (length,) = struct.unpack(">I", header)
    return recvn(sock, length)
