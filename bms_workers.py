import threading
import queue
import time
import struct
import csv
import os
import datetime
import serial
from bms_config import (
    TX_SYNC_HEADER, RX_SYNC_HEADER, 
    HEADER_SIZE, FRAME_CONFIG, TX_FRAME_CONFIG
)
from bms_utils import (
    calculate_crc16, DataParser, TxBuilder, PAYLOAD_FMT, 
    PARSED_HEADERS, TOTAL_SIZE, CRC_SIZE, PAYLOAD_SIZE
)

# ==========================================
#           THREADED MODULES
# ==========================================
class CSVLoggerThread(threading.Thread):
    def __init__(self, log_queue=None):
        super().__init__(daemon=True)
        self.log_queue = log_queue
        self.queue = queue.Queue()
        self.running = False
        self.filename = None
        self.file_handle = None
        self.writer = None
        self._date = None

    def start_logging(self, filename):
        self.filename = os.path.splitext(filename)[0]
        self.running = True
        self.start()

    def stop_logging(self):
        self.running = False
        self.queue.put(None)

    def _rotate(self):
        if self.file_handle: self.file_handle.close()
        current_date = datetime.date.today().isoformat()
        fname = f"{self.filename}_{current_date}.csv"
        
        new_file = not os.path.exists(fname)
        self.file_handle = open(fname, 'a', newline='')
        self.writer = csv.writer(self.file_handle)
        
        if new_file:
            header = ["Timestamp_Sec", "ISO_Time"] + [h['name'] for h in PARSED_HEADERS]
            self.writer.writerow(header)
        self._date = datetime.date.today()

    def run(self):
        while self.running or not self.queue.empty():
            try:
                data_packet = self.queue.get(timeout=1)
                if data_packet is None: break 
                
                if datetime.date.today() != self._date: self._rotate()
                elif not self.file_handle: self._rotate()
                
                ts, flat, stats = data_packet
                iso_time = datetime.datetime.fromtimestamp(ts).isoformat()
                
                # Standardize Timestamp to 3 decimal places
                row = [f"{ts:.3f}", iso_time]
                
                flat_idx = 0
                for h in PARSED_HEADERS:
                    val = 0
                    if h['type'] == 'calc':
                        val = stats.get(h['key'], 0)
                    elif h['type'] == 'bit':
                        val = flat[flat_idx]
                        flat_idx += 1
                    else:
                        val = flat[flat_idx]
                        flat_idx += 1
                    
                    # Apply Dynamic Format String
                    if h['type'] == 'bit':
                        row.append(1 if val else 0)
                    else:
                        row.append(h['fmt'].format(val))

                self.writer.writerow(row)
                self.file_handle.flush() 
            except queue.Empty:
                continue
            except Exception as e:
                if self.log_queue:
                    self.log_queue.put(f"CSV Error: {e}")
                else:
                    print(f"CSV Error: {e}")
        
        if self.file_handle: self.file_handle.close()

class SerialWorker(threading.Thread):
    def __init__(self, port, baud, data_queue, status_queue, log_queue):
        super().__init__(daemon=True)
        self.port = port
        self.baud = baud
        self.data_queue = data_queue
        self.status_queue = status_queue 
        self.log_queue = log_queue
        self.stop_event = threading.Event()
        self.ser = None

    def stop(self):
        self.stop_event.set()
        if self.ser and self.ser.is_open:
            try:
                self.ser.close()
            except: pass

    def send_tx_frame(self, data_map):
        if not self.ser or not self.ser.is_open: return
        try:
            payload = TX_SYNC_HEADER + TxBuilder.pack(data_map, TX_FRAME_CONFIG)
            crc = calculate_crc16(payload)
            frame = payload + struct.pack('>H', crc)
            self.ser.write(frame)
        except Exception as e:
            self.log_queue.put(f"TX Error: {e}")
            self.status_queue.put(("ERROR", f"Transmission Failed: {e}"))

    def run(self):
        buffer = bytearray()
        try:
            self.ser = serial.Serial(self.port, self.baud, timeout=0.05)
            self.log_queue.put(f"Connected to {self.port} @ {self.baud}bps")

            while not self.stop_event.is_set():
                if not self.ser.is_open:
                    raise serial.SerialException("Port closed unexpectedly")

                if self.ser.in_waiting:
                    buffer.extend(self.ser.read(self.ser.in_waiting))
                else:
                    time.sleep(0.001) # Optimization: Low latency sleep (1ms) only when idle

                while len(buffer) >= TOTAL_SIZE:
                    if buffer[:HEADER_SIZE] == RX_SYNC_HEADER:
                        # CRC Check
                        check_data = buffer[:TOTAL_SIZE - CRC_SIZE]
                        rx_crc = struct.unpack('>H', buffer[TOTAL_SIZE - CRC_SIZE:TOTAL_SIZE])[0]
                        calc_crc = calculate_crc16(check_data)

                        if calc_crc != rx_crc:
                            self.log_queue.put(f"CRC Error: Recv {rx_crc:#06x} != Calc {calc_crc:#06x}")
                            del buffer[:1]
                            continue

                        frame = buffer[HEADER_SIZE : HEADER_SIZE + PAYLOAD_SIZE]
                        try:
                            # 1. Capture Time Immediately on Receipt
                            rx_time = time.time()
                            
                            # 2. Parse
                            raw = struct.unpack(PAYLOAD_FMT, frame)
                            processed = DataParser.parse(raw, FRAME_CONFIG)
                            
                            # 3. Queue (Time, Data)
                            self.data_queue.put((rx_time, processed))
                            
                            del buffer[:TOTAL_SIZE]
                        except struct.error:
                            self.log_queue.put("Corrupt Frame. Sync lost.")
                            del buffer[:1]
                    else:
                        del buffer[:1] 

        except (OSError, serial.SerialException):
            self.status_queue.put(("ERROR", "The USB device was unplugged or the COM port became unavailable."))
        except Exception as e:
            self.status_queue.put(("ERROR", f"System Error: {str(e)}"))
        finally:
            if self.ser: self.ser.close()
            self.log_queue.put("Serial Thread Exited")