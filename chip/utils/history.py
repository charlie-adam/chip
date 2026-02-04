from google.genai import types

def sanitise_tool_outputs(history):
    """
    Scans history for large Tool Responses and truncates them to save tokens.
    """
    for i in range(len(history) - 3):
        message = history[i]
        if message.role == "user":
            for part in message.parts:
                if part.function_response:
                    current_response = part.function_response.response
                    if "result" in current_response and len(str(current_response["result"])) > 2000:
                        original_len = len(str(current_response["result"]))
                        part.function_response.response = {
                            "result": f"[Output Truncated - Original Length: {original_len} chars]. Context: Tool executed successfully."
                        }
    return history

def safe_trim_history(history, max_length=14):
    """
    Trims history but ensures we always start with a clean User message.
    """
    if len(history) <= max_length:
        return history

    start_index = len(history) - max_length
    while start_index < len(history):
        message = history[start_index]
        if message.role == "user":
            is_tool_response = any(part.function_response for part in message.parts)
            if not is_tool_response:
                return history[start_index:]
        start_index += 1

    return history[-2:]