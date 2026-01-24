from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
import os
import pandas as pd
from werkzeug.utils import secure_filename
from stock_analyzer import StockAnalyzer
import tempfile
from dotenv import load_dotenv
from functools import wraps

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
# Usar clave secreta del .env
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key') 
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Credenciales
ADMIN_USER = os.getenv('FLASK_USER')
ADMIN_PASS = os.getenv('FLASK_PASSWORD')

ALLOWED_EXTENSIONS = {'pdf', 'xlsx', 'xls'}

# ALMACÉN DE ESTADO GLOBAL (Simulando persistencia simple en memoria)
# Estructura: {'username': StockAnalyzer_Instance}
USER_ANALYZERS = {}

def get_user_analyzer(username):
    if username not in USER_ANALYZERS:
        USER_ANALYZERS[username] = StockAnalyzer()
    return USER_ANALYZERS[username]

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logged_in'] = True
            session['user'] = username
            # Inicializar analyzer limpio al login
            USER_ANALYZERS[username] = StockAnalyzer()
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos.')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    username = session.get('user')
    if username and username in USER_ANALYZERS:
        del USER_ANALYZERS[username]
    session.pop('logged_in', None)
    session.pop('user', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    analyzer = get_user_analyzer(session['user'])
    
    # Datos para la vista
    inventory_loaded = analyzer.df_inventory_working is not None
    history = analyzer.history
    current_results = analyzer.last_results
    
    return render_template(
        'index.html',
        inventory_loaded=inventory_loaded,
        history=history,
        results=current_results, # Resultados actuales si los hay
        stats=analyzer.get_summary_stats() if current_results else None
    )

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    # Verificar archivos
    # Punch y Laser siempre requeridos (o al menos uno)
    if 'punch_file' not in request.files or 'laser_file' not in request.files:
        flash('Faltan archivos PDF.')
        return redirect(url_for('index'))

    punch_file = request.files['punch_file']
    laser_file = request.files['laser_file']
    inventory_file = request.files.get('inventory_file') # Opcional si ya está cargado

    analyzer = get_user_analyzer(session['user'])

    # Validar inventario
    inventory_needed = analyzer.df_inventory_working is None
    
    if inventory_needed and (not inventory_file or inventory_file.filename == ''):
        flash('El archivo de Inventario es requerido para el primer análisis.')
        return redirect(url_for('index'))

    temp_dir = tempfile.mkdtemp()
    
    try:
        # Guardar PDFs
        if punch_file.filename:
            punch_path = os.path.join(temp_dir, secure_filename(punch_file.filename))
            punch_file.save(punch_path)
            punch_data = analyzer.load_pdf_data(punch_path, "Punch")
        else:
            punch_data = None # Permitir correr sin uno? Asumamos que suben ambos o maneja error
            
        if laser_file.filename:
            laser_path = os.path.join(temp_dir, secure_filename(laser_file.filename))
            laser_file.save(laser_path)
            laser_data = analyzer.load_pdf_data(laser_path, "Laser")
        else:
            laser_data = None
            
        # Cargar inventario si viene nuevo
        inventory_data = None
        if inventory_file and inventory_file.filename:
            inventory_path = os.path.join(temp_dir, secure_filename(inventory_file.filename))
            inventory_file.save(inventory_path)
            inventory_data = analyzer.load_inventory_excel(inventory_path)
        
        if not punch_data and not laser_data:
             flash('Debe subir al menos un PDF válido.')
             return redirect(url_for('index'))
        
        # Capturar metadatos del formulario
        metadata = {
            'project': request.form.get('project', ''),
            'model': request.form.get('model', ''),
            'module': request.form.get('module', '')
        }
             
        analyzer.run_full_analysis(punch_data, laser_data, inventory_data, metadata)
        
        flash('Análisis completado exitosamente.')
        return redirect(url_for('index'))
        
    except Exception as e:
        flash(f'Error crítico: {str(e)}')
        return redirect(url_for('index'))

@app.route('/reset', methods=['POST'])
@login_required
def reset_stock():
    analyzer = get_user_analyzer(session['user'])
    analyzer.reset()
    flash('Stock y memoria reiniciados correctamente.')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
