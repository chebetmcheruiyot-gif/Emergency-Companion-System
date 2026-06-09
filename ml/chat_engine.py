import pickle
import json
import random
import os
import requests
import sys
import re
from dotenv import load_dotenv

# Suppress ALL console output during normal operation
class SuppressOutput:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = None
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

BASE_DIR = os.path.dirname(__file__)

# Load ML model (as backup only)
try:
    model = pickle.load(open(os.path.join(BASE_DIR, "model.pkl"), "rb"))
    vectorizer = pickle.load(open(os.path.join(BASE_DIR, "vectorizer.pkl"), "rb"))
except:
    model = None
    vectorizer = None

# Load intents
with open(os.path.join(BASE_DIR, "intents.json")) as file:
    intents = json.load(file)

# Track emergency context
current_emergency = None

def call_groq(user_input, context=None):
    """Main response generator - uses Groq API (silent)"""
    if not GROQ_API_KEY:
        return None
    
    try:
        context_prompt = ""
        if context:
            context_prompt = f"Previous context: {context}\n"
        
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": "You are SHELL, an emergency response assistant. Give ONLY brief action steps. No bold text. No asterisks. No labels. Be concise and helpful."},
                    {"role": "user", "content": f"{context_prompt}User emergency: {user_input}"}
                ],
                "temperature": 0.3,
                "max_tokens": 150
            },
            timeout=5
        )
        if response.status_code == 200:
            result = response.json()["choices"][0]["message"]["content"]
            # Clean up formatting
            result = result.replace("**", "").replace("*", "")
            result = re.sub(r'\d+\.\s*', '', result)
            result = result.replace("SHELL:", "").replace("Assistant:", "").strip()
            return result
    except:
        pass  # Silently fail - no user sees this
    
    return None

def call_ml_fallback(user_input):
    """Fallback to ML model if Groq fails (silent)"""
    if model is None or vectorizer is None:
        return None
    
    with SuppressOutput():
        try:
            text_vec = vectorizer.transform([user_input.lower()])
            probs = model.predict_proba(text_vec)[0]
            confidence = max(probs)
            intent = model.classes_[probs.argmax()]
            
            if confidence > 0.45:
                for item in intents["intents"]:
                    if item["tag"] == intent:
                        steps = item["responses"]
                        if len(steps) > 1:
                            clean_steps = [step.replace("**", "") for step in steps]
                            clean_steps = [re.sub(r'^\d+\.\s*', '', s) for s in clean_steps]
                            return "\n".join(clean_steps)
                        return random.choice(steps)
        except:
            pass
    
    return None

def get_response(user_input, conversation_history=None):
    """Main function - PRIORITIZES GROQ API for good responses (NO DEBUG OUTPUT)"""
    global current_emergency
    
    if not user_input:
        return "Please describe your emergency."
    
    user_lower = user_input.lower().strip()
    
    # Quick responses for greetings/goodbyes
    if any(word in user_lower for word in ['hello', 'hi', 'hey']) and len(user_lower.split()) <= 3:
        for item in intents["intents"]:
            if item["tag"] == "greeting":
                return random.choice(item["responses"])
    
    if any(word in user_lower for word in ['thank you', 'thanks', 'goodbye', 'bye']):
        current_emergency = None
        for item in intents["intents"]:
            if item["tag"] == "goodbye":
                return random.choice(item["responses"])
    
    # Build context from history
    context = None
    if conversation_history:
        last_few = conversation_history[-4:] if len(conversation_history) > 4 else conversation_history
        context_parts = []
        for entry in last_few:
            if entry.get('role') == 'user':
                context_parts.append(f"User said: {entry.get('content', '')}")
        if context_parts:
            context = " | ".join(context_parts)
    
    # PRIORITY 1: Try Groq API (best responses)
    groq_response = call_groq(user_input, context)
    if groq_response:
        return groq_response
    
    # PRIORITY 2: Try ML fallback (ok responses)
    ml_response = call_ml_fallback(user_input)
    if ml_response:
        return ml_response
    
    # PRIORITY 3: Final fallback
    return "Call 999 immediately. Tell me what's happening - medical, fire, police, or accident?"

if __name__ == "__main__":
   
    print("SHELL Emergency Assistant")
   
    print("\nType 'quit' to exit\n")
    
    while True:
        msg = input("You: ")
        if msg.lower() in ["quit", "exit"]:
            print("SHELL: Stay safe. Goodbye!")
            break
        response = get_response(msg)
        print(f"SHELL: {response}")
        print()