# game_logic/board.py

class ConnectFourBoard:
    def __init__(self, rows=6, cols=7):
        self.rows = rows
        self.cols = cols
        self.board = [[None for _ in range(cols)] for _ in range(rows)]
        self.last_move = None

    def drop_piece(self, col, player_id):
        """
        Attempts to drop a piece into the specified column.
        Returns (row, col) if successful, or None if column is full.
        """
        if col < 0 or col >= self.cols:
            return None

        for row in reversed(range(self.rows)):
            if self.board[row][col] is None:
                self.board[row][col] = player_id
                self.last_move = (row, col)
                return row, col
        return None

    def valid_moves(self):
        """Returns a list of columns where a move is possible."""
        return [col for col in range(self.cols) if self.board[0][col] is None]

    def is_full(self):
        """Returns True if the board is full."""
        return all(self.board[0][col] is not None for col in range(self.cols))

    def is_winning_move(self, player_id):
        """Checks if the last move caused a win for the given player."""
        if not self.last_move:
            return False

        row, col = self.last_move
        directions = [
            (0, 1),   # horizontal
            (1, 0),   # vertical
            (1, 1),   # diagonal \
            (1, -1),  # diagonal /
        ]

        for dr, dc in directions:
            count = 1
            # Check in the positive direction
            r, c = row + dr, col + dc
            while 0 <= r < self.rows and 0 <= c < self.cols and self.board[r][c] == player_id:
                count += 1
                r += dr
                c += dc

            # Check in the negative direction
            r, c = row - dr, col - dc
            while 0 <= r < self.rows and 0 <= c < self.cols and self.board[r][c] == player_id:
                count += 1
                r -= dr
                c -= dc

            if count >= 4:
                return True

        return False

    def reset(self):
        """Clears the board."""
        self.board = [[None for _ in range(self.cols)] for _ in range(self.rows)]
        self.last_move = None

    def get_state(self):
        """Returns a copy of the current board state (for debugging/testing)."""
        return [row[:] for row in self.board]
