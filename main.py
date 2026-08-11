from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
import sqlite3
import os
import re
import random
from collections import defaultdict
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
    answers: List[ExamAnswer]

class TranslateReq(BaseModel):
    word: str
    phrase: str
    sentence: str

# --- Database Initialization with Safety Nets ---
def init_db():
    if not os.path.exists('patente_quiz.db'):
        return
    conn = sqlite3.connect('patente_quiz.db', timeout=10)
    
    def safe_add_column(col_name, col_type):
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass 
            
    # Standard Memory
    safe_add_column("flagged", "INTEGER DEFAULT 0")
    safe_add_column("status", "TEXT DEFAULT 'unseen'")
    safe_add_column("ever_wrong", "INTEGER DEFAULT 0")
    safe_add_column("ever_guessed", "INTEGER DEFAULT 0")
    
    # Jaccard Independent Memory
    safe_add_column("jaccard_status", "TEXT DEFAULT 'unseen'")
    safe_add_column("jaccard_ever_wrong", "INTEGER DEFAULT 0")
    safe_add_column("jaccard_ever_guessed", "INTEGER DEFAULT 0")
    
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

@app.get("/jaccard")
def read_jaccard():
    return FileResponse("static/jaccard.html", media_type="text/html")

# --- Study App APIs ---
@app.get("/api/categories")
def get_categories():
    try:
        conn = get_db_connection()
        categories = conn.execute('SELECT categoria, COUNT(*) as count FROM questions WHERE categoria IS NOT NULL GROUP BY categoria').fetchall()
        conn.close()
        
        important_keywords = ['pericolo', 'divieto', 'obbligo', 'precedenza', 'orizzontale', 'semafor', 'velocit', 'distanza', 'incroc', 'norme', 'sorpasso', 'ingombro', 'sicurezza', 'incident', 'psico']
        
        result = []
        for row in categories:
            cat_name = str(row['categoria'])
            # Tag as important if it matches official keywords
            is_imp = any(kw in cat_name.lower() for kw in important_keywords)
            result.append({
                "name": cat_name, 
                "count": row['count'],
                "is_important": is_imp
            })
            
        # Sort: Important chapters first, then ordered by size
        result.sort(key=lambda x: (not x['is_important'], -x['count']))
        return result
    except Exception as e: return {"error": str(e)}

@app.get("/api/subcategories")
def get_subcategories(category: str):
    try:
        conn = get_db_connection()
        # Subcategories are ordered purely by count size (most questions first)
        subcats = conn.execute('SELECT sottocategoria, COUNT(*) as count FROM questions WHERE categoria = ? AND sottocategoria IS NOT NULL GROUP BY sottocategoria ORDER BY count DESC', (category,)).fetchall()
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

@app.post("/api/translate_smart")
def translate_smart(req: TranslateReq):
    try:
        translator = GoogleTranslator(source='it', target='en')
        clean_w = re.sub(r'[^\w\s\']', '', req.word).strip()
        clean_p = re.sub(r'[^\w\s\']', '', req.phrase).strip()
        
        t_word = translator.translate(clean_w).lower() if clean_w else ""
        t_phrase = translator.translate(clean_p).lower() if clean_p else ""
        t_sentence = translator.translate(req.sentence)
        
        return {"word": t_word, "phrase": t_phrase, "sentence": t_sentence}
    except Exception as e: return {"error": str(e)}

# --- Unified Stats API ---
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
        
        try:
            ew = conn.execute('SELECT COUNT(*) as c FROM questions WHERE ever_wrong = 1').fetchone()['c']
            eg = conn.execute('SELECT COUNT(*) as c FROM questions WHERE ever_guessed = 1').fetchone()['c']
        except sqlite3.OperationalError:
            ew, eg = 0, 0
        conn.close()
        
        stat_dict = {'unseen': 0, 'correct': 0, 'wrong': 0, 'skipped': 0, 'ever_wrong': ew, 'ever_guessed': eg}
        for row in stats: stat_dict[row['status']] = row['count']
        return stat_dict
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

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
        
        if question is None: raise HTTPException(status_code=404, detail="Nessuna domanda trovata.")
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
        all_cats = [row['categoria'] for row in conn.execute('SELECT DISTINCT categoria FROM questions WHERE categoria IS NOT NULL').fetchall()]
        important_keywords = ['pericolo', 'divieto', 'obbligo', 'precedenza', 'orizzontale', 'semafor', 'velocit', 'distanza', 'incroc', 'norme', 'sorpasso', 'ingombro', 'sicurezza', 'incident', 'psico']
        important_cats = [c for c in all_cats if any(kw in str(c).lower() for kw in important_keywords)]
        less_cats = [c for c in all_cats if c not in important_cats]
        
        random.shuffle(important_cats)
        cats_getting_two = important_cats[:5]
        cats_getting_one = important_cats[5:]
        
        exam_questions = []
        def fetch_questions(cat, limit):
            try:
                query = '''SELECT id, domanda, figura, risposta FROM questions 
                           WHERE categoria = ? AND (status = 'unseen' OR ever_wrong = 1 OR ever_guessed = 1)
                           ORDER BY RANDOM() LIMIT ?'''
                return [dict(row) for row in conn.execute(query, (cat, limit)).fetchall()]
            except Exception:
                query = '''SELECT id, domanda, figura, risposta FROM questions WHERE categoria = ? AND status = 'unseen' ORDER BY RANDOM() LIMIT ?'''
                return [dict(row) for row in conn.execute(query, (cat, limit)).fetchall()]
            
        for cat in cats_getting_two: exam_questions.extend(fetch_questions(cat, 2))
        for cat in cats_getting_one: exam_questions.extend(fetch_questions(cat, 1))
        for cat in less_cats: exam_questions.extend(fetch_questions(cat, 1))
            
        conn.close()
        random.shuffle(exam_questions)
        return {"questions": exam_questions}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

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
            except Exception: pass 
            conn.execute('UPDATE questions SET status = ? WHERE id = ?', (new_status, ans.id))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

# --- Independent Jaccard APIs ---
@app.get("/api/jaccard_stats")
def get_jaccard_stats():
    try:
        conn = get_db_connection()
        try:
            stats = conn.execute('SELECT jaccard_status, COUNT(*) as count FROM questions GROUP BY jaccard_status').fetchall()
            ew = conn.execute('SELECT COUNT(*) as c FROM questions WHERE jaccard_ever_wrong = 1').fetchone()['c']
            eg = conn.execute('SELECT COUNT(*) as c FROM questions WHERE jaccard_ever_guessed = 1').fetchone()['c']
        except sqlite3.OperationalError:
            stats = []
            ew, eg = 0, 0
        conn.close()
        
        stat_dict = {'unseen': 0, 'correct': 0, 'wrong': 0, 'skipped': 0, 'ever_wrong': ew, 'ever_guessed': eg}
        for row in stats:
            status_val = row['jaccard_status'] if row['jaccard_status'] else 'unseen'
            if status_val in stat_dict: stat_dict[status_val] += row['count']
            else: stat_dict[status_val] = row['count']
        return stat_dict
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/submit_jaccard_exam")
def submit_jaccard_exam(submit: ExamSubmit):
    try:
        conn = get_db_connection()
        for ans in submit.answers:
            new_status = 'correct' if ans.is_correct else 'wrong'
            try:
                if not ans.is_correct:
                    conn.execute('UPDATE questions SET jaccard_ever_wrong = 1 WHERE id = ?', (ans.id,))
                if ans.is_guessed:
                    conn.execute('UPDATE questions SET jaccard_ever_guessed = 1 WHERE id = ?', (ans.id,))
            except Exception: pass 
            conn.execute('UPDATE questions SET jaccard_status = ? WHERE id = ?', (new_status, ans.id))
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/generate_jaccard_exam")
def generate_jaccard_exam():
    try:
        conn = get_db_connection()
        try:
            all_qs = conn.execute('SELECT id, domanda, categoria, figura, risposta, jaccard_status, jaccard_ever_wrong, jaccard_ever_guessed FROM questions WHERE categoria IS NOT NULL').fetchall()
        except sqlite3.OperationalError:
            all_qs = conn.execute('SELECT id, domanda, categoria, figura, risposta, "unseen" as jaccard_status, 0 as jaccard_ever_wrong, 0 as jaccard_ever_guessed FROM questions WHERE categoria IS NOT NULL').fetchall()
            
        conn.close()
        
        grouped = defaultdict(lambda: {'V': [], 'F': []})
        questions_by_id = {}
        for row in all_qs:
            q = dict(row)
            questions_by_id[q['id']] = q
            fig = q['figura'] or 'no_image'
            if q['risposta']: grouped[(q['categoria'], fig)]['V'].append(q)
            else: grouped[(q['categoria'], fig)]['F'].append(q)
            
        trick_ids = set()
        def jaccard(s1, s2):
            set1, set2 = set(str(s1).lower().split()), set(str(s2).lower().split())
            u = len(set1.union(set2))
            return len(set1.intersection(set2)) / u if u else 0
            
        for (cat, fig), vf in grouped.items():
            for v in vf['V']:
                for f in vf['F']:
                    if jaccard(v['domanda'], f['domanda']) > 0.35:
                        trick_ids.add(v['id'])
                        trick_ids.add(f['id'])
                        
        trick_by_cat = defaultdict(list)
        for q_id in trick_ids:
            q = questions_by_id[q_id]
            trick_by_cat[q['categoria']].append(q)
            
        all_by_cat = defaultdict(list)
        for q in all_qs:
            all_by_cat[q['categoria']].append(q)
            
        all_cats = list(all_by_cat.keys())
        important_keywords = ['pericolo', 'divieto', 'obbligo', 'precedenza', 'orizzontale', 'semafor', 'velocit', 'distanza', 'incroc', 'norme', 'sorpasso', 'ingombro', 'sicurezza', 'incident', 'psico']
        important_cats = [c for c in all_cats if any(kw in str(c).lower() for kw in important_keywords)]
        less_cats = [c for c in all_cats if c not in important_cats]
        
        random.shuffle(important_cats)
        cats_getting_two = important_cats[:5]
        cats_getting_one = important_cats[5:]
        
        exam_questions = []
        def fetch_trick_q(cat, limit):
            pool = trick_by_cat.get(cat, [])
            valid_pool = [q for q in pool if q.get('jaccard_status', 'unseen') == 'unseen' or q.get('jaccard_ever_wrong') == 1 or q.get('jaccard_ever_guessed') == 1]
            
            if len(valid_pool) >= limit:
                return random.sample(valid_pool, limit)
            else:
                needed = limit - len(valid_pool)
                fallback_pool = [q for q in all_by_cat[cat] if q['id'] not in [p['id'] for p in valid_pool] and (q.get('jaccard_status', 'unseen') == 'unseen' or q.get('jaccard_ever_wrong') == 1 or q.get('jaccard_ever_guessed') == 1)]
                return valid_pool + random.sample(fallback_pool, min(needed, len(fallback_pool)))
                
        for cat in cats_getting_two: exam_questions.extend(fetch_trick_q(cat, 2))
        for cat in cats_getting_one: exam_questions.extend(fetch_trick_q(cat, 1))
        for cat in less_cats: exam_questions.extend(fetch_trick_q(cat, 1))
        
        random.shuffle(exam_questions)
        formatted_exam = [{"id": q["id"], "domanda": q["domanda"], "figura": q["figura"], "risposta": q["risposta"]} for q in exam_questions]
        return {"questions": formatted_exam}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import List
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
    answers: List[ExamAnswer]

# NEW: Model for Smart Context Translation
class TranslateReq(BaseModel):
    word: str
    phrase: str
    sentence: str

# --- Database Initialization with Safety Nets ---
def init_db():
    if not os.path.exists('patente_quiz.db'):
        return
    conn = sqlite3.connect('patente_quiz.db', timeout=10)
    
    def safe_add_column(col_name, col_type):
        try:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {col_name} {col_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass 
            
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
        categories = conn.execute('SELECT categoria, COUNT(*) as count FROM questions WHERE categoria IS NOT NULL GROUP BY categoria ORDER BY count DESC').fetchall()
        conn.close()
        return [{"name": str(row['categoria']), "count": row['count']} for row in categories]
    except Exception as e: return {"error": str(e)}

@app.get("/api/subcategories")
def get_subcategories(category: str):
    try:
        conn = get_db_connection()
        subcats = conn.execute('SELECT sottocategoria, COUNT(*) as count FROM questions WHERE categoria = ? AND sottocategoria IS NOT NULL GROUP BY sottocategoria ORDER BY count DESC', (category,)).fetchall()
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

# NEW: Smart Context Translation Endpoint
@app.post("/api/translate_smart")
def translate_smart(req: TranslateReq):
    try:
        translator = GoogleTranslator(source='it', target='en')
        
        # Strip common punctuation for cleaner word/phrase translation
        clean_w = re.sub(r'[^\w\s\']', '', req.word).strip()
        clean_p = re.sub(r'[^\w\s\']', '', req.phrase).strip()
        
        t_word = translator.translate(clean_w).lower() if clean_w else ""
        t_phrase = translator.translate(clean_p).lower() if clean_p else ""
        t_sentence = translator.translate(req.sentence)
        
        return {"word": t_word, "phrase": t_phrase, "sentence": t_sentence}
    except Exception as e: 
        return {"error": str(e)}

# --- Unified Stats API ---
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
        all_cats = [row['categoria'] for row in conn.execute('SELECT DISTINCT categoria FROM questions WHERE categoria IS NOT NULL').fetchall()]
        
        important_keywords = ['pericolo', 'divieto', 'obbligo', 'precedenza', 'orizzontale', 'semafor', 'velocit', 'distanza', 'incroc', 'norme', 'sorpasso', 'ingombro', 'sicurezza', 'incident', 'psico']
        
        important_cats = [c for c in all_cats if any(kw in str(c).lower() for kw in important_keywords)]
        less_cats = [c for c in all_cats if c not in important_cats]
        
        random.shuffle(important_cats)
        cats_getting_two = important_cats[:5]
        cats_getting_one = important_cats[5:]
        
        exam_questions = []
        
        def fetch_questions(cat, limit):
            try:
                query = '''SELECT id, domanda, figura, risposta FROM questions 
                           WHERE categoria = ? AND (status = 'unseen' OR ever_wrong = 1 OR ever_guessed = 1)
                           ORDER BY RANDOM() LIMIT ?'''
                return [dict(row) for row in conn.execute(query, (cat, limit)).fetchall()]
            except Exception:
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
            except Exception:
                pass 
                
            conn.execute('UPDATE questions SET status = ? WHERE id = ?', (new_status, ans.id))
            
        conn.commit()
        conn.close()
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
