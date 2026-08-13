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
import sys
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

# ---------- Redireciona Alt+Tab / tecla Windows para a maquina remota ----------

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    _WH_KEYBOARD_LL = 13
    _WM_KEYDOWN = 0x0100
    _WM_SYSKEYDOWN = 0x0104
    _VK_TAB = 0x09
    _VK_MENU = 0x12
    _VK_LWIN = 0x5B
    _VK_RWIN = 0x5C

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    _LowLevelKeyboardProc = ctypes.WINFUNCTYPE(
        ctypes.c_long, ctypes.c_int, wintypes.WPARAM, ctypes.POINTER(_KBDLLHOOKSTRUCT)
    )

    _user32.SetWindowsHookExW.restype = wintypes.HANDLE
    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, _LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD,
    ]
    _user32.CallNextHookEx.restype = ctypes.c_long
    _user32.CallNextHookEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, ctypes.POINTER(_KBDLLHOOKSTRUCT),
    ]
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetForegroundWindow.restype = wintypes.HWND


class AltTabRedirector:
    """No Windows, impede que Alt+Tab e a tecla Windows troquem de janela
    na maquina local enquanto a janela de visualizacao remota estiver em
    primeiro plano, encaminhando essas teclas para a maquina remota em vez
    disso.
    """

    _active_by_hwnd = {}
    _hook_handle = None
    _hook_proc = None

    @classmethod
    def register(cls, hwnd: int, send_key_event) -> None:
        if not IS_WINDOWS:
            return
        cls._active_by_hwnd[hwnd] = send_key_event
        if cls._hook_handle is None:
            try:
                cls._hook_proc = _LowLevelKeyboardProc(cls._callback)
                cls._hook_handle = _user32.SetWindowsHookExW(
                    _WH_KEYBOARD_LL, cls._hook_proc, None, 0
                ) or None
            except OSError:
                cls._hook_handle = None

    @classmethod
    def unregister(cls, hwnd: int) -> None:
        if not IS_WINDOWS:
            return
        cls._active_by_hwnd.pop(hwnd, None)
        if not cls._active_by_hwnd and cls._hook_handle is not None:
            _user32.UnhookWindowsHookEx(cls._hook_handle)
            cls._hook_handle = None
            cls._hook_proc = None

    @classmethod
    def _callback(cls, code, wparam, lparam):
        if code == 0 and cls._active_by_hwnd:
            try:
                vk = lparam.contents.vkCode
                foreground = _user32.GetForegroundWindow()
                send_key_event = cls._active_by_hwnd.get(foreground)
                if send_key_event is not None:
                    down = wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
                    alt_down = bool(_user32.GetAsyncKeyState(_VK_MENU) & 0x8000)
                    if vk == _VK_TAB and alt_down:
                        send_key_event({"type": "key", "key": "tab", "pressed": down})
                        return 1
                    if vk in (_VK_LWIN, _VK_RWIN):
                        send_key_event({"type": "key", "key": "super", "pressed": down})
                        return 1
            except Exception:
                pass
        return _user32.CallNextHookEx(cls._hook_handle, code, wparam, lparam)


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

        # Tamanho real da tela remota (definido ao chegar o primeiro frame),
        # tamanho com que a imagem foi exibida por ultimo e deslocamento
        # (a imagem fica centralizada quando a proporcao da janela nao bate
        # com a da tela remota) - usados para converter as coordenadas do
        # mouse na janela para coordenadas da tela remota.
        self.remote_size = None
        self.display_size = None
        self.display_offset = (0, 0)

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
        AltTabRedirector.register(self.root.winfo_id(), self.send_event)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.mainloop()

    def on_close(self) -> None:
        AltTabRedirector.unregister(self.root.winfo_id())
        self.root.destroy()

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
        self.display_offset = ((target_w - display_size[0]) // 2, (target_h - display_size[1]) // 2)

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
        offset_x, offset_y = self.display_offset
        image_x = max(0, min(x - offset_x, display_w - 1))
        image_y = max(0, min(y - offset_y, display_h - 1))
        remote_x = int(image_x * remote_w / display_w)
        remote_y = int(image_y * remote_h / display_h)
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
