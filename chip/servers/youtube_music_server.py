import asyncio
from distro import like
import requests
import json
from mcp.server.fastmcp import FastMCP
from ytmusicapi import YTMusic

mcp = FastMCP("Arc YTM Controller")
yt = YTMusic()

DEBUG_PORT = 9222
YTM_URL = "music.youtube.com"

async def get_arc_tab():
    """Finds an existing YTM tab in Arc or connects to a new one."""
    try:
        resp = requests.get(f"http://127.0.0.1:{DEBUG_PORT}/json")
        tabs = resp.json()
        for tab in tabs:
            if YTM_URL in tab.get('url', ''):
                return tab
        for tab in tabs:
            if tab.get('url') == 'about:blank':
                return tab
        if tabs:
            return tabs[0]
    except requests.exceptions.ConnectionError:
        raise RuntimeError("Could not connect to Arc. Is it running with --remote-debugging-port=9222?")
    return None

async def send_cdp_command(tab, method, params=None):
    import websockets
    ws_url = tab.get('webSocketDebuggerUrl')
    if not ws_url:
        raise RuntimeError("Tab does not support remote control.")
    async with websockets.connect(ws_url) as ws:
        msg = {"id": 1, "method": method, "params": params or {}}
        await ws.send(json.dumps(msg))
        response = await ws.recv()
        return json.loads(response)

async def execute_script(script):
    tab = await get_arc_tab()
    if not tab:
        raise RuntimeError("No suitable tab found.")
    return await send_cdp_command(tab, "Runtime.evaluate", {
        "expression": script,
        "userGesture": True
    })
    
@mcp.tool()
async def list_playlists() -> str:
    """Lists available playlists in the sidebar of Youtube Music."""
    script = """
    (() => {
        const items = document.querySelectorAll('ytmusic-guide-entry-renderer');
        let playlists = [];
        for (const item of items) {
            const titleEl = item.querySelector('.title');
            if (titleEl) {
                playlists.push(titleEl.innerText);
            }
        }
        return playlists.join(", ");
    })()
    """
    result = await execute_script(script)
    try:
        return "Available playlists: " + result['result']['result']['value']
    except:
        return "Failed to retrieve playlists."

@mcp.tool()
async def play_playlist(name: str) -> str:
    """Finds a playlist in your sidebar (like 'Liked Music' or '2025 Top 100') and plays it."""
    script = f"""
    (() => {{
        const items = document.querySelectorAll('ytmusic-guide-entry-renderer');
        for (const item of items) {{
            const titleEl = item.querySelector('.title');
            if (titleEl && titleEl.innerText.toLowerCase().includes("{name.lower()}")) {{
                const playButton = item.querySelector('#play-button');
                if (playButton) {{
                    playButton.click();
                    return "Playing " + titleEl.innerText;
                }}
            }}
        }}
        return "Playlist not found in sidebar";
    }})()
    """
    result = await execute_script(script)
    try:
        return result['result']['result']['value']
    except:
        return "Failed to trigger playlist playback."

@mcp.tool()
async def play_song(query: str) -> str:
    """Search for a song and play it in the existing Arc tab."""
    results = yt.search(query, filter="songs")
    if not results:
        return f"No songs found for '{query}'"
    
    video_id = results[0]['videoId']
    title = results[0]['title']
    target_url = f"https://music.youtube.com/watch?v={video_id}"
    
    tab = await get_arc_tab()
    if tab:
        await send_cdp_command(tab, "Page.navigate", {"url": target_url})
        return f"Playing '{title}' in Arc."
    return "Could not find Arc browser instance."

@mcp.tool()
async def control_playback(action: str) -> str:
    """Controls media. Action: 'play', 'pause', 'next', 'prev'."""
    js_map = {
        "play": "document.querySelector('#play-pause-button').click()",
        "pause": "document.querySelector('#play-pause-button').click()",
        "next": "document.querySelector('.next-button').click()",
        "prev": "document.querySelector('.previous-button').click()"
    }
    script = js_map.get(action.lower())
    if not script: return "Invalid action."
    await execute_script(script)
    return f"Executed {action}."

@mcp.tool()
async def what_is_playing() -> str:
    """Reads current song from Arc."""
    script = "document.querySelector('yt-formatted-string.title').innerText"
    result = await execute_script(script)
    try:
        return f"Currently playing: {result['result']['result']['value']}"
    except:
        return "Nothing playing or could not read title."

if __name__ == "__main__":
    mcp.run()