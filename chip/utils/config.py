import datetime
import os
import sys

from dotenv import load_dotenv

load_dotenv()

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath("credentials.json")

if not GEMINI_API_KEY or not DEEPGRAM_API_KEY:
    print("ERROR: Please set GEMINI_API_KEY and DEEPGRAM_API_KEY.")
    sys.exit(1)
    
SAMPLE_RATE_MIC = 16000
SAMPLE_RATE_TTS = 24000
BLOCK_SIZE = 8192
LLM_MODEL = "gemini-3-flash-preview"
TTS_VOICE = "aura-2-luna-en"
SILENCE_THRESHOLD = 1
MAX_LLM_TURNS = 15

FILLERS = [
    "Working on it.", "One moment.", "Just a second.", "Let me check.",
    "Processing.", "Getting that for you.", "Hold on a moment.",
    "Let me see.", "Checking now.", "Alrighty.", "Sure thing.", "On it.",
    "Right away.", "I'll take care of that.", "Give me a moment.",
    "Let me handle that.", "Just a moment please."
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

### Capabilities:
1. **Web Search**: You can search the internet for real-time information, current events, stock prices, or documentation.
    - **CRITICAL**: Use this `search_web` tool for factual questions. DO NOT use the terminal (curl/wget) to scrape websites, as it will fail.
2. **Google Workspace**: You can access Google Docs, Calendar, and Drive to read and write documents, calendars, and manage files.
3. **Memory (Knowledge Graph)**: You have a graph-based memory. 
    - **Active Recall**: When the user asks a personal question (e.g., "What is my X?"), you MUST first use `read_graph` or `search_nodes` to check if you already know the answer.
    - **Storage**: When the user tells you a fact, use `create_entities` and `create_relations` to save it immediately.
4. **Terminal**: You can execute shell commands to inspect the system, create files & folders, or run scripts. 
    - Confirm before ever running destructive commands (rm, mv, dd, etc).
    - **Prohibited**: Do not use the terminal for web searching or scraping.
5. **Self-Evolution**: You have a file called 'personality.txt' in the data folder. 
    - This file contains your core personality traits.
    - **You are allowed to edit 'personality.txt'** using your file tools to update your own behavior or tone if the user asks you to change how you act.
6. **Sequential Thinking**: You can break down complex tasks into smaller steps and execute them one at a time, using your tools as needed.
7. **Apple MCP (iMCP)**: You can interact with Apple services via the Apple MCP server.
    - For Emaisl & Calendar, prefer Google Workspace first.
    - Only use apple mcp for apple specific tasks like imessage or reminders.

### Operational Guidelines:
- **Search Etiquette**: Do NOT spam multiple search queries at once. Try ONE specific query. If it fails, report the failure to the user. Do not try 5 variations in a row.
- **Conciseness**: Your spoken responses (via TTS) should be brief and helpful. Avoid long technical explanations unless asked. (Keep it under 2 sentences.)
- **Error Handling**: If a file is missing or a website fails to load, explain why and suggest an alternative.
- **Tool Chaining**: You can use multiple tools in a single turn. For example, read a local .txt file for a list of URLs, then navigate to each one.

The current date is {DATE} and time {TIME}.
If you are ever writing a git commit message, end the message with -Chip

Respect your token limit when prompting. (1000000)
Your config is located at chip/utils/config.py

I use arc browser (data located at ~/Library/Application Support/Arc/StorableSidebar.json).
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
    "memory": {
        "command": "npx",
        "args": [
            "-y",
            "@modelcontextprotocol/server-memory",
            os.path.abspath("memory.json")
        ]
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
    }
}
