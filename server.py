"""Servidor de acesso remoto: roda na maquina que sera controlada.

Abre duas conexoes TCP (video e controle), autentica por senha e entao:
- transmite capturas de tela em JPEG pela conexao de video;
- recebe eventos de mouse/teclado pela conexao de controle e os aplica.

Uso:
    python server.py --password "minha-senha"
"""

import argparse
import io
import json
import socket
import sys
import threading
import time

import mss
from PIL import Image
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

from common import (
    DEFAULT_CONTROL_PORT,
    DEFAULT_VIDEO_PORT,
    hash_password,
    recv_line,
    send_frame,
    send_line,
)

mouse = MouseController()
keyboard = KeyboardController()

BUTTON_MAP = {"left": Button.left, "right": Button.right, "middle": Button.middle}

SPECIAL_KEYS = {
    "enter": Key.enter,
    "esc": Key.esc,
    "space": Key.space,
    "tab": Key.tab,
    "backspace": Key.backspace,
    "shift": Key.shift,
    "control": Key.ctrl,
    "alt": Key.alt,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "delete": Key.delete,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "caps_lock": Key.caps_lock,
}


def resolve_key(name: str):
    if len(name) == 1:
        return name
    return SPECIAL_KEYS.get(name)


def authenticate(conn, expected_hash: str) -> bool:
    try:
        received = recv_line(conn)
    except OSError:
        return False
    ok = received == expected_hash
    send_line(conn, "OK" if ok else "FAIL")
    return ok


def video_loop(conn, monitor_index: int, quality: int, fps: int) -> None:
    interval = 1.0 / fps
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        while True:
            start = time.time()
            shot = sct.grab(monitor)
            image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            image.save(buf, format="JPEG", quality=quality)
            try:
                send_frame(conn, buf.getvalue())
            except OSError:
                return
            elapsed = time.time() - start
            if elapsed < interval:
                time.sleep(interval - elapsed)


def apply_event(event: dict) -> None:
    etype = event.get("type")
    if etype == "move":
        mouse.position = (event["x"], event["y"])
    elif etype == "click":
        button = BUTTON_MAP.get(event.get("button", "left"))
        if button is None:
            return
        if event.get("pressed"):
            mouse.press(button)
        else:
            mouse.release(button)
    elif etype == "scroll":
        mouse.scroll(event.get("dx", 0), event.get("dy", 0))
    elif etype == "key":
        key = resolve_key(event.get("key", ""))
        if key is None:
            return
        if event.get("pressed"):
            keyboard.press(key)
        else:
            keyboard.release(key)


def control_loop(conn) -> None:
    buf = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line:
                continue
            try:
                event = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            apply_event(event)


def handle_video_client(conn, expected_hash: str, args) -> None:
    if not authenticate(conn, expected_hash):
        conn.close()
        return
    print("[video] cliente autenticado")
    video_loop(conn, args.monitor, args.quality, args.fps)


def handle_control_client(conn, expected_hash: str) -> None:
    if not authenticate(conn, expected_hash):
        conn.close()
        return
    print("[controle] cliente autenticado")
    control_loop(conn)


def serve_forever(sock, handler, *handler_args) -> None:
    while True:
        conn, addr = sock.accept()
        print(f"Conexao de {addr}")
        threading.Thread(target=handler, args=(conn, *handler_args), daemon=True).start()


def make_listener(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(1)
    return sock


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor de acesso remoto (rede domestica)")
    parser.add_argument("--password", required=True, help="Senha de acesso")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--video-port", type=int, default=DEFAULT_VIDEO_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--monitor", type=int, default=1, help="indice do monitor (mss); 1 = principal")
    parser.add_argument("--quality", type=int, default=60, help="qualidade JPEG (1-100)")
    parser.add_argument("--fps", type=int, default=15)
    args = parser.parse_args()

    expected_hash = hash_password(args.password)

    video_sock = make_listener(args.host, args.video_port)
    control_sock = make_listener(args.host, args.control_port)

    print(f"Servidor ouvindo em {args.host}:{args.video_port} (video) e {args.control_port} (controle)")

    threading.Thread(
        target=serve_forever, args=(video_sock, handle_video_client, expected_hash, args), daemon=True
    ).start()
    threading.Thread(
        target=serve_forever, args=(control_sock, handle_control_client, expected_hash), daemon=True
    ).start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Encerrando servidor...")
        sys.exit(0)


if __name__ == "__main__":
    main()
