# ui/home_screen.py

import tkinter as tk
from tkinter import ttk
from connect_four.ui.setup_screen import SetupScreen
from connect_four.ui.join_screen import NetworkPlayJoinScreen


class HomeScreen(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.geometry("600x400")
        tk.Label(self, text="Connect Four", font=("Arial", 24)).pack(pady=40)
        ttk.Button(self, text="Local Play", command=lambda: master.switch_screen(SetupScreen)).pack(pady=10)
        ttk.Button(self, text="Network Play", command=lambda: master.switch_screen(NetworkPlayJoinScreen)).pack(pady=10)
