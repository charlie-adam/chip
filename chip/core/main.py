import asyncio
import sys
import threading
import json
import os
import random
import subprocess
import time
from contextlib import AsyncExitStack
from google.genai import types

from mcp.client.stdio import stdio_client
from mcp import ClientSession

from chip.utils import smalls, config, tools_handler
from chip.core import state, services, context_manager
from chip.audio import audio_engine

async def main():
    services.restart_imcp()

    personality_text, last_summary = context_manager.load_context()
    full_system_prompt = f"{config.SYSTEM_PROMPT}\n\n### CURRENT PERSONALITY SETTINGS:\n{personality_text}\n\n### PREVIOUS SESSION MEMORY:\n{last_summary}"

    mic_id = audio_engine.select_microphone()
    engine = audio_engine.AudioEngine()
    engine.start() 
    
    mic = audio_engine.Microphone()
    mic.start(mic_id)
    
    asyncio.create_task(services.start_deepgram_stt())
    
    tm = tools_handler.ToolManager(config.MCP_SERVERS)
    all_tools = [config.RESTART_TOOL]
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
            loop = asyncio.get_running_loop()
            threading.Thread(target=services.console_listener, args=(loop,), daemon=True).start()

            while True:
                user_input = await state.input_queue.get()
                if getattr(state, "IS_PROCESSING", False): continue
                state.IS_PROCESSING = True
                
                clean_text = user_input.replace("[USER] ", "") if user_input.startswith("[USER]") else user_input
                if not user_input.startswith("[USER]"):
                    print(f"[USER (Text)] {clean_text}")

                history.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_text)]))

                try:
                    has_played_filler = False 
                    for _ in range(config.MAX_LLM_TURNS): 
                        response = await services.ask_llm(history, system_instruction=full_system_prompt, tools=all_tools)
                        if not response.candidates: break
                        
                        candidate = response.candidates[0]
                        history.append(candidate.content)
                        tool_calls = [p.function_call for p in candidate.content.parts if p.function_call]
                        text_parts = [p.text for p in candidate.content.parts if p.text]

                        for text in text_parts:
                            print(f"[CHIP] {text}")
                            await services.stream_tts(iter([text]))

                        if not tool_calls: break
                        
                        if not has_played_filler:
                            filler = random.choice(config.FILLERS)
                            print(f"[CHIP (Filler)] {filler}")
                            await services.stream_tts(iter([filler]))
                            has_played_filler = True

                        response_parts = []
                        for fn in tool_calls:
                            fname, fargs = fn.name, fn.args 
                            if fname == "restart_system":
                                await services.stream_tts(iter(["Rebooting system now."]))
                                subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
                                if history: await context_manager.generate_and_save_summary(history, services)
                                os.execv(sys.executable, [sys.executable] + sys.argv)

                            session = tool_to_session.get(fname)
                            res_str = ""
                            if session:
                                try:
                                    print(f"[SYSTEM] Calling tool: {fname} with args {fargs}")
                                    res = await session.call_tool(fname, fargs)
                                    res_str = "".join([c.text if hasattr(c, 'text') else str(c) for c in res.content])
                                except Exception as e: res_str = f"Error: {e}"
                            else: res_str = f"Error: Tool {fname} not found."
                            
                            response_parts.append(types.Part.from_function_response(name=fname, response={"result": res_str}))
                        history.append(types.Content(role="user", parts=response_parts))

                except Exception as e: print(f"[ERROR] LLM Loop: {e}")
                finally: state.IS_PROCESSING = False

    finally:
        subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
        if history: await context_manager.generate_and_save_summary(history, services)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n[SYSTEM] Shutdown.")
