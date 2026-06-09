import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from ml.chat_engine import get_response
from voice.speech_to_text import listen
from voice.text_to_speech import speak

print("🎤 Voice Assistant. Say 'stop' or 'quit' to end.\n")

try:
    while True:
        user_input = listen()
        
        if not user_input:
            continue
        
        if any(word in user_input.lower() for word in ["stop", "quit", "exit", "goodbye"]):
            speak("Stay safe. Goodbye.")
            break
        
        # Get response (no debug output)
        response = get_response(user_input)
        print(f"Agent: {response}")
        
        # Speak the response
        speak(response)

except KeyboardInterrupt:
    print("\nStopped.")