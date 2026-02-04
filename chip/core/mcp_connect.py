import asyncio
from mcp.client.stdio import stdio_client
from mcp import ClientSession
from chip.utils import schema
from colorama import init, Fore, Style
init(autoreset=True)

async def connect_single_server(stack, tool_manager, server_name):
    """Connects to a single server and returns its tools and session."""
    params = tool_manager.get_server_params(server_name)
    try:
        print(f"{Fore.YELLOW}[/] BOOTING {server_name}...{Style.RESET_ALL}")
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        
        mcp_tools_list = await session.list_tools()
        
        for tool in mcp_tools_list.tools:
            if hasattr(tool, "inputSchema"):
                tool.inputSchema = schema.clean_schema(tool.inputSchema)
        
        formatted_tools = tool_manager.get_openai_tools(mcp_tools_list.tools)
        
        server_tool_to_session = {t.name: session for t in mcp_tools_list.tools}
        print(f"{Fore.GREEN}[+] BOOTED {server_name} with tools: {list(server_tool_to_session.keys())}{Style.RESET_ALL}")
        
        return formatted_tools, server_tool_to_session
    except Exception as e:
        print(f"{Fore.RED}[-] BOOTING FAILED {server_name}: {e}{Style.RESET_ALL}")
        return [], {}

async def connect_servers(stack, tool_manager, config_servers):
    """
    Connects to all config servers asynchronously.
    Returns: (all_tools_list, tool_to_session_map)
    """
    tasks = [connect_single_server(stack, tool_manager, s) for s in config_servers]
    results = await asyncio.gather(*tasks)
    
    all_tools = []
    tool_to_session = {}
    
    for formatted_tools, server_tool_to_session in results:
        all_tools.extend(formatted_tools)
        tool_to_session.update(server_tool_to_session)
        
    return all_tools, tool_to_session
