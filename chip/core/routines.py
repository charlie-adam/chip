import os
import time
import json
from google.genai import types
from chip.utils import config
from chip.core import state
from colorama import Fore, Style, init
init(autoreset=True)

async def run_startup_routine(services, history, system_prompt, all_tools, tool_to_session):
    """
    Checks last startup time. If > 1 hour, runs the autonomous check-in loop.
    """
    state_data = state._load_state()
    last_startup = state_data.get("last_startup", 0)
    
    state._update_state({"last_startup": time.time()})
    
    print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Last Startup: {time.ctime(last_startup)}{Style.RESET_ALL}")
    
    if (time.time() - last_startup) <= 3600:
        return history # Skip routine

    print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Initiating Startup Routine...{Style.RESET_ALL}")
    await services.stream_tts(iter(["Initiating Startup Routine"]))
    
    startup_prompt = (
        f"SYSTEM STARTUP PROTOCOL initiated at {config.TIME} on {config.DATE}. "
        "1. Use your tools to list my Google Calendar events for today. "
        "2. Check for any unread emails. "
        "3. Load memory for context. "
        "4. Synthesise into a warm, short spoken greeting. "
    )
    
    history.append(types.Content(role="user", parts=[types.Part.from_text(text=startup_prompt)]))
    
    startup_complete = False
    startup_turns = 0
    
    while not startup_complete and startup_turns < 5:
        startup_turns += 1
        response = await services.ask_llm(history, system_instruction=system_prompt, tools=all_tools)
        if not response.candidates: break
        
        candidate = response.candidates[0]
        history.append(candidate.content)
        
        tool_calls = [p.function_call for p in candidate.content.parts if p.function_call]
        text_parts = [p.text for p in candidate.content.parts if p.text]

        for text in text_parts:
            print(f"{Fore.LIGHTBLACK_EX}[CHIP (Startup)] {text}{Style.RESET_ALL}")
            await services.stream_tts(iter([text]))
        
        if not tool_calls:
            startup_complete = True
            history = [] # Flush startup context
            print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Startup context flushed.{Style.RESET_ALL}")
        else:
            response_parts = []
            for fn in tool_calls:
                fname, fargs = fn.name, fn.args
                session = tool_to_session.get(fname)
                res_str = ""
                if session:
                    try:
                        print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Startup Tool: {fname}{Style.RESET_ALL}")
                        res = await session.call_tool(fname, fargs)
                        res_str = "".join([c.text if hasattr(c, 'text') else str(c) for c in res.content])
                    except Exception as e: res_str = f"Error: {e}"
                else: res_str = f"Error: Tool {fname} not found."
                response_parts.append(types.Part.from_function_response(name=fname, response={"result": res_str}))
            
            history.append(types.Content(role="user", parts=response_parts))
            
    return history