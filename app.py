import os
import json
import pyodbc
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import io

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Necesar pentru flash messages

# Creeaza directoarele necesare
os.makedirs("forms", exist_ok=True)
os.makedirs("exports", exist_ok=True)

# Conexiune SQL Server
conn_str = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=DESKTOP-T4ENDDB\\SQLEXPRESS;"
    "DATABASE=FormulareBazaDate;"
    "Trusted_Connection=yes;"
    "Encrypt=no;"
)

def get_connection():
    return pyodbc.connect(conn_str)

def table_exists(table_name):
    """Verifică dacă tabelul există în baza de date"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.TABLES 
                WHERE TABLE_NAME = ?
            """, (table_name,))
            return cursor.fetchone()[0] > 0
    except:
        return False

def get_form_data(form_name):
    """Preia toate datele dintr-un formular"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM [{form_name}]")
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            return columns, rows
    except Exception as e:
        return None, str(e)

@app.route('/')
def index():
    forms = [f.replace('.json', '') for f in os.listdir('forms') if f.endswith('.json')]
    return render_template('index.html', forms=forms)

@app.route('/create_form', methods=['GET', 'POST'])
def create_form():
    if request.method == 'POST':
        form_name = request.form['form_name'].strip()
        fields = [f.strip() for f in request.form.getlist('field_name') if f.strip()]
        field_types = request.form.getlist('field_type')
        
        if not form_name or not fields:
            flash('Numele formularului și câmpurile sunt obligatorii!', 'error')
            return render_template('create_form.html')
        
        # Verifica daca formularul exista deja
        if os.path.exists(f'forms/{form_name}.json'):
            flash(f'Formularul "{form_name}" există deja!', 'error')
            return render_template('create_form.html')
        
        # Creeaza structura formularului
        form_structure = {
            "form_name": form_name,
            "fields": []
        }
        
        for i, field in enumerate(fields):
            field_type = field_types[i] if i < len(field_types) else 'text'
            form_structure["fields"].append({
                "name": field,
                "type": field_type,
                "required": request.form.get(f'required_{i}') == 'on'
            })
        
        # Salveaza JSON
        try:
            with open(f'forms/{form_name}.json', 'w', encoding='utf-8') as f:
                json.dump(form_structure, f, ensure_ascii=False, indent=2)
        except Exception as e:
            flash(f'Eroare la salvare fișier JSON: {e}', 'error')
            return render_template('create_form.html')
        
        # Creeaza tabel SQL
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                columns = []
                for field_info in form_structure["fields"]:
                    field_name = field_info["name"]
                    field_type = field_info["type"]
                    
                    if field_type == 'number':
                        sql_type = 'INT'
                    elif field_type == 'email':
                        sql_type = 'NVARCHAR(255)'
                    elif field_type == 'date':
                        sql_type = 'DATE'
                    else:
                        sql_type = 'NVARCHAR(MAX)'
                    
                    columns.append(f"[{field_name}] {sql_type}")
                
                columns_str = ", ".join(columns)
                cursor.execute(f"""
                    CREATE TABLE [{form_name}] (
                        ID INT IDENTITY(1,1) PRIMARY KEY,
                        {columns_str},
                        CreatedAt DATETIME DEFAULT GETDATE()
                    )
                """)
                conn.commit()
        except Exception as e:
            # Sterge fisierul JSON daca tabelul nu s-a creat
            if os.path.exists(f'forms/{form_name}.json'):
                os.remove(f'forms/{form_name}.json')
            flash(f'Eroare la creare tabel SQL Server: {e}', 'error')
            return render_template('create_form.html')
        
        flash(f'Formularul "{form_name}" a fost creat cu succes!', 'success')
        return redirect(url_for('index'))
    
    return render_template('create_form.html')

@app.route('/upload_form', methods=['POST'])
def upload_form():
    if 'form_file' not in request.files:
        flash('Nu a fost selectat niciun fișier!', 'error')
        return redirect(url_for('index'))
    
    file = request.files['form_file']
    if file.filename == '':
        flash('Nu a fost selectat niciun fișier!', 'error')
        return redirect(url_for('index'))
    
    try:
        data = json.load(file)
        form_name = data['form_name']
        
        # Verifica daca formularul exista deja
        if os.path.exists(f'forms/{form_name}.json'):
            flash(f'Formularul "{form_name}" există deja! Nu se poate face upload duplicat.', 'error')
            return redirect(url_for('index'))
        
        # Verifica daca tabelul exista deja in baza de date
        if table_exists(form_name):
            flash(f'Tabelul pentru formularul "{form_name}" există deja în baza de date!', 'error')
            return redirect(url_for('index'))
        
        # Creeaza tabelul in baza de date
        fields = data.get('fields', [])
        if isinstance(fields[0], dict):
            # Format nou cu tipuri de campuri
            columns = []
            for field_info in fields:
                field_name = field_info["name"]
                field_type = field_info.get("type", "text")
                
                if field_type == 'number':
                    sql_type = 'INT'
                elif field_type == 'email':
                    sql_type = 'NVARCHAR(255)'
                elif field_type == 'date':
                    sql_type = 'DATE'
                else:
                    sql_type = 'NVARCHAR(MAX)'
                
                columns.append(f"[{field_name}] {sql_type}")
        else:
            # Format vechi - doar nume de campuri
            columns = [f"[{f}] NVARCHAR(MAX)" for f in fields]
        
        with get_connection() as conn:
            cursor = conn.cursor()
            columns_str = ", ".join(columns)
            cursor.execute(f"""
                CREATE TABLE [{form_name}] (
                    ID INT IDENTITY(1,1) PRIMARY KEY,
                    {columns_str},
                    CreatedAt DATETIME DEFAULT GETDATE()
                )
            """)
            conn.commit()
        
        # Salveaza fisierul JSON
        with open(f'forms/{form_name}.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        flash(f'Formularul "{form_name}" a fost încărcat cu succes!', 'success')
        
    except json.JSONDecodeError:
        flash('Fișierul încărcat nu este un JSON valid!', 'error')
    except Exception as e:
        flash(f'Eroare la încărcarea formularului: {e}', 'error')
    
    return redirect(url_for('index'))

@app.route('/fill_form', methods=['GET', 'POST'])
def fill_form():
    if request.method == 'POST':
        form_name = request.form['form_name']
        file_path = f'forms/{form_name}.json'
        
        if not os.path.exists(file_path):
            flash(f'Formularul "{form_name}" nu există!', 'error')
            return redirect(url_for('fill_form'))
        
        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)
        
        return render_template('fill_form.html', form_data=data)
    
    forms = [f.replace('.json', '') for f in os.listdir('forms') if f.endswith('.json')]
    return render_template('select_form.html', forms=forms)

@app.route('/submit_form/<form_name>', methods=['POST'])
def submit_form(form_name):
    file_path = f'forms/{form_name}.json'
    if not os.path.exists(file_path):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    try:
        with open(file_path, encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        flash(f'Eroare la citirea formularului: {e}', 'error')
        return redirect(url_for('index'))
    
    fields = data['fields']
    values = []
    
    # Validare campuri
    for field_info in fields:
        if isinstance(field_info, dict):
            field_name = field_info['name']
            field_type = field_info.get('type', 'text')
            required = field_info.get('required', False)
        else:
            field_name = field_info
            field_type = 'text'
            required = False
        
        value = request.form.get(field_name, '').strip()
        
        if required and not value:
            flash(f'Câmpul "{field_name}" este obligatoriu!', 'error')
            return render_template('fill_form.html', form_data=data)
        
        # Validare tip de date
        if value and field_type == 'email' and '@' not in value:
            flash(f'Câmpul "{field_name}" trebuie să conțină o adresă email validă!', 'error')
            return render_template('fill_form.html', form_data=data)
        
        if value and field_type == 'number':
            try:
                value = int(value)
            except ValueError:
                flash(f'Câmpul "{field_name}" trebuie să conțină un număr valid!', 'error')
                return render_template('fill_form.html', form_data=data)
        
        values.append(value)
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            placeholders = ', '.join(['?'] * len(values))
            
            if isinstance(fields[0], dict):
                columns = ', '.join([f"[{f['name']}]" for f in fields])
            else:
                columns = ', '.join([f"[{f}]" for f in fields])
            
            sql = f"INSERT INTO [{form_name}] ({columns}) VALUES ({placeholders})"
            cursor.execute(sql, values)
            conn.commit()
            
        flash('Formularul a fost trimis cu succes!', 'success')
        return redirect(url_for('index'))
        
    except Exception as e:
        flash(f'Eroare la salvarea datelor: {e}', 'error')
        return render_template('fill_form.html', form_data=data)

@app.route('/view_data/<form_name>')
def view_data(form_name):
    if not os.path.exists(f'forms/{form_name}.json'):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    columns, rows = get_form_data(form_name)
    if columns is None:
        flash(f'Eroare la citirea datelor: {rows}', 'error')
        return redirect(url_for('index'))
    
    return render_template('view_data.html', form_name=form_name, columns=columns, rows=rows)

@app.route('/export_pdf/<form_name>')
def export_pdf(form_name):
    if not os.path.exists(f'forms/{form_name}.json'):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    columns, rows = get_form_data(form_name)
    if columns is None:
        flash(f'Eroare la citirea datelor: {rows}', 'error')
        return redirect(url_for('index'))
    
    # Genereaza PDF
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Titlu
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, f"Date formular: {form_name}")
    
    # Header tabel
    y = height - 100
    p.setFont("Helvetica-Bold", 10)
    x = 50
    for col in columns:
        p.drawString(x, y, col)
        x += 100
    
    # Date
    p.setFont("Helvetica", 9)
    y -= 20
    for row in rows:
        if y < 50:  # Pagina noua
            p.showPage()
            y = height - 50
        
        x = 50
        for item in row:
            p.drawString(x, y, str(item)[:15])  # Limiteaza lungimea textului
            x += 100
        y -= 15
    
    p.save()
    buffer.seek(0)
    
    # Salveaza PDF
    pdf_path = f'exports/{form_name}_export.pdf'
    with open(pdf_path, 'wb') as f:
        f.write(buffer.read())
    
    flash(f'PDF exportat cu succes în {pdf_path}', 'success')
    return redirect(url_for('view_data', form_name=form_name))

@app.route('/delete_form/<form_name>')
def delete_form(form_name):
    try:
        # Sterge fisierul JSON
        if os.path.exists(f'forms/{form_name}.json'):
            os.remove(f'forms/{form_name}.json')
        
        # Sterge tabelul din baza de date
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"DROP TABLE IF EXISTS [{form_name}]")
            conn.commit()
        
        flash(f'Formularul "{form_name}" a fost șters cu succes!', 'success')
    except Exception as e:
        flash(f'Eroare la ștergerea formularului: {e}', 'error')
    
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)