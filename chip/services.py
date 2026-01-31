import asyncio
import json
import sys
import requests
import websockets
import re
import os
from google import genai
from google.genai import types

import config
import state

# --- Client Initialization ---
# The new SDK handles async via the .aio attribute
client = genai.Client(api_key=config.GEMINI_API_KEY)

# --- Tool Conversion ---
def _convert_tools_to_gemini(openai_tools):
    """Converts OpenAI-formatted tools to Gemini types.Tool, sanitizing parameters."""
    if not openai_tools:
        return None
    
    declarations = []
    for tool in openai_tools:
        f = tool['function']
        
        params = f.get('parameters', {}).copy()
        if '$schema' in params:
            del params['$schema']
            
        declarations.append(types.FunctionDeclaration(
            name=f['name'],
            description=f.get('description'),
            parameters=params 
        ))
        
    return [types.Tool(function_declarations=declarations)]

# --- STT (Deepgram) ---
async def start_deepgram_stt():
    url = f"wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate={config.SAMPLE_RATE_MIC}&model=nova-2&smart_format=true&endpointing=true"
    headers = {"Authorization": f"Token {config.DEEPGRAM_API_KEY}"}

    try:
        connect = websockets.connect(url, additional_headers=headers)
    except TypeError:
        connect = websockets.connect(url, extra_headers=headers)

    while True:
        try:
            print("[SYSTEM] Connecting to Deepgram STT...")
            async with connect as ws:
                print("[SYSTEM] Deepgram Connected.")
                
                async def sender():
                    while True:
                        data = await state.mic_queue.get()
                        await ws.send(data)

                async def receiver():
                    buffer = []
                    last_activity = asyncio.get_event_loop().time()
                    TURN_TIMEOUT = config.SILENCE_THRESHOLD

                    async def flush_loop():
                        nonlocal last_activity
                        while True:
                            await asyncio.sleep(0.1)
                            silence_duration = asyncio.get_event_loop().time() - last_activity
                            
                            if buffer and silence_duration > TURN_TIMEOUT:
                                full_text = " ".join(buffer).strip()
                                buffer.clear()
                                if full_text:
                                    sys.stdout.write("\r\033[K")
                                    print(f"[USER] {full_text}")
                                    await state.input_queue.put(f"[USER] {full_text}")
                            
                            elif buffer and silence_duration > 0.5:
                                remaining = round(TURN_TIMEOUT - silence_duration, 1)
                                sys.stdout.write(f"\r[WAITING {remaining}s] {' '.join(buffer)}")
                                sys.stdout.flush()

                    asyncio.create_task(flush_loop())

                    async for msg in ws:
                        res = json.loads(msg)
                        if 'channel' in res:
                            alt = res['channel']['alternatives'][0]
                            transcript = alt['transcript'].strip()
                            if transcript:
                                last_activity = asyncio.get_event_loop().time()
                                if res.get('is_final'):
                                    buffer.append(transcript)
                                else:
                                    current_text = " ".join(buffer) + " " + transcript
                                    sys.stdout.write(f"\r[LISTENING] {current_text}")
                                    sys.stdout.flush()
                        
                await asyncio.gather(sender(), receiver())
        except Exception as e:
            print(f"[ERROR] Deepgram Disconnected: {e}. Reconnecting in 2s...")
            await asyncio.sleep(2)

# --- TTS ---
async def stream_tts(text_iterator):
    buffer = ""
    MIN_CHUNK_SIZE = 50 
    
    async def content_generator():
        if hasattr(text_iterator, '__aiter__'):
            async for item in text_iterator:
                yield item
        else:
            for item in text_iterator:
                yield item

    async for chunk in content_generator():
        buffer += chunk
        if len(buffer) > MIN_CHUNK_SIZE or "\n" in buffer:
            parts = re.split(r'(?<=[.?!])\s+', buffer, maxsplit=1)
            if len(parts) > 1:
                sentence, buffer = parts[0], parts[1]
                if sentence.strip():
                    await _fetch_audio(sentence)

    if buffer.strip():
        await _fetch_audio(buffer)

async def _fetch_audio(text):
    state.IS_SPEAKING = True
    url = f"https://api.deepgram.com/v1/speak?model={config.TTS_VOICE}&encoding=linear16&sample_rate=48000&container=none"
    headers = {
        "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: _request_stream(url, headers, text))
    finally:
        await asyncio.sleep(0.5)
        state.IS_SPEAKING = False

def _request_stream(url, headers, text):
    with requests.post(url, headers=headers, json={"text": text}, stream=True) as r:
        for chunk in r.iter_content(chunk_size=2048):
            if chunk:
                state.audio_queue.put(chunk)

# --- LLM (New Google GenAI SDK) ---
async def ask_llm(history, system_instruction=None, tools=None):
    """
    Sends history to Gemini using the new genai.Client
    """
    gemini_tools = _convert_tools_to_gemini(tools) if tools else None

    # Configure generation options
    config_params = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=gemini_tools,
        temperature=0.7
    )

    # Use the async client (.aio)
    # Note: 'history' must be a list of types.Content or compatible dicts
    response = await client.aio.models.generate_content(
        model=config.LLM_MODEL,
        contents=history,
        config=config_params
    )
    
    return response

async def stream_llm_response(history, system_instruction=None):
    config_params = types.GenerateContentConfig(
        system_instruction=system_instruction
    )
    
    stream = await client.aio.models.generate_content_stream(
        model=config.LLM_MODEL,
        contents=history,
        config=config_params
    )
    
    async def generator():
        full_text = ""
        print("[CHIP] ", end="", flush=True)
        async for chunk in stream:
            if chunk.text:
                text = chunk.text
                full_text += text
                print(text, end="", flush=True)
                yield text
        print()
    
    return generator()