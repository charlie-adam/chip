import json
import os
from mcp import StdioServerParameters

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