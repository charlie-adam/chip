import asyncio
import queue

# Queues
input_queue = asyncio.Queue()  # Text from STT -> LLM
mic_queue = asyncio.Queue()    # Audio from Mic -> Deepgram STT
audio_queue = queue.Queue()    # Audio from TTS -> Speakers

# Internal states
IS_SPEAKING = False
IS_PROCESSING = False

def update_ui():
    state_val = "IDLE"
    if IS_SPEAKING:
        state_val = "SPEAKING"
    elif IS_PROCESSING:
        state_val = "THINKING"
    
    try:
        # Using an absolute-ish path or relative to the root
        with open("chip_state.txt", "w") as f:
            f.write(state_val)
    except Exception as e:
        print(f"[ERROR] Failed to update state file: {e}")

def set_processing(val):
    global IS_PROCESSING
    IS_PROCESSING = val
    update_ui()

def set_speaking(val):
    global IS_SPEAKING
    IS_SPEAKING = val
    update_ui()
update_ui()
