from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session
import os
import pandas as pd
from werkzeug.utils import secure_filename
from stock_analyzer import StockAnalyzer
import tempfile
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
# Usar clave secreta del .env
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'default_secret_key') 
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

@app.after_request
def add_header(response):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

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
        stats=analyzer.get_summary_stats() if current_results else None,
        inventory_summary=analyzer.get_inventory_summary() if current_results else None
    )

@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    # Verificar archivos
    # Punch y Laser siempre requeridos (o al menos uno)
    if 'punch_file' not in request.files and 'laser_file' not in request.files and 'stopa_file' not in request.files:
        flash('Faltan archivos para analizar.')
        return redirect(url_for('index'))

    punch_file = request.files.get('punch_file')
    laser_file = request.files.get('laser_file')
    stopa_file = request.files.get('stopa_file')
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
        punch_data = None
        if punch_file and punch_file.filename:
            punch_path = os.path.join(temp_dir, secure_filename(punch_file.filename))
            punch_file.save(punch_path)
            punch_data = analyzer.load_pdf_data(punch_path, "Punch")
            
        laser_data = None
        if laser_file and laser_file.filename:
            laser_path = os.path.join(temp_dir, secure_filename(laser_file.filename))
            laser_file.save(laser_path)
            laser_data = analyzer.load_pdf_data(laser_path, "Laser")
            
        # Cargar Stopa
        stopa_data = None
        if stopa_file and stopa_file.filename:
            stopa_path = os.path.join(temp_dir, secure_filename(stopa_file.filename))
            stopa_file.save(stopa_path)
            stopa_data = analyzer.load_stopa_excel(stopa_path)

        # Cargar inventario si viene nuevo
        inventory_data = None
        if inventory_file and inventory_file.filename:
            inventory_path = os.path.join(temp_dir, secure_filename(inventory_file.filename))
            inventory_file.save(inventory_path)
            inventory_data = analyzer.load_inventory_excel(inventory_path)
        
        # Validar: Si no hay data nueva Y no hay inventario en memoria -> Error
        if not inventory_data and analyzer.df_inventory_working is None:
            flash('El archivo de Inventario es requerido para el primer análisis o si no hay sesión activa.')
            return redirect(url_for('index'))

        if not punch_data and not laser_data and not stopa_data:
             flash('Debe subir al menos un archivo válido (PDF o Stopa Excel).')
             return redirect(url_for('index'))
        
        # Capturar metadatos del formulario
        metadata = {
            'project': request.form.get('project', ''),
            'model': request.form.get('model', ''),
            'module': request.form.get('module', '')
        }
        
        # Capturar reglas de análisis (Checkboxes)
        enabled_rules = {
            'rule_10034': 'rule_10034' in request.form,
            'rule_special_parts': 'rule_special_parts' in request.form,
            'rule_external_low': 'rule_external_low' in request.form
        }
             
        analyzer.run_full_analysis(punch_data, laser_data, inventory_data, stopa_data, metadata, enabled_rules)
        
        if not analyzer.last_results:
             flash('Análisis completado pero NO se generaron resultados. Verifique que los archivos tengan las columnas correctas (Stopa: "Item", Inventario: "stopaMaterialName").', 'warning')
        else:
             flash(f'Análisis completado. {len(analyzer.last_results)} items procesados.')
             
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

@app.route('/export/<export_type>')
@login_required
def export_results(export_type):
    analyzer = get_user_analyzer(session['user'])
    
    # Validar que haya datos
    if not analyzer.last_results:
        flash("No hay resultados para exportar.")
        return redirect(url_for('index'))

    import io
    output = io.BytesIO()
    
    # Configurar Pandas Writer
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        
        # Caso 1: Inventory Summary
        if export_type == 'inventory':
            data = analyzer.get_inventory_summary()
            if not data:
                flash("No hay resumen de inventario disponible.")
                return redirect(url_for('index'))

            # Convertir a DataFrame
            df = pd.DataFrame(data)
            # Renombrar columnas para el Excel
            df = df.rename(columns={
                'part_number': 'Part #',
                'materiel': 'Matériel',
                'material_type': 'Tipo Material',
                'epaisseur': 'Épaisseur',
                'length': 'Length',
                'width': 'Width',
                'total_required': 'Total a Producir',
                'initial_stock': 'Stock Total (Disp.)',
                'missing': 'Faltante (Deficit)'
            })
            # Asegurar orden de columnas
            cols = ['Part #', 'Matériel', 'Tipo Material', 'Épaisseur', 'Length', 'Width', 'Total a Producir', 'Stock Total (Disp.)', 'Faltante (Deficit)']
            df = df[cols]
            
            df.to_excel(writer, sheet_name='Resumen Inventario', index=False)
            filename = f"Inventario_Resumen_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
        # Caso 2: Punch o Laser (Resultados detallados)
        elif export_type in ['punch', 'laser']:
            # Filtrar resultados por origen (Case sensitive en origen: 'Punch', 'Laser')
            target_origin = export_type.capitalize()
            filtered_data = [r for r in analyzer.last_results if r['origen'] == target_origin]
            
            if not filtered_data:
                # Si está vacío, crear DF vacío pero con columnas
                df = pd.DataFrame(columns=['Origen', 'Part #', 'Qté Prod.', 'Stock Int.', 'Stock Ext.', 'Length', 'Width', 'Clasif.', 'Razón', 'Faltante Auto.', 'Posible Cambio', 'Kanban', 'Reservado', 'Disponible'])
            else:
                # Construir lista de dicts plana para DataFrame
                clean_rows = []
                for r in filtered_data:
                    clean_rows.append({
                        'Origen': r['origen'],
                        'Part #': r['part_number'],
                        'Qté Prod.': r['qte_a_produire'],
                        'Stock Int.': r['stopa_quantity'],
                        'Stock Ext.': r['external_quantity'],
                        'Length': r.get('length', 0),
                        'Width': r.get('width', 0),
                        'Clasif.': r['clasificacion'],
                        'Razón': r['razon'],
                        'Faltante Auto.': r.get('deficit_internal', 0) if r.get('deficit_internal') else '',
                        'Posible Cambio': r.get('possible_substitute', ''),
                        'Kanban': r.get('substitute_info', {}).get('kanban', '') if r.get('substitute_info') else '',
                        'Reservado': r.get('substitute_info', {}).get('reserved', '') if r.get('substitute_info') else '',
                        'Disponible': r.get('substitute_info', {}).get('free', '') if r.get('substitute_info') else ''
                    })
                df = pd.DataFrame(clean_rows)
            
            df.to_excel(writer, sheet_name=f'Resultados {target_origin}', index=False)
            filename = f"Resultados_{target_origin}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        
        # Caso 3: Stopa
        elif export_type == 'stopa':
            filtered_data = [r for r in analyzer.last_results if r['origen'] == 'Stopa']
            
            if not filtered_data:
                 df = pd.DataFrame(columns=['Item (Stopa)', 'Cantidad (Stopa)', 'Part # (Calculado)', 'Part # (Original)'])
            else:
                clean_rows = []
                for r in filtered_data:
                    clean_rows.append({
                        'Item (Stopa)': r.get('stopa_item', ''),
                        'Cantidad (Stopa)': r.get('stopa_quantity', ''),
                        'Part # (Calculado)': r.get('calculated_part_number', ''),
                        'Part # (Original)': r.get('original_part', ''),
                        'Length': r.get('length', 0),
                        'Width': r.get('width', 0)
                    })
                df = pd.DataFrame(clean_rows)
            
            df.to_excel(writer, sheet_name='Análisis Stopa', index=False)
            filename = f"Resultados_Stopa_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
        else:
            flash("Tipo de exportación no válido.")
            return redirect(url_for('index'))

    output.seek(0)
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

if __name__ == '__main__':
    app.run(debug=True)
