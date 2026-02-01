import asyncio
import sys
import threading
import json
import os
import random
import subprocess
import time  # Added for the delay
from contextlib import AsyncExitStack
from google.genai import types

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
sys.path.append(os.path.abspath(os.path.join(current_dir, "../..")))

from mcp.client.stdio import stdio_client
from mcp import ClientSession
from google.genai import types

from chip.utils import smalls
from chip.utils import config
from chip.core import state
from chip.audio import audio_engine
from chip.core import services
from chip.utils import tools_handler
from chip.core import context_manager

FILLERS = [
    "Working on it.", "One moment.", "Just a second.", "Let me check.",
    "Processing.", "Getting that for you.", "Hold on a moment.",
    "I'll find out.", "Let me see.", "Checking now."
]

def console_listener(loop):
    while True:
        try:
            text = sys.stdin.readline()
            if text.strip():
                asyncio.run_coroutine_threadsafe(state.input_queue.put(text.strip()), loop)
        except: break

def restart_imcp():
    """
    1. Force kills iMCP and its server to clear any zombie states.
    2. Relaunches the app.
    3. Waits for it to be ready.
    """
    print("[SYSTEM] Restarting iMCP to ensure clean connection...")
    
    subprocess.run(["pkill", "-f", "iMCP"], stderr=subprocess.DEVNULL)
    subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
    
    time.sleep(1) # Wait for death
    
    try:
        subprocess.run(["open", "/Applications/iMCP.app"], check=True)
        
        print("[SYSTEM] iMCP launching... waiting 2s for initialization...")
        time.sleep(2) 
        
    except Exception as e:
        print(f"[ERROR] Failed to launch iMCP: {e}")

async def main():
    restart_imcp()

    personality_text, last_summary = context_manager.load_context()
    
    full_system_prompt = f"{config.SYSTEM_PROMPT}\n\n### CURRENT PERSONALITY SETTINGS:\n{personality_text}\n\n### PREVIOUS SESSION MEMORY:\n{last_summary}"

    mic_id = audio_engine.select_microphone()
    engine = audio_engine.AudioEngine()
    engine.start() 
    
    mic = audio_engine.Microphone()
    mic.start(mic_id)
    
    asyncio.create_task(services.start_deepgram_stt())
    
    tm = tools_handler.ToolManager(config.MCP_SERVERS)
    all_tools = []
    tool_to_session = {}
    history = []

    try:
        async with AsyncExitStack() as stack:
            for server_name in config.MCP_SERVERS:
                print(f"[SYSTEM] Connecting to {server_name}...")
                params = tm.get_server_params(server_name)
                try:
                    read, write = await stack.enter_async_context(stdio_client(params))
                    session = await stack.enter_async_context(ClientSession(read, write))
                    await session.initialize()
                    
                    mcp_tools_list = await session.list_tools()
                    
                    for tool in mcp_tools_list.tools:
                        if hasattr(tool, "inputSchema"):
                            tool.inputSchema = smalls.clean_schema(tool.inputSchema)

                    formatted_tools = tm.get_openai_tools(mcp_tools_list.tools)
                    
                    for t in mcp_tools_list.tools:
                        tool_to_session[t.name] = session
                    
                    all_tools.extend(formatted_tools)
                except Exception as e:
                    print(f"[ERROR] Failed to connect to {server_name}: {e}")

            print(f"[SYSTEM] Ready. Loaded {len(all_tools)} tools.")
            print(f"[SYSTEM] Loaded Personality: {personality_text[:30]}...")

            loop = asyncio.get_running_loop()
            threading.Thread(target=console_listener, args=(loop,), daemon=True).start()

            while True:
                user_input = await state.input_queue.get()
                
                if getattr(state, "IS_PROCESSING", False):
                    continue
                    
                state.IS_PROCESSING = True
                
                clean_text = user_input.replace("[USER] ", "") if user_input.startswith("[USER]") else user_input
                if not user_input.startswith("[USER]"):
                    print(f"[USER (Text)] {clean_text}")

                history.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_text)]))

                try:
                    has_played_filler = False 

                    for _ in range(5): 
                        response = await services.ask_llm(
                            history, 
                            system_instruction=full_system_prompt, 
                            tools=all_tools
                        )
                        
                        if not response.candidates:
                            print("[ERROR] No candidates returned from Gemini.")
                            break

                        candidate = response.candidates[0]
                        history.append(candidate.content)

                        tool_calls = []
                        
                        for part in candidate.content.parts:
                            if part.text:
                                print(f"[CHIP] {part.text}")
                                await services.stream_tts(iter([part.text]))
                            
                            if part.function_call:
                                tool_calls.append(part.function_call)

                        if not tool_calls:
                            break
                        
                        if not has_played_filler:
                            filler = random.choice(FILLERS)
                            print(f"[CHIP (Filler)] {filler}")
                            await services.stream_tts(iter([filler]))
                            has_played_filler = True

                        response_parts = []
                        
                        for fn in tool_calls:
                            fname = fn.name
                            fargs = fn.args 
                            
                            session = tool_to_session.get(fname)
                            tool_result_str = ""
                            
                            if session:
                                print(f"[TOOL] Executing {fname} with args {fargs}")
                                try:
                                    res = await session.call_tool(fname, fargs)
                                    for content in res.content:
                                        if hasattr(content, 'text'):
                                            tool_result_str += content.text
                                        else:
                                            tool_result_str += str(content)
                                except Exception as e:
                                    tool_result_str = f"Error: {str(e)}"
                            else:
                                tool_result_str = f"Error: Tool {fname} not found."

                            response_parts.append(types.Part.from_function_response(
                                name=fname,
                                response={"result": tool_result_str}
                            ))

                        history.append(types.Content(role="user", parts=response_parts))

                except Exception as e:
                    print(f"[ERROR] LLM Loop: {e}")
                finally:
                    state.IS_PROCESSING = False

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n[SYSTEM] Stopping loop and closing tools...")

    finally:
        if history:
            print("[SYSTEM] Tools closed. Generating session summary...")
            await context_manager.generate_and_save_summary(history, services)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown.")