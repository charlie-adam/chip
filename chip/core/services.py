import asyncio
import json
import sys
import httpx
import websockets
import re
import os
import subprocess
import time
from google import genai
from google.genai import types

from chip.utils import config
from chip.core import state

# --- Client Initialization ---
client = genai.Client(api_key=config.GEMINI_API_KEY)

# --- System Utilities ---
def console_listener(loop):
    while True:
        try:
            text = sys.stdin.readline()
            if text.strip():
                asyncio.run_coroutine_threadsafe(state.input_queue.put(text.strip()), loop)
        except: break
    

def console_listener(loop):
    while True:
        try:
            text = sys.stdin.readline()
            if text.strip():
                # Change: Wrap in dict with source
                payload = {"text": text.strip(), "source": "text"}
                asyncio.run_coroutine_threadsafe(state.input_queue.put(payload), loop)
        except: break

def restart_imcp():
    print("[SYSTEM] Restarting iMCP to ensure clean connection...")
    subprocess.run(["pkill", "-f", "iMCP"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        subprocess.run(["open", "/Applications/iMCP.app"], check=True)
        print("[SYSTEM] iMCP launching... waiting 2s for initialization...")
        time.sleep(2) 
    except Exception as e:
        print(f"[ERROR] Failed to launch iMCP: {e}")

# --- Tool Conversion ---
def _convert_tools_to_gemini(openai_tools):
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
                        try:
                            data = await asyncio.wait_for(state.mic_queue.get(), timeout=3.0)
                            await ws.send(data)
                        except asyncio.TimeoutError:
                            await ws.send(json.dumps({"type": "KeepAlive"}))
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
                                    payload = {"text": f"[USER] {full_text}", "source": "voice"}
                                    await state.input_queue.put(payload)
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
    """
    Receives an iterator of COMPLETE sentences/phrases and streams audio.
    """
    async def content_generator():
        if hasattr(text_iterator, '__aiter__'):
            async for item in text_iterator:
                yield item
        else:
            for item in text_iterator:
                yield item
                
    async for text_chunk in content_generator():
        if not text_chunk.strip(): continue
        await _fetch_audio(text_chunk)

async def _fetch_audio(text):
    state.set_speaking(True)
    url = f"https://api.deepgram.com/v1/speak?model={config.TTS_VOICE}&encoding=linear16&sample_rate={config.SAMPLE_RATE_TTS}&container=none"
    headers = {
        "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        async with httpx.AsyncClient() as client_http:
            async with client_http.stream("POST", url, headers=headers, json={"text": text}) as r:
                async for chunk in r.aiter_bytes(chunk_size=2048):
                    if chunk:
                        state.audio_queue.put(chunk)
    except Exception as e:
        print(f"[ERROR] TTS Streaming failed: {e}")
    finally:
        await asyncio.sleep(0.1) 
        state.set_speaking(False)

# --- LLM ---
async def ask_llm_stream(history, system_instruction=None, tools=None):
    gemini_tools = _convert_tools_to_gemini(tools) if tools else None
    
    stream = await client.aio.models.generate_content_stream(
        model=config.LLM_MODEL,
        contents=history,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            temperature=0.7
        )
    )

    accumulated_parts = []
    text_buffer = ""

    async for chunk in stream:
        if chunk.candidates and chunk.candidates[0].content.parts:
            for part in chunk.candidates[0].content.parts:
                accumulated_parts.append(part)

        if chunk.text:
            text = chunk.text
            text_buffer += text
            
            sentences = re.split(r'(?<=[.?!])\s+', text_buffer)
            
            if len(sentences) > 1:
                # Yield all COMPLETE sentences
                for sentence in sentences[:-1]:
                    if sentence.strip():
                        yield {"type": "text", "content": sentence.strip()}
                text_buffer = sentences[-1]
    if text_buffer.strip():
        yield {"type": "text", "content": text_buffer.strip()}
    yield {"type": "complete_message", "content": accumulated_parts}

async def ask_llm(history, system_instruction=None, tools=None):
    gemini_tools = _convert_tools_to_gemini(tools) if tools else None
    config_params = types.GenerateContentConfig(
        system_instruction=system_instruction,
        tools=gemini_tools,
        temperature=0.7
    )
    response = await client.aio.models.generate_content(
        model=config.LLM_MODEL,
        contents=history,
        config=config_params
    )
    return response