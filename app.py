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
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

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

try:
    from version import APP_VERSION
except ImportError:
    APP_VERSION = "dev"

GITHUB_REPO = "zaureliojr-bit/acessoRemoto"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases/latest"


def fetch_latest_version():
    """Retorna (tag_da_ultima_versao, erro). Um dos dois e sempre None."""
    try:
        request = urllib.request.Request(
            LATEST_RELEASE_API, headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("tag_name"), None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, str(exc)

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
    "super": Key.cmd,
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


HISTORY_PATH = Path.home() / ".acesso_remoto_historico.json"
MAX_HISTORY = 10


def load_history() -> list:
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(host) for host in data] if isinstance(data, list) else []


def save_history(history: list) -> None:
    try:
        HISTORY_PATH.write_text(json.dumps(history), encoding="utf-8")
    except OSError:
        pass


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


# ---------- Redireciona Alt+Tab / tecla Windows para a maquina remota ----------

IS_WINDOWS = sys.platform.startswith("win")

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.windll.user32

    _WH_KEYBOARD_LL = 13
    _WM_KEYDOWN = 0x0100
    _WM_KEYUP = 0x0101
    _WM_SYSKEYDOWN = 0x0104
    _WM_SYSKEYUP = 0x0105
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


class AltTabRedirector:
    """No Windows, impede que Alt+Tab e a tecla Windows troquem de janela
    na maquina local enquanto uma janela de visualizacao remota estiver em
    primeiro plano, encaminhando essas teclas para a maquina remota em vez
    disso. Sem isso, o Windows local intercepta Alt+Tab antes mesmo do
    aplicativo receber o evento, e o alternador de janelas local aparece
    por cima em vez do comando chegar na maquina remota.

    Usa os eventos de foco do proprio Tkinter (<FocusIn>/<FocusOut>) para
    saber se a janela de visualizacao esta ativa, em vez de comparar o
    identificador de janela do Tk com GetForegroundWindow do Windows -
    essa comparacao direta se mostrou pouco confiavel na pratica.
    """

    _active_send_event = None
    _hook_handle = None
    _hook_proc = None

    @classmethod
    def activate(cls, send_key_event) -> None:
        if not IS_WINDOWS:
            return
        cls._active_send_event = send_key_event
        if cls._hook_handle is None:
            try:
                cls._hook_proc = _LowLevelKeyboardProc(cls._callback)
                cls._hook_handle = _user32.SetWindowsHookExW(
                    _WH_KEYBOARD_LL, cls._hook_proc, None, 0
                ) or None
            except OSError:
                cls._hook_handle = None

    @classmethod
    def deactivate(cls, send_key_event) -> None:
        if not IS_WINDOWS:
            return
        if cls._active_send_event is send_key_event:
            cls._active_send_event = None

    @classmethod
    def _callback(cls, code, wparam, lparam):
        if code == 0 and cls._active_send_event is not None:
            try:
                vk = lparam.contents.vkCode
                down = wparam in (_WM_KEYDOWN, _WM_SYSKEYDOWN)
                if vk == _VK_TAB and (_user32.GetAsyncKeyState(_VK_MENU) & 0x8000):
                    cls._active_send_event({"type": "key", "key": "tab", "pressed": down})
                    return 1
                if vk in (_VK_LWIN, _VK_RWIN):
                    cls._active_send_event({"type": "key", "key": "super", "pressed": down})
                    return 1
            except Exception:
                pass
        return _user32.CallNextHookEx(cls._hook_handle, code, wparam, lparam)


# ---------- Lado cliente: janela que mostra e controla o computador remoto ----------

class ViewerWindow(tk.Toplevel):
    MAX_INITIAL_SIZE = (1024, 768)
    MIN_SIZE = (320, 240)

    def __init__(self, master, host: str, password: str, video_port: int, control_port: int):
        super().__init__(master)
        self.title(f"Acesso Remoto - {host}")
        self.label = tk.Label(self, bg="black")
        self.label.pack(fill="both", expand=True)
        self.minsize(*self.MIN_SIZE)

        self.password_hash = hash_password(password)
        self.host = host
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

        self.label.bind("<Motion>", self.on_motion)
        self.label.bind("<Button-1>", lambda e: self.on_click("left", True))
        self.label.bind("<ButtonRelease-1>", lambda e: self.on_click("left", False))
        self.label.bind("<Button-3>", lambda e: self.on_click("right", True))
        self.label.bind("<ButtonRelease-3>", lambda e: self.on_click("right", False))
        self.label.bind("<MouseWheel>", self.on_scroll)
        self.bind("<KeyPress>", lambda e: self.on_key(e, True))
        self.bind("<KeyRelease>", lambda e: self.on_key(e, False))
        self.bind("<FocusIn>", lambda e: AltTabRedirector.activate(self.send_event))
        self.bind("<FocusOut>", lambda e: AltTabRedirector.deactivate(self.send_event))
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Uma janela Toplevel nao recebe foco de teclado automaticamente no
        # Windows; sem isso, o video/mouse funcionam mas as teclas nunca
        # chegam a esta janela.
        self.after(150, self.focus_force)

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
        self.geometry(f"{int(remote_w * scale)}x{int(remote_h * scale)}")
        self.update_idletasks()

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
            self.focus_force()
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
        AltTabRedirector.deactivate(self.send_event)
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

        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("TkDefaultFont", 14, "bold"))
        style.configure("Subtitle.TLabel", foreground="gray")
        style.configure("Value.TLabel", font=("TkDefaultFont", 11, "bold"))
        style.configure("Footer.TLabel", foreground="gray")

        container = ttk.Frame(self.root, padding=12)
        container.pack(fill="both", expand=True)

        self._build_header(container)
        self._build_host_section(container)
        self._build_client_section(container)
        self._build_footer(container)

        self.host_server = Host(get_password_hash=lambda: hash_password(self.password))
        try:
            self.host_server.start()
        except OSError as exc:
            messagebox.showerror(
                "Acesso Remoto",
                f"Nao foi possivel abrir as portas {DEFAULT_VIDEO_PORT}/{DEFAULT_CONTROL_PORT}: {exc}",
            )

    def _build_header(self, parent) -> None:
        header = ttk.Frame(parent)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="Acesso Remoto", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header, text="Para uso na sua rede doméstica", style="Subtitle.TLabel"
        ).pack(anchor="w")

    def _build_host_section(self, parent) -> None:
        frame = ttk.LabelFrame(parent, text="Permitir que me acessem", padding=10)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Seu IP na rede local:").grid(row=0, column=0, sticky="w")
        ttk.Label(frame, text=local_ip(), style="Value.TLabel").grid(
            row=0, column=1, sticky="w", padx=(6, 6)
        )
        ttk.Button(
            frame, text="Copiar", width=8, command=lambda: self.copy_to_clipboard(local_ip())
        ).grid(row=0, column=2, sticky="e")

        ttk.Label(frame, text="Senha de acesso:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.password_var = tk.StringVar(value=self.password)
        ttk.Entry(frame, textvariable=self.password_var, width=16).grid(
            row=1, column=1, sticky="w", padx=(6, 6), pady=(6, 0)
        )
        ttk.Button(
            frame, text="Copiar", width=8, command=lambda: self.copy_to_clipboard(self.password)
        ).grid(row=1, column=2, sticky="e", pady=(6, 0))

        ttk.Button(frame, text="Gerar nova senha", command=self.regenerate_password).grid(
            row=2, column=0, columnspan=3, pady=(10, 0), sticky="w"
        )

        ttk.Label(
            frame,
            text="Compartilhe o IP e a senha acima com quem vai te acessar.",
            wraplength=360, justify="left", style="Subtitle.TLabel",
        ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def copy_to_clipboard(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def regenerate_password(self) -> None:
        self.password = generate_password()
        self.password_var.set(self.password)

    def _build_client_section(self, parent) -> None:
        self.history = load_history()

        frame = ttk.LabelFrame(parent, text="Acessar outro computador", padding=10)
        frame.pack(fill="x", pady=(0, 10))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="IP do computador remoto:").grid(row=0, column=0, sticky="w")
        self.remote_ip_var = tk.StringVar()
        self.ip_combo = ttk.Combobox(
            frame, textvariable=self.remote_ip_var, values=self.history, width=18
        )
        self.ip_combo.grid(row=0, column=1, columnspan=2, sticky="w", padx=(6, 0))

        ttk.Label(frame, text="Senha:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.remote_password_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self.remote_password_var, width=20).grid(
            row=1, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=(6, 0)
        )

        ttk.Button(frame, text="Conectar", command=self.connect_to_remote).grid(
            row=2, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Button(frame, text="Limpar histórico", command=self.clear_history).grid(
            row=2, column=1, columnspan=2, sticky="e", pady=(10, 0)
        )

    def clear_history(self) -> None:
        self.history = []
        save_history(self.history)
        self.ip_combo["values"] = self.history

    def remember_host(self, host: str) -> None:
        if host in self.history:
            self.history.remove(host)
        self.history.insert(0, host)
        self.history = self.history[:MAX_HISTORY]
        save_history(self.history)
        self.ip_combo["values"] = self.history

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
            return

        self.remember_host(host)

    def _build_footer(self, parent) -> None:
        footer = ttk.Frame(parent)
        footer.pack(fill="x", pady=(4, 0))

        ttk.Label(footer, text=f"Versão: {APP_VERSION}", style="Footer.TLabel").pack(side="left")
        ttk.Button(
            footer, text="Verificar atualizações", command=self.check_updates
        ).pack(side="right")

    def check_updates(self) -> None:
        threading.Thread(target=self._check_updates_worker, daemon=True).start()

    def _check_updates_worker(self) -> None:
        latest_tag, error = fetch_latest_version()
        self.root.after(0, self._show_update_result, latest_tag, error)

    def _show_update_result(self, latest_tag, error) -> None:
        if error:
            messagebox.showerror(
                "Verificar atualizações",
                f"Não foi possível verificar agora. Confira sua conexão com a internet.\n\n{error}",
            )
            return
        if not latest_tag or latest_tag == APP_VERSION:
            messagebox.showinfo(
                "Verificar atualizações", f"Você já está com a versão mais recente ({APP_VERSION})."
            )
            return
        if messagebox.askyesno(
            "Atualização disponível",
            f"Há uma versão mais nova disponível: {latest_tag}\nVocê está usando: {APP_VERSION}\n\n"
            "Abrir a página de download?",
        ):
            webbrowser.open(RELEASES_PAGE_URL)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    App().run()


if __name__ == "__main__":
    main()
