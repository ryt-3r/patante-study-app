# Patente B - Study Hub 🚗🧠

Studying for the Italian Patente B theory exam can be brutal, so I built this local, AI-powered study platform to make it actually bearable.

Under the hood, it’s powered by FastAPI and SQLite, but on the outside, it’s a modern, dark glassmorphism web app. It comes packed with smart translations, study cards, and AI-generated cheat sheets specifically designed to help you dodge those notoriously tricky exam questions.

## 🌟 What's Inside?

* **📚 Questions Hub:** Dive into specific topics and categories. If you're struggling with the Italian phrasing, it includes inline smart translations and AI-generated hints to guide you.
* **🧠 AI Cheat Sheet Library (`/libreria`):** My favorite part of the app. It's an interactive, searchable library of AI-generated core rules and "trap words" (the fake words they use to trick you). It's all neatly organized by chapter, complete with instant English translation toggles.
* **📝 Practice Mode:** A comprehensive session where you can just grind through the entire database at your own pace.
* **🏛️ Official Exam Simulator:** The real deal. 30 questions, 20 minutes, strictly matching the official ministerial rules.
* **🎯 The Jaccard Quiz:** I built a custom similarity-scoring algorithm for this one. It specifically hunts down and quizzes you on tricky statements that look almost identical but have completely different answers.
* **📊 Cross-Database Analysis (`/analisi`):** The ultimate anti-redundancy tool for the 7000+ question pool. It strips away duplicates to show you absolute unique questions color-coded by brain-training rules (Always True vs. Always False with luminescent filters), and groups repeated template questions into clean modal popups complete with hover-zoom road sign previews.

## 🛠️ Built With

* **Backend:** Python, FastAPI, Uvicorn, SQLite
* **Frontend:** HTML5, CSS3 (Dynasty Glassmorphism UI), Vanilla JavaScript
* **AI & Utilities:** Deep Translator, Regex, Jinja2 Templates

## 🚀 How to Run It

Want to run this locally? It's pretty straightforward.

1. **Install the prerequisites**
Make sure you have Python installed, then grab the required libraries:
```bash
pip install fastapi uvicorn jinja2 pydantic deep-translator

```


2. **Check your folders**
Make sure your project structure looks like this so the app can find all the files and images:
```text
patante-study-app-main/
├── main.py                # The FastAPI backend
├── patente_quiz.db        # The SQLite database with all the questions
├── img_sign/              # Folder containing all the road signs & figures
└── static/                # Frontend assets & templates (HTML/JSON)
    ├── index.html
    ├── domande.html
    ├── libreria.html
    ├── analisi.html         # The new cross-database analysis dashboard
    ├── cheatsheets.json
    └── text_cheatsheets.json

```


3. **Fire it up**
Open your terminal in the project folder and run the Uvicorn server:
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

```



Finally, just open your browser and go to `http://localhost:8000`. Happy studying! 🚦
