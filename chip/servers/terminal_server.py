import os
import subprocess
from mcp.server.fastmcp import FastMCP

# Initialize the server
mcp = FastMCP("terminal")

# Track the current directory persistently
CURRENT_DIR = os.getcwd()

@mcp.tool()
def execute_command(command: str) -> str:
    """
    Executes a shell command in the terminal. 
    Supports stateful 'cd' commands to change directories.
    """
    global CURRENT_DIR
    
    # Security: Block obvious destructive commands (Basic filter)
    FORBIDDEN = ["rm -rf /", ":(){ :|:& };:"] 
    if any(bad in command for bad in FORBIDDEN):
        return "Error: Command blocked for security reasons."

    try:
        # Handle 'cd' manually because subprocess runs in a subshell
        if command.strip().startswith("cd "):
            target = command.strip().split(" ", 1)[1]
            new_path = os.path.abspath(os.path.join(CURRENT_DIR, target))
            
            if os.path.exists(new_path) and os.path.isdir(new_path):
                CURRENT_DIR = new_path
                return f"Changed directory to: {CURRENT_DIR}"
            else:
                return f"Error: Directory not found: {target}"

        # Execute standard commands
        result = subprocess.run(
            command,
            cwd=CURRENT_DIR,
            shell=True,
            capture_output=True,
            text=True,
            timeout=5  # Timeout to prevent hanging
        )
        
        output = result.stdout
        if result.stderr:
            output += f"\n[STDERR]\n{result.stderr}"
            
        return output.strip() or "[Command executed successfully with no output]"

    except subprocess.TimeoutExpired:
        return "Error: Command timed out after 5 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"

if __name__ == "__main__":
    mcp.run()