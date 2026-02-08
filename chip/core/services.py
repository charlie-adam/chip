import asyncio
import json
import sys
import httpx
import re
import os
import subprocess
import time
import datetime
from google import genai
from google.genai import types
import websockets
import struct

from chip.utils import config
from chip.core import state

from colorama import init, Fore, Style
init(autoreset=True)

client = genai.Client(api_key=config.GEMINI_API_KEY)
httpx_client = httpx.AsyncClient(timeout=10.0)

ACTIVE_CACHE = None

# --- System Utilities ---
def console_listener(loop):
    while True:
        try:
            text = sys.stdin.readline()
            if text.strip():
                payload = {"text": text.strip(), "source": "text"}
                asyncio.run_coroutine_threadsafe(state.input_queue.put(payload), loop)
        except: break

def restart_imcp():
    print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Restarting iMCP to ensure clean connection...{Style.RESET_ALL}")
    subprocess.run(["pkill", "-f", "iMCP"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
    time.sleep(1)
    try:
        subprocess.run(
            ["open", "/Applications/iMCP.app"], 
            check=True, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] iMCP launching... waiting 1s for initialisation...{Style.RESET_ALL}")
        time.sleep(1) 
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Failed to launch iMCP: {e}{Style.RESET_ALL}")

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

STATE_FILE = f"data/{config.STATE_JSON}"

def _get_or_create_cache(system_instruction, tools):
    global ACTIVE_CACHE
    gemini_tools = _convert_tools_to_gemini(tools) if tools else None
    ttl_seconds = f"{config.CACHE_SECONDS}s"

    if ACTIVE_CACHE is None:
        state_data = state._load_state()
        cache_name = state_data.get("cache_name")
        
        if cache_name:
            try:
                # Verify cache actually exists on server
                ACTIVE_CACHE = client.caches.get(name=cache_name)
                print(f"{Fore.GREEN}[CACHE] Resumed: {ACTIVE_CACHE.name}{Style.RESET_ALL}")
            except Exception:
                # Silent fail: Cache expired/deleted. Proceed to create new.
                ACTIVE_CACHE = None

    # 2. Update TTL if cache exists
    if ACTIVE_CACHE:
        try:
            client.caches.update(
                name=ACTIVE_CACHE.name,
                config=types.UpdateCachedContentConfig(ttl=ttl_seconds)
            )
            return ACTIVE_CACHE.name
        except Exception:
            print(f"{Fore.YELLOW}[CACHE] Refresh failed. Recreating...{Style.RESET_ALL}")
            ACTIVE_CACHE = None

    try:
        print(f"{Fore.YELLOW}[CACHE] Creating new Gemini Cache...{Style.RESET_ALL}")
        ACTIVE_CACHE = client.caches.create(
            model=config.LLM_MODEL,
            config=types.CreateCachedContentConfig(
                display_name="chip_session_cache",
                system_instruction=system_instruction,
                tools=gemini_tools,
                ttl=ttl_seconds
            )
        )
        print(f"{Fore.GREEN}[CACHE] Created: {ACTIVE_CACHE.name}{Style.RESET_ALL}")

        state._update_state({
            "cache_name": ACTIVE_CACHE.name,
            "cache_created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        })
        
        return ACTIVE_CACHE.name

    except Exception as e:
        print(f"{Fore.RED}[ERROR] Cache failed: {e}. Falling back to standard requests.{Style.RESET_ALL}")
        ACTIVE_CACHE = None
        return None

async def start_deepgram_stt():
    url = (
        f"wss://api.deepgram.com/v2/listen?"
        f"model=flux-general-en&"
        f"encoding=linear16&"
        f"sample_rate={config.SAMPLE_RATE_MIC}" 
    )
    
    headers = {"Authorization": f"Token {config.DEEPGRAM_API_KEY}"}
    DIGITAL_GAIN = 3.0

    SILENCE_FRAME = b'\x00' * 9600

    while True:
        try:
            async with websockets.connect(url, additional_headers=headers) as ws:

                async def sender():
                    while True:
                        try:
                            data = await asyncio.wait_for(state.mic_queue.get(), timeout=0.5)
                            
                            if DIGITAL_GAIN != 1.0 and len(data) % 2 == 0:
                                count = len(data) // 2
                                fmt = f"{count}h"
                                samples = list(struct.unpack(fmt, data))
                                boosted = [max(min(int(s * DIGITAL_GAIN), 32767), -32768) for s in samples]
                                data = struct.pack(fmt, *boosted)

                            await ws.send(data)
                            
                        except asyncio.TimeoutError:
                            await ws.send(SILENCE_FRAME)
                            
                        except Exception:
                            break

                async def receiver():
                    async for msg in ws:
                        try:
                            res = json.loads(msg)
                            if res.get("type") == "TurnInfo":
                                event = res.get("event")
                                transcript = res.get("transcript", "")

                                if event == "StartOfTurn":
                                    if hasattr(state, 'is_speaking') and state.is_speaking():
                                        sys.stdout.write(f"{Fore.RED}[INTERRUPT] Stopping TTS...{Style.RESET_ALL}\n")
                                        while not state.audio_queue.empty():
                                            try: state.audio_queue.get_nowait()
                                            except: pass
                                    # Fallback if function missing
                                    elif not state.audio_queue.empty():
                                        while not state.audio_queue.empty():
                                            try: state.audio_queue.get_nowait()
                                            except: pass

                                elif event == "Update" and transcript:
                                    sys.stdout.write(f"\r\033[K{Fore.CYAN}[LISTENING] {transcript}{Style.RESET_ALL}")
                                    sys.stdout.flush()

                                elif event == "EndOfTurn" and transcript:
                                    sys.stdout.write(f"\r\033[K") 
                                    print(f"{Fore.GREEN}[USER] {transcript}{Style.RESET_ALL}")
                                    payload = {"text": f"[USER] {transcript}", "source": "voice"}
                                    await state.input_queue.put(payload)

                        except Exception as e:
                            print(f"{Fore.RED}[ERROR] Parse: {e}{Style.RESET_ALL}")

                await asyncio.gather(sender(), receiver())

        except Exception as e:
            print(f"{Fore.RED}[ERROR] Deepgram Disconnected: {e}. Reconnecting in 2s...{Style.RESET_ALL}")
            await asyncio.sleep(2)

async def stream_tts(text_iterator):
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
        async with httpx_client.stream("POST", url, headers=headers, json={"text": text}) as r:
            async for chunk in r.aiter_bytes(chunk_size=2048):
                if chunk:
                    state.audio_queue.put(chunk)
    except Exception as e:
        print(f"{Fore.RED}[ERROR] TTS Streaming failed: {e}{Style.RESET_ALL}")
    finally:
        state.set_speaking(False)

async def ask_llm_stream(history, system_instruction=None, tools=None):
    
    # 1. Try to use Cache
    cache_name = _get_or_create_cache(system_instruction, tools)
    
    generate_config = None

    if cache_name:
        generate_config = types.GenerateContentConfig(
            cached_content=cache_name,
            temperature=0.7
        )
    else:
        gemini_tools = _convert_tools_to_gemini(tools) if tools else None
        generate_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            temperature=0.7
        )

    stream = await client.aio.models.generate_content_stream(
        model=config.LLM_MODEL,
        contents=history,
        config=generate_config
    )

    accumulated_parts = []
    text_buffer = ""
    printed_usage = False

    async for chunk in stream:
        if chunk.usage_metadata and not printed_usage:
            u = chunk.usage_metadata
            cached = u.cached_content_token_count if hasattr(u, 'cached_content_token_count') else 0
            new_bits = u.prompt_token_count - cached
            # print(f"\n\033[92m[METRICS] Total Context: {u.prompt_token_count} | Cached: {cached} | Billed: {new_bits} | Output: {u.candidates_token_count}\033[0m")
            printed_usage = True

        if chunk.candidates and chunk.candidates[0].content.parts:
            for part in chunk.candidates[0].content.parts:
                accumulated_parts.append(part)
                
                if part.text:
                    text_buffer += part.text
                    
                    sentences = re.split(r'(?<=[.?!])\s+', text_buffer)
                    
                    if len(sentences) > 1:
                        for sentence in sentences[:-1]:
                            if sentence.strip():
                                yield {"type": "text", "content": sentence.strip()}
                        text_buffer = sentences[-1]

    if text_buffer.strip():
        yield {"type": "text", "content": text_buffer.strip()}
    
    yield {"type": "complete_message", "content": accumulated_parts}

async def ask_llm(history, system_instruction=None, tools=None):
    cache_name = _get_or_create_cache(system_instruction, tools)
    generate_config = None

    if cache_name:
        generate_config = types.GenerateContentConfig(
            cached_content=cache_name,
            temperature=0.7
        )
    else:
        gemini_tools = _convert_tools_to_gemini(tools) if tools else None
        generate_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=gemini_tools,
            temperature=0.7
        )

    response = await client.aio.models.generate_content(
        model=config.LLM_MODEL,
        contents=history,
        config=generate_config
    )
    
    if response.usage_metadata:
        u = response.usage_metadata
        cached = u.cached_content_token_count if hasattr(u, 'cached_content_token_count') else 0
        new_bits = u.prompt_token_count - cached
        # print(f"\033[92m[METRICS] Total Context: {u.prompt_token_count} | Cached: {cached} | Billed: {new_bits} | Output: {u.candidates_token_count}\033[0m")
    
    return response
