import struct
import math
import os
import ctypes
from typing import List, Dict, Any, Tuple
from bms_config import FRAME_CONFIG, TX_FRAME_CONFIG, CALC_GROUPS, HEADER_SIZE

# ==========================================
#           CORE LOGIC & UTILITIES
# ==========================================
def calculate_crc16(data: bytes) -> int:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 1) != 0:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

# --- SYSTEM SLEEP PREVENTION (WINDOWS) ---
ES_CONTINUOUS       = 0x80000000
ES_SYSTEM_REQUIRED  = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

def set_system_awake(enable=True):
    """
    Prevents the system from sleeping while logging is active.
    Works on Windows via kernel32.SetThreadExecutionState.
    """
    if os.name == 'nt':
        try:
            if enable:
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
            else:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
        except:
            pass

def get_precision_fmt(factor):
    """
    Returns a format string (e.g., "{:.4f}") with at least 4 decimal places,
    based on the factor.
    """
    if not factor or factor == 1:
        return "{:.0f}"
    
    # Calculate decimals: -log10(factor)
    try:
        # Calculate required decimals from factor
        calculated_decimals = int(round(-math.log10(factor)))
        if calculated_decimals < 0: calculated_decimals = 0
        
        # Ensure at least 4 decimal places as requested
        final_decimals = max(4, calculated_decimals)
        return "{:." + str(final_decimals) + "f}"
    except:
        return "{:.4f}" # Fallback

class DataParser:
    TYPE_MAP = {'int8':'b', 'uint8':'B', 'int16':'h', 'uint16':'H', 'int32':'i', 'uint32':'I', 'float':'f'}

    @staticmethod
    def prepare_config(config: List[Dict]) -> Tuple[str, List[Dict]]:
        fmt = "<" # Little Endian
        headers = []
        for field in config:
            count = field.get('count', 1)
            fmt += str(count) + DataParser.TYPE_MAP[field['fmt']] if count > 1 else DataParser.TYPE_MAP[field['fmt']]
            
            # Determine format string once based on factor
            f_val = field.get('factor', 1) # Default to 1 if missing
            if 'func' in field:
                fmt_str = "{:.1f}" # Use 1 decimal place for calculated values like Temp
            else:
                fmt_str = get_precision_fmt(f_val)
            
            # Expand Headers
            if 'bits' in field:
                for b in field['bits']: 
                    headers.append({'name': b, 'unit': 'Bit', 'type': 'bit', 'key': b, 'fmt': "{:.0f}"})
            elif count > 1:
                for i in range(count): 
                    headers.append({'name': f"{field['name']} {i+1}", 'unit': field['unit'], 'type': 'val', 'factor': f_val, 'group': field.get('group'), 'fmt': fmt_str})
            else:
                headers.append({'name': field['name'], 'unit': field['unit'], 'type': 'val', 'factor': f_val, 'group': field.get('group'), 'fmt': fmt_str})

        # Add Calc Headers
        for grp, meta in CALC_GROUPS.items():
            # Find the base factor for this group to determine precision
            base_factor = 1.0
            for field in config:
                if field.get('group') == grp:
                    base_factor = field.get('factor', 1.0)
                    break
            
            grp_fmt = get_precision_fmt(base_factor)
            
            for stat in meta['stats']:
                headers.append({'name': f"{grp} {stat.title()}", 'unit': meta['unit'], 'type': 'calc', 'key': f"{grp}_{stat}", 'fmt': grp_fmt})
        
        return fmt, headers

    @staticmethod
    def parse(raw_data: tuple, config: List[Dict]) -> Dict[str, Any]:
        vals = []
        groups = {k: [] for k in CALC_GROUPS.keys()}
        idx = 0
        
        for field in config:
            count = field.get('count', 1)
            chunk = raw_data[idx : idx+count]
            idx += count
            
            if 'bits' in field:
                val = chunk[0]
                for i in range(len(field['bits'])):
                    vals.append((val >> i) & 1)
            else:
                for item in chunk:
                    if 'func' in field:
                        val = field['func'](item)
                    else:
                        val = item * field.get('factor', 1) if field.get('factor') else item
                    vals.append(val)
                    if field.get('group') in groups: groups[field.get('group')].append(val)

        stats = {}
        for grp, values in groups.items():
            if values:
                v_min, v_max = min(values), max(values)
                v_sum = sum(values)
                v_avg = v_sum / len(values)
                
                req_stats = CALC_GROUPS[grp]['stats']
                if 'min' in req_stats: stats[f"{grp}_min"] = v_min
                if 'max' in req_stats: stats[f"{grp}_max"] = v_max
                if 'diff' in req_stats: stats[f"{grp}_diff"] = v_max - v_min
                if 'sum' in req_stats: stats[f"{grp}_sum"] = v_sum
                if 'avg' in req_stats: stats[f"{grp}_avg"] = v_avg
        
        return {'flat': vals, 'stats': stats}

PAYLOAD_FMT, PARSED_HEADERS = DataParser.prepare_config(FRAME_CONFIG)
PAYLOAD_SIZE = struct.calcsize(PAYLOAD_FMT)
CRC_SIZE = 2
TOTAL_SIZE = HEADER_SIZE + PAYLOAD_SIZE + CRC_SIZE

class TxBuilder:
    @staticmethod
    def build_fmt(config: List[Dict]) -> str:
        fmt = "<" # Little Endian
        for field in config:
            fmt += DataParser.TYPE_MAP[field['fmt']]
        return fmt

    @staticmethod
    def pack(data_map: Dict[str, Any], config: List[Dict]) -> bytes:
        values = []
        for field in config:
            if field['type'] == 'bitfield':
                # Pack bits into integer
                val = 0
                for bit_def in field['bits']:
                    if data_map.get(bit_def['name'], False):
                        val |= (1 << bit_def['pos'])
                values.append(val)
            else:
                # Handle Values with Factor
                raw_val = data_map.get(field['name'], field.get('default', 0))
                
                # OPTIMIZATION: Validate numeric input to prevent crashes
                if not isinstance(raw_val, (int, float)):
                    try:
                        raw_val = float(raw_val)
                    except (ValueError, TypeError):
                        raw_val = field.get('default', 0)

                factor = field.get('factor', 1)
                # Inverse factor for TX (Value -> Raw)
                values.append(int(raw_val / factor) if factor != 1 else int(raw_val))
        
        return struct.pack(TxBuilder.build_fmt(config), *values)