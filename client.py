"""Cliente de acesso remoto: roda na maquina que vai controlar a outra.

Conecta no servidor (video + controle), autentica por senha, mostra a
tela remota numa janela e envia eventos de mouse/teclado capturados
nessa janela.

Uso:
    python client.py 192.168.0.42 --password "minha-senha"
"""

import argparse
import io
import json
import socket
import threading
import tkinter as tk

from PIL import Image, ImageTk

from common import (
    DEFAULT_CONTROL_PORT,
    DEFAULT_VIDEO_PORT,
    hash_password,
    recv_frame,
    recv_line,
    send_line,
)

KEYSYM_MAP = {
    "return": "enter",
    "escape": "esc",
    "prior": "page_up",
    "next": "page_down",
}

PASSTHROUGH_KEYSYMS = {
    "up", "down", "left", "right", "space", "tab", "backspace",
    "delete", "home", "end", "caps_lock",
}

MODIFIER_KEYSYMS = {
    "shift_l": "shift", "shift_r": "shift",
    "control_l": "control", "control_r": "control",
    "alt_l": "alt", "alt_r": "alt",
}


class RemoteClient:
    MAX_INITIAL_SIZE = (1024, 768)
    MIN_SIZE = (320, 240)

    def __init__(self, host: str, password: str, video_port: int, control_port: int):
        self.host = host
        self.password_hash = hash_password(password)
        self.video_port = video_port
        self.control_port = control_port
        self.video_sock = None
        self.control_sock = None

        # Tamanho real da tela remota (definido ao chegar o primeiro frame)
        # e tamanho com que a imagem foi exibida por ultimo, usados para
        # converter as coordenadas do mouse na janela para coordenadas da
        # tela remota quando a janela e redimensionada.
        self.remote_size = None
        self.display_size = None

        self.root = tk.Tk()
        self.root.title(f"Acesso Remoto - {host}")
        self.label = tk.Label(self.root, bg="black")
        self.label.pack(fill="both", expand=True)
        self.root.minsize(*self.MIN_SIZE)

        self.label.bind("<Motion>", self.on_motion)
        self.label.bind("<Button-1>", lambda e: self.on_click("left", True))
        self.label.bind("<ButtonRelease-1>", lambda e: self.on_click("left", False))
        self.label.bind("<Button-3>", lambda e: self.on_click("right", True))
        self.label.bind("<ButtonRelease-3>", lambda e: self.on_click("right", False))
        self.label.bind("<MouseWheel>", self.on_scroll)
        self.root.bind("<KeyPress>", lambda e: self.on_key(e, True))
        self.root.bind("<KeyRelease>", lambda e: self.on_key(e, False))
        self.root.after(150, self.root.focus_force)

    def connect(self) -> None:
        self.video_sock = socket.create_connection((self.host, self.video_port))
        send_line(self.video_sock, self.password_hash)
        if recv_line(self.video_sock) != "OK":
            raise RuntimeError("Falha na autenticacao (video). Verifique a senha.")

        self.control_sock = socket.create_connection((self.host, self.control_port))
        send_line(self.control_sock, self.password_hash)
        if recv_line(self.control_sock) != "OK":
            raise RuntimeError("Falha na autenticacao (controle). Verifique a senha.")

    def start(self) -> None:
        self.connect()
        threading.Thread(target=self.video_loop, daemon=True).start()
        self.root.mainloop()

    def video_loop(self) -> None:
        while True:
            data = recv_frame(self.video_sock)
            if data is None:
                break
            image = Image.open(io.BytesIO(data))
            self.root.after(0, self._set_image, image)

    def _set_image(self, image) -> None:
        if self.remote_size is None:
            self.remote_size = image.size
            self._set_initial_geometry(image.size)

        remote_w, remote_h = self.remote_size
        target_w = max(self.label.winfo_width(), 1)
        target_h = max(self.label.winfo_height(), 1)
        scale = min(target_w / remote_w, target_h / remote_h)
        display_size = (max(int(remote_w * scale), 1), max(int(remote_h * scale), 1))
        if display_size != image.size:
            image = image.resize(display_size, Image.BILINEAR)
        self.display_size = display_size

        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo)
        self.label.image = photo

    def _set_initial_geometry(self, remote_size) -> None:
        remote_w, remote_h = remote_size
        max_w, max_h = self.MAX_INITIAL_SIZE
        scale = min(max_w / remote_w, max_h / remote_h, 1.0)
        self.root.geometry(f"{int(remote_w * scale)}x{int(remote_h * scale)}")
        self.root.update_idletasks()

    def send_event(self, event: dict) -> None:
        try:
            self.control_sock.sendall((json.dumps(event) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _to_remote_coords(self, x: int, y: int):
        if not self.remote_size or not self.display_size:
            return x, y
        remote_w, remote_h = self.remote_size
        display_w, display_h = self.display_size
        remote_x = int(x * remote_w / display_w)
        remote_y = int(y * remote_h / display_h)
        return max(0, min(remote_x, remote_w - 1)), max(0, min(remote_y, remote_h - 1))

    def on_motion(self, event) -> None:
        x, y = self._to_remote_coords(event.x, event.y)
        self.send_event({"type": "move", "x": x, "y": y})

    def on_click(self, button: str, pressed: bool) -> None:
        if pressed:
            self.root.focus_force()
        self.send_event({"type": "click", "button": button, "pressed": pressed})

    def on_scroll(self, event) -> None:
        direction = 1 if event.delta > 0 else -1
        self.send_event({"type": "scroll", "dx": 0, "dy": direction})

    def on_key(self, event, pressed: bool) -> None:
        key = self.translate_key(event)
        if key is None:
            return
        self.send_event({"type": "key", "key": key, "pressed": pressed})

    def translate_key(self, event):
        keysym = event.keysym.lower()
        if keysym in KEYSYM_MAP:
            return KEYSYM_MAP[keysym]
        if keysym in MODIFIER_KEYSYMS:
            return MODIFIER_KEYSYMS[keysym]
        if keysym in PASSTHROUGH_KEYSYMS:
            return keysym
        if len(event.char) == 1 and event.char.isprintable():
            return event.char
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Cliente de acesso remoto (rede domestica)")
    parser.add_argument("host", help="IP ou hostname da maquina remota na rede local")
    parser.add_argument("--password", required=True)
    parser.add_argument("--video-port", type=int, default=DEFAULT_VIDEO_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    args = parser.parse_args()

    client = RemoteClient(args.host, args.password, args.video_port, args.control_port)
    client.start()


if __name__ == "__main__":
    main()
