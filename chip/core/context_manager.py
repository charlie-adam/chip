import os
import asyncio
from google.genai import types

# File paths
PERSONALITY_FILE = "data/personality.txt"
SUMMARY_FILE = "data/last_session.txt"

def ensure_files_exist():
    """Creates the files if they don't exist yet."""
    if not os.path.exists(PERSONALITY_FILE):
        with open(PERSONALITY_FILE, "w") as f:
            f.write("You are a helpful and witty assistant.")
    
    if not os.path.exists(SUMMARY_FILE):
        with open(SUMMARY_FILE, "w") as f:
            f.write("No previous session context available.")

def load_context():
    """Reads the personality and last summary."""
    ensure_files_exist()
    
    with open(PERSONALITY_FILE, "r") as f:
        personality = f.read().strip()
        
    with open(SUMMARY_FILE, "r") as f:
        last_summary = f.read().strip()
        
    return personality, last_summary

async def generate_and_save_summary(full_history, services_module):
    """
    Takes the chat history, asks the LLM to summarize it, 
    and saves it to last_session.txt.
    """
    print("\n[SYSTEM] Generating session summary...")
    
    summary_request = "Summarize the key topics, decisions, and user preferences from our conversation above. Keep it concise (under 100 words) so you remember it for next time."
    
    full_history.append(types.Content(role="user", parts=[types.Part.from_text(text=summary_request)]))
    
    try:
        response = await services_module.ask_llm(
            full_history, 
            system_instruction="You are a helpful summarizer.",
            tools=[] 
        )
        
        if response.candidates:
            summary_text = response.candidates[0].content.parts[0].text
            
            with open(SUMMARY_FILE, "w") as f:
                f.write(summary_text)
            
            print(f"[SYSTEM] Summary saved: {summary_text[:50]}...")
    except Exception as e:
        print(f"[ERROR] Could not save summary: {e}")