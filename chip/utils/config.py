import datetime
import os
import sys

from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPERMEMORY_BEARER = os.getenv("SUPERMEMORY_BEARER", "")
PICOVOICE_ACCESS_KEY = os.getenv("PICOVOICE_ACCESS_KEY", "")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath("credentials.json")

if not GEMINI_API_KEY or not DEEPGRAM_API_KEY or not PICOVOICE_ACCESS_KEY:
    print("ERROR: Please set GEMINI_API_KEY, DEEPGRAM_API_KEY, and PICOVOICE_ACCESS_KEY.")
    sys.exit(1)
    
# SAMPLE_RATE_MIC = 48000
SAMPLE_RATE_MIC = 16000
SAMPLE_RATE_TTS = 24000
KEYWORD_FILE_PATH = "hey_chip_ww.ppn"
BLOCK_SIZE = 8192
LLM_MODEL = "gemini-3-flash-preview"
TTS_VOICE = "aura-2-luna-en"
SPEECH_END_TIMEOUT = 0.7
MAX_LLM_TURNS = 15
STATE_JSON = "chip_state.json"
CACHE_SECONDS = 86400
SPEAK_MODE = "always" #always, never, dynamic
PREFERRED_INPUT_DEVICE = 'MacBook Air Microphone' 
PREFERRED_OUTPUT_DEVICE = 'Charlie’s AirPods'
HISTORY_MAX_LENGTH = 40

FILLERS_START = [
    "Let me check.", "One moment.", "Just a second.", 
    "Checking now.", "On it.", "I'll take care of that.", 
    "Let me see.", "Right away."
]

FILLERS_CONTINUED = [
    "Still working on it.", "Processing...", "Just another moment.",
    "Still going...", "Almost there...", "Digging a bit deeper...",
    "Hang tight...", "Getting that for you...", "This is taking a bit longer...",
    "Thanks for your patience...", "Working on it...", "Let me focus on that...",
    "Doing my best here..."
]

RESTART_TOOL = {
    "type": "function",
    "function": {
        "name": "restart_system",
        "description": "Restarts the entire AI system (Chip). Use this if you are stuck, experiencing errors, or if the user explicitly asks you to reboot/restart.",
        "parameters": {
            "type": "object", 
            "properties": {}
        }
    }
}

TARGET_FOLDER = os.path.abspath(".")
DATE = datetime.datetime.now().strftime("%B %d, %Y")
TIME = datetime.datetime.now().strftime("%I:%M %p")
SYSTEM_PROMPT = f"""
ROLE: Chip, an advanced voice-first AI assistant.
CURRENT_TIME: {DATE} @ {TIME}
CONFIG_PATH: chip/utils/config.py

### CRITICAL OUTPUT RULES (STRICT ENFORCEMENT)
1. **VOICE ONLY**: Output MUST be pure, speakable English. NO markdown, NO code blocks, NO lists, NO special chars.
2. **BREVITY**: Max 2 sentences per response unless explicitly asked for detail.
3. **CLARIFICATION**: If audio input is ambiguous/garbled, DO NOT GUESS. Ask: "I think you said X, is that correct?"

### TOOL PROTOCOLS
- **Web Search**: Use for ALL factual queries. NEVER use terminal (curl/wget) for scraping.
- **Google Workspace**: PRIMARY tool for Email/Calendar/Drive.
- **Apple MCP (iMCP)**: Use ONLY for Apple-specifics (iMessage/Reminders).
- **Memory**: Store user details generously (Threshold: Importance > 3/10).
- **Terminal**: Confirm before destructive commands (rm, dd). NEVER use for web scraping.
- **YouTube Music**: Controls music in Arc Browser. Confirm execution with a simple "Done".
- **Self-Evolution**: `data/personality.txt` defines your traits. Edit this file if requested to change behavior.

### OPERATIONAL & SAFETY GUIDELINES
- **Action Confirmation**: EXPLICITLY confirm before:
    1. Sending messages/emails (Human impact).
    2. Destructive file operations.
    3. Executing ambiguous commands.
- **Search Etiquette**: ONE specific query at a time. Report failures; do not spam variations.
- **Filesystem**: NEVER `cat` unknown/large files.
- **Git**: Append "-Chip" to all commit messages.

### GOAL
Execute tasks efficiently using Sequential Thinking. Be helpful, concise, and conversational. (don't just be a search engine - synthesize information and provide value).
Be personable and engaging in your responses, but avoid unnecessary verbosity. Always prioritize user intent and clarity in communication.
"""

ALLOWED_FS_PATH = os.path.abspath(".")

MCP_SERVERS = {
    "web_search": {
        "command": "uv",
        "args": ["run", "chip/servers/web_search_server.py"]
    },
    "workspace": {
        "command": "node",
        "args": [
            os.path.expanduser("~/mcp-servers/google-workspace/workspace-server/dist/index.js")
        ],
        "env": {
        "GOOGLE_APPLICATION_CREDENTIALS": os.path.abspath("credentials.json")
        }
    },
    "supermemory-mcp": {
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://mcp.supermemory.ai/mcp", "--transport", "sse-only"],
        "env": {},
        "headers": {
            "Authorization": f"Bearer {SUPERMEMORY_BEARER}"
        }
    },
    "terminal": {
        "command": "uv",
        "args": ["run", "chip/servers/terminal_server.py"] 
    },
    "sequential-thinking": {
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-sequential-thinking"
        ]
    },
    "iMCP": {
        "command": "/Applications/iMCP.app/Contents/MacOS/imcp-server",
        "args": [],
        "env": {}
    },
    "Youtube Music": {
        "command": "uv",
        "args": ["run", "chip/servers/youtube_music_applescript_server.py"]
    }
}
