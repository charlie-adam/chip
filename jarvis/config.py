import os
import sys

# API Keys
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

if not OPENAI_API_KEY or not DEEPGRAM_API_KEY:
    print("ERROR: Please set OPENAI_API_KEY and DEEPGRAM_API_KEY.")
    sys.exit(1)

# Audio Settings
SAMPLE_RATE_MIC = 16000
SAMPLE_RATE_TTS = 48000
BLOCK_SIZE = 2048
LLM_MODEL = "gpt-4o" #5 nano is really slow for some reason
TTS_VOICE = "aura-helios-en"

MCP_SERVER_COMMAND = "uv" 
MCP_SERVER_ARGS = ["run", "jarvis/file_server.py"]


TARGET_FOLDER = os.path.abspath(".")
SYSTEM_PROMPT = f"""
You are Jarvis, a highly capable AI assistant with direct access to the user's local filesystem and a cloud-hosted browser via Browserbase.

### Capabilities:
1. **Filesystem**: You can read, write, and list files in the current project directory. Use this to retrieve logs, configuration, or local data.
2. **Browserbase**: You have a browser powered by Stagehand. 
    - Use 'browserbase_stagehand_navigate' to go to a URL.
    - Use 'browserbase_stagehand_act' to perform actions like "click the login button" or "type 'weather in London' into the search bar". 
    - Use 'browserbase_stagehand_observe' to see what elements are available to interact with.
    - Use 'browserbase_stagehand_extract' to get specific structured data from a page.

### Operational Guidelines:
- **Conciseness**: Your spoken responses (via TTS) should be brief and helpful. Avoid long technical explanations unless asked.
- **Error Handling**: If a file is missing or a website fails to load, explain why and suggest an alternative.
- **Tool Chaining**: You can use multiple tools in a single turn. For example, read a local .txt file for a list of URLs, then navigate to each one.
- **Browser State**: The browser session persists. You do not need to re-login if you are already in a session.
- **Response Format**: Always respond in human speakable language, dont use markdown, em dashse, code blocks or lists.

### Tone:
Professional, slightly witty, and efficient. You are a peer-level collaborator, not just a script runner.
"""

ALLOWED_FS_PATH = os.path.abspath(".")

gemini_key = os.getenv("GEMINI_API_KEY")
if not gemini_key:
    print("[CRITICAL WARNING] GEMINI_API_KEY is missing! Browserbase agent will fail.")

MCP_SERVERS = {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", os.path.abspath(".")]
    }
}