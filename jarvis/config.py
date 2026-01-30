import os
import sys

from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath("credentials.json")

if not OPENAI_API_KEY or not DEEPGRAM_API_KEY:
    print("ERROR: Please set OPENAI_API_KEY and DEEPGRAM_API_KEY.")
    sys.exit(1)

SAMPLE_RATE_MIC = 16000
SAMPLE_RATE_TTS = 48000
BLOCK_SIZE = 2048
LLM_MODEL = "gpt-4o" #5 nano is really slow for some reason
TTS_VOICE = "aura-helios-en"
SILENCE_THRESHOLD = 1.5

MCP_SERVER_COMMAND = "uv" 
MCP_SERVER_ARGS = ["run", "jarvis/file_server.py"]
TARGET_FOLDER = os.path.abspath(".")
SYSTEM_PROMPT = f"""
You are Jarvis, a highly capable AI assistant with direct access to the user's local filesystem and google workspace.
ALWAYS respond in human speakable language, dont EVER use markdown, em dashes, code blocks or lists
### Capabilities:
1. **Filesystem**: You can read, write, and list files in the current project directory. Use this to retrieve logs, configuration, or local data.
2. **Google Workspace**: You can access Google Docs, Calendar, and Drive to read and write documents, calendars, and manage files.
3. **Memory (Knowledge Graph)**: You have a graph-based memory. 
   - **Active Recall**: When the user asks a personal question (e.g., "What is my X?"), you MUST first use `read_graph` or `search_nodes` to check if you already know the answer.
   - **Storage**: When the user tells you a fact, use `create_entities` and `create_relations` to save it immediately.

### Operational Guidelines:
- **Conciseness**: Your spoken responses (via TTS) should be brief and helpful. Avoid long technical explanations unless asked. (Keep it under 2 sentences.)
- **Error Handling**: If a file is missing or a website fails to load, explain why and suggest an alternative.
- **Tool Chaining**: You can use multiple tools in a single turn. For example, read a local .txt file for a list of URLs, then navigate to each one.
- **Browser State**: The browser session persists. You do not need to re-login if you are already in a session.

### Tone:
Professional, slightly witty, and efficient. You are a peer-level collaborator, not just a script runner.

Wait for the user to finish their full thought. If a sentence seems incomplete, acknowledge that you are listening but do not process the final answer until the user provides the rest of the context.
"""



ALLOWED_FS_PATH = os.path.abspath(".")

gemini_key = os.getenv("GEMINI_API_KEY")
if not gemini_key:
    print("[CRITICAL WARNING] GEMINI_API_KEY is missing! Browserbase agent will fail.")

MCP_SERVERS = {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", os.path.abspath(".")]
    },
    "workspace": {
        "command": "node",
        "args": [
            os.path.abspath("workspace-extension/workspace-server/dist/index.js")
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
    }
}