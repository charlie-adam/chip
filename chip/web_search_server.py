import asyncio
from mcp.server.fastmcp import FastMCP
from ddgs import DDGS
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_search")

mcp = FastMCP("web_search")

@mcp.tool()
async def search_web(query: str) -> str:
    """
    Searches the web for the given query using DuckDuckGo.
    Use this to find current events, facts, stock prices, or information not in your memory.
    
    Args:
        query: The search query string (e.g., "current google stock price", "news about AI")
    """
    print(f"[SEARCH] Querying: {query}")
    
    # 1. Artificial delay to prevent Rate Limits
    await asyncio.sleep(1.0) 

    try:
        # Run synchronous DDGS in a separate thread
        results = await asyncio.to_thread(_perform_search, query)
        
        if not results:
            return "System Notification: The search engine returned no results. This might be a connection issue. Do not retry."
        
        formatted_results = []
        for r in results:
            title = r.get('title', 'No Title')
            link = r.get('href', 'No Link')
            body = r.get('body', 'No Description')
            formatted_results.append(f"Title: {title}\nLink: {link}\nSnippet: {body}")
            
        return "\n---\n".join(formatted_results)

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return f"System Notification: Search tool failed with error: {str(e)}."

def _perform_search(query):
    # CHANGED: 'html' is deprecated. Use 'duckduckgo' (native) or 'api'.
    with DDGS() as ddgs:
        return list(ddgs.text(query, max_results=4, backend="duckduckgo"))

if __name__ == "__main__":
    mcp.run()