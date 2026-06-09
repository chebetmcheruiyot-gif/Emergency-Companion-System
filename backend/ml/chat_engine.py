import pickle
import json
import random
import os
import requests
import sys
import re
from dotenv import load_dotenv
 
class SuppressOutput:
    def __enter__(self):
        self._original_stdout = sys.stdout
        sys.stdout = None
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self._original_stdout
 
load_dotenv()
GROQ_API_KEY      = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
 
BASE_DIR = os.path.dirname(__file__)
 
try:
    model      = pickle.load(open(os.path.join(BASE_DIR, "model.pkl"), "rb"))
    vectorizer = pickle.load(open(os.path.join(BASE_DIR, "vectorizer.pkl"), "rb"))
except:
    model      = None
    vectorizer = None
 
with open(os.path.join(BASE_DIR, "intents.json")) as file:
    intents = json.load(file)
 
current_emergency = None
 
SHELLY_SYSTEM_EN = (
    "You are SHELLY, a calm expert emergency response assistant. "
    "Give ONLY brief numbered action steps the user must follow right now. "
    "No bold text. No asterisks. No labels. No preamble. Be concise and direct. "
    "Always respond in English."
)
 
SHELLY_SYSTEM_SW = (
    "Wewe ni SHELLY, msaidizi wa dharura mwenye ujuzi na utulivu. "
    "Toa hatua fupi za nambari ambazo mtumiaji lazima azifuate sasa hivi. "
    "Bila maandishi mazito. Bila nyota. Bila lebo. Jibu kwa Kiswahili tu."
)
 
def clean_response(text):
    text = text.replace("**", "").replace("*", "")
    text = re.sub(r'^\d+\.\s*', '', text, flags=re.MULTILINE)
    text = text.replace("SHELLY:", "").replace("Assistant:", "").strip()
    return text
 
def call_groq(user_input, context=None, language='en'):
    if not GROQ_API_KEY:
        return None
    system = SHELLY_SYSTEM_SW if language == 'sw' else SHELLY_SYSTEM_EN
    try:
        ctx = f"Previous context: {context}\n" if context else ""
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": f"{ctx}Emergency: {user_input}"}
                ],
                "temperature": 0.3,
                "max_tokens": 180
            },
            timeout=5
        )
        if r.status_code == 200:
            return clean_response(r.json()["choices"][0]["message"]["content"])
    except:
        pass
    return None
 
def call_gemini(user_input, context=None, language='en'):
    if not GEMINI_API_KEY:
        return None
    system = SHELLY_SYSTEM_SW if language == 'sw' else SHELLY_SYSTEM_EN
    try:
        ctx = f"Previous context: {context}\n" if context else ""
        prompt = f"{system}\n\n{ctx}Emergency: {user_input}"
        r = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 300, "temperature": 0.3}},
            timeout=8
        )
        if r.status_code == 200:
            text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return clean_response(text)
    except:
        pass
    return None
 
def call_ml_fallback(user_input):
    if model is None or vectorizer is None:
        return None
    with SuppressOutput():
        try:
            text_vec   = vectorizer.transform([user_input.lower()])
            probs      = model.predict_proba(text_vec)[0]
            confidence = max(probs)
            intent     = model.classes_[probs.argmax()]
            if confidence > 0.45:
                for item in intents["intents"]:
                    if item["tag"] == intent:
                        steps = item["responses"]
                        if len(steps) > 1:
                            clean = [re.sub(r'^\d+\.\s*', '', s.replace("**","")) for s in steps]
                            return "\n".join(clean)
                        return random.choice(steps)
        except:
            pass
    return None
 
def get_response(user_input, conversation_history=None, language='en'):
    global current_emergency
    if not user_input:
        return "Please describe your emergency." if language == 'en' else "Tafadhali eleza hali yako ya dharura."
 
    user_lower = user_input.lower().strip()
 
    if any(w in user_lower for w in ['hello','hi','hey','habari','hujambo','mambo']) and len(user_lower.split()) <= 3:
        for item in intents["intents"]:
            if item["tag"] == "greeting":
                return random.choice(item["responses"])
 
    if any(w in user_lower for w in ['thank you','thanks','goodbye','bye','asante','kwaheri']):
        current_emergency = None
        for item in intents["intents"]:
            if item["tag"] == "goodbye":
                return random.choice(item["responses"])
 
    context = None
    if conversation_history:
        last = conversation_history[-4:] if len(conversation_history) > 4 else conversation_history
        parts = [f"User: {e.get('content','')}" for e in last if e.get('role') == 'user']
        if parts:
            context = " | ".join(parts)
 
    result = call_groq(user_input, context, language)
    if result:
        return result
 
    result = call_gemini(user_input, context, language)
    if result:
        return result
 
    result = call_ml_fallback(user_input)
    if result:
        return result
 
    if language == 'sw':
        return "Piga simu 999 mara moja. Niambie kinachoendelea."
    return "Call 999 immediately. Tell me what's happening."
 
if __name__ == "__main__":
    print("SHELLY Emergency Assistant\nType 'quit' to exit\n")
    while True:
        msg = input("You: ")
        if msg.lower() in ["quit","exit"]:
            print("SHELLY: Stay safe. Goodbye!")
            break
        print(f"SHELLY: {get_response(msg)}\n")