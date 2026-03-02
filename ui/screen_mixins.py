from tkinter import messagebox

class PeerAwareMixin:
    def on_peer_left(self):
        if hasattr(self, "turn_label"):
            self.turn_label.config(text="Your opponent left the game.")
        if hasattr(self, "connection") and self.connection:
            self.connection.close()

