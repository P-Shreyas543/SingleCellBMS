import os
import sys
import subprocess

# Check for Pillow (PIL) for image generation
try:
    from PIL import Image
except ImportError:
    print("Error: 'Pillow' library is required to generate the icon.")
    print("Please run: pip install Pillow")
    sys.exit(1)

from bms_assets import ICON_RAW_HEX, ICON_WIDTH, ICON_HEIGHT

def create_ico():
    """
    Generates logo.ico from the raw hex data in bms_assets.py
    """
    print("Generating logo.ico from assets...")
    
    # Create a new RGBA image (Transparent Background)
    img = Image.new("RGBA", (ICON_WIDTH, ICON_HEIGHT), (255, 255, 255, 0))
    pixels = img.load()

    # Define Colors
    COLOR_FG = (0, 85, 166, 255)   # #0055A6 (Decibels Blue)
    COLOR_BG = (0, 0, 0, 0)        # Transparent

    bytes_per_row = ICON_WIDTH // 8

    for r in range(ICON_HEIGHT):
        for c in range(bytes_per_row):
            idx = r * bytes_per_row + c
            if idx < len(ICON_RAW_HEX):
                byte_val = ICON_RAW_HEX[idx]
                # Process bits MSB first (Bit 7 to 0) to match bms_gui logic
                for bit in range(7, -1, -1):
                    is_set = (byte_val >> bit) & 1
                    
                    # Calculate x coordinate
                    # c is byte index in row, (7-bit) is pixel index in byte
                    x = c * 8 + (7 - bit)
                    y = r
                    
                    if x < ICON_WIDTH and y < ICON_HEIGHT:
                        pixels[x, y] = COLOR_FG if is_set else COLOR_BG

    img.save("logo.ico", format="ICO", sizes=[(32, 32)])
    print("logo.ico created successfully.")

def build_exe():
    print("Starting PyInstaller build...")
    
    main_script = "SingleCellBMS_QC_TestSerialControler.py"
    exe_name = "QC_Test_Application"
    
    # PyInstaller Command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",       # Bundle into a single .exe
        "--windowed",      # No console window
        "--clean",
        f"--icon=logo.ico",
        f"--name={exe_name}",
        main_script
    ]
    
    try:
        subprocess.check_call(cmd)
        print(f"\n[SUCCESS] Build Complete!")
        print(f"Find your app here: {os.path.join(os.getcwd(), 'dist', exe_name + '.exe')}")
    except subprocess.CalledProcessError as e:
        print(f"\n[FAILED] Build Error: {e}")
    except FileNotFoundError:
        print("\n[ERROR] PyInstaller not found. Please run: pip install pyinstaller")

if __name__ == "__main__":
    create_ico()
    build_exe()