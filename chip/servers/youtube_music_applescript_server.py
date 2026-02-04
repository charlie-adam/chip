import subprocess
import json
from mcp.server.fastmcp import FastMCP
# Use a custom header to prevent potential search blocks
from ytmusicapi import YTMusic

mcp = FastMCP("Arc YTM AppleScript Controller")
yt = YTMusic()

def run_applescript(script_content):
    """Universal wrapper for osascript execution."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script_content],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: AppleScript timed out. Is Arc responding?"

@mcp.tool()
async def play_song(query: str) -> str:
    """Search for a song and navigate to it in the YTM tab."""
    # 1. Search for the song
    results = yt.search(query, filter="songs")
    if not results:
        return f"No songs found for '{query}'"
    
    video_id = results[0]['videoId']
    title = results[0]['title'].replace('"', "'") # Prevent quote breaks
    target_url = f"https://music.youtube.com/watch?v={video_id}"
    
    # 2. AppleScript to find or create tab
    # We use 'quoted form of' to safely handle URLs and titles
    script = f'''
    tell application "Arc"
        set foundTab to missing value
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "music.youtube.com" then
                    set foundTab to t
                    exit repeat
                end if
            end repeat
            if foundTab is not missing value then exit repeat
        end repeat
        
        if foundTab is not missing value then
            set URL of foundTab to "{target_url}"
            return "Successfully playing: {title}"
        else
            tell front window to make new tab with properties {{URL:"{target_url}"}}
            return "Opened {title} in a new tab"
        end if
    end tell
    '''
    return run_applescript(script)

@mcp.tool()
async def control_playback(action: str) -> str:
    """Controls media (play, pause, next, prev)."""
    js_map = {
        "play": "document.querySelector('#play-pause-button').click()",
        "pause": "document.querySelector('#play-pause-button').click()",
        "next": "document.querySelector('.next-button').click()",
        "prev": "document.querySelector('.previous-button').click()"
    }
    
    action_js = js_map.get(action.lower())
    if not action_js:
        return "Invalid action. Use play, pause, next, or prev."
    
    # Escape for AppleScript
    escaped_js = action_js.replace('"', '\\"')
    
    script = f'''
    tell application "Arc"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "music.youtube.com" then
                    tell t to execute javascript "{escaped_js}"
                    return "Media command sent: {action}"
                end if
            end repeat
        end repeat
    end tell
    return "Error: No YouTube Music tab found to control."
    '''
    return run_applescript(script)

@mcp.tool()
async def play_playlist(name: str) -> str:
    """Finds a playlist in the sidebar and clicks play."""
    # We search the sidebar for the text provided
    js = f"""
    (() => {{
        const items = document.querySelectorAll('ytmusic-guide-entry-renderer');
        for (const item of items) {{
            const titleEl = item.querySelector('.title');
            if (titleEl && titleEl.innerText.toLowerCase().includes('{name.lower()}')) {{
                const playButton = item.querySelector('#play-button');
                if (playButton) {{
                    playButton.click();
                    return 'Success: Playing playlist ' + titleEl.innerText;
                }}
            }}
        }}
        return 'Error: Playlist not found in sidebar';
    }})()
    """.replace('"', '\\"')

    script = f'''
    tell application "Arc"
        repeat with w in windows
            repeat with t in tabs of w
                if URL of t contains "music.youtube.com" then
                    return (tell t to execute javascript "{js}")
                end if
            end repeat
        end repeat
    end tell
    return "Error: No YouTube Music tab open."
    '''
    return run_applescript(script)

if __name__ == "__main__":
    mcp.run()