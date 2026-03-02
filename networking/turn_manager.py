# networking/turn_manager.py

import threading

class TurnManager:
    def __init__(self, is_first_player=True, ack_timeout=5.0):
        self.my_turn = is_first_player
        self.lock = threading.Lock()
        self.ack_received = threading.Event()
        self.ack_timeout = ack_timeout
        self.last_move = None

    def can_move(self):
        with self.lock:
            return self.my_turn

    def send_move(self, move_data):
        with self.lock:
            if not self.my_turn:
                raise RuntimeError("Not your turn!")
            self.last_move = move_data
            self.ack_received.clear()
            self.my_turn = False
        return True

    def wait_for_ack(self):
        return self.ack_received.wait(timeout=self.ack_timeout)

    def receive_ack(self):
        self.ack_received.set()

    def receive_opponent_move(self, move_data):
        with self.lock:
            self.last_move = move_data
            self.my_turn = True
        return True
