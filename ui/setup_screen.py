import tkinter as tk
from tkinter import messagebox
from connect_four.ui.game_screen import GameScreen
from connect_four.networking.peer import PeerConnection
from connect_four.ui.screen_mixins import PeerAwareMixin
from connect_four.shared.inputs import AVAILABLE_COLORS

LONGEST_COLOR = max(AVAILABLE_COLORS, key=len)

class SetupScreen(tk.Frame, PeerAwareMixin):
    def __init__(self, master, is_networked=False, is_host=False, peer_name=None, peer_ip=None, peer_port=None,
                 local_name=None, connection=None, server_ip=None, p2p_port=None):
        super().__init__(master)
        self.master.geometry("600x400")
        self.is_networked = is_networked
        self.is_host = is_host
        self.peer_name = peer_name
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.local_name = local_name
        self.connection = connection
        self.server_ip = server_ip      # NEW: to enable return-to-lobby
        self.p2p_port = p2p_port        # NEW: to enable return-to-lobby
        self.connected = False
        self.ready_ack_received = False

        self.rows = tk.IntVar()
        self.cols = tk.IntVar()
        self.rows.set(8)
        self.cols.set(11)

        self.color1 = tk.StringVar(value="red")
        self.color2 = tk.StringVar(value="yellow")
        self.name1 = tk.StringVar(value=local_name or "Player 1")
        self.name2 = tk.StringVar(value=peer_name or "Player 2")

        self.ready_label = None
        self.start_button = None

        self.build_ui()

        if self.is_networked and (not self.connection or not self.connection.wait_until_connected()):
            self.connect_to_peer()

        if self.is_networked and self.connection:
            self.connection.on_message = self.on_message

        if self.is_networked and self.is_host:
            self.after(100, self.sync_initial_state_if_host)

    def connect_to_peer(self):
        try:
            self.connection = PeerConnection(
                is_host=self.is_host,
                ip=self.peer_ip,
                port=self.peer_port,
                on_message=self.on_message
            )
            self.connected = True
        except Exception as e:
            print("[CONNECT ERROR]", e)
            messagebox.showerror("Error", "Failed to establish P2P connection")
            self.master.switch_screen(self.master.HomeScreen)

    def sync_initial_state_if_host(self):
        self.send_config_update(rows=self.rows.get(), cols=self.cols.get(), color1=self.color1.get())

    def build_ui(self):
        tk.Label(self, text="Game Setup", font=("Arial", 18)).pack(pady=10)
        form = tk.Frame(self)
        form.pack(pady=10)

        tk.Label(form, text="You:").grid(row=0, column=0, sticky="e")
        tk.Entry(form, textvariable=self.name1, state="disabled").grid(row=0, column=1)
        tk.Label(form, text="Color:").grid(row=0, column=2)
        self.color_menu1 = self.create_color_menu(form, self.color1, row=0, col=3, is_my_color=True)

        tk.Label(form, text="Opponent:").grid(row=1, column=0, sticky="e")
        tk.Entry(form, textvariable=self.name2, state="disabled").grid(row=1, column=1)
        tk.Label(form, text="Color:").grid(row=1, column=2)
        self.color_menu2 = self.create_color_menu(form, self.color2, row=1, col=3, is_my_color=False)

        tk.Label(form, text="Rows:").grid(row=2, column=0, sticky="e")
        even_rows = tuple(i for i in range(6, 21, 2))
        row_box = tk.Spinbox(
            form,
            values=even_rows,
            state="normal" if not self.is_networked or self.is_host else "disabled",
            command=self.send_dim_update
        )
        row_box.grid(row=2, column=1)
        row_box.config(textvariable=self.rows)

        tk.Label(form, text="Cols:").grid(row=3, column=0, sticky="e")
        odd_cols = tuple(i for i in range(7, 22, 2))
        col_box = tk.Spinbox(
            form,
            values=odd_cols,
            state="normal" if not self.is_networked or self.is_host else "disabled",
            command=self.send_dim_update
        )
        col_box.grid(row=3, column=1)
        col_box.config(textvariable=self.cols)

        if not self.is_networked or self.is_host:
            self.start_button = tk.Button(self, text="Start!", command=self.start_game, state="disabled" if self.is_networked else "normal")
            self.start_button.pack(pady=20)
            self.ready_label = tk.Label(self, text="", fg="green")
            self.ready_label.pack()
        else:
            tk.Button(self, text="Ready To Play!", command=self.send_ready).pack(pady=20)

        tk.Button(self, text="Back", command=self.cancel_and_exit).pack()

    def create_color_menu(self, parent, var, row, col, is_my_color):
        menu = tk.Menubutton(parent, textvariable=var, relief=tk.RAISED, width=len(LONGEST_COLOR) + 2)
        menu.menu = tk.Menu(menu, tearoff=0)
        menu["menu"] = menu.menu

        for color in AVAILABLE_COLORS:
            menu.menu.add_radiobutton(
                label=color,
                background=color,
                variable=var,
                value=color,
                command=lambda c=color, ismine=is_my_color: self.send_color_change(c, ismine)
            )

        state = "normal" if not self.is_networked or (self.is_host == is_my_color) else "disabled"
        menu.config(state=state)
        menu.grid(row=row, column=col)

        def update_bg(*_): menu.config(bg=var.get())
        var.trace_add("write", update_bg)
        menu.config(bg=var.get())
        return menu

    def send_dim_update(self):
        if self.is_networked and self.is_host:
            self.send_config_update(rows=self.rows.get(), cols=self.cols.get())

    def send_color_change(self, color_value, is_my_color):
        if not self.is_networked:
            return

        should_send = (
            (self.is_host and is_my_color) or
            (not self.is_host and not is_my_color)
        )
        if should_send:
            key = "color1" if self.is_host else "color2"
            self.send_config_update(**{key: color_value})

    def send_config_update(self, **kwargs):
        if self.is_networked and self.connection:
            msg = {"type": "config_update", **kwargs}
            # print(f"[SEND CONFIG] {msg}")
            self.connection.send(msg)

    def send_ready(self):
        if self.connection:
            msg = {"type": "ready"}
            # print(f"[SEND READY] {msg}")
            self.connection.send(msg)

    def cancel_and_exit(self):
        """User is backing out of setup. Politely notify peer, then fully close P2P."""
        if self.connection:
            try:
                # Best‑effort notifications so peer UI can react promptly
                self.connection.send({"type": "cancel"})
                self.connection.send({"type": "leave"})
            except Exception:
                pass
            try:
                self.connection.close()
            except Exception:
                pass
            self.connection = None
        self.master.switch_screen(self.master.HomeScreen)

    def on_message(self, msg):
        # print(f"[RECV MESSAGE] {msg}")
        msg_type = msg.get("type")

        if msg_type == "start_game":
            config = msg["config"]
            self.master.switch_screen(GameScreen,
                rows=config["rows"],
                cols=config["cols"],
                player1=self.name1.get() if self.is_host else self.name2.get(),
                player2=self.name2.get() if self.is_host else self.name1.get(),
                color1=config["color1"] if not self.is_host else self.color1.get(),
                color2=self.color2.get(),
                is_networked=True,
                connection=self.connection,
                is_host=self.is_host,
                # pass server info so GameScreen can return to lobby cleanly
                server_ip=self.server_ip,
                p2p_port=self.p2p_port
            )

        elif msg_type == "config_update":
            self.handle_config_update(msg)

        elif msg_type == "cancel":
            messagebox.showinfo("Cancelled", "The opponent cancelled the setup.")
            if self.connection:
                try:
                    self.connection.close()
                except Exception:
                    pass
            self.connection = None
            self.master.switch_screen(self.master.HomeScreen)

        elif msg_type == "ready":
            self.ready_ack_received = True
            if self.start_button:
                self.start_button.config(state="normal")
            if self.ready_label:
                self.ready_label.config(text=f"{self.name2.get()} is ready!")

        elif msg_type == "leave":
            # Override generic mixin behavior during setup: return to Home.
            try:
                self.on_peer_left()
            finally:
                messagebox.showinfo("Opponent Left", "Your opponent left during setup.")
                if self.connection:
                    try:
                        self.connection.close()
                    except Exception:
                        pass
                self.connection = None
                self.master.switch_screen(self.master.HomeScreen)

    def handle_config_update(self, data):
        if not self.is_host:
            if "rows" in data: self.rows.set(data["rows"])
            if "cols" in data: self.cols.set(data["cols"])
            if "color1" in data: self.color1.set(data["color1"])
        else:
            if "color2" in data:
                self.color2.set(data["color2"])
                if hasattr(self, "color_menu2"):
                    self.color_menu2.config(bg=self.color2.get())

    def start_game(self):
        config = {
            "rows": self.rows.get(),
            "cols": self.cols.get(),
            "color1": self.color1.get(),
            "color2": self.color2.get()
        }
        if self.connection:
            self.connection.send({"type": "start_game", "config": config})
        self.master.switch_screen(GameScreen,
            rows=config["rows"],
            cols=config["cols"],
            player1=self.name1.get(),
            player2=self.name2.get(),
            color1=config["color1"],
            color2=config["color2"],
            is_networked=self.is_networked,
            connection=self.connection,
            is_host=True,
            # pass server info so GameScreen can return to lobby
            server_ip=self.server_ip,
            p2p_port=self.p2p_port
        )
