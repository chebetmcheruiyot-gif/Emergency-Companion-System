import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from ml.chat_engine import get_response
from voice.speech_to_text import listen

print("🎤 Voice to Text. Say 'stop' or 'quit' to end.\n")

try:
    while True:
        user_input = listen()
        
        if not user_input:
            continue
        
        if any(word in user_input.lower() for word in ["stop", "quit", "exit", "goodbye"]):
            print("Agent: Stay safe. Goodbye!")
            break
        
        response = get_response(user_input)
        print(f"Agent: {response}\n")

except KeyboardInterrupt:
    print("\nStopped.")