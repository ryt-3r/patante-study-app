from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from collections import defaultdict
from deep_translator import GoogleTranslator
import sqlite3
import json
import random
import re
import os

app = FastAPI()

# Mount the static folder so the browser can read the HTML, JSON, and CSS
app.mount("/static", StaticFiles(directory="static"), name="static")

# Mount the img_sign folder so FastAPI allows images to load everywhere
app.mount("/img_sign", StaticFiles(directory="img_sign"), name="img_sign")

# Setup the templates folder (pointing to static, since that's where your HTML is)
templates = Jinja2Templates(directory="static")

DB_PATH = 'patente_quiz.db'
STATE_FILE = "flashcard_progress.json"
REVIEW_QUEUE_FILE = "flashcard_review_queue.json"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# ==========================================
# PYDANTIC DATA MODELS
# ==========================================
class FlagUpdate(BaseModel):
    id: int
    flagged: int

class TranslateReq(BaseModel):
    word: str
    phrase: str
    sentence: str

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
    is_guessed: bool = False

class ExamSubmit(BaseModel):
    answers: List[ExamAnswer]

class FlashcardState(BaseModel):
    decks: List[Dict[str, Any]]
    currentIndex: int


# ==========================================
# 1. PAGE ROUTES
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/domande", response_class=HTMLResponse)
async def domande(request: Request):
    return templates.TemplateResponse(request=request, name="domande.html")

@app.get("/libreria", response_class=HTMLResponse)
async def libreria(request: Request):
    return templates.TemplateResponse(request=request, name="libreria.html")

@app.get("/all_quiz", response_class=HTMLResponse)
async def all_quiz(request: Request):
    return templates.TemplateResponse(request=request, name="quiz.html")

@app.get("/official_quiz", response_class=HTMLResponse)
async def official_quiz(request: Request):
    return templates.TemplateResponse(request=request, name="official.html")

@app.get("/jaccard_quiz", response_class=HTMLResponse)
async def jaccard_quiz(request: Request):
    return templates.TemplateResponse(request=request, name="jaccard.html")

@app.get("/analisi", response_class=HTMLResponse)
def get_analisi_page():
    with open("static/analisi.html", "r", encoding="utf-8") as f:
        return f.read()

# ==========================================
# 2. API ENDPOINTS 
# ==========================================

# --- Flashcard Deck State Persistence APIs ---
@app.get('/api/flashcard/state')
def get_flashcard_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"decks": [], "currentIndex": 0}

@app.post('/api/flashcard/state')
def save_flashcard_state(state: FlashcardState):
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state.dict(), f, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Review Queue Persistence APIs ---
@app.get('/api/flashcard/review_queue')
def get_review_queue():
    if os.path.exists(REVIEW_QUEUE_FILE):
        try:
            with open(REVIEW_QUEUE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"custom_decks": [], "current_queue": []}

@app.post('/api/flashcard/review_queue')
def save_review_queue(state: Dict[str, Any]):
    try:
        with open(REVIEW_QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Study App APIs ---
@app.get("/api/categories")
def get_categories():
    try:
        conn = get_db_connection()
        categories = conn.execute('SELECT categoria, COUNT(*) as count FROM questions WHERE categoria IS NOT NULL GROUP BY categoria').fetchall()
        conn.close()
        
        # Official learning sequence order mapping
        official_chapter_order = [
            'definizioni-generali-doveri-strada',
            'segnali-pericolo',
            'segnali-divieto',
            'segnali-obbligo',
            'precedenza-incroci',
            'norme-di-circolazione',
            'limiti-di-velocita',
            'distanza-di-sicurezza',
            'sorpasso',
            'arresto-fermata-sosta',
            'segnaletica-orizzontale-ostacoli',
            'semafori-vigili',
            'segnali-precedenza',
            'pannelli-integrativi',
            'segnali-indicazione',
            'elementi-veicolo-manutenzione-comportamenti',
            'consumi-ambiente-inquinamento',
            'cinture-casco-sicurezza',
            'incidenti-stradali-comportamenti',
            'alcool-droga-primo-soccorso',
            'patente-punti-documenti',
            'responsabilita-civile-penale-assicurazione',
            'norme-varie-autostrade-pannelli',
            'luci-dispositivi-acustici',
            'trasporto-merci-traino-rimorchi'
        ]
        
        def get_order_index(cat_name):
            slug = str(cat_name).lower().strip()
            if slug in official_chapter_order:
                return official_chapter_order.index(slug)
            return 999

        result = []
        for row in categories:
            cat_name = str(row['categoria'])
            result.append({
                "name": cat_name, 
                "count": row['count'],
                "is_important": True
            })
            
        # Sort strictly by official textbook chapter flow order
        result.sort(key=lambda x: get_order_index(x['name']))
        return result
    except Exception as e: return {"error": str(e)}

@app.get("/api/subcategories")
def get_subcategories(category: str):
    try:
        conn = get_db_connection()
        subcats = conn.execute('SELECT sottocategoria, COUNT(*) as count FROM questions WHERE categoria = ? AND sottocategoria IS NOT NULL GROUP BY sottocategoria', (category,)).fetchall()
        conn.close()
        
        # Return subcategories in natural database occurrence order (no alphabetical or count sorting)
        return [{"name": str(row['sottocategoria']), "count": row['count']} for row in subcats]
    except Exception as e: return {"error": str(e)}

@app.get("/api/figures")
def get_figures(category: str, subcategory: str):
    try:
        conn = get_db_connection()
        figures = conn.execute('SELECT figura, COUNT(*) as count FROM questions WHERE categoria = ? AND sottocategoria = ? AND figura IS NOT NULL GROUP BY figura', (category, subcategory)).fetchall()
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
        raise HTTPException(status_code=500, detail=str(e))
        
@app.get("/api/analysis/duplicates")
def analyze_duplicates():
    import sqlite3
    conn = sqlite3.connect('patente_quiz.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    c.execute("SELECT id, domanda, risposta, figura, categoria, sottocategoria FROM questions")
    rows = c.fetchall()
    conn.close()
    
    analysis = {}
    
    for r in rows:
        norm_text = " ".join(r['domanda'].lower().split())
        
        if norm_text not in analysis:
            analysis[norm_text] = {
                "original": r['domanda'],
                "count": 0,
                "V": [],
                "F": []
            }
        
        analysis[norm_text]["count"] += 1
        
        fig_text = f" (Fig. {r['figura']})" if r['figura'] and r['figura'] != 'no_image' else ""
        location = f"{r['categoria']} > {r['sottocategoria']}{fig_text}"
        
        if r['risposta'] == 1 or r['risposta'] == 'V':
            if location not in analysis[norm_text]["V"]:
                analysis[norm_text]["V"].append(location)
        else:
            if location not in analysis[norm_text]["F"]:
                analysis[norm_text]["F"].append(location)
                
    unique = []
    repeated = []
    
    for k, v in analysis.items():
        if v["count"] == 1:
            ans = 'V' if len(v['V']) > 0 else 'F'
            loc = v['V'][0] if ans == 'V' else v['F'][0]
            unique.append({"domanda": v["original"], "risposta": ans, "location": loc})
        else:
            repeated.append(v)
            
    repeated.sort(key=lambda x: x["count"], reverse=True)
    
    return {"unique": unique, "repeated": repeated, "total_processed": len(rows)}
