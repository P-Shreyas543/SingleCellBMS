import math

# ==========================================
#        ASSETS & VISUAL CONFIG
# ==========================================
# (Assets moved to bms_assets.py)

# ==========================================
#        MASTER CONFIGURATION
# ==========================================
# --- PROTOCOL ---
TX_SYNC_HEADER = b'\xAA\x55'
RX_SYNC_HEADER = b'\xAA\x55'
HEADER_SIZE    = len(RX_SYNC_HEADER)

# --- FRAME DEFINITIONS ---
# Conversion factors based on a 12-bit ADC (4096 steps)
ADC_VREF = 3  # Volts. Change this if your MCU reference voltage is different.
ADC_RESOLUTION = 4095
VOLTAGE_FACTOR = ADC_VREF / ADC_RESOLUTION

# Current Sensing Config
SHUNT_RESISTOR = 0.006  # 6 mOhms
AMPLIFIER_GAIN = 66.6
CURRENT_FACTOR = VOLTAGE_FACTOR / (SHUNT_RESISTOR * AMPLIFIER_GAIN)

# NTC Configuration
R_FIXED = 6800.0    # 6.8k Ohm Fixed Resistor
R_25    = 10000.0   # 10k Ohm NTC at 25C
BETA    = 3950.0    # Beta Value
T_25    = 298.15    # 25C in Kelvin

def ntc_celsius(adc_val):
    if adc_val == 0 or adc_val >= ADC_RESOLUTION: return -40.0 # Fault/Open
    # Calculate Resistance (Assuming NTC to Ground, Pull-up to Vref)
    r_ntc = R_FIXED * (adc_val / (ADC_RESOLUTION - adc_val))
    return (1 / ((1/T_25) + (math.log(r_ntc/R_25)/BETA))) - 273.15

FRAME_CONFIG = [
    # --- VOLTAGE READINGS ---
    {'name': 'Cell 1 Voltage', 'fmt': 'uint32', 'unit': 'V', 'factor': VOLTAGE_FACTOR*2},
    {'name': 'Cell 2 Voltage', 'fmt': 'uint32', 'unit': 'V', 'factor': VOLTAGE_FACTOR*2},
    {'name': 'Load Sense Voltage', 'fmt': 'uint32', 'unit': 'V', 'factor': VOLTAGE_FACTOR*2},
    {'name': 'Vin Sense Voltage', 'fmt': 'uint32', 'unit': 'V', 'factor': VOLTAGE_FACTOR*6},
    {'name': 'Charge Sense Voltage', 'fmt': 'uint32', 'unit': 'V', 'factor': VOLTAGE_FACTOR*2},
    {'name': 'Charge Current', 'fmt': 'uint32', 'unit': 'A', 'factor': CURRENT_FACTOR},
    {'name': 'Discharge Current', 'fmt': 'uint32', 'unit': 'A', 'factor': CURRENT_FACTOR},
    # --- TEMPERATURE READINGS (as voltage from NTC divider) ---
    {'name': 'Temp NTC 1', 'fmt': 'uint32', 'unit': '°C', 'func': ntc_celsius},
    {'name': 'Temp NTC 2', 'fmt': 'uint32', 'unit': '°C', 'func': ntc_celsius},
    {'name': 'Temp NTC 3', 'fmt': 'uint32', 'unit': '°C', 'func': ntc_celsius},
    {'name': 'Temp NTC 4', 'fmt': 'uint32', 'unit': '°C', 'func': ntc_celsius},
    {'name': 'Temp NTC 5', 'fmt': 'uint32', 'unit': '°C', 'func': ntc_celsius},
    # --- STATUS FLAGS ---
    {'name': 'Status Field','fmt': 'uint8', 'unit': 'Bitfield', 'bits': ["Main Charge Status", "Charge Comparator", "Discharge Comparator"]}
]

# --- TX FRAME DEFINITION ---
# Frame Structure (Total 10 Bytes, Little Endian):
# Byte 0: Start Byte (0x5A)
# Byte 1: Power Mode (Bit 0: Discharge, Bit 1: Charge, Bit 2: Standby)
# Byte 2-3: Charge Voltage (mV, uint16)
# Byte 4-5: Charge Current (mA, uint16)
# Byte 6: Load Selector (Bit 0-3: Loads 1-4)
# Byte 7: Actions (Bit 0: Chg Reset, Bit 1: Dsg Reset)
# Byte 8-9: CRC-16 (Modbus)
TX_FRAME_CONFIG = [
    # CASE 1: Vertical Bitfield with Mutual Exclusivity
    # USE CASE: Mode selection where only one state is valid at a time (e.g., Power State).
    # GUI BEHAVIOR: Renders as a group of checkboxes. Selecting one automatically deselects others in the same 'group'.
    {'name': 'Relay Selection', 'fmt': 'uint8', 'type': 'bitfield', 'layout': 'vertical', 'bits': [
        {'name': 'Cell Enable Relay',   'type': 'on_off', 'pos': 2},
        {'name': 'Cell 1 Select',    'type': 'on_off', 'pos': 1, 'group': 'cell_select', 'default': True},
        {'name': 'Cell 2 Select',    'type': 'on_off', 'pos': 0, 'group': 'cell_select'},
    ]},
    
    
    {'name': 'Power Mode', 'fmt': 'uint8', 'type': 'bitfield', 'layout': 'vertical', 'bits': [
        {'name': 'Charge',    'type': 'on_off', 'pos': 1, 'group': 'power_mode'},
        {'name': 'Discharge', 'type': 'on_off', 'pos': 0, 'group': 'power_mode'},
        {'name': 'Standby',   'type': 'on_off', 'pos': 2, 'group': 'power_mode', 'default': True},
    ]},

    # CASE 2: Horizontal Choice (Pre-defined Options)
    # USE CASE: Selecting specific, safe voltage thresholds.
    # GUI BEHAVIOR: Renders as a horizontal row of Radio Buttons.
    {'name': 'Charge Voltage', 'fmt': 'uint16', 'type': 'choice', 'unit': 'V', 'factor': 0.001, 
     'options': [3.6, 4.2], 'default': 3.6, 'layout': 'horizontal'},
     
    # CASE 3: Horizontal Choice (Pre-defined Options)
    # USE CASE: Selecting specific current limits.
    # GUI BEHAVIOR: Renders as a horizontal row of Radio Buttons.
    {'name': 'Charge Current', 'fmt': 'uint16', 'type': 'choice', 'unit': 'A', 'factor': 0.001, 
     'options': [0.5, 1.0, 1.5], 'default': 0.5, 'layout': 'horizontal'},

    # CASE 4: Horizontal Bitfield (Independent Toggles)
    # USE CASE: Controlling multiple independent loads or switches (e.g., GPIOs).
    # GUI BEHAVIOR: Renders as a row of independent Checkboxes.
    {'name': 'Load Selector', 'fmt': 'uint8', 'type': 'bitfield', 'layout': 'horizontal', 'bits': [
        {'name': 'L(1)',  'type': 'on_off', 'pos': 0},
        {'name': 'L(2)',  'type': 'on_off', 'pos': 1},
        {'name': 'L(3)',  'type': 'on_off', 'pos': 2},
        {'name': 'L(4)',  'type': 'on_off', 'pos': 3},
    ]},

    # CASE 5: Momentary Triggers
    # USE CASE: Sending a temporary signal (pulse) to reset counters or clear faults.
    # GUI BEHAVIOR: Renders as Buttons that set the bit High on press and Low on release.
    {'name': 'Actions', 'fmt': 'uint8', 'type': 'bitfield', 'layout': 'horizontal', 'bits': [
        {'name': 'Charge Reset', 'type': 'trig', 'pos': 0},
        {'name': 'Discharge Reset', 'type': 'trig', 'pos': 1},
    ]},

    # CASE 6: Standard Value Entry (Example - Commented Out)
    # USE CASE: Allowing the user to type a specific numeric value.
    # GUI BEHAVIOR: Renders as a Text Entry box.
    #{'name': 'Custom UVP', 'fmt': 'uint16', 'type': 'value', 'unit': 'V', 'factor': 0.001, 'default': 3.0}
]

# Define CALC_GROUPS to prevent NameError
CALC_GROUPS = {}