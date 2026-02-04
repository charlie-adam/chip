import json
import os
from mcp import StdioServerParameters
from colorama import Fore, Style, init
init(autoreset=True)
class ToolManager:
    def __init__(self, server_configs):
        self.server_configs = server_configs
        self.sessions = {} # Map of server_name -> session

    def get_server_params(self, name):
        cfg = self.server_configs[name]
        # Use .get() for env to avoid KeyError if it's missing in config
        extra_env = cfg.get("env") or {}
        
        return StdioServerParameters(
            command=cfg["command"],
            args=cfg["args"],
            env={**os.environ, **extra_env}
        )

    def get_openai_tools(self, mcp_tools_list):
        openai_tools = []
        for tool in mcp_tools_list:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            })
        return openai_tools

async def execute_tool(session, fname, fargs):
    """
    Executes a tool on the given MCP session with safety truncation.
    """
    if not session:
        return f"Error: Tool {fname} not found."
    try:
        print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Calling tool: {fname} with args {fargs}{Style.RESET_ALL}")
        res = await session.call_tool(fname, fargs)
        
        full_text = "".join([c.text if hasattr(c, 'text') else str(c) for c in res.content])
        MAX_CHARS = 8000 
        
        if len(full_text) > MAX_CHARS:
            truncated_text = full_text[:MAX_CHARS]
            warning_msg = (
                f"\n\n{Fore.RED}[ERROR] Output too large ({len(full_text)} characters). "
                f"Truncated to first {MAX_CHARS} characters to save costs.\n"
                "If you need to read this file, use 'head', 'tail', or 'grep' instead of 'cat'."
                f"{Style.RESET_ALL}"
            )
            return truncated_text + warning_msg
            
        return full_text

    except Exception as e:
        return f"Error executing {fname}: {e}"