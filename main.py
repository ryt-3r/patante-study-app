from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import os
import re
import random
from deep_translator import GoogleTranslator

app = FastAPI()

app.mount("/img_sign", StaticFiles(directory="img_sign"), name="img_sign")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Data Models ---
class FlagUpdate(BaseModel):
    id: int
    flagged: int

class AnswerUpdate(BaseModel):
    id: int
    status: str

class ResetRequest(BaseModel):
    category: str
    subcategory: str
    figure: str

class ExamAnswer(BaseModel):
    id: int
    is_correct: bool
    is_guessed: bool

class ExamSubmit(BaseModel):
    answers: list[ExamAnswer]

# --- Database Initialization with Safety Nets ---
def init_db():
    if not os.path.exists('patente_quiz.db'):
        return
    # Added a timeout in case the database is briefly locked
    conn = sqlite3.connect('patente_quiz.db', timeout=10)
    
    def safe_add_column(col_name, col_type):
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass # Column already exists or DB locked
            
    safe_add_column("flagged", "INTEGER DEFAULT 0")
    safe_add_column("status", "TEXT DEFAULT 'unseen'")
    safe_add_column("ever_wrong", "INTEGER DEFAULT 0")
    safe_add_column("ever_guessed", "INTEGER DEFAULT 0")
    
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect('patente_quiz.db', timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

# --- Web Page Routes ---
@app.get("/")
def read_root():
    return FileResponse("static/index.html", media_type="text/html")

@app.get("/domande")
def read_domande():
    return FileResponse("static/domande.html", media_type="text/html")

@app.get("/quiz")
def read_quiz():
    return FileResponse("static/quiz.html", media_type="text/html")

@app.get("/official")
def read_official():
    return FileResponse("static/official.html", media_type="text/html")

# --- Study App APIs ---
@app.get("/api/categories")
def get_categories():
    try:
        conn = get_db_connection()
        categories = conn.execute('SELECT categoria, COUNT(*) as count FROM questions GROUP BY categoria ORDER BY count DESC').fetchall()
        conn.close()
        return [{"name": str(row['categoria']), "count": row['count']} for row in categories]
    except Exception as e: return {"error": str(e)}

@app.get("/api/subcategories")
def get_subcategories(category: str):
    try:
        conn = get_db_connection()
        subcats = conn.execute('SELECT sottocategoria, COUNT(*) as count FROM questions WHERE categoria = ? GROUP BY sottocategoria ORDER BY count DESC', (category,)).fetchall()
        conn.close()
        return [{"name": str(row['sottocategoria']), "count": row['count']} for row in subcats]
    except Exception as e: return {"error": str(e)}

@app.get("/api/figures")
def get_figures(category: str, subcategory: str):
    try:
        conn = get_db_connection()
        figures = conn.execute('SELECT figura, COUNT(*) as count FROM questions WHERE categoria = ? AND sottocategoria = ? AND figura IS NOT NULL GROUP BY figura ORDER BY count DESC', (category, subcategory)).fetchall()
        conn.close()
        return [{"name": str(row['figura']), "count": row['count']} for row in figures]
    except Exception as e: return {"error": str(e)}

@app.get("/api/content")
def get_content(category: str, subcategory: str = 'all', figure: str = 'all', flagged_only: str = 'false'):
    try:
        conn = get_db_connection()
        params = [category]
        
        if flagged_only == 'true':
            query = 'SELECT * FROM questions WHERE categoria = ? AND flagged = 1'
        else:
            if subcategory == 'all':
                conn.close()
                return {"data": [], "message": "Seleziona un Argomento (2) o clicca su 'Ripassa Salvate'."}
            query = 'SELECT * FROM questions WHERE categoria = ? AND sottocategoria = ?'
            params.append(subcategory)
            if figure != 'all':
                query += ' AND figura = ?'
                params.append(figure)
                
        rows = conn.execute(query, params).fetchall()
        conn.close()
        
        grouped_content = {}
        for row in rows:
            row_dict = dict(row)
            fig = row_dict['figura'] or 'no_image'
            if fig not in grouped_content:
                grouped_content[fig] = {"figura": row_dict['figura'], "vero": [], "falso": []}
                
            q_data = {"id": row_dict['id'], "domanda": str(row_dict['domanda']), "flagged": row_dict.get('flagged', 0)}
            if row_dict['risposta']: grouped_content[fig]["vero"].append(q_data)
            else: grouped_content[fig]["falso"].append(q_data)
                
        return {"data": list(grouped_content.values()), "message": ""}
    except Exception as e: return {"error": str(e)}

@app.post("/api/toggle_flag")
def toggle_flag(update: FlagUpdate):
    conn = get_db_connection()
    conn.execute('UPDATE questions SET flagged = ? WHERE id = ?', (update.flagged, update.id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.get("/api/translate")
def translate_word(word: str):
    try:
        clean_word = re.sub(r'[^\w\s\']', '', word).strip()
        if not clean_word: return {"translation": ""}
        translator = GoogleTranslator(source='it', target='en')
        return {"translation": translator.translate(clean_word).lower()}
    except Exception as e: return {"error": str(e)}

# --- Unified Stats API (Supports Both Quizzes) ---
@app.get("/api/stats")
def get_stats(category: str = 'all', subcategory: str = 'all', figure: str = 'all'):
    try:
        conn = get_db_connection()
        query = 'SELECT status, COUNT(*) as count FROM questions WHERE 1=1'
        params = []
        
        if category != 'all':
            query += ' AND categoria = ?'
            params.append(category)
        if subcategory != 'all':
            query += ' AND sottocategoria = ?'
            params.append(subcategory)
        if figure != 'all':
            query += ' AND figura = ?'
            params.append(figure)
            
        query += ' GROUP BY status'
        stats = conn.execute(query, params).fetchall()
        
        # Self-healing check if memory columns failed to create
        try:
            ew = conn.execute('SELECT COUNT(*) as c FROM questions WHERE ever_wrong = 1').fetchone()['c']
            eg = conn.execute('SELECT COUNT(*) as c FROM questions WHERE ever_guessed = 1').fetchone()['c']
        except sqlite3.OperationalError:
            ew, eg = 0, 0
            
        conn.close()
        
        stat_dict = {'unseen': 0, 'correct': 0, 'wrong': 0, 'skipped': 0, 'ever_wrong': ew, 'ever_guessed': eg}
        for row in stats:
            stat_dict[row['status']] = row['count']
        return stat_dict
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Original Quiz APIs ---
@app.get("/api/question")
def get_question(mode: str = 'unseen', category: str = 'all', subcategory: str = 'all', figure: str = 'all'):
    try:
        conn = get_db_connection()
        query = 'SELECT * FROM questions WHERE status = ?'
        params = [mode]
        
        if category != 'all':
            query += ' AND categoria = ?'
            params.append(category)
        if subcategory != 'all':
            query += ' AND sottocategoria = ?'
            params.append(subcategory)
        if figure != 'all':
            query += ' AND figura = ?'
            params.append(figure)
            
        query += ' ORDER BY RANDOM() LIMIT 1'
        question = conn.execute(query, params).fetchone()
        conn.close()
        
        if question is None:
            raise HTTPException(status_code=404, detail="Nessuna domanda trovata.")
        return dict(question)
    except HTTPException: raise
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/update_status")
def update_status(update: AnswerUpdate):
    conn = get_db_connection()
    conn.execute('UPDATE questions SET status = ? WHERE id = ?', (update.status, update.id))
    conn.commit()
    conn.close()
    return {"success": True}

@app.post("/api/reset")
def reset_progress(req: ResetRequest):
    conn = get_db_connection()
    query = "UPDATE questions SET status = 'unseen' WHERE 1=1"
    params = []
    
    if req.category != 'all':
        query += " AND categoria = ?"
        params.append(req.category)
    if req.subcategory != 'all':
        query += " AND sottocategoria = ?"
        params.append(req.subcategory)
    if req.figure != 'all':
        query += " AND figura = ?"
        params.append(req.figure)
        
    conn.execute(query, params)
    conn.commit()
    conn.close()
    return {"success": True}

# --- Official Exam APIs ---
@app.get("/api/generate_exam")
def generate_exam():
    try:
        conn = get_db_connection()
        all_cats = [row['categoria'] for row in conn.execute('SELECT DISTINCT categoria FROM questions').fetchall()]
        
        important_keywords = ['pericolo', 'divieto', 'obbligo', 'precedenza', 'orizzontale', 'semafor', 'velocit', 'distanza', 'incroc', 'norme', 'sorpasso', 'ingombro', 'sicurezza', 'incident', 'psico']
        important_cats = [c for c in all_cats if any(kw in c.lower() for kw in important_keywords)]
        less_cats = [c for c in all_cats if c not in important_cats]
        
        random.shuffle(important_cats)
        cats_getting_two = important_cats[:5]
        cats_getting_one = important_cats[5:]
        
        exam_questions = []
        
        def fetch_questions(cat, limit):
            # Try/Catch completely isolates database read failures
            try:
                query = '''SELECT id, domanda, figura, risposta FROM questions 
                           WHERE categoria = ? AND (status = 'unseen' OR ever_wrong = 1 OR ever_guessed = 1)
                           ORDER BY RANDOM() LIMIT ?'''
                return [dict(row) for row in conn.execute(query, (cat, limit)).fetchall()]
            except sqlite3.OperationalError:
                # Failsafe if the ever_wrong columns are missing
                query = '''SELECT id, domanda, figura, risposta FROM questions 
                           WHERE categoria = ? AND status = 'unseen'
                           ORDER BY RANDOM() LIMIT ?'''
                return [dict(row) for row in conn.execute(query, (cat, limit)).fetchall()]
            
        for cat in cats_getting_two: exam_questions.extend(fetch_questions(cat, 2))
        for cat in cats_getting_one: exam_questions.extend(fetch_questions(cat, 1))
        for cat in less_cats: exam_questions.extend(fetch_questions(cat, 1))
            
        conn.close()
        random.shuffle(exam_questions)
        return {"questions": exam_questions}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/submit_exam")
def submit_exam(submit: ExamSubmit):
    try:
        conn = get_db_connection()
        for ans in submit.answers:
            new_status = 'correct' if ans.is_correct else 'wrong'
            
            try:
                if not ans.is_correct:
                    conn.execute('UPDATE questions SET ever_wrong = 1 WHERE id = ?', (ans.id,))
                if ans.is_guessed:
                    conn.execute('UPDATE questions SET ever_guessed = 1 WHERE id = ?', (ans.id,))
            except sqlite3.OperationalError:
                pass # Silently proceed if memory columns failed to create
                
            conn.execute('UPDATE questions SET status = ? WHERE id = ?', (new_status, ans.id))
            
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
