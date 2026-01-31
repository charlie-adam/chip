import asyncio
import json
import sys
import requests
import websockets
import re
from google import genai
from google.genai.types import (
    Tool, 
    GoogleSearch, 
    GenerateContentConfig, 
    FunctionDeclaration,
    Part,
    Content
)
import config
import state

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

client = genai.Client(api_key=config.GEMINI_API_KEY)

class CompatFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments

class CompatToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = CompatFunction(name, arguments)

class CompatMessage:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

def _convert_to_google_messages(messages):
    google_contents = []
    
    for m in messages:
        role = m["role"]
        content = m.get("content")
        
        if role == "system":
            continue 
        elif role == "assistant":
            role = "model"
        elif role == "tool":
            role = "user" 
        
        parts = []
        
        if content and role != "user" and not m.get("tool_calls"): 
             parts.append(Part(text=content))
        elif content and role == "user":
             parts.append(Part(text=content))

        if "tool_calls" in m and m["tool_calls"]:
            for tc in m["tool_calls"]:
                parts.append(Part(
                    function_call={
                        "name": tc["name"], 
                        "args": json.loads(tc["content"]) if isinstance(tc["content"], str) else {} 
                    }
                ))
        
        if m.get("role") == "tool":
            parts.append(Part(
                function_response={
                    "name": m.get("name"),
                    "response": {"result": content} 
                }
            ))

        if parts:
            google_contents.append(Content(role=role, parts=parts))
            
    return google_contents

async def ask_llm(messages, tools=None):
    google_tools = []
    if tools:
        funcs = []
        for t in tools:
            f_schema = t['function']
            funcs.append(FunctionDeclaration(
                name=f_schema['name'],
                description=f_schema.get('description'),
                parameters=f_schema.get('parameters')
            ))
        
        google_tools = [Tool(
            function_declarations=funcs,
            google_search=GoogleSearch() 
        )]

    system_instruction = None
    if messages and messages[0]['role'] == 'system':
        system_instruction = messages[0]['content']

    contents = _convert_to_google_messages(messages)

    response = await client.aio.models.generate_content(
        model=config.LLM_MODEL,
        contents=contents,
        config=GenerateContentConfig(
            tools=google_tools,
            system_instruction=system_instruction,
            temperature=0.7
        )
    )

    content_text = ""
    tool_calls = []
    
    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if part.text:
                content_text += part.text
            if part.function_call:
                tool_calls.append(CompatToolCall(
                    id="call_" + part.function_call.name,
                    name=part.function_call.name,
                    arguments=json.dumps(part.function_call.args)
                ))

    return CompatMessage(content=content_text, tool_calls=tool_calls)

async def stream_llm_response(messages):
    print("[ERROR] Streaming not fully implemented for new GenAI adapter yet.")
    yield ""