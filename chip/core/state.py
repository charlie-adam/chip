import asyncio
import queue
import os
import json
import time
import datetime

STATE_FILE = os.path.join("data", "chip_state.json")

def _load_state():
    """Safely loads the state JSON, returning an empty dict if missing/corrupt."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}

def _update_state(updates):
    """Merges 'updates' dict into the existing state file."""
    current_data = _load_state()
    current_data.update(updates)
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    
    with open(STATE_FILE, "w") as f:
        json.dump(current_data, f, indent=2)
        
input_queue = asyncio.Queue()  # Text from STT -> LLM
mic_queue = asyncio.Queue()    # Audio from Mic -> Deepgram STT
audio_queue = queue.Queue()    # Audio from TTS -> Speakers