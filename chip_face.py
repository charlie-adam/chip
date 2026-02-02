import time
import os
import signal
import sys

FACES = {
    "IDLE": "(•_•)",
    "THINKING": "(0_0)",
    "SPEAKING": "(^▿^)"
}

STATE_FILE = "chip_state.txt"

def get_state():
    if not os.path.exists(STATE_FILE):
        return "IDLE"
    try:
        with open(STATE_FILE, "r") as f:
            return f.read().strip().upper()
    except:
        return "IDLE"

def cleanup(signum, frame):
    os.system('clear')
    if sys.platform == "darwin":
        os.system("osascript -e 'tell application \"Terminal\" to close (every window whose name contains \"ChipFace\") saving no' &")
    sys.exit(0)

def main():
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    last_state = None
    try:
        while True:
            current_state = get_state()
            if current_state not in FACES:
                current_state = "IDLE"
            
            if current_state != last_state:
                os.system('clear')
                print("\n\n")
                print(FACES[current_state])
                print("\n" + current_state)
                last_state = current_state
            
            time.sleep(0.5)
    except Exception:
        cleanup(None, None)

if __name__ == "__main__":
    main()
