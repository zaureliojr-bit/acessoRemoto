"""Acesso Remoto - aplicativo unico (servidor + cliente) para uso em rede domestica.

Ao abrir, a janela ja fica pronta para ser acessada (mostra o IP local e
uma senha gerada automaticamente) e tambem permite conectar em outro
computador que esteja rodando este mesmo programa, informando o IP e a
senha exibidos na tela dele.
"""

import io
import json
import secrets
import socket
import string
import threading
import time
import tkinter as tk
from tkinter import messagebox

import mss
from PIL import Image, ImageTk
from pynput.keyboard import Controller as KeyboardController, Key
from pynput.mouse import Button, Controller as MouseController

from common import (
    DEFAULT_CONTROL_PORT,
    DEFAULT_VIDEO_PORT,
    hash_password,
    recv_frame,
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

KEYSYM_MAP = {"return": "enter", "escape": "esc", "prior": "page_up", "next": "page_down"}
PASSTHROUGH_KEYSYMS = {
    "up", "down", "left", "right", "space", "tab", "backspace",
    "delete", "home", "end", "caps_lock",
}
MODIFIER_KEYSYMS = {
    "shift_l": "shift", "shift_r": "shift",
    "control_l": "control", "control_r": "control",
    "alt_l": "alt", "alt_r": "alt",
}


def resolve_key(name: str):
    if len(name) == 1:
        return name
    return SPECIAL_KEYS.get(name)


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def generate_password(length: int = 6) -> str:
    return "".join(secrets.choice(string.digits) for _ in range(length))


# ---------- Lado servidor: permite que este computador seja acessado ----------

class Host:
    def __init__(self, get_password_hash, monitor=1, quality=60, fps=15,
                 video_port=DEFAULT_VIDEO_PORT, control_port=DEFAULT_CONTROL_PORT):
        self.get_password_hash = get_password_hash
        self.monitor = monitor
        self.quality = quality
        self.fps = fps
        self.video_port = video_port
        self.control_port = control_port

    def start(self) -> None:
        video_sock = self._make_listener(self.video_port)
        control_sock = self._make_listener(self.control_port)
        threading.Thread(target=self._serve_forever, args=(video_sock, self._handle_video), daemon=True).start()
        threading.Thread(target=self._serve_forever, args=(control_sock, self._handle_control), daemon=True).start()

    @staticmethod
    def _make_listener(port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", port))
        sock.listen(1)
        return sock

    @staticmethod
    def _serve_forever(sock, handler) -> None:
        while True:
            conn, _addr = sock.accept()
            threading.Thread(target=handler, args=(conn,), daemon=True).start()

    def _authenticate(self, conn) -> bool:
        try:
            received = recv_line(conn)
        except OSError:
            return False
        ok = received == self.get_password_hash()
        send_line(conn, "OK" if ok else "FAIL")
        return ok

    def _handle_video(self, conn) -> None:
        if not self._authenticate(conn):
            conn.close()
            return
        interval = 1.0 / self.fps
        with mss.mss() as sct:
            monitor = sct.monitors[self.monitor]
            while True:
                start = time.time()
                shot = sct.grab(monitor)
                image = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                buf = io.BytesIO()
                image.save(buf, format="JPEG", quality=self.quality)
                try:
                    send_frame(conn, buf.getvalue())
                except OSError:
                    return
                elapsed = time.time() - start
                if elapsed < interval:
                    time.sleep(interval - elapsed)

    def _handle_control(self, conn) -> None:
        if not self._authenticate(conn):
            conn.close()
            return
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
                self._apply_event(event)

    @staticmethod
    def _apply_event(event: dict) -> None:
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


# ---------- Lado cliente: janela que mostra e controla o computador remoto ----------

class ViewerWindow(tk.Toplevel):
    def __init__(self, master, host: str, password: str, video_port: int, control_port: int):
        super().__init__(master)
        self.title(f"Acesso Remoto - {host}")
        self.label = tk.Label(self)
        self.label.pack()

        self.password_hash = hash_password(password)
        self.host = host
        self.video_port = video_port
        self.control_port = control_port
        self.video_sock = None
        self.control_sock = None

        self.label.bind("<Motion>", self.on_motion)
        self.label.bind("<Button-1>", lambda e: self.on_click("left", True))
        self.label.bind("<ButtonRelease-1>", lambda e: self.on_click("left", False))
        self.label.bind("<Button-3>", lambda e: self.on_click("right", True))
        self.label.bind("<ButtonRelease-3>", lambda e: self.on_click("right", False))
        self.label.bind("<MouseWheel>", self.on_scroll)
        self.bind("<KeyPress>", lambda e: self.on_key(e, True))
        self.bind("<KeyRelease>", lambda e: self.on_key(e, False))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def connect(self) -> None:
        self.video_sock = socket.create_connection((self.host, self.video_port), timeout=5)
        send_line(self.video_sock, self.password_hash)
        if recv_line(self.video_sock) != "OK":
            raise RuntimeError("Falha na autenticacao (video). Verifique IP e senha.")

        self.control_sock = socket.create_connection((self.host, self.control_port), timeout=5)
        send_line(self.control_sock, self.password_hash)
        if recv_line(self.control_sock) != "OK":
            raise RuntimeError("Falha na autenticacao (controle). Verifique IP e senha.")

        threading.Thread(target=self.video_loop, daemon=True).start()

    def video_loop(self) -> None:
        while True:
            try:
                data = recv_frame(self.video_sock)
            except OSError:
                return
            if data is None:
                return
            image = Image.open(io.BytesIO(data))
            self.after(0, self._set_image, image)

    def _set_image(self, image) -> None:
        photo = ImageTk.PhotoImage(image)
        self.label.configure(image=photo)
        self.label.image = photo

    def send_event(self, event: dict) -> None:
        try:
            self.control_sock.sendall((json.dumps(event) + "\n").encode("utf-8"))
        except OSError:
            pass

    def on_motion(self, event) -> None:
        self.send_event({"type": "move", "x": event.x, "y": event.y})

    def on_click(self, button: str, pressed: bool) -> None:
        self.send_event({"type": "click", "button": button, "pressed": pressed})

    def on_scroll(self, event) -> None:
        direction = 1 if event.delta > 0 else -1
        self.send_event({"type": "scroll", "dx": 0, "dy": direction})

    def on_key(self, event, pressed: bool) -> None:
        key = self.translate_key(event)
        if key is None:
            return
        self.send_event({"type": "key", "key": key, "pressed": pressed})

    @staticmethod
    def translate_key(event):
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

    def on_close(self) -> None:
        for sock in (self.video_sock, self.control_sock):
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
        self.destroy()


# ---------- Janela principal ----------

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Acesso Remoto")
        self.root.resizable(False, False)
        self.password = generate_password()

        self._build_host_section()
        self._build_client_section()

        self.host_server = Host(get_password_hash=lambda: hash_password(self.password))
        try:
            self.host_server.start()
        except OSError as exc:
            messagebox.showerror(
                "Acesso Remoto",
                f"Nao foi possivel abrir as portas {DEFAULT_VIDEO_PORT}/{DEFAULT_CONTROL_PORT}: {exc}",
            )

    def _build_host_section(self) -> None:
        frame = tk.LabelFrame(self.root, text="Permitir que me acessem", padx=10, pady=10)
        frame.pack(fill="x", padx=10, pady=10)

        tk.Label(frame, text="Seu IP na rede local:").grid(row=0, column=0, sticky="w")
        tk.Label(frame, text=local_ip(), font=("TkDefaultFont", 11, "bold")).grid(row=0, column=1, sticky="w")

        tk.Label(frame, text="Senha de acesso:").grid(row=1, column=0, sticky="w")
        self.password_var = tk.StringVar(value=self.password)
        tk.Entry(frame, textvariable=self.password_var, width=16).grid(row=1, column=1, sticky="w")

        tk.Button(frame, text="Gerar nova senha", command=self.regenerate_password).grid(
            row=2, column=0, columnspan=2, pady=(8, 0)
        )

        tk.Label(
            frame,
            text="Compartilhe o IP e a senha acima com quem vai te acessar.",
            wraplength=360, justify="left", fg="gray",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def regenerate_password(self) -> None:
        self.password = generate_password()
        self.password_var.set(self.password)

    def _build_client_section(self) -> None:
        frame = tk.LabelFrame(self.root, text="Acessar outro computador", padx=10, pady=10)
        frame.pack(fill="x", padx=10, pady=10)

        tk.Label(frame, text="IP do computador remoto:").grid(row=0, column=0, sticky="w")
        self.remote_ip_var = tk.StringVar()
        tk.Entry(frame, textvariable=self.remote_ip_var, width=20).grid(row=0, column=1, sticky="w")

        tk.Label(frame, text="Senha:").grid(row=1, column=0, sticky="w")
        self.remote_password_var = tk.StringVar()
        tk.Entry(frame, textvariable=self.remote_password_var, width=20).grid(row=1, column=1, sticky="w")

        tk.Button(frame, text="Conectar", command=self.connect_to_remote).grid(
            row=2, column=0, columnspan=2, pady=(8, 0)
        )

    def connect_to_remote(self) -> None:
        host = self.remote_ip_var.get().strip()
        password = self.remote_password_var.get().strip()
        if not host or not password:
            messagebox.showerror("Acesso Remoto", "Informe o IP e a senha do computador remoto.")
            return

        viewer = ViewerWindow(self.root, host, password, DEFAULT_VIDEO_PORT, DEFAULT_CONTROL_PORT)
        try:
            viewer.connect()
        except (OSError, RuntimeError) as exc:
            viewer.destroy()
            messagebox.showerror("Acesso Remoto", f"Nao foi possivel conectar: {exc}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
