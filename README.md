# Local AI Assistant (Chip)

A professional, highly capable AI assistant with direct access to local files and Google Workspace.

## Features
- **Voice Interaction**: STT via Deepgram, TTS via Deepgram Aura.
- **Tool Integration**: MCP-based tools for Web Search, Google Workspace, and Terminal access.
- **Memory**: Persistent knowledge graph for personal facts.
- **Self-Evolution**: Ability to modify its own personality and behavior.

## Project Structure
- `chip/`: Core source code.
  - `main.py`: Entry point.
  - `services.py`: LLM, STT, and TTS integrations.
  - `config.py`: Configuration and system prompts.
  - `tools_handler.py`: MCP tool management.
- `personality.txt`: Defines the AI's persona.
- `credentials.json`: Google Workspace credentials.

## Setup
1. Install dependencies using `uv sync`.
2. Set environment variables in a `.env` file (see `.env.example`).
3. Run with `uv run chip/main.py`.
