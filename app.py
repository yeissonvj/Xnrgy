from flask import Flask, render_template, request, send_file, flash, redirect, url_for, session, jsonify
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
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB para múltiples archivos

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
    
    # Calcular etiquetas únicas de PDFs por tipo para sub-pestañas
    punch_pdf_labels = []
    laser_pdf_labels = []
    if current_results:
        seen_p = set()
        seen_l = set()
        for r in current_results:
            label = r.get('pdf_label', '')
            origen = r.get('origen', '')
            if origen == 'Punch' and label not in seen_p:
                punch_pdf_labels.append(label)
                seen_p.add(label)
            elif origen == 'Laser' and label not in seen_l:
                laser_pdf_labels.append(label)
                seen_l.add(label)
    
    return render_template(
        'index.html',
        inventory_loaded=inventory_loaded,
        history=history,
        results=current_results,
        stats=analyzer.get_summary_stats() if current_results else None,
        inventory_summary=analyzer.get_inventory_summary() if current_results else None,
        punch_pdf_labels=punch_pdf_labels,
        laser_pdf_labels=laser_pdf_labels,
    )

@app.route('/preview_pdf', methods=['POST'])
@login_required
def preview_pdf():
    source_type = request.form.get('source_type', 'Punch')
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({'error': 'No file provided'}), 400

    analyzer = get_user_analyzer(session['user'])
    temp_dir = tempfile.mkdtemp()
    try:
        path = os.path.join(temp_dir, secure_filename(file.filename))
        file.save(path)
        data = analyzer.load_pdf_data(path, source_type)
        if not data:
            return jsonify({'error': 'No se pudo parsear el PDF'}), 400
        items = analyzer.extract_pdf_items(data, source_type)
        rows = [
            {
                'part_number': str(item.get('part_number', '')),
                'qte_a_produire': int(item.get('qte_a_produire', 0)),
                'materiel': str(item.get('materiel', '')),
                'epaisseur': str(item.get('epaisseur', '')),
            }
            for item in items
        ]
        return jsonify({'rows': rows, 'total': len(rows)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/analyze', methods=['POST'])
@login_required
def analyze():
    # Obtener todos los archivos Punch (puede haber varios con el mismo campo 'punch_files')
    punch_files_uploaded = request.files.getlist('punch_files')
    laser_files_uploaded = request.files.getlist('laser_files')
    stopa_file = request.files.get('stopa_file')
    inventory_file = request.files.get('inventory_file')
    priority = request.form.get('priority_machine', None)  # 'punch', 'laser', o None (sin prioridad)

    # Filtrar archivos vacíos
    punch_files_uploaded = [f for f in punch_files_uploaded if f and f.filename]
    laser_files_uploaded = [f for f in laser_files_uploaded if f and f.filename]

    analyzer = get_user_analyzer(session['user'])

    # Validar: necesitamos al menos un PDF
    if not punch_files_uploaded and not laser_files_uploaded and (not stopa_file or not stopa_file.filename):
        flash('Debe subir al menos un archivo PDF (Punch o Laser) para analizar.')
        return redirect(url_for('index'))

    # Validar inventario
    inventory_needed = analyzer.df_inventory_working is None
    if inventory_needed and (not inventory_file or inventory_file.filename == ''):
        flash('El archivo de Inventario es requerido para el primer análisis.')
        return redirect(url_for('index'))

    temp_dir = tempfile.mkdtemp()
    
    try:
        # Guardar y cargar PDFs de Punch
        punch_data_list = []
        for idx, f in enumerate(punch_files_uploaded):
            # Prefijo numérico para evitar colisión cuando el mismo archivo se sube varias veces
            safe_name = f"{idx}_{secure_filename(f.filename)}"
            path = os.path.join(temp_dir, safe_name)
            f.save(path)
            data = analyzer.load_pdf_data(path, "Punch")
            if data:
                # Restaurar el nombre original del archivo como etiqueta visible
                data['file_path'] = os.path.join(temp_dir, f"{idx}_{f.filename}")
                data['_display_name'] = f.filename
                punch_data_list.append(data)

        # Guardar y cargar PDFs de Laser
        laser_data_list = []
        for idx, f in enumerate(laser_files_uploaded):
            safe_name = f"{idx}_{secure_filename(f.filename)}"
            path = os.path.join(temp_dir, safe_name)
            f.save(path)
            data = analyzer.load_pdf_data(path, "Laser")
            if data:
                data['file_path'] = os.path.join(temp_dir, f"{idx}_{f.filename}")
                data['_display_name'] = f.filename
                laser_data_list.append(data)

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

        if not punch_data_list and not laser_data_list and not stopa_data:
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
             
        # Leer filas excluidas por archivo (índices separados por coma)
        punch_excluded = {}
        for i in range(len(punch_data_list)):
            excl_str = request.form.get(f'punch_excluded_{i}', '').strip()
            if excl_str:
                punch_excluded[i] = {int(x) for x in excl_str.split(',') if x.strip().isdigit()}

        laser_excluded = {}
        for i in range(len(laser_data_list)):
            excl_str = request.form.get(f'laser_excluded_{i}', '').strip()
            if excl_str:
                laser_excluded[i] = {int(x) for x in excl_str.split(',') if x.strip().isdigit()}

        analyzer.run_full_analysis(
            punch_data_list,
            laser_data_list,
            inventory_data,
            stopa_data,
            metadata,
            enabled_rules,
            priority=priority,
            punch_excluded=punch_excluded or None,
            laser_excluded=laser_excluded or None,
        )
        
        if not analyzer.last_results:
             flash('Análisis completado pero NO se generaron resultados. Verifique que los archivos tengan las columnas correctas (Stopa: "Item", Inventario: "stopaMaterialName").', 'warning')
        else:
             total = len(analyzer.last_results)
             punch_count = sum(1 for r in analyzer.last_results if r.get('origen') == 'Punch')
             laser_count = sum(1 for r in analyzer.last_results if r.get('origen') == 'Laser')
             priority_msg = f'Prioridad: {priority.capitalize()}.' if priority else 'Sin prioridad (análisis intercalado).'
             flash(f'Análisis completado. {total} items procesados — Punch: {punch_count}, Laser: {laser_count}. {priority_msg}')
             
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
            
        # Caso 2: Punch o Laser (Resultados detallados — todas las sub-pestañas combinadas)
        elif export_type in ['punch', 'laser']:
            target_origin = export_type.capitalize()
            filtered_data = [r for r in analyzer.last_results if r['origen'] == target_origin]
            
            if not filtered_data:
                df = pd.DataFrame(columns=['PDF', 'Origen', 'Part #', 'Qté Prod.', 'Stock Int.', 'Stock Ext.', 'Length', 'Width', 'Clasif.', 'Razón', 'Faltante Auto.', 'Posible Cambio', 'Kanban', 'Reservado', 'Disponible'])
            else:
                clean_rows = []
                for r in filtered_data:
                    clean_rows.append({
                        'PDF': r.get('pdf_label', ''),
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
