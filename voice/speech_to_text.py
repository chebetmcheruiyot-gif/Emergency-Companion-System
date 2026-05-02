import speech_recognition as sr

def listen():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300        # Sensitive to normal speech
    recognizer.pause_threshold = 1.5         # Stop after 1.5 seconds of silence
    recognizer.phrase_threshold = 0.3
    recognizer.non_speaking_duration = 0.5
    
    with sr.Microphone() as source:
        print("Listening (speak freely)...", end="", flush=True)
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        
        try:
            # Listen up to 30 seconds for speech, capture up to 30 seconds
            audio = recognizer.listen(source, timeout=30, phrase_time_limit=30)
            print("\rProcessing...", end="", flush=True)
            
            text = recognizer.recognize_google(audio, show_all=False)
            print(f"\rYou: {text}")
            return text
        except sr.WaitTimeoutError:
            print("\rNo speech detected. Try again.")
            return ""
        except sr.UnknownValueError:
            print("\rCould not understand. Try again.")
            return ""
        except sr.RequestError:
            print("\rNetwork error. Check connection.")
            return ""