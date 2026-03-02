# connect_four/ui/lobby_screen.py
# Lobby client with:
# - self-filter by session_id OR identity (ip+p2p_port+name) to hide "own ghost"
# - dedupe roster by identity (not session_id)
# - tracked after() callbacks to avoid Tk "invalid command name" after teardown
# - robust leave/close sequencing for server socket
# - consistent use of helper across Back / window close / P2P handoff

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import socket
import json
import time

from connect_four.networking.peer import PeerConnection
from connect_four.networking.server import PORT as SERVER_PORT
from connect_four.ui.setup_screen import SetupScreen


class LobbyScreen(tk.Frame):
    def __init__(self, master, server_ip, name, p2p_port):
        super().__init__(master)
        self.master.geometry("600x400")

        # --- basics ---------------------------------------------------------
        self.server_ip = server_ip
        self.name = name
        self.p2p_port = int(p2p_port)
        self.session_id = None
        self.local_ip = self._get_local_ip()  # used for identity-based self filtering

        # server connection state
        self.server_sock: socket.socket | None = None
        self.running = threading.Event()
        self.running.set()
        self.heartbeat_secs = 25  # must be < server timeout
        self.heartbeat_thread: threading.Thread | None = None

        # peer state
        self.peer_list: list[dict] = []
        self.selected_peer: dict | None = None
        self.connection: PeerConnection | None = None   # outgoing
        self.listener:   PeerConnection | None = None   # incoming host

        # track scheduled callbacks to cancel on teardown
        self._after_ids: set[int] = set()

        # --- UI -------------------------------------------------------------
        tk.Label(self, text=f"Welcome, {name}", font=("Arial", 18)).pack(pady=10)

        self.listbox = tk.Listbox(self, height=10)
        self.listbox.pack(pady=10, fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select_peer)

        self.status_label = tk.Label(self, text="", fg="red")
        self.status_label.pack()

        self.request_button = ttk.Button(self, text="Request Game",
                                         command=self._send_request, state=tk.DISABLED)
        self.request_button.pack(pady=5)

        ttk.Button(self, text="Back", command=self._on_back).pack(pady=5)

        try:
            self.master.protocol("WM_DELETE_WINDOW", self._on_window_close)
        except Exception:
            pass

        # --- networking -----------------------------------------------------
        self._start_server_listener()
        self._start_peer_listener()

    # ===================== Server (lobby) handling ==========================

    def _start_server_listener(self):
        threading.Thread(target=self._listen_to_server, daemon=True, name="LobbyServerListener").start()

    def _listen_to_server(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect((self.server_ip, SERVER_PORT))
            self.server_sock = sock

            # join
            self._send_to_server({"type": "join", "name": self.name, "p2p_port": self.p2p_port})

            # start heartbeats
            self._start_heartbeat_thread()

            buffer = ""
            while self.running.is_set():
                try:
                    data = sock.recv(4096)
                    if not data:
                        break
                    buffer += data.decode("utf-8", errors="ignore")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            msg = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        mtype = msg.get("type")
                        if mtype == "welcome":
                            self.session_id = msg.get("session_id")

                        elif mtype == "client_list":
                            raw = msg.get("clients", [])

                            # (1) Filter out "self" by session_id OR identity (ip+p2p_port+name)
                            filtered = [c for c in raw if not self._is_self_entry(c)]

                            # (2) Hard dedupe by identity, NOT session_id
                            uniq_by_identity: dict[str, dict] = {}
                            for c in filtered:
                                key = self._identity_key(c)
                                # Prefer entries that have a session_id (in case of mixed legacy/modern)
                                prev = uniq_by_identity.get(key)
                                if not prev or (c.get("session_id") and not prev.get("session_id")):
                                    uniq_by_identity[key] = c
                            self.peer_list = list(uniq_by_identity.values())

                            # (3) schedule a SAFE UI update
                            self._schedule(self._update_listbox)

                        # ignore others
                except socket.timeout:
                    continue
        except Exception as e:
            print("[SERVER ERROR]", e)
        finally:
            self._shutdown_server_socket()

    def _identity_key(self, entry: dict) -> str:
        return f"{entry.get('ip')}:{entry.get('p2p_port')}:{entry.get('name')}"

    def _is_self_entry(self, entry: dict) -> bool:
        # 1) Prefer session_id match if present
        if self.session_id and entry.get("session_id"):
            if entry["session_id"] == self.session_id:
                return True

        # 2) Identity-based fallback (handles "own ghost" with different session_id)
        try:
            same_name = entry.get("name") == self.name
            same_port = int(entry.get("p2p_port", -1)) == self.p2p_port
            # Server records our LAN IP as seen from the socket; that should match our local_ip
            same_ip = entry.get("ip") in (self.local_ip, "127.0.0.1", "::1")
            return same_name and same_port and same_ip
        except Exception:
            return False

    def _start_heartbeat_thread(self):
        if self.heartbeat_thread and self.heartbeat_thread.is_alive():
            return

        def hb():
            while self.running.is_set():
                for _ in range(self.heartbeat_secs):
                    if not self.running.is_set():
                        return
                    time.sleep(1)
                self._send_to_server({"type": "heartbeat"})
        self.heartbeat_thread = threading.Thread(target=hb, daemon=True, name="LobbyHB")
        self.heartbeat_thread.start()

    def _send_to_server(self, obj: dict) -> bool:
        try:
            if self.server_sock:
                raw = json.dumps(obj) + "\n"
                self.server_sock.sendall(raw.encode("utf-8"))
                return True
        except Exception:
            pass
        return False

    def _leave_and_close_server(self, reason: str):
        """Orderly leave: send leave, half-close write, short sleep, then close."""
        self.running.clear()  # stop heartbeats first
        sock = self.server_sock
        try:
            if sock:
                try:
                    sock.sendall((json.dumps({"type": "leave", "reason": reason}) + "\n").encode("utf-8"))
                except Exception:
                    pass
                try:
                    sock.shutdown(socket.SHUT_WR)
                except Exception:
                    pass
                time.sleep(0.05)
        finally:
            self._shutdown_server_socket()

    def _shutdown_server_socket(self):
        try:
            if self.server_sock:
                try:
                    self.server_sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                self.server_sock.close()
        except Exception:
            pass
        finally:
            self.server_sock = None

    # ========================= Peer (P2P) handling ==========================

    def _start_peer_listener(self):
        def host():
            self.listener = PeerConnection(
                is_host=True, ip="", port=self.p2p_port, on_message=self._on_peer_message
            )
        threading.Thread(target=host, daemon=True, name="P2PHost").start()

    def _on_peer_message(self, msg: dict):
        mtype = msg.get("type")

        if mtype == "game_request":
            requester = msg.get("from")
            if requester == self.name:
                return  # ignore looped self

            if messagebox.askyesno("Game Request", f'"{requester}" wants to start a game with you. Accept?'):
                # tell peer yes, then leave lobby immediately
                try:
                    self.listener.send({"type": "accepted"})
                except Exception:
                    pass
                self._cancel_scheduled()
                self._leave_and_close_server("starting_p2p_game")
                self._switch_to_setup(
                    is_host=False,
                    peer_name=requester,
                    peer_ip=msg.get("ip"),
                    peer_port=msg.get("port"),
                    connection=self.listener
                )
            else:
                try:
                    self.listener.send({"type": "declined"})
                except Exception:
                    pass

        elif mtype == "accepted":
            # our outgoing request accepted -> be host
            sel = self.selected_peer or {}
            self._cancel_scheduled()
            self._leave_and_close_server("starting_p2p_game")
            self._switch_to_setup(
                is_host=True,
                peer_name=sel.get("name", "Opponent"),
                peer_ip=sel.get("ip"),
                peer_port=sel.get("p2p_port"),
                connection=self.connection
            )

        elif mtype == "declined":
            sel = self.selected_peer or {"name": "Opponent"}
            self.status_label.config(text=f"{sel['name']} declined your request.")

    # =============================== UI ====================================

    def _update_listbox(self):
        # Safe against teardown races
        try:
            if (not self.winfo_exists()) or (self.listbox is None) or (not self.listbox.winfo_exists()):
                return
            self.listbox.delete(0, tk.END)
            for c in self.peer_list:
                self.listbox.insert(tk.END, f"{c['name']} ({c['ip']}:{c['p2p_port']})")
        except tk.TclError:
            # Widget already destroyed; ignore
            return

    def _on_select_peer(self, _evt):
        idx = self.listbox.curselection() if self.listbox and self.listbox.winfo_exists() else ()
        if not idx:
            self.selected_peer = None
            self.request_button.config(state=tk.DISABLED)
            return
        self.selected_peer = self.peer_list[idx[0]]
        self.request_button.config(state=tk.NORMAL)
        self.status_label.config(text="")

    def _send_request(self):
        if not self.selected_peer:
            return

        # clean any previous outgoing connection
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None

        peer = self.selected_peer
        try:
            self.connection = PeerConnection(
                is_host=False, ip=peer["ip"], port=peer["p2p_port"], on_message=self._on_peer_message
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to connect to peer: {e}")
            return

        self.connection.send({
            "type": "game_request",
            "from": self.name,
            "ip": self.local_ip,
            "port": self.p2p_port
        })

    # ============================ Navigation ================================

    def _on_back(self):
        # Leave lobby and return home
        self._cancel_scheduled()
        self._leave_and_close_server("user_left_lobby")
        self._close_p2p()
        self.master.switch_screen(self.master.HomeScreen)

    def _switch_to_setup(self, is_host, peer_name, peer_ip, peer_port, connection):
        self.master.switch_screen(
            SetupScreen,
            is_networked=True,
            is_host=is_host,
            peer_name=peer_name,
            peer_ip=peer_ip,
            peer_port=peer_port,
            local_name=self.name,
            connection=connection,
            server_ip=self.server_ip,
            p2p_port=self.p2p_port
        )

    def _on_window_close(self):
        self._cancel_scheduled()
        self._leave_and_close_server("app_window_close")
        self._close_p2p()
        try:
            self.master.destroy()
        except Exception:
            pass

    def _close_p2p(self):
        for c in ("connection", "listener"):
            pc = getattr(self, c, None)
            if pc:
                try:
                    pc.close()
                except Exception:
                    pass
                setattr(self, c, None)

    # ============================= helpers =================================

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ---------- safe scheduling / cancellation of UI callbacks --------------

    def _schedule(self, func, *args, **kwargs):
        """Schedule a UI update and track it so we can cancel on teardown."""
        def runner():
            try:
                func(*args, **kwargs)
            except tk.TclError:
                pass
            finally:
                if aid in self._after_ids:
                    self._after_ids.discard(aid)

        aid = self.after(0, runner)
        self._after_ids.add(aid)

    def _cancel_scheduled(self):
        """Cancel all pending tracked after() callbacks."""
        for aid in list(self._after_ids):
            try:
                self.after_cancel(aid)
            except Exception:
                pass
        self._after_ids.clear()
