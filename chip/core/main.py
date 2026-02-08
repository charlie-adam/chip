import asyncio
import sys
import threading
import os
import random
import subprocess
import time
import shutil
from contextlib import AsyncExitStack
from google.genai import types
from colorama import init, Fore, Style

from chip.utils import config, tools_handler, history as history_utils
from chip.core import state, services, context_manager, mcp_connect, routines
from chip.audio import audio_engine

init(autoreset=True)

async def main():
    services.restart_imcp()
    
    engine = audio_engine.AudioEngine()
    engine.start()

    personality_text, last_summary = context_manager.load_context()
    full_system_prompt = config.SYSTEM_PROMPT 

    tm = tools_handler.ToolManager(config.MCP_SERVERS)
    base_tools = [config.RESTART_TOOL]
    history = []

    try:
        async with AsyncExitStack() as stack:
            mcp_tools, tool_to_session = await mcp_connect.connect_servers(stack, tm, config.MCP_SERVERS)
            all_tools = base_tools + mcp_tools
            print(f"{Fore.GREEN}[SYSTEM] Ready. Loaded {len(all_tools)} tools.{Style.RESET_ALL}")
            
            history = await routines.run_startup_routine(
                services, 
                history, 
                full_system_prompt, 
                all_tools, 
                tool_to_session,
                personality_text,
                last_summary
            )
            
            mic_id = audio_engine.select_microphone()
            mic = audio_engine.Microphone()
            mic.start(mic_id)
            
            asyncio.create_task(services.start_deepgram_stt())

            loop = asyncio.get_running_loop()
            threading.Thread(target=services.console_listener, args=(loop,), daemon=True).start()
            
            services._get_or_create_cache(full_system_prompt, all_tools)
            
            os.system('clear')
            print(f"{Fore.CYAN}[SYSTEM] Chip Awake - {time.strftime('%a %d %b %H:%M:%S %Y')}{Style.RESET_ALL}")
            print(f"{Fore.LIGHTBLACK_EX}(Waiting for 'Hey Chip' or text input...){Style.RESET_ALL}")

            state.last_speech_time = 0 

            while True:
                first_chunk = await state.input_queue.get()
                
                current_text = first_chunk.get("text", "") if isinstance(first_chunk, dict) else str(first_chunk)
                source = first_chunk.get("source", "mic") if isinstance(first_chunk, dict) else "mic"

                if source == "mic":
                    last_wake = getattr(state, "last_speech_time", 0)
                    if time.time() - last_wake > 15: 
                        # print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Ignored (No wake word){Style.RESET_ALL}")
                        continue

                speech_timeout = getattr(config, 'SPEECH_END_TIMEOUT', 0.8)
                
                if source == "mic":
                    while True:
                        try:
                            next_chunk = await asyncio.wait_for(state.input_queue.get(), timeout=speech_timeout)
                            next_text = next_chunk.get("text", "") if isinstance(next_chunk, dict) else str(next_chunk)
                            if next_text.strip():
                                current_text += " " + next_text
                                print(f"{Fore.LIGHTBLACK_EX}[BUFFER] Merged: '...{next_text}'{Style.RESET_ALL}")
                        except asyncio.TimeoutError:
                            break
                
                user_input = current_text.strip()
                if not user_input: continue

                should_speak = False if source == "text" else True
                if (config.SPEAK_MODE == "always"): should_speak = True
                if (config.SPEAK_MODE == "never"): should_speak = False

                if state.IS_PROCESSING: continue
                state.set_processing(True)
                
                clean_text = user_input.replace("[USER] ", "") if user_input.startswith("[USER]") else user_input
                if not user_input.startswith("[USER]"): 
                    print(f"{Fore.BLUE}[USER (Text)] {clean_text}{Style.RESET_ALL}")

                history.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_text)]))
                history = history_utils.safe_trim_history(history, max_length=config.HISTORY_MAX_LENGTH)

                try:
                    for loop_index in range(config.MAX_LLM_TURNS): 
                        full_content_parts = [] 
                        tool_calls = []         
                        
                        print(f"{Fore.MAGENTA}[CHIP] ", end="", flush=True)
                        
                        async for chunk in services.ask_llm_stream(history, system_instruction=full_system_prompt, tools=all_tools):
                            if chunk["type"] == "text":
                                text = chunk["content"]
                                print(f"{Fore.MAGENTA}{text}{Style.RESET_ALL} ", end="", flush=True)
                                if should_speak: await services.stream_tts(iter([text])) 
                            elif chunk["type"] == "complete_message":
                                full_content_parts = chunk["content"]
                                tool_calls = [p.function_call for p in full_content_parts if p.function_call]

                        print(Style.RESET_ALL)
                        if full_content_parts:
                            history.append(types.Content(role="model", parts=full_content_parts))

                        if not tool_calls: break
                        
                        if tool_calls:
                            if should_speak and not any(fn.name == "restart_system" for fn in tool_calls):
                                try:
                                    base_path = os.path.dirname(os.path.abspath(__file__)) # chip/core
                                    root_path = os.path.dirname(os.path.dirname(base_path)) # project root
                                    sound_path = os.path.join(root_path, "sounds", "thinking.mp3")
                                    
                                    if sys.platform == "darwin":
                                        player = "afplay"

                                    if os.path.exists(sound_path):
                                        subprocess.Popen([player, sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                                    else:
                                        print(f"{Fore.RED}[ERROR] Sound missing at: {sound_path}{Style.RESET_ALL}")
                                except Exception as e:
                                    print(f"[ERROR] Sound failed: {e}")

                                # Filler Text
                                filler_text = None
                                if loop_index == 0: filler_text = random.choice(config.FILLERS_START)
                                elif random.random() < 0.2: filler_text = random.choice(config.FILLERS_CONTINUED)
                                
                                if filler_text:
                                    print(f"{Fore.MAGENTA}[CHIP (Filler)] {filler_text}{Style.RESET_ALL}")
                                    asyncio.create_task(services.stream_tts(iter([filler_text])))
                                
                            tool_tasks = []
                            tool_names = []
                            
                            for fn in tool_calls:
                                fname, fargs = fn.name, fn.args
                                
                                if fname == "restart_system":
                                    print(f"{Fore.CYAN}[SYSTEM] Restart initiated...{Style.RESET_ALL}")
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
    except (RuntimeError, Exception):
        print(f"{Fore.RED}[ERROR] Unhandled exception: {sys.exc_info()[0]} - {sys.exc_info()[1]}{Style.RESET_ALL}")
        pass
    except KeyboardInterrupt: print("\n[SYSTEM] Shutdown.")