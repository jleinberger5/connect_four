import tkinter as tk
from connect_four.ui.home_screen import HomeScreen

class ConnectFourApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Connect Four")
        self.geometry("800x600")
        self.minsize(600, 400)
        self.current_screen = None
        self.HomeScreen = HomeScreen
        self.switch_screen(HomeScreen)

    def switch_screen(self, screen_class, **kwargs):
        if self.current_screen:
            self.current_screen.destroy()

        # Determine if this screen should allow resizing
        resizable = screen_class.__name__ == "GameScreen"

        # Update resizability
        self.resizable(resizable, resizable)

        # Now launch the new screen
        self.current_screen = screen_class(self, **kwargs)
        self.current_screen.pack(fill="both", expand=True)


if __name__ == "__main__":
    app = ConnectFourApp()
    app.mainloop()
