from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import json
import pyodbc
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, Response
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
import io
import requests
import json
import base64
from secret.key import URL

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Necesar pentru flash messages

# Configurare Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

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

def send_email_via_google_script(recipient, subject, body=None, pdf_path=None):
    # Configurare
    script_url = URL  # URL DE LA GOOGLE
    
    # Pregătește datele
    payload = {
        "recipient": recipient,
        "subject": subject,
        "body": body or " ",
    }
    
    # Adaugă PDF dacă există
    if pdf_path:
        with open(pdf_path, "rb") as f:
            pdf_data = base64.b64encode(f.read()).decode("utf-8")
        payload.update({
            "pdfData": pdf_data,
            "pdfName": pdf_path.split("/")[-1]
        })
    
    # Trimite request
    headers = {"Content-Type": "application/json"}
    response = requests.post(
        script_url,
        data=json.dumps(payload),
        headers=headers
    )
    
    # Procesează răspuns
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Error {response.status_code}: {response.text}")

# Creare tabel utilizatori în baza de date
def init_users_table():
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                IF NOT EXISTS (SELECT * FROM sysobjects WHERE name='users' AND xtype='U')
                CREATE TABLE users (
                    id INT IDENTITY(1,1) PRIMARY KEY,
                    username NVARCHAR(100) NOT NULL UNIQUE,
                    email NVARCHAR(100) NOT NULL UNIQUE,
                    password NVARCHAR(200) NOT NULL,
                    role NVARCHAR(20) NOT NULL DEFAULT 'user',
                    created_at DATETIME DEFAULT GETDATE()
                )
            """)
            conn.commit()
            
            # Verifică dacă există admin și creează-l dacă nu există
            cursor.execute("SELECT COUNT(*) FROM users WHERE username = 'admin'")
            if cursor.fetchone()[0] == 0:
                hashed_password = generate_password_hash('admin123')
                cursor.execute(
                    "INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
                    ('admin', 'admin@example.com', hashed_password, 'admin')
                )
                conn.commit()
    except Exception as e:
        print(f"Eroare la inițializarea tabelului users: {e}")

# Apelăm funcția la start
init_users_table()

class User(UserMixin):
    def __init__(self, user_id, username, email, role):
        self.id = user_id
        self.username = username
        self.email = email
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, email, role FROM users WHERE id = ?", (user_id,))
            user_data = cursor.fetchone()
            if user_data:
                return User(user_data[0], user_data[1], user_data[2], user_data[3])
            return None
    except:
        return None

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

def get_form_data(form_name, user_id=None):
    """Preia toate datele dintr-un formular filtrate după user"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            if user_id and current_user.role != 'admin':
                cursor.execute(f"SELECT * FROM [{form_name}] WHERE UserID = ?", (user_id,))
            else:
                cursor.execute(f"SELECT * FROM [{form_name}]")
            columns = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
            return columns, rows
    except Exception as e:
        return None, str(e)

def get_single_record(form_name, record_id):
    """Preia o singură înregistrare din formular"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM [{form_name}] WHERE ID = ?", (record_id,))
            columns = [column[0] for column in cursor.description]
            row = cursor.fetchone()
            if row:
                return dict(zip(columns, row))
            return None
    except Exception as e:
        return None

# Modific ruta index() pentru a filtra formularele
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            forms = [f.replace('.json', '') for f in os.listdir('forms') if f.endswith('.json')]
        else:
            forms = get_user_forms(current_user.id)
    else:
        forms = []
    return render_template('index.html', forms=forms)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id, username, email, password, role FROM users WHERE username = ? OR email = ?", (username, username))
                user_data = cursor.fetchone()
                
                if user_data and check_password_hash(user_data[3], password):
                    user = User(user_data[0], user_data[1], user_data[2], user_data[4])
                    login_user(user)
                    flash('Autentificare reușită!', 'success')
                    return redirect(url_for('index'))
                else:
                    flash('Nume de utilizator sau parolă incorectă', 'error')
        except Exception as e:
            flash(f'Eroare la autentificare: {e}', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Ați fost deconectat cu succes.', 'success')
    return redirect(url_for('index'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Parolele nu coincid!', 'error')
            return render_template('register.html')
        
        try:
            hashed_password = generate_password_hash(password)
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                    (username, email, hashed_password)
                )
                conn.commit()
                flash('Cont creat cu succes! Vă puteți autentifica.', 'success')
                return redirect(url_for('login'))
        except Exception as e:
            flash(f'Eroare la crearea contului: {e}', 'error')
    
    return render_template('register.html')

@app.route('/create_form', methods=['GET', 'POST'])
@login_required
def create_form():
    if current_user.role != 'admin':
        flash('Nu aveți permisiunea de a accesa această pagină', 'error')
        return redirect(url_for('index'))
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
                    CreatedAt DATETIME DEFAULT GETDATE(),
                    UserID INT NOT NULL DEFAULT {current_user.id}
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

# Adăugăm o funcție pentru a obține formularele utilizatorului curent
def get_user_forms(user_id=None):
    forms = []
    try:
        for f in os.listdir('forms'):
            if f.endswith('.json'):
                form_name = f.replace('.json', '')
                # Verificăm dacă tabelul există și are câmpul UserID
                if table_exists(form_name):
                    forms.append(form_name)
    except Exception as e:
        print(f"Eroare la obținerea formularelor: {e}")
    return forms

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

@app.route('/fill_form_with_data/<form_name>/<int:record_id>')
def fill_form_with_data(form_name, record_id):
    """Pre-completează formularul cu date existente"""
    file_path = f'forms/{form_name}.json'
    if not os.path.exists(file_path):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    # Încarcă structura formularului
    with open(file_path, encoding='utf-8') as f:
        form_data = json.load(f)
    
    # Preia datele înregistrării
    record_data = get_single_record(form_name, record_id)
    if not record_data:
        flash(f'Înregistrarea cu ID {record_id} nu există!', 'error')
        return redirect(url_for('view_data', form_name=form_name))
    
    return render_template('fill_form.html', form_data=form_data, record_data=record_data)

@app.route('/edit_record/<form_name>/<int:record_id>')
def edit_record(form_name, record_id):
    """Editează o înregistrare existentă"""
    file_path = f'forms/{form_name}.json'
    if not os.path.exists(file_path):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    # Încarcă structura formularului
    with open(file_path, encoding='utf-8') as f:
        form_data = json.load(f)
    
    # Preia datele înregistrării
    record_data = get_single_record(form_name, record_id)
    if not record_data:
        flash(f'Înregistrarea cu ID {record_id} nu există!', 'error')
        return redirect(url_for('view_data', form_name=form_name))
    
    return render_template('edit_form.html', form_data=form_data, record_data=record_data, record_id=record_id)

@app.route('/update_record/<form_name>/<int:record_id>', methods=['POST'])
def update_record(form_name, record_id):
    """Actualizează o înregistrare în baza de date"""
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
    set_clauses = []
    
    # Validare și pregătire date pentru update
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
            record_data = get_single_record(form_name, record_id)
            return render_template('edit_form.html', form_data=data, record_data=record_data, record_id=record_id)
        
        # Validare tip de date
        if value and field_type == 'email' and '@' not in value:
            flash(f'Câmpul "{field_name}" trebuie să conțină o adresă email validă!', 'error')
            record_data = get_single_record(form_name, record_id)
            return render_template('edit_form.html', form_data=data, record_data=record_data, record_id=record_id)
        
        if value and field_type == 'number':
            try:
                value = int(value)
            except ValueError:
                flash(f'Câmpul "{field_name}" trebuie să conțină un număr valid!', 'error')
                record_data = get_single_record(form_name, record_id)
                return render_template('edit_form.html', form_data=data, record_data=record_data, record_id=record_id)
        
        set_clauses.append(f"[{field_name}] = ?")
        values.append(value)
    
    # Adaugă ID-ul pentru clauza WHERE
    values.append(record_id)
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            set_clause = ', '.join(set_clauses)
            sql = f"UPDATE [{form_name}] SET {set_clause} WHERE ID = ?"
            cursor.execute(sql, values)
            conn.commit()
            
        flash('Înregistrarea a fost actualizată cu succes!', 'success')
        return redirect(url_for('view_data', form_name=form_name))
        
    except Exception as e:
        flash(f'Eroare la actualizarea datelor: {e}', 'error')
        record_data = get_single_record(form_name, record_id)
        return render_template('edit_form.html', form_data=data, record_data=record_data, record_id=record_id)

@app.route('/delete_record/<form_name>/<int:record_id>')
def delete_record(form_name, record_id):
    if current_user.role != 'admin':
        flash('Nu aveți permisiunea de a șterge formulare', 'error')
        return redirect(url_for('index'))
    """Șterge o înregistrare din baza de date"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM [{form_name}] WHERE ID = ?", (record_id,))
            conn.commit()
            
        flash('Înregistrarea a fost ștearsă cu succes!', 'success')
    except Exception as e:
        flash(f'Eroare la ștergerea înregistrării: {e}', 'error')
    
    return redirect(url_for('view_data', form_name=form_name))

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
            
            # Adăugăm UserID la interogare
            sql = f"INSERT INTO [{form_name}] ({columns}, UserID) VALUES ({placeholders}, ?)"
            values.append(current_user.id)  # Adăugăm ID-ul userului curent
            cursor.execute(sql, values)
            conn.commit()
            
        flash('Formularul a fost trimis cu succes!', 'success')
        return redirect(url_for('index'))
        
    except Exception as e:
        flash(f'Eroare la salvarea datelor: {e}', 'error')
        return render_template('fill_form.html', form_data=data)

@app.route('/view_data/<form_name>')
def view_data(form_name):
    if not current_user.is_authenticated:
        flash('Nu aveți permisiunea de a vedea formulare nelogat.', 'error')
        return redirect(url_for('index'))
    if not os.path.exists(f'forms/{form_name}.json'):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    columns, rows = get_form_data(form_name, current_user.id if current_user.role != 'admin' else None)
    if columns is None:
        flash(f'Eroare la citirea datelor: {rows}', 'error')
        return redirect(url_for('index'))
    
    return render_template('view_data.html', form_name=form_name, columns=columns, rows=rows)

@app.route('/download_pdf/<form_name>')
@login_required
def download_pdf(form_name):
    if current_user.role != 'admin':
        flash('Doar administratorii pot descărca toate datele ca PDF', 'error')
        return redirect(url_for('view_data', form_name=form_name))
    """Generează și descarcă PDF-ul unui formular"""
    if not os.path.exists(f'forms/{form_name}.json'):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))
    
    columns, rows = get_form_data(form_name)
    if columns is None:
        flash(f'Eroare la citirea datelor: {rows}', 'error')
        return redirect(url_for('index'))
    
    # Genereaza PDF în memorie
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # Titlu
    p.setFont("Helvetica-Bold", 16)
    p.drawString(50, height - 50, f"Date formular: {form_name}")
    
    # Data generării
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 70, f"Generat la: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Header tabel
    y = height - 100
    p.setFont("Helvetica-Bold", 10)
    x = 50
    for col in columns:
        p.drawString(x, y, col)
        x += 100
    
    # Linie separator
    p.line(50, y - 5, width - 50, y - 5)
    
    # Date
    p.setFont("Helvetica", 9)
    y -= 20
    for row in rows:
        if y < 50:  # Pagina noua
            p.showPage()
            y = height - 50
        
        x = 50
        for item in row:
            p.drawString(x, y, str(item)[:15] if item is not None else '')
            x += 100
        y -= 15
    
    p.save()
    buffer.seek(0)
    
    # Returnează PDF-ul pentru download
    return Response(
        buffer.read(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename={form_name}_export.pdf'
        }
    )

@app.route('/send_pdf_email/<form_name>', methods=['POST'])
@login_required
def send_pdf_email(form_name):
    """Rută nouă care trimite doar pe email"""
    try:
        # 1. Generează PDF-ul (folosește aceeași logică ca la download)
        if not os.path.exists(f'forms/{form_name}.json'):
            flash(f'Formularul "{form_name}" nu există!', 'error')
            return redirect(url_for('index'))

        columns, rows = get_form_data(form_name)
        if columns is None:
            flash(f'Eroare la citirea datelor: {rows}', 'error')
            return redirect(url_for('index'))
        
        # Genereaza PDF în memorie
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter
            
        # Titlu
        p.setFont("Helvetica-Bold", 16)
        p.drawString(50, height - 50, f"Date formular: {form_name}")
            
        # Data generării
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 70, f"Generat la: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
            
        # Header tabel
        y = height - 100
        p.setFont("Helvetica-Bold", 10)
        x = 50
        for col in columns:
            p.drawString(x, y, col)
            x += 100
            
        # Linie separator
        p.line(50, y - 5, width - 50, y - 5)
            
        # Date
        p.setFont("Helvetica", 9)
        y -= 20
        for row in rows:
            if y < 50:  # Pagina noua
                p.showPage()
                y = height - 50
            
            x = 50
            for item in row:
                p.drawString(x, y, str(item)[:15] if item is not None else '')
                x += 100
            y -= 15
            
        p.save()
        buffer.seek(0)
        
        # 2. Salvează temporar pe server
        temp_path = f"temp_email_{form_name}_{current_user.id}.pdf"
        with open(temp_path, 'wb') as f:
            f.write(buffer.getvalue())
        
        # 3. Folosește funcția ta existentă pentru trimitere email
        result = send_email_via_google_script(
            recipient=current_user.email,
            subject=f"Export {form_name}",
            body=f"""
            <p>Bună ziua,</p>
            <p>Atașat găsiți exportul formularului <b>{form_name}</b>.</p>
            <p>Data generării: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
            <p>Vă mulțumim!</p>
            """,
            pdf_path=temp_path
        )
        
        # 4. Șterge fișierul temporar
        os.remove(temp_path)
        
        flash('PDF trimis cu succes pe email!', 'success')
        
    except Exception as e:
        flash(f'Eroare la trimitere email: {str(e)}', 'error')
    
    return redirect(url_for('view_data', form_name=form_name))

@app.route('/download_record_pdf/<form_name>/<int:record_id>')
@login_required
def download_record_pdf(form_name, record_id):
    # Verifică existența formularului
    file_path = f'forms/{form_name}.json'
    if not os.path.exists(file_path):
        flash(f'Formularul "{form_name}" nu există!', 'error')
        return redirect(url_for('index'))

    # Verifică permisiunile
    if current_user.role != 'admin':
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT UserID FROM [{form_name}] WHERE ID = ?", 
                    (record_id,)
                )
                result = cursor.fetchone()
                
                if not result:
                    flash('Înregistrarea nu există!', 'error')
                    return redirect(url_for('view_data', form_name=form_name))
                
                if result[0] != current_user.id:
                    flash('Nu aveți permisiunea de a exporta această înregistrare', 'error')
                    return redirect(url_for('view_data', form_name=form_name))
        except Exception as e:
            flash(f'Eroare la verificarea permisiunilor: {e}', 'error')
            return redirect(url_for('index'))

    # Încarcă structura formularului
    try:
        with open(file_path, encoding='utf-8') as f:
            form_data = json.load(f)
    except Exception as e:
        flash(f'Eroare la citirea formularului: {e}', 'error')
        return redirect(url_for('index'))

    # Preia datele înregistrării
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM [{form_name}] WHERE ID = ?", (record_id,))
            columns = [column[0] for column in cursor.description]
            record_data = cursor.fetchone()
            
            if not record_data:
                flash('Înregistrarea nu a fost găsită!', 'error')
                return redirect(url_for('view_data', form_name=form_name))
    except Exception as e:
        flash(f'Eroare la preluarea datelor: {e}', 'error')
        return redirect(url_for('view_data', form_name=form_name))

    # Generează PDF-ul
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Header PDF
    p.setFont("Helvetica-Bold", 18)
    p.drawString(50, height - 50, f"Formular: {form_name}")
    p.setFont("Helvetica", 10)
    p.drawString(50, height - 70, f"Generat la: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    p.drawString(50, height - 85, f"ID Înregistrare: {record_id}")
    
    # Dacă e admin, afișează și userul
    if current_user.role == 'admin':
        p.drawString(50, height - 100, f"User ID: {record_data[columns.index('UserID')]}")
        y_position = height - 130
    else:
        y_position = height - 115

    p.line(50, y_position + 15, width - 50, y_position + 15)

    # Conținut PDF
    p.setFont("Helvetica", 12)
    
    for field_info in form_data['fields']:
        field_name = field_info['name'] if isinstance(field_info, dict) else field_info
        
        # Nume câmp
        p.setFont("Helvetica-Bold", 12)
        p.drawString(50, y_position, f"{field_name}:")
        
        # Valoare câmp
        p.setFont("Helvetica", 12)
        try:
            value = str(record_data[columns.index(field_name)])
        except (ValueError, IndexError):
            value = ""
        p.drawString(200, y_position, value)
        
        y_position -= 25
        if y_position < 50:  # Pagină nouă dacă necesar
            p.showPage()
            y_position = height - 50

    p.save()
    buffer.seek(0)

    # Răspuns download
    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename={form_name}_record_{record_id}.pdf'
        }
    )

@app.route('/export_pdf/<form_name>')
@login_required
def export_pdf(form_name):
    """
    Exportă datele formularului ca PDF cu suport pentru diacritice
    """
    try:
        # ============================================
        # 1. VERIFICĂRI PERMISIUNI ȘI EXISTENȚĂ DATE
        # ============================================
        if current_user.role != 'admin':
            flash('Doar administratorii pot exporta date complete', 'error')
            return redirect(url_for('view_data', form_name=form_name))

        if not os.path.exists(f'forms/{form_name}.json'):
            flash(f'Formularul "{form_name}" nu există!', 'error')
            return redirect(url_for('index'))

        # ============================================
        # 2. CONFIGURARE FONTURI CU DIACRITICE
        # ============================================
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
        from reportlab.lib import colors
        
        # Încărcare fonturi (folosim Helvetica ca fallback)
        try:
            pdfmetrics.registerFont(TTFont('ArialUnicode', 'arial.ttf'))
            bold_font = 'ArialUnicode'
            regular_font = 'ArialUnicode'
        except:
            bold_font = 'Helvetica-Bold'
            regular_font = 'Helvetica'
            flash('Fontul cu diacritice nu a fost găsit, folosim Helvetica', 'warning')

        # ============================================
        # 3. PREGĂTIRE DIRECTOR EXPORT
        # ============================================
        export_dir = os.path.join(app.root_path, 'exports')
        os.makedirs(export_dir, exist_ok=True)

        # ============================================
        # 4. OBȚINERE DATE
        # ============================================
        columns, rows = get_form_data(form_name)
        if not rows:
            flash('Nu există date de exportat', 'warning')
            return redirect(url_for('view_data', form_name=form_name))

        # ============================================
        # 5. GENERARE PDF PROFESIONALĂ
        # ============================================
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pdf_path = os.path.join(export_dir, f'{form_name}_export_{timestamp}.pdf')
        
        # Creare document
        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        elements = []
        
        # Stiluri
        styles = getSampleStyleSheet()
        style_normal = styles['Normal']
        style_normal.fontName = regular_font
        style_normal.leading = 12
        
        # Header
        from reportlab.platypus import Paragraph
        title = Paragraph(f"<b>Export date: {form_name}</b>", styles['Title'])
        elements.append(title)
        
        subtitle = Paragraph(f"Generat la: {datetime.now().strftime('%d/%m/%Y %H:%M')}<br/>"
                           f"Total înregistrări: {len(rows)}", styles['Normal'])
        elements.append(subtitle)
        
        # Pregătire date tabel
        table_data = [columns]  # Header
        for row in rows:
            table_data.append([str(cell)[:50] if cell else '' for cell in row])  # Limităm la 50 caractere
        
        # Creare tabel
        table = Table(table_data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#007BFF')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('ALIGN', (0,0), (-1,-1), 'LEFT'),
            ('FONTNAME', (0,0), (-1,0), bold_font),
            ('FONTNAME', (0,1), (-1,-1), regular_font),
            ('FONTSIZE', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,0), 12),
            ('BACKGROUND', (0,1), (-1,-1), colors.beige),
            ('GRID', (0,0), (-1,-1), 1, colors.black),
            ('WORDWRAP', (0,0), (-1,-1), 'ON')
        ]))
        
        elements.append(table)
        
        # Generare PDF
        doc.build(elements)
        
        flash('PDF generat cu succes!', 'success')
        app.logger.info(f'Export PDF reușit: {pdf_path}')
        
    except Exception as e:
        app.logger.error(f'Eroare export PDF: {str(e)}', exc_info=True)
        flash(f'Eroare la generarea PDF: {str(e)}', 'error')
    
    return redirect(url_for('view_data', form_name=form_name))

@app.route('/delete_form/<form_name>')
@login_required
def delete_form(form_name):
    if current_user.role != 'admin':
        flash('Nu aveți permisiunea de a șterge formulare', 'error')
        return redirect(url_for('index'))
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

@app.route('/send_record_email/<form_name>/<int:record_id>', methods=['POST'])
@login_required
def send_record_email(form_name, record_id):
    """Trimite un singur record pe email"""
    try:
        # Verifică existența formularului
        file_path = f'forms/{form_name}.json'
        if not os.path.exists(file_path):
            flash(f'Formularul "{form_name}" nu există!', 'error')
            return redirect(url_for('index'))

        # Încarcă structura formularului
        with open(file_path, encoding='utf-8') as f:
            form_data = json.load(f)

        # Preia datele înregistrării
        record_data = get_single_record(form_name, record_id)
        if not record_data:
            flash('Înregistrarea nu a fost găsită!', 'error')
            return redirect(url_for('view_data', form_name=form_name))

        # Verifică permisiunile
        if current_user.role != 'admin' and record_data.get('UserID') != current_user.id:
            flash('Nu aveți permisiunea de a trimite această înregistrare pe email', 'error')
            return redirect(url_for('view_data', form_name=form_name))

        # Generează PDF-ul
        buffer = io.BytesIO()
        p = canvas.Canvas(buffer, pagesize=letter)
        width, height = letter

        # Header PDF
        p.setFont("Helvetica-Bold", 18)
        p.drawString(50, height - 50, f"Formular: {form_name}")
        p.setFont("Helvetica", 10)
        p.drawString(50, height - 70, f"Generat la: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        p.drawString(50, height - 85, f"ID Înregistrare: {record_id}")
        
        # Dacă e admin, afișează și userul
        if current_user.role == 'admin':
            p.drawString(50, height - 100, f"User ID: {record_data.get('UserID', 'N/A')}")
            y_position = height - 130
        else:
            y_position = height - 115

        p.line(50, y_position + 15, width - 50, y_position + 15)

        # Conținut PDF
        p.setFont("Helvetica", 12)
        
        for field_info in form_data['fields']:
            field_name = field_info['name'] if isinstance(field_info, dict) else field_info
            
            # Nume câmp
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y_position, f"{field_name}:")
            
            # Valoare câmp
            p.setFont("Helvetica", 12)
            value = str(record_data.get(field_name, ''))
            p.drawString(200, y_position, value)
            
            y_position -= 25
            if y_position < 50:  # Pagină nouă dacă necesar
                p.showPage()
                y_position = height - 50

        p.save()
        buffer.seek(0)
        
        # Salvează temporar pe server
        temp_path = f"temp_email_{form_name}_record_{record_id}_{current_user.id}.pdf"
        with open(temp_path, 'wb') as f:
            f.write(buffer.getvalue())
        
        # Folosește funcția existentă pentru trimitere email
        result = send_email_via_google_script(
            recipient=current_user.email,
            subject=f"Înregistrare {record_id} din formularul {form_name}",
            body=f"""
            <p>Bună ziua,</p>
            <p>Atașat găsiți înregistrarea <b>{record_id}</b> din formularul <b>{form_name}</b>.</p>
            <p>Data generării: {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
            <p>Vă mulțumim!</p>
            """,
            pdf_path=temp_path
        )
        
        # Șterge fișierul temporar
        os.remove(temp_path)
        
        flash('Înregistrarea a fost trimisă cu succes pe email!', 'success')
        
    except Exception as e:
        flash(f'Eroare la trimitere email: {str(e)}', 'error')
    
    return redirect(url_for('view_data', form_name=form_name))


if __name__ == '__main__':
    app.run(debug=True)


    