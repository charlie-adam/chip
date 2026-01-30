import asyncio
import queue

# Queues
input_queue = asyncio.Queue()  # Text from STT -> LLM
mic_queue = asyncio.Queue()    # Audio from Mic -> Deepgram STT
audio_queue = queue.Queue()    # Audio from TTS -> Speakers

# The "Mute Switch"
# We use a primitive boolean for speed, protected by the Python GIL
IS_SPEAKING = False