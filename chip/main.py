import asyncio
import sys
import threading
import json
import os
import random
from contextlib import AsyncExitStack

from mcp.client.stdio import stdio_client
from mcp import ClientSession

# New SDK Types
from google.genai import types

import config
import state
import audio_engine
import services
import tools_handler

FILLERS = [
    "One moment, let me check that.",
    "I'll have a quick look.",
    "Just a second.",
    "Processing that for you.",
    "Let me see.",
    "Checking on that.",
    "On it."
]

def console_listener(loop):
    while True:
        try:
            text = sys.stdin.readline()
            if text.strip():
                asyncio.run_coroutine_threadsafe(state.input_queue.put(text.strip()), loop)
        except: break

async def main():
    mic_id = audio_engine.select_microphone()
    engine = audio_engine.AudioEngine()
    engine.start() 
    
    mic = audio_engine.Microphone()
    mic.start(mic_id)
    
    asyncio.create_task(services.start_deepgram_stt())
    
    tm = tools_handler.ToolManager(config.MCP_SERVERS)
    all_tools = []
    tool_to_session = {}

    async with AsyncExitStack() as stack:
        for server_name in config.MCP_SERVERS:
            print(f"[SYSTEM] Connecting to {server_name}...")
            params = tm.get_server_params(server_name)
            try:
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                
                mcp_tools_list = await session.list_tools()
                # Get OpenAI format tools
                formatted_tools = tm.get_openai_tools(mcp_tools_list.tools)
                
                for t in mcp_tools_list.tools:
                    tool_to_session[t.name] = session
                
                all_tools.extend(formatted_tools)
            except Exception as e:
                print(f"[ERROR] Failed to connect to {server_name}: {e}")

        print(f"[SYSTEM] Ready. Loaded {len(all_tools)} tools.")

        loop = asyncio.get_running_loop()
        threading.Thread(target=console_listener, args=(loop,), daemon=True).start()

        # History: List of types.Content or dicts
        history = []

        while True:
            user_input = await state.input_queue.get()
            
            if getattr(state, "IS_PROCESSING", False):
                continue
                
            state.IS_PROCESSING = True
            
            clean_text = user_input.replace("[USER] ", "") if user_input.startswith("[USER]") else user_input
            if not user_input.startswith("[USER]"):
                print(f"[USER (Text)] {clean_text}")

            # Add User Message to History
            history.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_text)]))

            is_first_tool_pass = True 

            try:
                while True:
                    # 1. Call Gemini
                    response = await services.ask_llm(
                        history, 
                        system_instruction=config.SYSTEM_PROMPT, 
                        tools=all_tools
                    )
                    
                    # 2. Extract Content (First Candidate)
                    # The new SDK response object is cleaner
                    if not response.candidates:
                         print("[ERROR] No candidates returned from Gemini.")
                         break

                    candidate = response.candidates[0]
                    model_content = candidate.content
                    
                    # 3. Process Parts
                    has_tool_calls = False
                    model_parts = []
                    
                    # Iterate through the model's returned parts
                    for part in model_content.parts:
                        model_parts.append(part) # Keep track of what the model said/requested
                        
                        # Handle Function Calls
                        if part.function_call:
                            has_tool_calls = True
                            fn = part.function_call
                            fname = fn.name
                            fargs = fn.args # args is already a dict in new SDK
                            
                            if is_first_tool_pass:
                                filler = random.choice(FILLERS)
                                print(f"[CHIP (Filler)] {filler}")
                                await services.stream_tts(iter([filler]))
                                is_first_tool_pass = False
                            
                            session = tool_to_session.get(fname)
                            tool_result_str = ""
                            
                            if session:
                                print(f"[TOOL] Executing {fname}...")
                                try:
                                    res = await session.call_tool(fname, fargs)
                                    # MCP Response handling
                                    for content in res.content:
                                        if hasattr(content, 'text'):
                                            tool_result_str += content.text
                                        else:
                                            tool_result_str += str(content)
                                except Exception as e:
                                    tool_result_str = f"Error: {str(e)}"
                            else:
                                tool_result_str = f"Error: Tool {fname} not found."
                            
                            # Add the function call (Model) to history
                            history.append(types.Content(role="model", parts=model_parts))
                            model_parts = [] # Reset for next turn or next part
                            
                            # Add the function response (User/Function) to history
                            # New SDK prefers explicit function_response part
                            response_part = types.Part.from_function_response(
                                name=fname,
                                response={"result": tool_result_str}
                            )
                            history.append(types.Content(role="user", parts=[response_part]))
                            
                        # Handle Text
                        elif part.text:
                            print(f"[CHIP] {part.text}")
                            await services.stream_tts(iter([part.text]))

                    # If no tools were called, we are finished with this turn
                    if not has_tool_calls:
                        # Add final model text to history
                        if model_parts:
                            history.append(types.Content(role="model", parts=model_parts))
                        break
                    
                    # If tools WERE called, the loop continues (Gemini sees the response in history)

            except Exception as e:
                print(f"[ERROR] LLM Loop: {e}")
            finally:
                state.IS_PROCESSING = False

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown.")