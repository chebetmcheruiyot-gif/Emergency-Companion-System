import pickle

# Load trained model
model = pickle.load(open("model.pkl", "rb"))
vectorizer = pickle.load(open("vectorizer.pkl", "rb"))

def predict(text):
    text_vec = vectorizer.transform([text])
    prediction = model.predict(text_vec)[0]
    return prediction

# Test cases
print("Fire test:", predict("i can smell smoke"))
print("Medical test:", predict("i feel nausea"))
print("Greeting test:", predict("have a nice day"))