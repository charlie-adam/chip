import time
import os

FACES = {
    "IDLE": """
      _______
     |       |
     | -   - |
     |   _   |
     |_______|
""",
    "THINKING": """
      _______
     |       |
     | *   * |
     |   ~   |
     |_______|
""",
    "SPEAKING": """
      _______
     |       |
     | ^   ^ |
     |   O   |
     |_______|
"""
}

STATE_FILE = "chip_state.txt"

def get_state():
    if not os.path.exists(STATE_FILE):
        return "IDLE"
    with open(STATE_FILE, "r") as f:
        return f.read().strip().upper()

def main():
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
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()
