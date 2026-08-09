from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import sqlite3
import os
import re
from deep_translator import GoogleTranslator

app = FastAPI()

app.mount("/img_sign", StaticFiles(directory="img_sign"), name="img_sign")
app.mount("/static", StaticFiles(directory="static"), name="static")

def init_db():
    if not os.path.exists('patente_quiz.db'):
        return
    conn = sqlite3.connect('patente_quiz.db')
    try:
        conn.execute('ALTER TABLE questions ADD COLUMN flagged INTEGER DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        pass
    finally:
        conn.close()

init_db()

class FlagUpdate(BaseModel):
    id: int
    flagged: int

def get_db_connection():
    conn = sqlite3.connect('patente_quiz.db')
    conn.row_factory = sqlite3.Row
    return conn

@app.get("/")
def read_root():
    return FileResponse("static/index.html", media_type="text/html")

@app.get("/api/categories")
def get_categories():
    try:
        conn = get_db_connection()
        categories = conn.execute('SELECT categoria, COUNT(*) as count FROM questions GROUP BY categoria ORDER BY count DESC').fetchall()
        conn.close()
        return [{"name": str(row['categoria']), "count": row['count']} for row in categories]
    except Exception as e:
        return {"error": f"Errore DB Categorie: {str(e)}"}

@app.get("/api/subcategories")
def get_subcategories(category: str):
    try:
        conn = get_db_connection()
        subcats = conn.execute('SELECT sottocategoria, COUNT(*) as count FROM questions WHERE categoria = ? GROUP BY sottocategoria ORDER BY count DESC', (category,)).fetchall()
        conn.close()
        return [{"name": str(row['sottocategoria']), "count": row['count']} for row in subcats]
    except Exception as e:
        return {"error": f"Errore DB Argomenti: {str(e)}"}

@app.get("/api/figures")
def get_figures(category: str, subcategory: str):
    try:
        conn = get_db_connection()
        figures = conn.execute('SELECT figura, COUNT(*) as count FROM questions WHERE categoria = ? AND sottocategoria = ? AND figura IS NOT NULL GROUP BY figura ORDER BY count DESC', (category, subcategory)).fetchall()
        conn.close()
        return [{"name": str(row['figura']), "count": row['count']} for row in figures]
    except Exception as e:
        return {"error": f"Errore DB Figure: {str(e)}"}

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
                
            q_data = {
                "id": row_dict['id'], 
                "domanda": str(row_dict['domanda']), 
                "flagged": row_dict.get('flagged', 0)
            }
            
            if row_dict['risposta']:
                grouped_content[fig]["vero"].append(q_data)
            else:
                grouped_content[fig]["falso"].append(q_data)
                
        return {"data": list(grouped_content.values()), "message": ""}
    except Exception as e:
        return {"error": f"Errore DB Contenuto: {str(e)}"}

@app.post("/api/toggle_flag")
def toggle_flag(update: FlagUpdate):
    conn = get_db_connection()
    conn.execute('UPDATE questions SET flagged = ? WHERE id = ?', (update.flagged, update.id))
    conn.commit()
    conn.close()
    return {"success": True}

# NEW: The Translation Endpoint
@app.get("/api/translate")
def translate_word(word: str):
    try:
        # Strip out common punctuation marks attached to words
        clean_word = re.sub(r'[^\w\s\']', '', word).strip()
        if not clean_word:
            return {"translation": ""}
            
        translator = GoogleTranslator(source='it', target='en')
        translated = translator.translate(clean_word)
        return {"translation": translated.lower()}
    except Exception as e:
        return {"error": str(e)}
