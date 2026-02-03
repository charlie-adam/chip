from mcp.client.stdio import stdio_client
from mcp import ClientSession
from chip.utils import schema

async def connect_servers(stack, tool_manager, config_servers):
    """
    Iterates through config servers and establishes AsyncContext connections.
    Returns: (all_tools_list, tool_to_session_map)
    """
    all_tools = []
    tool_to_session = {}

    for server_name in config_servers:
        params = tool_manager.get_server_params(server_name)
        try:
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            
            mcp_tools_list = await session.list_tools()
            
            for tool in mcp_tools_list.tools:
                if hasattr(tool, "inputSchema"):
                    tool.inputSchema = schema.clean_schema(tool.inputSchema)
            
            formatted_tools = tool_manager.get_openai_tools(mcp_tools_list.tools)
            
            for t in mcp_tools_list.tools:
                tool_to_session[t.name] = session
            
            all_tools.extend(formatted_tools)
        except Exception as e:
            print(f"[ERROR] Failed to connect to {server_name}: {e}")

    return all_tools, tool_to_session