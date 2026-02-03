import asyncio
import sys
import threading
import os
import random
import subprocess
import time
from contextlib import AsyncExitStack
from google.genai import types

from chip.utils import config, tools_handler, history as history_utils
from chip.core import state, services, context_manager, mcp_connect, routines
from chip.audio import audio_engine

async def main():
    services.restart_imcp()
    
    mic_id = audio_engine.select_microphone()
    engine = audio_engine.AudioEngine()
    engine.start() 
    mic = audio_engine.Microphone()
    mic.start(mic_id)
    asyncio.create_task(services.start_deepgram_stt())

    personality_text, last_summary = context_manager.load_context()
    full_system_prompt = f"{config.SYSTEM_PROMPT}\n\n### SETTINGS:\n{personality_text}\n\n### MEMORY:\n{last_summary}"

    tm = tools_handler.ToolManager(config.MCP_SERVERS)
    base_tools = [config.RESTART_TOOL]
    history = []

    try:
        async with AsyncExitStack() as stack:
            mcp_tools, tool_to_session = await mcp_connect.connect_servers(stack, tm, config.MCP_SERVERS)
            all_tools = base_tools + mcp_tools
            print(f"[SYSTEM] Ready. Loaded {len(all_tools)} tools.")
            
            history = await routines.run_startup_routine(
                services, history, full_system_prompt, all_tools, tool_to_session
            )

            loop = asyncio.get_running_loop()
            threading.Thread(target=services.console_listener, args=(loop,), daemon=True).start()
            services._get_or_create_cache(full_system_prompt, all_tools)
            
            os.system('clear')
            print(f"[SYSTEM] Chip Awake - {time.strftime('%a %d %b %H:%M:%S %Y')}")

            while True:
                input_data = await state.input_queue.get()
                
                user_input = input_data.get("text", "") if isinstance(input_data, dict) else str(input_data)
                should_speak = False if isinstance(input_data, dict) and input_data.get("source") == "text" else True

                if state.IS_PROCESSING: continue
                state.set_processing(True)
                
                clean_text = user_input.replace("[USER] ", "") if user_input.startswith("[USER]") else user_input
                if not user_input.startswith("[USER]"): print(f"[USER (Text)] {clean_text}")

                history.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_text)]))
                history = history_utils.safe_trim_history(history, max_length=14)

                try:
                    for loop_index in range(config.MAX_LLM_TURNS): 
                        full_content_parts = [] 
                        tool_calls = []         
                        
                        print(f"[CHIP] ", end="", flush=True)
                        
                        async for chunk in services.ask_llm_stream(history, system_instruction=full_system_prompt, tools=all_tools):
                            if chunk["type"] == "text":
                                text = chunk["content"]
                                print(text, end="", flush=True)
                                if should_speak: await services.stream_tts(iter([text])) 
                            elif chunk["type"] == "complete_message":
                                full_content_parts = chunk["content"]
                                tool_calls = [p.function_call for p in full_content_parts if p.function_call]

                        print() 
                        if full_content_parts:
                            history.append(types.Content(role="model", parts=full_content_parts))

                        if not tool_calls: break
                        
                        # Handle Filler Audio
                        if should_speak and tool_calls:
                            filler_text = None
                            if loop_index == 0: filler_text = random.choice(config.FILLERS_START)
                            elif random.random() < 0.2: filler_text = random.choice(config.FILLERS_CONTINUED)
                            
                            if filler_text:
                                print(f"[CHIP (Filler)] {filler_text}")
                                asyncio.create_task(services.stream_tts(iter([filler_text])))
                                
                        # Execute Tools
                        tool_tasks = []
                        tool_names = []
                        
                        for fn in tool_calls:
                            fname, fargs = fn.name, fn.args
                            
                            if fname == "restart_system":
                                print("[SYSTEM] Restart initiated...")
                                if should_speak: await services.stream_tts(iter(["Rebooting system."]))
                                subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
                                if history: await context_manager.generate_and_save_summary(history, services)
                                os.execv(sys.executable, [sys.executable, "-m", "chip.core.main"])

                            session = tool_to_session.get(fname)
                            tool_names.append(fname)
                            tool_tasks.append(tools_handler.execute_tool(session, fname, fargs))

                        if tool_tasks:
                            results = await asyncio.gather(*tool_tasks)
                            tool_outputs = [
                                types.Part.from_function_response(name=tool_names[i], response={"result": res})
                                for i, res in enumerate(results)
                            ]
                            history.append(types.Content(role="user", parts=tool_outputs))
                            history = history_utils.sanitise_tool_outputs(history)

                except Exception as e: print(f"[ERROR] LLM Loop: {e}")
                finally: state.set_processing(False)

    finally:
        subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
        if history: await context_manager.generate_and_save_summary(history, services)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n[SYSTEM] Shutdown.")