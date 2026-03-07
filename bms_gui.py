import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import serial.tools.list_ports
import queue
import datetime
import os
from bms_config import TX_FRAME_CONFIG
from bms_assets import LOGO_RAW_HEX, ICON_RAW_HEX, ICON_WIDTH, ICON_HEIGHT, generate_corrected_xbm
from bms_utils import set_system_awake, PARSED_HEADERS, TxBuilder
from bms_workers import SerialWorker, CSVLoggerThread

# ==========================================
#              GUI APPLICATION
# ==========================================
class BMS_Logger_App:
    def __init__(self, root):
        self.root = root
        self.root.title("QC Test Application v1.0")
        # Version Control Test: Initializing the main window geometry
        self.root.geometry("1280x720")
        
        # --- Data & State ---
        self.gui_log_queue = queue.Queue()
        self.serial_data_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.serial_thread = None
        self.csv_thread = None
        self.is_connected = False
        self.entries = {} 
        self.tx_state = {} # Stores current TX values
        self.tx_vars = {}
        self.tx_bit_groups = {} # Stores groups for mutual exclusivity

        self.build_ui()
        self.root.after(50, self._system_tick)

    def build_ui(self):
        # 1. Header
        header_frame = tk.Frame(self.root, pady=10, bg="#f5f5f5", relief="groove", borderwidth=1)
        header_frame.pack(side=tk.TOP, fill="x")
        self.create_header(header_frame)

        # 2. Main Area
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Split Main Area: Left (RX) and Right (TX)
        self.paned = tk.PanedWindow(main_frame, orient=tk.HORIZONTAL, sashwidth=4, bg="#d9d9d9")
        self.paned.pack(fill="both", expand=True)
        
        self.create_rx_area(self.paned)
        self.create_tx_area(self.paned)

        # 3. Log
        log_frame = tk.LabelFrame(self.root, text="System Log", height=120, font=("PT Sans", 10, "bold"))
        log_frame.pack(side=tk.BOTTOM, fill="x", padx=10, pady=10)
        self.log_area = scrolledtext.ScrolledText(log_frame, height=6, state='disabled', font=("Consolas", 9))
        self.log_area.pack(fill="both", expand=True)

    def create_header(self, parent):
        left_container = tk.Frame(parent, bg="#f5f5f5")
        left_container.pack(side=tk.LEFT, padx=20)

        try:
            xbm_data = generate_corrected_xbm(LOGO_RAW_HEX)
            self.logo_img = tk.BitmapImage(data=xbm_data, foreground="#0055A6", background="#f5f5f5")
            
            # Create PhotoImage for Window Icon using separate bitmap (32x32)
            self.icon_img = tk.PhotoImage(width=ICON_WIDTH, height=ICON_HEIGHT)
            icon_data = []
            bytes_per_row = ICON_WIDTH // 8
            
            for r in range(ICON_HEIGHT):
                row_colors = []
                for c in range(bytes_per_row):
                    idx = r * bytes_per_row + c
                    if idx < len(ICON_RAW_HEX):
                        b = ICON_RAW_HEX[idx]
                        # MSB First
                        for bit in range(7, -1, -1):
                            color = "#0055A6" if (b >> bit) & 1 else "#f5f5f5"
                            row_colors.append(color)
                icon_data.append(row_colors)
            
            self.icon_img.put(icon_data)
            self.root.iconphoto(True, self.icon_img)
            
            logo_label = tk.Label(left_container, image=self.logo_img, bg="#f5f5f5")
            logo_label.pack(side=tk.LEFT, padx=(0, 15))
        except Exception as e:
            tk.Label(left_container, text="[DECIBELS]", font=("PT Sans", 16, "bold"), bg="#ddd").pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(left_container, text="QC TEST APPLICATION", font=("PT Sans", 20, "bold"), fg="#333", bg="#f5f5f5").pack(side=tk.LEFT)

        right_container = tk.Frame(parent, bg="#f5f5f5")
        right_container.pack(side=tk.RIGHT, padx=20)

        # --- LOGGING CONTROLS ---
        self.lbl_log_status = tk.Label(right_container, text="Log: IDLE", font=("PT Sans", 9), fg="gray", bg="#f5f5f5")
        self.lbl_log_status.pack(side=tk.LEFT, padx=(0, 10))

        self.btn_record = tk.Button(right_container, text="START LOGGING", command=self._toggle_recording, 
                                  bg="#e6f7ff", font=("PT Sans", 9, "bold"), width=14, state="disabled")
        self.btn_record.pack(side=tk.LEFT, padx=(0, 15))

        tk.Frame(right_container, width=1, bg="#cccccc").pack(side=tk.LEFT, fill="y", padx=(0, 15), pady=5)

        tk.Label(right_container, text="COM port:", bg="#f5f5f5", font=("PT Sans", 11)).pack(side=tk.LEFT, padx=(0,5))
        self.port_combo = ttk.Combobox(right_container, width=12, font=("PT Sans", 10))
        self.port_combo.pack(side=tk.LEFT)
        
        self.btn_refresh = tk.Button(right_container, text="⟳", command=self._scan_ports, 
                                   font=("Segoe UI", 10, "bold"), width=3, bg="#e0e0e0")
        self.btn_refresh.pack(side=tk.LEFT, padx=(2, 15))
        self._scan_ports()

        tk.Label(right_container, text="Baud rate:", bg="#f5f5f5", font=("PT Sans", 11)).pack(side=tk.LEFT, padx=(0,5))
        self.baud_combo = ttk.Combobox(right_container, values=["9600", "115200", "921600"], width=9, font=("PT Sans", 10))
        self.baud_combo.current(1)
        self.baud_combo.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_connect = tk.Button(right_container, text="Connect", command=self._toggle_connect, 
                                   bg="#dddddd", font=("PT Sans", 10, "bold"), width=12)
        self.btn_connect.pack(side=tk.LEFT)

    def create_rx_area(self, parent):
        rx_container = tk.LabelFrame(parent, text="RX Monitoring", font=("PT Sans", 10, "bold"), padx=5, pady=5)
        self.paned.add(rx_container, minsize=500, stretch="always")
        
        list_frame = tk.Frame(rx_container)
        list_frame.pack(fill="both", expand=True, pady=5)
        canvas = tk.Canvas(list_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        self.scrollable_frame = ttk.Frame(canvas)
        self.scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        headers = [("Parameter Name", 40), ("Current Value", 15), ("Unit", 10)]
        header_font = ("PT Sans", 10, "bold")
        for col, (text, width) in enumerate(headers):
            tk.Label(self.scrollable_frame, text=text, font=header_font, width=width, 
                     anchor="w" if col==0 else "center", bg="#e8e8e8", relief="flat").grid(row=0, column=col, padx=2, pady=2, sticky="ew")

        row_font = ("PT Sans", 10)
        mono_font = ("Consolas", 10)
        
        for idx, h in enumerate(PARSED_HEADERS, start=1):
            bg_color = "#ffffff" if idx % 2 == 0 else "#f9f9f9"
            
            tk.Label(self.scrollable_frame, text=h['name'], anchor="w", bg=bg_color, font=row_font).grid(row=idx, column=0, padx=5, pady=2, sticky="nsew")
            
            entry_frame = tk.Frame(self.scrollable_frame, bg=bg_color)
            entry_frame.grid(row=idx, column=1, padx=2, pady=2, sticky="nsew")
            entry = tk.Entry(entry_frame, width=15, justify="center", font=mono_font, relief="flat", bg=bg_color)
            entry.insert(0, "--")
            entry.configure(state="readonly") 
            entry.pack(pady=2)
            
            key = h.get('key') or h.get('calc_key') or h.get('name')
            self.entries[key] = entry 
            
            tk.Label(self.scrollable_frame, text=h['unit'], fg="#0066cc", bg=bg_color, font=row_font).grid(row=idx, column=2, padx=2, pady=2, sticky="nsew")

        def _on_mousewheel(event): canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        list_frame.bind('<Enter>', lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        list_frame.bind('<Leave>', lambda e: canvas.unbind_all("<MouseWheel>"))

    def create_tx_area(self, parent):
        tx_container = tk.LabelFrame(parent, text="TX Control", font=("PT Sans", 10, "bold"), padx=5, pady=5)
        self.paned.add(tx_container, minsize=300, stretch="never")
        
        # Create Scrollable Canvas for TX
        canvas = tk.Canvas(tx_container, highlightthickness=0)
        scrollbar = ttk.Scrollbar(tx_container, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Mousewheel scrolling for TX
        def _on_mousewheel(event): canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        # Bind to container so it activates when hovering over the TX area
        tx_container.bind('<Enter>', lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        tx_container.bind('<Leave>', lambda e: canvas.unbind_all("<MouseWheel>"))
        
        for field in TX_FRAME_CONFIG:
            f_frame = tk.Frame(scrollable_frame, pady=5)
            f_frame.pack(fill="x", padx=5)
            
            if field['type'] == 'bitfield':
                tk.Label(f_frame, text=field['name'], font=("PT Sans", 10, "bold", "underline")).pack(anchor="w")
                bits_frame = tk.Frame(f_frame)
                bits_frame.pack(fill="x", pady=2)
                
                layout = field.get('layout', 'vertical')
                
                for bit in field['bits']:
                    # Read default state from config, fallback to False
                    is_default = bit.get('default', False)
                    self.tx_state[bit['name']] = is_default
                    
                    if bit['type'] == 'on_off':
                        var = tk.BooleanVar(value=is_default)
                        self.tx_vars[bit['name']] = var
                        
                        if 'group' in bit:
                            grp = bit['group']
                            if grp not in self.tx_bit_groups: self.tx_bit_groups[grp] = []
                            self.tx_bit_groups[grp].append((bit['name'], var))

                        cb = tk.Checkbutton(bits_frame, text=bit['name'], variable=var, 
                                          command=lambda n=bit['name'], v=var: self._on_tx_bool_change(n, v))
                        
                        if layout == 'horizontal': cb.pack(side=tk.LEFT, padx=5)
                        else: cb.pack(anchor="w", padx=5)

                    elif bit['type'] == 'trig':
                        btn = tk.Button(bits_frame, text=bit['name'], bg="#e1e1e1", width=16)
                        # Mouse Down -> Set True & Send
                        btn.bind('<Button-1>', lambda e, n=bit['name']: self._on_tx_trig(n, True))
                        # Mouse Up -> Set False & Send
                        btn.bind('<ButtonRelease-1>', lambda e, n=bit['name']: self._on_tx_trig(n, False))
                        
                        if layout == 'horizontal': btn.pack(side=tk.LEFT, padx=5)
                        else: btn.pack(anchor="w", padx=5, pady=2)

            elif field['type'] == 'choice':
                tk.Label(f_frame, text=f"{field['name']} ({field.get('unit','')})", font=("PT Sans", 10)).pack(side=tk.LEFT)
                
                default_val = field.get('default', 0)
                self.tx_state[field['name']] = default_val
                
                var = tk.DoubleVar(value=default_val)
                opts_frame = tk.Frame(f_frame)
                opts_frame.pack(side=tk.RIGHT, padx=5)
                layout = field.get('layout', 'horizontal')

                for opt in field['options']:
                    rb = tk.Radiobutton(opts_frame, text=str(opt), variable=var, value=opt,
                                      command=lambda n=field['name'], v=var: self._on_tx_choice_change(n, v))
                    if layout == 'vertical': rb.pack(anchor="w")
                    else: rb.pack(side=tk.LEFT)

            elif field['type'] == 'value':
                tk.Label(f_frame, text=f"{field['name']} ({field.get('unit','')})", font=("PT Sans", 10)).pack(side=tk.LEFT)
                
                default_val = field.get('default', 0)
                self.tx_state[field['name']] = default_val
                
                val_frame = tk.Frame(f_frame)
                val_frame.pack(side=tk.RIGHT, padx=5)

                entry = tk.Entry(val_frame, width=10, justify="center")
                entry.insert(0, str(default_val))
                entry.pack(side=tk.LEFT, padx=2)
                
                btn = tk.Button(val_frame, text="Set", font=("Segoe UI", 8), 
                              command=lambda n=field['name'], ent=entry: self._on_tx_val_change(n, ent))
                btn.pack(side=tk.LEFT, padx=2)

                entry.bind('<Return>', lambda e, n=field['name'], ent=entry: self._on_tx_val_change(n, ent))

    def _on_tx_bool_change(self, name, var):
        is_on = var.get()
        self.tx_state[name] = is_on
        
        # Handle Mutual Exclusivity Groups
        if is_on:
            for grp, members in self.tx_bit_groups.items():
                # Check if the changed item is in this group
                if any(m_name == name for m_name, _ in members):
                    # Turn off all others in the group
                    for m_name, m_var in members:
                        if m_name != name:
                            m_var.set(False)
                            self.tx_state[m_name] = False

        self._send_tx_update()

    def _on_tx_choice_change(self, name, var):
        self.tx_state[name] = var.get()
        self._send_tx_update()

    def _on_tx_trig(self, name, state):
        self.tx_state[name] = state
        self._send_tx_update()

    def _on_tx_val_change(self, name, entry_widget):
        try:
            val = float(entry_widget.get())
            self.tx_state[name] = val
            self._send_tx_update()
            entry_widget.config(bg="white")
        except ValueError:
            # Visual feedback for invalid input
            entry_widget.config(bg="#ffcccc")

    def _send_tx_update(self):
        if self.serial_thread and self.is_connected:
            self.serial_thread.send_tx_frame(self.tx_state)

    def _scan_ports(self):
        ports = serial.tools.list_ports.comports()
        self.port_combo['values'] = [p.device for p in ports]
        if not ports: self.port_combo.set("")
        else: self.port_combo.current(0)

    def _toggle_connect(self):
        if not self.is_connected:
            port = self.port_combo.get()
            baud = self.baud_combo.get()
            if not port: return
            
            try:
                self.serial_thread = SerialWorker(port, int(baud), self.serial_data_queue, self.status_queue, self.gui_log_queue)
                self.serial_thread.start()
                self.is_connected = True
                
                self.btn_connect.config(text="Disconnect", bg="#ffcccc")
                self.port_combo.config(state="disabled")
                self.baud_combo.config(state="disabled")
                self.btn_record.config(state="normal")
            except Exception as e:
                self.log_gui(f"Connection Failed: {e}")
                messagebox.showerror("Error", str(e))
        else:
            self._disconnect()

    def _disconnect(self):
        if self.csv_thread: self._toggle_recording()
        if self.serial_thread:
            self.serial_thread.stop()
            self.serial_thread = None
            
        self.is_connected = False
        self.btn_connect.config(text="Connect", bg="#dddddd")
        self.port_combo.config(state="normal")
        self.baud_combo.config(state="normal")
        self.btn_record.config(state="disabled")
        self.log_gui("Disconnected.")

    def _toggle_recording(self):
        if self.csv_thread is None:
            fname = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV Log", "*.csv")], title="Save Log File")
            if fname:
                # 1. Prevent Sleep
                set_system_awake(True)
                
                # 2. Start Logger
                self.csv_thread = CSVLoggerThread()
                self.csv_thread.start_logging(fname)
                self.btn_record.config(text="STOP LOGGING", bg="#ffe6e6")
                self.lbl_log_status.config(text=f"Recording: {os.path.basename(fname)}", fg="red")
                self.log_gui(f"Started logging to {fname} (System Sleep Disabled)")
        else:
            # 1. Stop Logger
            self.csv_thread.stop_logging()
            self.csv_thread = None
            
            # 2. Allow Sleep
            set_system_awake(False)
            
            self.btn_record.config(text="START LOGGING", bg="#e6f7ff")
            self.lbl_log_status.config(text="Log: IDLE", fg="gray")
            self.log_gui("Stopped logging (System Sleep Enabled)")

    def _system_tick(self):
        while not self.gui_log_queue.empty():
            msg = self.gui_log_queue.get_nowait()
            self.log_gui(msg, internal=True)

        while not self.status_queue.empty():
            msg_type, msg_val = self.status_queue.get_nowait()
            if msg_type == "ERROR":
                self._disconnect()
                messagebox.showerror("Connection Error", f"Lost Connection:\n{msg_val}")

        while not self.serial_data_queue.empty():
            rx_time, data = self.serial_data_queue.get_nowait()
            
            if self.csv_thread and self.csv_thread.running:
                self.csv_thread.queue.put((rx_time, data['flat'], data['stats']))

            self._update_gui(data)
            
        self.root.after(50, self._system_tick)

    def _update_gui(self, data):
        flat = data['flat']
        stats = data['stats']
        flat_idx = 0
        
        for h in PARSED_HEADERS:
            key = h.get('key') or h.get('calc_key') or h.get('name')
            if key not in self.entries: continue
            
            val = 0
            val_str = "--"
            
            if h['type'] == 'calc':
                val = stats.get(h['key'], 0)
            elif h['type'] == 'bit':
                val = flat[flat_idx]
                flat_idx += 1
            else:
                val = flat[flat_idx]
                flat_idx += 1
            
            # Dynamic Formatting based on Factor
            if h['type'] == 'bit':
                val_str = "ON" if val else "OFF"
            else:
                val_str = h['fmt'].format(val)
            
            entry = self.entries[key]
            
            # OPTIMIZATION: Only update if value changed to prevent race conditions and reduce flicker
            if entry.get() != val_str:
                entry.configure(state="normal")
                entry.delete(0, tk.END)
                entry.insert(0, val_str)
                entry.configure(state="readonly")

    def log_gui(self, msg, internal=False):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        self.log_area.config(state='normal')
        self.log_area.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_area.see(tk.END)
        self.log_area.config(state='disabled')