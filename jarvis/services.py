import asyncio
import json
import requests
import websockets
import re
from openai import AsyncOpenAI
import config
import state

# --- STT (Deepgram WebSocket) ---
async def start_deepgram_stt():
    url = f"wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate={config.SAMPLE_RATE_MIC}&model=nova-2&smart_format=true&endpointing=500"
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
                    async for msg in ws:
                        res = json.loads(msg)
                        if 'channel' in res:
                            transcript = res['channel']['alternatives'][0]['transcript']
                            if transcript and res['is_final']:
                                if not state.IS_SPEAKING:
                                    print(f"\r[USER] {transcript}")
                                    await state.input_queue.put(f"[USER] {transcript}")

                await asyncio.gather(sender(), receiver())
        except Exception as e:
            print(f"[ERROR] Deepgram Disconnected: {e}. Reconnecting in 2s...")
            await asyncio.sleep(2)

# --- TTS (The Voice Flow Fix) ---
async def stream_tts(text_iterator):
    buffer = ""
    MIN_CHUNK_SIZE = 50 
    
    # --- HELPER: Handle both Async Generators and Standard Lists ---
    async def content_generator():
        if hasattr(text_iterator, '__aiter__'):
            # It is an async generator (OpenAI Stream)
            async for item in text_iterator:
                yield item
        else:
            # It is a standard list/iterator (Static Text)
            for item in text_iterator:
                yield item

    # --- MAIN LOOP ---
    async for chunk in content_generator():
        buffer += chunk
        
        # Only check for splitting if we have enough text OR a newline
        if len(buffer) > MIN_CHUNK_SIZE or "\n" in buffer:
            
            # Look for a sentence ending [.?!] followed by a space
            parts = re.split(r'(?<=[.?!])\s+', buffer, maxsplit=1)
            
            if len(parts) > 1:
                sentence, buffer = parts[0], parts[1]
                if sentence.strip():
                    await _fetch_audio(sentence)

    # Flush whatever is left at the end
    if buffer.strip():
        await _fetch_audio(buffer)

async def _fetch_audio(text):
    url = f"https://api.deepgram.com/v1/speak?model={config.TTS_VOICE}&encoding=linear16&sample_rate=48000&container=none"
    headers = {
        "Authorization": f"Token {config.DEEPGRAM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: _request_stream(url, headers, text))

def _request_stream(url, headers, text):
    with requests.post(url, headers=headers, json={"text": text}, stream=True) as r:
        for chunk in r.iter_content(chunk_size=2048):
            if chunk:
                state.audio_queue.put(chunk)

# --- LLM ---
client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

async def ask_llm(messages, tools=None):
    response = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        tools=tools,
        tool_choice="auto"
    )
    return response.choices[0].message

async def stream_llm_response(messages):
    stream = await client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        stream=True
    )
    async def generator():
        full_text = ""
        print("[JARVIS] ", end="", flush=True)
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
                full_text += text
                print(text, end="", flush=True)
                yield text
        print()
        messages.append({'role': 'assistant', 'content': full_text})
    
    return generator()