import asyncio
import sys
import threading
import json
import os
from contextlib import AsyncExitStack

from mcp.client.stdio import stdio_client
from mcp import ClientSession

import config
import state
import audio_engine
import services
import tools_handler

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
                formatted_tools = tm.get_openai_tools(mcp_tools_list.tools)
                
                for t in mcp_tools_list.tools:
                    tool_to_session[t.name] = session
                
                all_tools.extend(formatted_tools)
            except Exception as e:
                print(f"[ERROR] Failed to connect to {server_name}: {e}")

        print(f"[SYSTEM] Ready. Loaded {len(all_tools)} tools across {len(config.MCP_SERVERS)} servers.")

        loop = asyncio.get_running_loop()
        threading.Thread(target=console_listener, args=(loop,), daemon=True).start()

        messages = [{'role': 'system', 'content': config.SYSTEM_PROMPT}]

        while True:
            user_input = await state.input_queue.get()
            
            if getattr(state, "IS_PROCESSING", False):
                continue
                
            state.IS_PROCESSING = True
            
            clean_text = user_input
            if user_input.startswith("[USER]"):
                clean_text = user_input.replace("[USER] ", "")
            else:
                print(f"[USER (Text)] {clean_text}")

            messages.append({'role': 'user', 'content': clean_text})

            try:
                while True:
                    msg = await services.ask_llm(messages, tools=all_tools)
                    
                    if not msg.tool_calls:
                        if msg.content:
                            print(f"[CHIP] {msg.content}")
                            # Send final response to TTS
                            await services.stream_tts(iter([msg.content]))
                            messages.append(msg)
                        break

                    # Handle Tool Calls
                    messages.append(msg)
                    for tc in msg.tool_calls:
                        fname = tc.function.name
                        fargs = json.loads(tc.function.arguments)
                        
                        session = tool_to_session.get(fname)
                        if session:
                            print(f"[TOOL] Executing {fname}...")
                            try:
                                res = await session.call_tool(fname, fargs)
                                tool_result = ""
                                for content in res.content:
                                    if hasattr(content, 'text'):
                                        tool_result += content.text
                                    else:
                                        tool_result += str(content)
                            except Exception as e:
                                tool_result = f"Error: {str(e)}"
                        else:
                            tool_result = f"Error: Tool {fname} not found."
                        
                        messages.append({
                            "tool_call_id": tc.id, 
                            "role": "tool", 
                            "name": fname, 
                            "content": str(tool_result)
                        })
                    # Loop continues to ask_llm with the tool results
            finally:
                state.IS_PROCESSING = False

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[SYSTEM] Shutdown.")