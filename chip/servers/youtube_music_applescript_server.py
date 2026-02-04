import subprocess
import json
import os
from mcp.server.fastmcp import FastMCP
from ytmusicapi import YTMusic

mcp = FastMCP("Arc YTM AppleScript Controller")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AUTH_FILE = os.path.join(SCRIPT_DIR, "browser.json")

# Initialize the API
try:
    yt = YTMusic(AUTH_FILE)
except Exception:
    yt = YTMusic()

def run_applescript(script_content):
    try:
        result = subprocess.run(
            ["osascript", "-e", script_content],
            capture_output=True, text=True, check=True, timeout=20
        )
        return result.stdout.strip()
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def list_playlists() -> str:
    """Returns a list of all playlists in the user's YouTube Music library."""
    if not os.path.exists(AUTH_FILE):
        return f"Error: Auth file not found at {AUTH_FILE}. Please run 'ytmusicapi setup'."
        
    try:
        playlists = yt.get_library_playlists(limit=100)
        names = [p['title'] for p in playlists]
        if "Liked Music" not in names:
            names.insert(0, "Liked Music")
        return "Playlists:\n" + "\n".join(f"- {name}" for name in names)
    except Exception as e:
        return f"Error: {str(e)}"

@mcp.tool()
async def play_playlist(name: str) -> str:
    """Finds a library playlist and plays it in Arc (handling existing or new tabs)."""
    try:
        playlists = yt.get_library_playlists(limit=100)
        search = name.lower()
        
        if "liked" in search:
            playlist_id, title = "LM", "Liked Music"
        else:
            target = next((p for p in playlists if search in p['title'].lower()), None)
            if not target: 
                return f"Playlist '{name}' not found."
            playlist_id, title = target['playlistId'], target['title']

        url = f"https://music.youtube.com/playlist?list={playlist_id}"
        
        # Big Play Button Selector identified in debug
        js_play = """
        (function() {
            const btn = document.querySelector('ytmusic-responsive-header-renderer ytmusic-play-button-renderer');
            if (btn) {
                btn.scrollIntoView({block: 'center'});
                setTimeout(() => btn.click(), 100);
                return 'CLICKED';
            }
            return 'NOT_FOUND';
        })()
        """.replace('"', '\\"')

        script = f'''
        tell application "Arc"
            activate
            set foundTab to false
            set winCount to count of windows
            
            -- Find existing YTM tab using indexed search
            if winCount > 0 then
                repeat with w from 1 to winCount
                    set tCount to count of tabs of window w
                    repeat with t from 1 to tCount
                        if URL of tab t of window w contains "music.youtube.com" then
                            set targetWinIndex to w
                            set targetTabIndex to t
                            set foundTab to true
                            exit repeat
                        end if
                    end repeat
                    if foundTab is true then exit repeat
                end repeat
            end if
            
            if foundTab is true then
                set URL of tab targetTabIndex of window targetWinIndex to "{url}"
                delay 3
                tell tab targetTabIndex of window targetWinIndex to execute javascript "{js_play}"
                return "Started playing: {title}"
            else
                -- Robust New Tab Logic
                if (count of windows) is 0 then
                    make new window
                end if
                
                tell window 1
                    make new tab with properties {{URL:"{url}"}}
                end tell
                
                delay 3
                
                try
                    tell active tab of window 1 to execute javascript "{js_play}"
                    return "Opened and started {title} in main window."
                on error
                    return "Opened {title}, but could not trigger the play button."
                end try
            end if
        end tell
        '''
        return run_applescript(script)
    except Exception as e:
        return f"Error: {str(e)}"
    
@mcp.tool()
async def play_song(query: str) -> str:
    """Search for a song and navigate to it in the main Arc window."""
    if any(word in query.lower() for word in ["playlist", "liked music"]):
        return "Please use the play_playlist tool for library requests."

    results = yt.search(query, filter="songs")
    if not results:
        return f"No songs found for '{query}'"
    
    video_id = results[0]['videoId']
    title = results[0]['title'].replace('"', "'")
    target_url = f"https://music.youtube.com/watch?v={video_id}"
    
    script = f'''
    tell application "Arc"
        activate
        set foundTab to false
        set winCount to count of windows
        repeat with w from 1 to winCount
            set tCount to count of tabs of window w
            repeat with t from 1 to tCount
                if URL of tab t of window w contains "music.youtube.com" then
                    set URL of tab t of window w to "{target_url}"
                    set foundTab to true
                    exit repeat
                end if
            end repeat
            if foundTab is true then exit repeat
        end repeat
        
        if foundTab is false then
            tell window 1 to make new tab with properties {{URL:"{target_url}"}}
            return "Opened {title} in a new tab"
        else
            return "Successfully playing: {title}"
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
    if not action_js: return "Invalid action."
    
    escaped_js = action_js.replace('"', '\\"')
    
    script = f'''
    tell application "Arc"
        set winCount to count of windows
        repeat with w from 1 to winCount
            set tCount to count of tabs of window w
            repeat with t from 1 to tCount
                if URL of tab t of window w contains "music.youtube.com" then
                    tell tab t of window w to execute javascript "{escaped_js}"
                    return "Sent {action} command."
                end if
            end repeat
        end repeat
    end tell
    '''
    return run_applescript(script)

@mcp.tool()
async def what_is_playing() -> str:
    """Reads current song title."""
    js = "document.querySelector('yt-formatted-string.title').innerText".replace('"', '\\"')
    script = f'''
    tell application "Arc"
        set winCount to count of windows
        repeat with w from 1 to winCount
            set tCount to count of tabs of window w
            repeat with t from 1 to tCount
                if URL of tab t of window w contains "music.youtube.com" then
                    return (tell tab t of window w to execute javascript "{js}")
                end if
            end repeat
        end repeat
    end tell
    '''
    result = run_applescript(script)
    return f"Currently playing: {result}" if result and "Error" not in result else "Nothing detected."

if __name__ == "__main__":
    mcp.run()