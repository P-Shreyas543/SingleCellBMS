# Single Cell BMS QC Application

A Python-based Quality Control (QC) application for Single Cell Battery Management Systems. This tool provides a Graphical User Interface (GUI) to monitor BMS parameters via Serial (UART) and log data to CSV files.

## Features

*   **Real-time Monitoring**: View Cell Voltages, Current, and NTC Temperatures.
*   **Serial Communication**: Connects via COM ports with adjustable baud rates.
*   **Data Logging**: Records session data to CSV format with timestamps.
*   **Control Interface**: Toggle relays, power modes, and reset flags directly from the UI.
*   **Visual Feedback**: Color-coded status indicators and error handling.

## Installation

1.  Install Python 3.x.
2.  Install dependencies:
    ```bash
    pip install pyserial pillow
    ```

## Usage

1.  Run the application:
    ```bash
    python bms_gui.py
    ```
2.  Select the correct **COM Port** from the dropdown.
3.  Click **Connect**.
4.  (Optional) Click **START LOGGING** to save data.

## Building the Executable

To create a standalone `.exe` file:
```bash
python build_app.py
```