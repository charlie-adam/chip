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

from chip.utils import config, tools_handler
from chip.core import state, services, context_manager
from chip.audio import audio_engine
from chip.utils import schema

def safe_trim_history(history, max_length=15):
    """
    Trims history to roughly max_length, but ensures we always start 
    with a clean User message (not a Tool Response) to prevent 400 Errors.
    """
    if len(history) <= max_length:
        return history

    start_index = len(history) - max_length
    
    while start_index < len(history):
        message = history[start_index]
        
        if message.role == "user":
            is_tool_response = any(part.function_response for part in message.parts)
            
            if not is_tool_response:
                return history[start_index:]
        
        start_index += 1

    return history[-2:]

async def execute_tool(session, fname, fargs):
    if not session:
        return f"Error: Tool {fname} not found."
    try:
        print(f"[SYSTEM] Calling tool: {fname} with args {fargs}")
        res = await session.call_tool(fname, fargs)
        return "".join([c.text if hasattr(c, 'text') else str(c) for c in res.content])
    except Exception as e:
        return f"Error executing {fname}: {e}"
    
async def main():
    services.restart_imcp()
    # subprocess.run(["pkill", "-f", "chip_face.py"], stderr=subprocess.DEVNULL)
    
    cwd = os.getcwd()
    python_path = sys.executable
    applescript = f'''
    tell application "Terminal"
        set newTab to do script "cd {cwd} && {python_path} chip_face.py"
        set custom title of newTab to "ChipFace"
    end tell
    '''
    # subprocess.run(["osascript", "-e", applescript], stderr=subprocess.DEVNULL)

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
                            tool.inputSchema = schema.clean_schema(tool.inputSchema)
                    
                    formatted_tools = tm.get_openai_tools(mcp_tools_list.tools)
                    for t in mcp_tools_list.tools:
                        tool_to_session[t.name] = session
                    
                    all_tools.extend(formatted_tools)
                except Exception as e:
                    print(f"[ERROR] Failed to connect to {server_name}: {e}")

            print(f"[SYSTEM] Ready. Loaded {len(all_tools)} tools.")
            state_file = os.path.join("data", "chip_state.json")
            
            #Get Start Time
            last_startup = 0
            if os.path.exists(state_file):
                with open(state_file, "r") as f:
                    try:
                        state_data = json.load(f)
                        last_startup = state_data.get("last_startup", 0)
                    except:
                        last_startup = 0         
            
            #Set Start Time
            with open(state_file, "w") as f:
                json.dump({"last_startup": time.time()}, f)
            print(f"[SYSTEM] Last Startup: {time.ctime(last_startup)}")
            
            if (time.time() - last_startup) > 3600:
                print("[SYSTEM] Initiating Startup Routine (more than 1 hour since last startup)...")
                await services.stream_tts(iter(["Initiating Startup Routine"]))
                
                startup_prompt = (
                    f"SYSTEM STARTUP PROTOCOL initiated at {config.TIME} on {config.DATE}. "
                    "1. Use your tools to list my Google Calendar events for today. "
                    "2. Check for any unread emails in my threads. "
                    "3. Load your memory for any important context. "
                    "4. Analyze the time of day: If it's evening and I had events earlier, assume they are finished. "
                    "5. Synthesize all this info into a warm, short spoken greeting. "
                    "Example: 'Welcome back. I see you had a meeting with X earlier, how did that go? You have Y coming up.'"
                    "(relevant to what data you get, if theres not much - just say 'Welcome back! How can I assist you today?') "
                )
                
                # Inject invisible system instruction as user message
                history.append(types.Content(role="user", parts=[types.Part.from_text(text=startup_prompt)]))
                
                # Loop to handle tool calls autonomously before handing control to user
                startup_complete = False
                startup_turns = 0
                
                while not startup_complete and startup_turns < 5:
                    startup_turns += 1
                    response = await services.ask_llm(history, system_instruction=full_system_prompt, tools=all_tools)
                    if not response.candidates: break
                    
                    candidate = response.candidates[0]
                    history.append(candidate.content)
                    
                    tool_calls = [p.function_call for p in candidate.content.parts if p.function_call]
                    text_parts = [p.text for p in candidate.content.parts if p.text]

                    # If text exists, it's likely the final summary. Speak it.
                    for text in text_parts:
                        print(f"[CHIP (Startup)] {text}")
                        await services.stream_tts(iter([text]))
                    
                    # If no tools are called, we are done with startup
                    if not tool_calls:
                        startup_complete = True
                        
                        # FLUSH HISTORY
                        # Once startup is done and the greeting is spoken, we wipe the memory.
                        # This removes the massive startup prompt and raw tool data.
                        history = []
                        print("[SYSTEM] Startup context flushed to reduce bloat.")

                    else:
                        # Execute tools (Calendar/Email)
                        response_parts = []
                        for fn in tool_calls:
                            fname, fargs = fn.name, fn.args
                            session = tool_to_session.get(fname)
                            res_str = ""
                            if session:
                                try:
                                    print(f"[SYSTEM] Startup Tool: {fname}")
                                    res = await session.call_tool(fname, fargs)
                                    res_str = "".join([c.text if hasattr(c, 'text') else str(c) for c in res.content])
                                except Exception as e: res_str = f"Error: {e}"
                            else: res_str = f"Error: Tool {fname} not found."
                            response_parts.append(types.Part.from_function_response(name=fname, response={"result": res_str}))
                        
                        history.append(types.Content(role="user", parts=response_parts))

            loop = asyncio.get_running_loop()
            threading.Thread(target=services.console_listener, args=(loop,), daemon=True).start()
            services._get_or_create_cache(full_system_prompt, all_tools)
            #clear the terminal, log chip Awake (With date Sat 2 Feb 14:23:45 format)
            os.system('clear')
            print(f"[SYSTEM] Chip Awake - {time.strftime('%a %d %b %H:%M:%S %Y')}")
            while True:
                input_data = await state.input_queue.get()
                
                user_input = ""
                should_speak = True # Default to speaking

                if isinstance(input_data, dict):
                    user_input = input_data.get("text", "")
                    # QUIET MODE: If input came from text, don't speak the response
                    if input_data.get("source") == "text":
                        should_speak = False
                else:
                    user_input = str(input_data)

                if state.IS_PROCESSING: continue
                state.set_processing(True)
                
                clean_text = user_input.replace("[USER] ", "") if user_input.startswith("[USER]") else user_input
                
                if not user_input.startswith("[USER]"):
                    print(f"[USER (Text)] {clean_text}")

                history.append(types.Content(role="user", parts=[types.Part.from_text(text=clean_text)]))
                
                history = safe_trim_history(history, max_length=14)

                try:
                    for loop_index in range(config.MAX_LLM_TURNS): 
                        
                        full_content_parts = [] 
                        tool_calls = []         
                        
                        print(f"[CHIP] ", end="", flush=True)
                        
                        async for chunk in services.ask_llm_stream(history, system_instruction=full_system_prompt, tools=all_tools):
                            if chunk["type"] == "text":
                                text = chunk["content"]
                                print(text, end="", flush=True)
                                
                                if should_speak:
                                    await services.stream_tts(iter([text])) 
                            
                            elif chunk["type"] == "complete_message":
                                full_content_parts = chunk["content"]
                                tool_calls = [p.function_call for p in full_content_parts if p.function_call]

                        print() 
                        
                        if full_content_parts:
                            history.append(types.Content(role="model", parts=full_content_parts))

                        if not tool_calls:
                            break
                        
                        if tool_calls:
                            if should_speak:
                                filler_active = False
                                filler_text = ""

                                if loop_index == 0:
                                    filler_active = True
                                    filler_text = random.choice(config.FILLERS_START)
                                elif random.random() < 0.2:
                                    filler_active = True
                                    filler_text = random.choice(config.FILLERS_CONTINUED)
                                
                                if filler_active:
                                    print(f"[CHIP (Filler)] {filler_text}")
                                    asyncio.create_task(services.stream_tts(iter([filler_text])))
                                
                        tool_tasks = []
                        tool_names = []
                        
                        for fn in tool_calls:
                            fname, fargs = fn.name, fn.args
                            
                            if fname == "restart_system":
                                print("[SYSTEM] Restart initiated by AI...")
                                if should_speak:
                                    await services.stream_tts(iter(["Rebooting system now."]))
                                    
                                subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
                                subprocess.run(["pkill", "-f", "chip_face.py"], stderr=subprocess.DEVNULL)
                                subprocess.run(["osascript", "-e", 'tell application "Terminal" to close (every window whose name contains "ChipFace") saving no'], stderr=subprocess.DEVNULL)
                                if history:
                                    await context_manager.generate_and_save_summary(history, services)
                                print("[SYSTEM] Re-executing process as module...")
                                os.execv(sys.executable, [sys.executable, "-m", "chip.core.main"])

                            session = tool_to_session.get(fname)
                            tool_names.append(fname)
                            tool_tasks.append(execute_tool(session, fname, fargs))

                        if tool_tasks:
                            results = await asyncio.gather(*tool_tasks)

                            tool_outputs = []
                            for i, res_str in enumerate(results):
                                tool_outputs.append(
                                    types.Part.from_function_response(
                                        name=tool_names[i], 
                                        response={"result": res_str}
                                    )
                                )
                            history.append(types.Content(role="user", parts=tool_outputs))

                except Exception as e: print(f"[ERROR] LLM Loop: {e}")
                finally: state.set_processing(False)

    finally:
        subprocess.run(["pkill", "-f", "imcp-server"], stderr=subprocess.DEVNULL)
        subprocess.run(["pkill", "-f", "chip_face.py"], stderr=subprocess.DEVNULL)
        subprocess.run(["osascript", "-e", 'tell application "Terminal" to close (every window whose name contains "ChipFace") saving no'], stderr=subprocess.DEVNULL)
        if history: await context_manager.generate_and_save_summary(history, services)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n[SYSTEM] Shutdown.")