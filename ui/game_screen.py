import tkinter as tk
from tkinter import ttk
from connect_four.game_logic.board import ConnectFourBoard
from connect_four.networking.turn_manager import TurnManager
from connect_four.ui.screen_mixins import PeerAwareMixin
from connect_four.shared.inputs import CONTRAST_TEXT_COLOR


class GameScreen(tk.Frame, PeerAwareMixin):
    def __init__(self, master, rows, cols, player1, player2, color1, color2,
                 is_networked=False, connection=None, is_host=False,
                 server_ip=None, p2p_port=None):
        super().__init__(master)
        self.master.minsize(600, 400)
        self.rows = rows
        self.cols = cols
        self.player1 = player1
        self.player2 = player2
        self.color1 = color1
        self.color2 = color2
        self.is_networked = is_networked
        self.connection = connection
        self.is_host = is_host
        self.server_ip = server_ip
        self.p2p_port = p2p_port
        self.player_id = 0 if is_host else 1
        self.opponent_id = 1 - self.player_id
        self.turn_manager = TurnManager(is_first_player=is_host if is_networked else True)
        self.board_logic = ConnectFourBoard(rows, cols)

        self.canvas = tk.Canvas(self, bg="lightgray", highlightthickness=0)
        self.canvas.bind("<Button-1>", self.handle_click)
        self.canvas.bind("<Configure>", self.on_resize)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Status area
        self.status_frame = tk.Frame(self)
        self.status_frame.pack(pady=10)

        self.name_bar = tk.Frame(self.status_frame)
        self.name_bar.pack()

        self.label_you = tk.Label(
            self.name_bar,
            text=f'"{self.get_my_name()}"',
            bg=self.get_my_color(),
            fg=CONTRAST_TEXT_COLOR.get(self.get_my_color(), "white"),
            font=("Arial", 14, "bold")
        )
        self.label_you.pack(side=tk.LEFT, padx=5)

        tk.Label(self.name_bar, text="vs", font=("Arial", 14, "bold")).pack(side=tk.LEFT, padx=5)

        self.label_opponent = tk.Label(
            self.name_bar,
            text=f'"{self.get_opponent_name()}"',
            bg=self.get_opponent_color(),
            fg=CONTRAST_TEXT_COLOR.get(self.get_opponent_color(), "white"),
            font=("Arial", 14, "bold")
        )
        self.label_opponent.pack(side=tk.LEFT, padx=5)

        self.turn_label = tk.Label(self.status_frame, text="", font=("Arial", 20, "bold"))
        self.turn_label.pack()

        self.quit_button = ttk.Button(self.status_frame, text="Quit Game", command=self.confirm_quit)
        self.quit_button.pack(pady=5)

        if self.is_networked:
            self.connection.on_message = self.on_network_message

        self.local_turn = 0  # for local play alternation
        self.update_turn_label()
        self.draw_board()

    def get_my_name(self):
        return self.player1 if self.player_id == 0 else self.player2

    def get_opponent_name(self):
        return self.player2 if self.player_id == 0 else self.player1

    def get_my_color(self):
        return self.color1 if self.player_id == 0 else self.color2

    def get_opponent_color(self):
        return self.color2 if self.player_id == 0 else self.color1

    def draw_board(self):
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()

        # Determine square size based on available canvas size
        cell_size = min(width / self.cols, height / self.rows)
        board_width = cell_size * self.cols
        board_height = cell_size * self.rows
        offset_x = (width - board_width) / 2
        offset_y = (height - board_height) / 2

        radius = cell_size * 0.4

        for r in range(self.rows):
            for c in range(self.cols):
                x = offset_x + (c + 0.5) * cell_size
                y = offset_y + (r + 0.5) * cell_size
                x0, y0 = x - radius, y - radius
                x1, y1 = x + radius, y + radius

                cell = self.board_logic.board[r][c]
                fill = "white"
                if cell == 0:
                    fill = self.color1
                elif cell == 1:
                    fill = self.color2
                self.canvas.create_oval(x0, y0, x1, y1, fill=fill, outline="black")

    def on_resize(self, _):
        self.draw_board()

    def handle_click(self, event):
        if self.is_networked and not self.turn_manager.can_move():
            return

        col = int(event.x / (self.canvas.winfo_width() / self.cols))
        current_id = self.player_id if self.is_networked else self.local_turn
        move = self.board_logic.drop_piece(col, current_id)
        if move is None:
            return

        self.draw_board()
        if self.board_logic.is_winning_move(current_id):
            if self.is_networked:
                self.send_win_or_tie(col, "win")
            self.end_game(winner=(current_id == self.player_id))
            return
        elif self.board_logic.is_full():
            if self.is_networked:
                self.send_win_or_tie(col, "tie")
            self.end_game(tie=True)
            return

        if self.is_networked:
            move_msg = {"type": "move", "col": col, "player": self.player_id}
            self.turn_manager.send_move(move_msg)
            self.connection.send(move_msg)
        else:
            self.local_turn = 1 - self.local_turn  # alternate
            self.player_id = self.local_turn

        self.update_turn_label()

    def send_win_or_tie(self, col, result):
        if self.connection:
            self.connection.send({"type": "move", "col": col, "player": self.player_id})
            self.connection.send({"type": result})

    def on_network_message(self, msg):
        msg_type = msg.get("type")

        if msg_type == "move":
            col = msg.get("col")
            pid = msg.get("player")
            if self.board_logic.drop_piece(col, pid):
                self.draw_board()
                self.turn_manager.receive_opponent_move(msg)
                if self.connection:
                    self.connection.send({"type": "ack"})
                self.update_turn_label()

        elif msg_type == "ack":
            self.turn_manager.receive_ack()

        elif msg_type == "win":
            self.end_game(winner=False)

        elif msg_type == "tie":
            self.end_game(tie=True)

        elif msg_type == "leave":
            self.on_peer_left()

    def end_game(self, winner=False, tie=False):
        self.canvas.unbind("<Button-1>")
        if tie:
            self.turn_label.config(text="It's a tie!")
        elif winner:
            if self.is_networked:
                self.turn_label.config(text="You Won! 😊")
            else:
                winner_name = self.player1 if self.local_turn == 0 else self.player2
                self.turn_label.config(text=f"{winner_name} Won! 🎉")
        else:
            if self.is_networked:
                self.turn_label.config(text="You Lost 😢")

    def update_turn_label(self):
        if self.is_networked:
            if self.turn_manager.can_move():
                self.turn_label.config(text="Your move!")
            else:
                self.turn_label.config(text=f"{self.get_opponent_name()}'s move...")
        else:
            current_name = self.player1 if self.local_turn == 0 else self.player2
            self.turn_label.config(text=f"{current_name}'s move...")

    def confirm_quit(self):
        """User clicked Quit. If networked, best‑effort notify peer, then fully close P2P
        before returning to lobby (fresh server join happens there)."""
        if self.connection:
            try:
                # best-effort leave notification to peer
                self.connection.send({"type": "leave"})
            except Exception:
                pass
            finally:
                try:
                    # ensure peer socket fully closes
                    self.connection.close()
                except Exception:
                    pass
                self.connection = None

        if self.is_networked:
            self.return_to_lobby()
        else:
            self.master.switch_screen(self.master.HomeScreen)

    def return_to_lobby(self):
        """Return to Lobby with a fresh server join. Do not carry any server socket here."""
        # Defensive: ensure no lingering P2P socket
        try:
            if self.connection:
                self.connection.close()
        except Exception:
            pass
        finally:
            self.connection = None

        from connect_four.ui.lobby_screen import LobbyScreen
        self.master.switch_screen(
            LobbyScreen,
            server_ip=self.server_ip,
            name=self.get_my_name(),
            p2p_port=self.p2p_port or 0
        )
