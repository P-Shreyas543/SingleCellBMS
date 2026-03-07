import tkinter as tk
from bms_gui import BMS_Logger_App

if __name__ == "__main__":
    root = tk.Tk()
    app = BMS_Logger_App(root)
    root.mainloop()