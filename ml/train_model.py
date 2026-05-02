import json
import pickle
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report

print("="*50)
print("Training Emergency Response Chat Model")
print("="*50)

# Load intents dataset
with open("intents.json", "r") as file:
    data = json.load(file)

sentences = []
labels = []

for intent in data["intents"]:
    for pattern in intent["patterns"]:
        if pattern.strip():  # Skip empty patterns
            sentences.append(pattern.lower())
            labels.append(intent["tag"])

print(f"\n📊 Dataset stats:")
print(f"   - Total training samples: {len(sentences)}")
print(f"   - Unique intents: {len(set(labels))}")
print(f"   - Intents: {list(set(labels))}")

# Convert text to numerical features - improved vectorizer
vectorizer = TfidfVectorizer(
    ngram_range=(1, 3),           # Unigrams, bigrams, trigrams for better context
    stop_words='english',
    max_features=5000,
    sublinear_tf=True,             # Better term weighting
    analyzer='word',
    strip_accents='unicode'
)
X = vectorizer.fit_transform(sentences)

print(f"\n🔧 Vectorizer created with {X.shape[1]} features")

# Split dataset
X_train, X_test, y_train, y_test = train_test_split(
    X, labels, test_size=0.2, random_state=42, stratify=labels
)

# Train with Random Forest (better than Logistic Regression)
model = RandomForestClassifier(
    n_estimators=100,
    max_depth=20,
    random_state=42,
    n_jobs=-1,
    min_samples_split=2,
    min_samples_leaf=1
)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)

print(f"\n📈 Model Performance:")
print(f"   - Accuracy: {accuracy * 100:.2f}%")

# Cross-validation score
cv_scores = cross_val_score(model, X, labels, cv=5)
print(f"   - Cross-validation (5-fold): {cv_scores.mean() * 100:.2f}% (±{cv_scores.std() * 100:.2f}%)")

# Save the trained model and vectorizer
with open("model.pkl", "wb") as f:
    pickle.dump(model, f)

with open("vectorizer.pkl", "wb") as f:
    pickle.dump(vectorizer, f)

print("\n✅ Model and vectorizer saved successfully!")
print("   - model.pkl")
print("   - vectorizer.pkl")
print("\n🚀 You can now run the chat engine!")