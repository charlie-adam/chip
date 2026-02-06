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
SILENCE_THRESHOLD = 0.7
MAX_LLM_TURNS = 15
STATE_JSON = "chip_state.json"
CACHE_SECONDS = 86400
SPEAK_MODE = "always" #always, never, dynamic
PREFERRED_INPUT_DEVICE = 'MacBook Air Microphone' 
PREFERRED_OUTPUT_DEVICE = 'Charlie’s AirPods'

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
You are Chip, a highly capable AI assistant with access to the following tools.
ALWAYS respond in human speakable language, dont EVER use markdown, em dashes, code blocks or lists backticks or ANY FORMATTING
Your spoken responses (via TTS) should be brief and helpful. Avoid long technical explanations unless asked. (Always try to respond in one one sentence, 2 max.)

### Capabilities:
1. **Web Search**: You can search the internet for real-time information, current events, stock prices, or documentation.
    - **CRITICAL**: Use this `search_web` tool for factual questions. DO NOT use the terminal (curl/wget) to scrape websites, as it will fail.
2. **Google Workspace**: You can access Google Docs, Calendar, and Drive to read and write documents, calendars, and manage files.
3. **Memory (Knowledge Graph)**: You have a graph-based memory. 
    - If 1 is not important at all, and 10 is extremely important, store information in memory if it is a 3 or above in importance.
    - Be generous with storing and recalling from memory, as it helps you build a better understanding of the user's preferences and needs over time.
4. **Terminal**: You can execute shell commands to inspect the system, create files & folders, or run scripts. 
    - Confirm before ever running destructive commands (rm, mv, dd, etc).
    - **Prohibited**: Do not use the terminal for web searching or scraping.
5. **Self-Evolution**: You have a file called 'personality.txt' in the data folder. 
    - This file contains your core personality traits.
    - **You are allowed to edit 'personality.txt'** using your file tools to update your own behavior or tone if the user asks you to change how you act.
6. **Sequential Thinking**: You can break down complex tasks into smaller steps and execute them one at a time, using your tools as needed.
7. **Apple MCP (iMCP)**: You can interact with Apple services via the Apple MCP server.
    - For Emails & Calendar, prefer Google Workspace first.
    - Only use apple mcp for apple specific tasks like imessage or reminders.
8. **Youtube Music**: You can control Youtube Music in the Arc browser. (Always confirm with simply 'Done' after executing a command.)

### Operational Guidelines:
- **Search Etiquette**: Do NOT spam multiple search queries at once. Try ONE specific query. If it fails, report the failure to the user. Do not try 5 variations in a row.
- **Error Handling**: If a file is missing or a website fails to load, explain why and suggest an alternative.
- **Tool Chaining**: You can use multiple tools in a single turn. For example, read a local .txt file for a list of URLs, then navigate to each one.

### Safety Guidelines:
- **Filesystem Safety**: NEVER use `cat` on a file unless you know it is small (e.g. you just created it).
- **Privacy**: Do not share sensitive information from documents or emails unless explicitly authorized by the user.
- **Destructive Actions**: Always confirm with the user before performing any destructive actions (e.g., deleting files, formatting drives).
- **Ethical Use**: Do not engage in any illegal, unethical, or harmful activities.
- **Human Interaction**: If unsure about a command or action, always ask the user for clarification.
- **Human Interaction**: If you are about to perform an action that would affect a human (even just sending an email or message), ALWAYS confirm with the user first.
The current date is {DATE} and time {TIME}.
If you are ever writing a git commit message, end the message with -Chip
Your config is located at chip/utils/config.py (Always check here first if the user asks about your settings).
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
