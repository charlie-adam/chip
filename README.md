# Local AI Assistant (Chip)

A professional, highly capable AI assistant with direct access a variety of MCP servers (see config)

## Features
- Voice Interaction: STT via Deepgram, TTS via Deepgram Aura.
- Tool Integration: MCP-based tools for Web Search, Google Workspace, and Terminal access.
- Apple Integration: Direct interaction with Apple services like iMessage and Reminders via iMCP.
- Memory: Persistent knowledge graph for personal facts.
- Self-Evolution: Ability to modify its own personality, behavior, code & everything else really - Including system restarts.

## Project Structure
- chip/: Source code directory.
  - audio/: Audio processing (STT/TTS).
  - core/: Main logic, state management, and services.
  - servers/: External tool servers (Terminal, Web Search).
  - utils/: Configuration and tool handling.
- data/: Persistent storage for personality and session history.
- credentials.json: Google Workspace credentials.

## Setup
1. Install dependencies using uv sync.
2. Set environment variables in a .env file (Needs GEMINI_API_KEY, DEEPGRAM_API_KEY)
3. Add credentials.json to root directory from google oath (with the google worksapce APIs enabled) 
4. Run with uv run python -m chip.core.main.
