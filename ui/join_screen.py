# connect_four/ui/join_screen.py
# Minimal entry screen for network play: collects name, server IP, and picks a free P2P port.
# Ensures we pass a fresh p2p_port into LobbyScreen where the server join occurs.

import tkinter as tk
from tkinter import ttk, messagebox
import socket

from connect_four.ui.lobby_screen import LobbyScreen


def get_free_port() -> int:
    """Reserve an ephemeral TCP port for P2P; close immediately so Peer host can bind."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("", 0))
        return s.getsockname()[1]
    finally:
        s.close()


class NetworkPlayJoinScreen(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.geometry("600x400")

        tk.Label(self, text="Join Network Game", font=("Arial", 18)).pack(pady=20)

        # Name entry
        tk.Label(self, text="Enter your name:").pack()
        self.name_entry = ttk.Entry(self)
        self.name_entry.pack(pady=5)

        # Server IP entry
        tk.Label(self, text="Enter server IP address:").pack()
        self.ip_entry = ttk.Entry(self)
        self.ip_entry.insert(0, self._get_local_ip_guess())
        self.ip_entry.pack(pady=5)

        # Choose an ephemeral P2P port now so host can bind to it in the lobby
        self.p2p_port = get_free_port()
        tk.Label(self, text=f"P2P Port (auto): {self.p2p_port}").pack(pady=4)

        btns = tk.Frame(self)
        btns.pack(pady=14)
        ttk.Button(btns, text="Join Lobby", command=self.join_lobby).pack(side=tk.LEFT, padx=6)
        ttk.Button(btns, text="Back", command=lambda: self.master.switch_screen(self.master.HomeScreen)).pack(side=tk.LEFT, padx=6)

    def _get_local_ip_guess(self) -> str:
        """Best-effort local IP for convenience; falls back to loopback."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def join_lobby(self):
        name = (self.name_entry.get() or "").strip()
        ip = (self.ip_entry.get() or "").strip()

        if not name or not ip:
            messagebox.showwarning("Missing Fields", "Both name and server IP must be filled in.")
            return

        # Simple sanity check: IP-like string
        try:
            socket.inet_aton(ip)
        except OSError:
            # Allow hostnames too; user may paste e.g. 'my-server.local'
            if not any(ch.isalpha() for ch in ip):
                messagebox.showwarning("Invalid Address", "Please enter a valid IP address or hostname.")
                return

        # Hand off to Lobby (fresh server join happens there)
        self.master.switch_screen(
            LobbyScreen,
            server_ip=ip,
            name=name,
            p2p_port=self.p2p_port
        )
