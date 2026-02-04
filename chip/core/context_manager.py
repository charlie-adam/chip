import os
import asyncio
from google.genai import types
from colorama import Fore, Style, init
init(autoreset=True)

# File paths
PERSONALITY_FILE = "data/personality.txt"
SUMMARY_FILE = "data/last_session.txt"
USER_CUSTOMS = "data/user_customs.txt"

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
    
    with open(USER_CUSTOMS, "r") as f:
        customs = f.read().strip()
        if customs:
            personality += f"\n\n### USER CUSTOMS:\n{customs}"
        
    return personality, last_summary

async def generate_and_save_summary(full_history, services_module):
    print(f"\n{Fore.LIGHTBLACK_EX}[SYSTEM] Generating session summary...{Style.RESET_ALL}")
    
    summary_request = "Summarise the key topics, decisions, and user preferences from our conversation above. Keep it concise (under 100 words) so you remember it for next time."
    
    full_history.append(types.Content(role="user", parts=[types.Part.from_text(text=summary_request)]))
    
    try:
        response = await services_module.ask_llm(
            full_history, 
            system_instruction="You are a helpful summariser. DO NOT use functions. Respond only with plain text.",
            tools=[] 
        )
        if response.candidates and response.candidates[0].content.parts:
            part = response.candidates[0].content.parts[0]
            if part.text:
                summary_text = part.text
            elif part.function_call:
                summary_text = part.function_call.args.get('content', '')
            
            if summary_text and isinstance(summary_text, str):
                with open(SUMMARY_FILE, "w") as f:
                    f.write(summary_text)
                print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Summary saved: {summary_text[:50]}...{Style.RESET_ALL}")
            else:
                print(f"{Fore.LIGHTBLACK_EX}[SYSTEM] Skipped: Model returned empty text.{Style.RESET_ALL}")
                
    except Exception as e:
        print(f"{Fore.RED}[ERROR] Could not save summary: {e}{Style.RESET_ALL}")