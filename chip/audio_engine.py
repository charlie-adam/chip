import sounddevice as sd
import numpy as np
import threading
import queue
import asyncio
import time
import state
import config

# Initialize a timestamp in state to track when the bot last stopped speaking
if not hasattr(state, 'last_speech_time'):
    state.last_speech_time = 0

class AudioEngine:
    def __init__(self):
        # FORCE 48kHz for crisp, non-muddy audio
        self.samplerate = 48000 
        self.blocksize = 2048 
        
        self.stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype='int16',
            blocksize=self.blocksize,
            callback=self._callback
        )
        
        self.running = False
        self._leftover_data = b''
        
        # --- Stability Flags ---
        self._is_starting_phrase = True
        self._buffer_threshold = 3  # Wait for 3 chunks before playing (Fixes crackling)
        self._has_started_playing = False

    def start(self):
        self.running = True
        self.stream.start()
        print(f"[SYSTEM] Audio Engine Started @ {self.samplerate}Hz (Anti-Echo Active)")

    def _apply_fade(self, audio_array, direction='in'):
        """Smooths the start/end of audio to prevent speaker 'clicks'"""
        length = len(audio_array)
        if direction == 'in':
            ramp = np.linspace(0, 1, length)
        else:
            ramp = np.linspace(1, 0, length)
        return (audio_array * ramp).astype(np.int16)

    def _callback(self, outdata, frames, time_info, status):
        bytes_needed = frames * 2
        output = b''

        # 1. JITTER BUFFER: Don't start playing until we have enough data
        # This prevents the stream from running dry if internet lags slightly
        if not self._has_started_playing:
            if state.audio_queue.qsize() >= self._buffer_threshold:
                self._has_started_playing = True
            else:
                # Still buffering... play silence
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
            
            # --- We have audio to play ---
            state.IS_SPEAKING = True
            audio_array = np.frombuffer(output, dtype='int16')

            # Fade In (Start of sentence)
            if self._is_starting_phrase:
                audio_array = self._apply_fade(audio_array, 'in')
                self._is_starting_phrase = False

            outdata[:] = audio_array.reshape(-1, 1)

        except queue.Empty:
            # --- Queue is empty (End of sentence) ---
            if len(output) > 0:
                # If we have partial data, pad with zeros
                padding = bytes_needed - len(output)
                output += b'\x00' * padding
                outdata[:] = np.frombuffer(output, dtype='int16').reshape(-1, 1)
            else:
                # COMPLETE SILENCE
                outdata.fill(0)
                
                if state.IS_SPEAKING:
                    # We JUST finished speaking.
                    state.IS_SPEAKING = False
                    state.last_speech_time = time.time() # Start the Cooldown Clock
                    
                    # Reset flags for next time
                    self._is_starting_phrase = True
                    self._has_started_playing = False 

    def stop(self):
        self.running = False
        self.stream.stop()
        self.stream.close()

class Microphone:
    def start(self, device_index):
        asyncio.create_task(self._mic_loop(device_index))

    async def _mic_loop(self, device_index):
        loop = asyncio.get_running_loop()
        
        def callback(indata, frames, time_info, status):
            # 1. Check if bot is currently speaking
            if state.IS_SPEAKING:
                return

            # 2. COOLDOWN CHECK (The Echo Fix)
            # If the bot stopped speaking less than 0.6s ago, ignore input.
            # This lets room reverb die down.
            time_since_speech = time.time() - getattr(state, 'last_speech_time', 0)
            if time_since_speech < 0.6: 
                return

            loop.call_soon_threadsafe(state.mic_queue.put_nowait, indata.tobytes())

        # Note: mic samplerate should usually stay at 16000 or 24000 for STT compatibility
        # unless your STT provider specifically supports 48k input.
        with sd.InputStream(
            device=device_index, 
            channels=1, 
            samplerate=config.SAMPLE_RATE_MIC, 
            dtype='int16', 
            blocksize=2048,
            callback=callback
        ):
            print(f"[SYSTEM] Microphone listening on Device {device_index}")
            while True:
                await asyncio.sleep(1)

def select_microphone():    
    return sd.default.device[0]