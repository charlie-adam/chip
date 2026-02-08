import struct
import asyncio
import time
import queue
import numpy as np
import sounddevice as sd
import pvporcupine 

from colorama import Fore, Style, init
from chip.core import state
from chip.utils import config

init(autoreset=True)

if not hasattr(state, 'last_speech_time'):
    state.last_speech_time = 0

class AudioEngine:
    def __init__(self):
        self.samplerate = config.SAMPLE_RATE_TTS
        self.blocksize = getattr(config, 'BLOCK_SIZE', 4096)
        
        device_idx = None
        preferred = getattr(config, "PREFERRED_OUTPUT_DEVICE", None)
        if preferred:
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if preferred.lower() in d["name"].lower() and d["max_output_channels"] > 0:
                    device_idx = i
                    break
        
        self.stream = sd.OutputStream(device=device_idx, 
            samplerate=self.samplerate,
            channels=1,
            dtype='int16',
            blocksize=self.blocksize,
            callback=self._callback
        )
        
        self._leftover_data = b''
        self._is_starting_phrase = True
        self._buffer_threshold = 2
        self._has_started_playing = False

    def start(self):
        self.stream.start()
        print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Audio Output Started @ {self.samplerate}Hz{Style.RESET_ALL}")

    def _apply_fade(self, audio_array, direction='in'):
        length = len(audio_array)
        ramp = np.linspace(0, 1, length) if direction == 'in' else np.linspace(1, 0, length)
        return (audio_array * ramp).astype(np.int16)

    def _callback(self, outdata, frames, time_info, status):
        bytes_needed = frames * 2
        output = b''

        if not self._has_started_playing:
            if state.audio_queue.qsize() >= self._buffer_threshold:
                self._has_started_playing = True
            else:
                outdata.fill(0)
                return

        try:
            while len(output) < bytes_needed:
                if self._leftover_data:
                    chunk = self._leftover_data
                    self._leftover_data = b''
                else:
                    chunk = state.audio_queue.get_nowait()
                output += chunk

            if len(output) > bytes_needed:
                self._leftover_data = output[bytes_needed:]
                output = output[:bytes_needed]
            
            state.IS_SPEAKING = True
            audio_array = np.frombuffer(output, dtype='int16')

            if self._is_starting_phrase:
                audio_array = self._apply_fade(audio_array, 'in')
                self._is_starting_phrase = False

            outdata[:] = audio_array.reshape(-1, 1)

        except queue.Empty:
            if len(output) > 0:
                padding = bytes_needed - len(output)
                output += b'\x00' * padding
                outdata[:] = np.frombuffer(output, dtype='int16').reshape(-1, 1)
            else:
                outdata.fill(0)
                
                if state.IS_SPEAKING:
                    state.IS_SPEAKING = False
                    
                    self._is_starting_phrase = True
                    self._has_started_playing = False 

    def stop(self):
        self.stream.stop()
        self.stream.close()

class Microphone:
    def __init__(self):
        try:
            self.porcupine = pvporcupine.create(
                access_key=config.PICOVOICE_ACCESS_KEY,
                # keywords=["computer"]
                keyword_paths=[config.KEYWORD_FILE_PATH] 
            )
            self.pcm_buffer = [] 
            print(f"{Fore.GREEN}[SYSTEM] Wake Word Active: 'Hey Chip'{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}[ERROR] Porcupine Init Failed: {e}{Style.RESET_ALL}")
            self.porcupine = None

    def start(self, device_index):
        asyncio.create_task(self._mic_loop(device_index))

    async def _mic_loop(self, device_index):
        loop = asyncio.get_running_loop()
        
        def callback(indata, frames, time_info, status):
            if state.IS_SPEAKING:
                return

            if self.porcupine:
                pcm_chunk = struct.unpack_from("h" * frames, indata)
                self.pcm_buffer.extend(pcm_chunk)
                while len(self.pcm_buffer) >= self.porcupine.frame_length:
                    frame = self.pcm_buffer[:self.porcupine.frame_length]
                    self.pcm_buffer = self.pcm_buffer[self.porcupine.frame_length:]
                    result = self.porcupine.process(frame)
                    if result >= 0:
                        print(f"{Fore.YELLOW}[WAKE WORD] Detected!{Style.RESET_ALL}")
                        # Set to 1s ago to capture the "Hey Chip" audio context if needed, 
                        # or set to exactly now.
                        state.last_speech_time = time.time()

            time_since_active = time.time() - getattr(state, 'last_speech_time', 0)
            
            if time_since_active < 10.0:
                loop.call_soon_threadsafe(state.mic_queue.put_nowait, indata.tobytes())

        with sd.InputStream(
            device=device_index, 
            channels=1, 
            samplerate=config.SAMPLE_RATE_MIC, 
            dtype='int16', 
            blocksize=config.BLOCK_SIZE,
            callback=callback
        ):
            while True:
                await asyncio.sleep(1) 

def select_microphone():    
    preferred = getattr(config, "PREFERRED_INPUT_DEVICE", None)
    if preferred:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if preferred.lower() in d["name"].lower() and d["max_input_channels"] > 0:
                return i
    return sd.default.device[0]