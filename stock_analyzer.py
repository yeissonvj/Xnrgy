import pandas as pd
import pdfplumber
import re
from datetime import datetime

class StockAnalyzer:
    def __init__(self, log_callback=None):
        """
        Inicializa el analizador.
        :param log_callback: Función opcional para enviar logs (mensaje, tipo)
        """
        self.log_callback = log_callback
        self.punch_data = None
        self.laser_data = None
        self.inventory_data = None
        # Inventario de trabajo persistente
        self.df_inventory_working = None
        self.inventory_data_raw = None # Store raw data for resets
        self.last_results = []
        # Historial de análisis
        self.history = [] 

    def log(self, message, msg_type="info"):
        if self.log_callback:
            self.log_callback(message, msg_type)
        else:
            print(f"[{msg_type.upper()}] {message}")

    def reset(self):
        """Reinicia todo el estado del analizador."""
        self.punch_data = None
        self.laser_data = None
        self.inventory_data = None
        self.df_inventory_working = None
        self.inventory_data_raw = None
        self.last_results = []
        self.history = []
        self.log("Estado del analizador reiniciado.", "warning")

    def load_pdf_data(self, file_path, source_name):
        """Carga datos de un PDF usando pdfplumber."""
        try:
            with pdfplumber.open(file_path) as pdf:
                all_tables = []
                for page in pdf.pages:
                    table = page.extract_table()
                    if table:
                        all_tables.extend(table)
                
                if all_tables:
                    headers = all_tables[0]
                    df = pd.DataFrame(all_tables[1:], columns=headers)
                    self.log(f"PDF {source_name} cargado: {len(df)} filas detectadas.", "success")
                    return {
                        'file_path': file_path,
                        'dataframe': df,
                        'headers': headers
                    }
                else:
                    raise Exception("No se encontraron tablas en el PDF")
        except Exception as e:
            self.log(f"Error cargando PDF {source_name}: {str(e)}", "error")
            return None

    def load_inventory_excel(self, file_path):
        """Carga el Excel de inventario."""
        try:
            df = pd.read_excel(file_path)
            self.log(f"Excel Inventario cargado: {len(df)} filas.", "success")
            return {
                'file_path': file_path,
                'dataframe': df,
                'rows': len(df)
            }
        except Exception as e:
            self.log(f"Error cargando Excel Inventario: {str(e)}", "error")
            return None

    def initialize_inventory(self, inventory_data=None, force_reload=True):
        """
        Inicializa el inventario de trabajo.
        Si inventory_data es None, intenta usar self.inventory_data_raw.
        Si force_reload es True, reconstruye desde raw data.
        """
        # 1. New data provided
        if inventory_data:
            self.inventory_data_raw = inventory_data

        # 2. Use existing working copy if valid and not forced
        if self.df_inventory_working is not None and not force_reload:
             self.log("Usando inventario existente en memoria.", "info")
             return self.df_inventory_working

        # 3. Need to rebuild but no raw data
        if not self.inventory_data_raw:
            return None
            
        # 4. Rebuild from raw
        df_inventory = self.inventory_data_raw['dataframe'].copy()
        self.df_inventory_working = df_inventory # Reset working copy
        
        # Normalizar y limpiar
        self.df_inventory_working['partNumber_normalized'] = self.df_inventory_working['partNumber'].astype(str).str.strip()
        self.df_inventory_working['stopaQuantity'] = pd.to_numeric(self.df_inventory_working['stopaQuantity'], errors='coerce').fillna(0)
        self.df_inventory_working['externalQuantity'] = pd.to_numeric(self.df_inventory_working['externalQuantity'], errors='coerce').fillna(0)
        

        # Detectar columnas de dimensiones (Length/Width)
        # Posibles nombres: 'Longeur (PO)', 'Length', 'Largo'
        # Posibles nombres: 'Largeur (PO)', 'Width', 'Ancho'
        length_col = None
        width_col = None
        
        for col in df_inventory.columns:
            c_lower = str(col).lower().strip()
            if not length_col and any(x in c_lower for x in ['longeur (po)', 'length']):
                length_col = col
            if not width_col and any(x in c_lower for x in ['largeur (po)', 'width']):
                width_col = col
                
        # Normalizar columnas de dimensiones
        if length_col:
            self.df_inventory_working['length_val'] = pd.to_numeric(self.df_inventory_working[length_col], errors='coerce').fillna(0)
        else:
            self.df_inventory_working['length_val'] = 0
            
        if width_col:
            self.df_inventory_working['width_val'] = pd.to_numeric(self.df_inventory_working[width_col], errors='coerce').fillna(0)
        else:
            self.df_inventory_working['width_val'] = 0

        # Limpiar materialType si existe
        if 'materialType' in self.df_inventory_working.columns:
            self.df_inventory_working['materialType'] = self.df_inventory_working['materialType'].astype(str).str.strip()

        # Limpiar/Normalizar reservedQuantity si existe
        if 'reservedQuantity' in self.df_inventory_working.columns:
             self.df_inventory_working['reservedQuantity'] = pd.to_numeric(self.df_inventory_working['reservedQuantity'], errors='coerce').fillna(0)
        else:
             self.df_inventory_working['reservedQuantity'] = 0

        # Limpiar kanban si existe (opcional, se usa as-is)
        if 'kanban' not in self.df_inventory_working.columns:
             self.df_inventory_working['kanban'] = 'No'

        # --- EXTENSION: AGREGACIÓN DE DUPLICADOS ---
        # Si un Part Number aparece varias veces, sumamos stocks y reservado.
        # Las otras columnas (Dimensiones, Material) se toman del primero.
        
        # Identificar columnas numéricas a sumar
        agg_cols = {'stopaQuantity': 'sum', 'externalQuantity': 'sum', 'reservedQuantity': 'sum'}
        
        # Identificar columnas numéricas de dimensiones (tomar maximo o primero? maximo es mas seguro)
        if 'length_val' in self.df_inventory_working.columns: agg_cols['length_val'] = 'max'
        if 'width_val' in self.df_inventory_working.columns: agg_cols['width_val'] = 'max'
        
        # Todas las demás columnas: 'first'
        other_cols = [c for c in self.df_inventory_working.columns if c not in agg_cols and c != 'partNumber_normalized']
        agg_dict = {c: 'first' for c in other_cols}
        agg_dict.update(agg_cols)
        
        try:
            self.df_inventory_working = self.df_inventory_working.groupby('partNumber_normalized', as_index=False).agg(agg_dict)
            self.log("Inventario consolidado (duplicados sumados).", "info")
            
            # DEBUG: Check after aggregation
            debug_after = self.df_inventory_working[self.df_inventory_working['partNumber_normalized'] == '15036']
            if not debug_after.empty:
                 r = debug_after.iloc[0]
                 self.log(f"DEBUG: 15036 post-agregación: Stopa={r['stopaQuantity']}, Ext={r['externalQuantity']}", "warning")

        except Exception as e:
            self.log(f"Error consolidando inventario: {e}", "warning")
            # Fallback: seguir con duplicados (pero analyze_item solo verá el primero)

        self.log(f"Inventario inicializado. Dimensiones detectadas: L={length_col}, W={width_col}", "info")
        return self.df_inventory_working

    def extract_pdf_items(self, pdf_data, source_name):
        """Extrae items del PDF."""
        items = []
        if not pdf_data:
            return items

        try:
            df = pdf_data['dataframe']
            self.log(f"Extrayendo items de {source_name}...", "process")
            
            part_col = None
            qte_col = None
            
            for col in df.columns:
                if col and 'Part' in str(col):
                    part_col = col
                if col and ('Qté' in str(col) or 'Qte' in str(col)) and 'Produire' in str(col):
                    qte_col = col
            
            if part_col and qte_col:
                # Estrategia de Tablas
                for idx, row in df.iterrows():
                    part_num = str(row[part_col]).strip() if pd.notna(row[part_col]) else ""
                    qte_str = str(row[qte_col]).strip() if pd.notna(row[qte_col]) else ""
                    
                    if not part_num or not qte_str:
                        continue
                    
                    try:
                        qte = int(float(qte_str))
                        if qte > 0:
                            # Extraer datos adicionales (Material, Espesor) si las columnas fueron detectadas
                            materiel_val = ""
                            epaisseur_val = ""
                            
                            # Buscar columnas dinámicamente si no se hizo arriba (o reusar logica)
                            # Para simplicidad, busquemos en row.keys() que coincidan
                            for key in row.keys():
                                k_str = str(key).lower()
                                if 'materiel' in k_str or 'material' in k_str:
                                    materiel_val = str(row[key]).strip() if pd.notna(row[key]) else ""
                                if 'epaisseur' in k_str or 'thickness' in k_str:
                                    epaisseur_val = str(row[key]).strip() if pd.notna(row[key]) else ""

                            items.append({
                                'part_number': part_num,
                                'qte_a_produire': qte,
                                'materiel': materiel_val,
                                'epaisseur': epaisseur_val,
                                'source': source_name,
                                'full_row': row.to_dict()
                            })
                    except (ValueError, TypeError):
                        continue
            
            self.log(f"Total items extraídos de {source_name}: {len(items)}", "success")

        except Exception as e:
            self.log(f"Error extrayendo items de {source_name}: {str(e)}", "error")
        
        return items

    def analyze_item(self, item, df_inventory, source, enabled_rules=None):
        """Analiza un item individual contra el inventario."""
        # Default rules if none provided (backward compatibility)
        if enabled_rules is None:
            enabled_rules = {
                'rule_10034': True,
                'rule_special_parts': True,
                'rule_external_low': True
            }

        part_number = str(item['part_number']).strip()
        qte_a_produire = item['qte_a_produire']
        
        result = {
            'origen': source,
            'part_number': part_number,
            'qte_a_produire': qte_a_produire,
            'materiel': item.get('materiel', ''),
            'epaisseur': item.get('epaisseur', ''),
            'encontrado_en_inventario': False,
            'stopa_quantity': 0,
            'external_quantity': 0,
            'clasificacion': None,
            'razon': '',
            'full_row': item.get('full_row', {})
        }
        
        try:
            mask = df_inventory['partNumber_normalized'] == part_number
            matches = df_inventory.loc[mask]
            
            if not matches.empty:
                result['encontrado_en_inventario'] = True
                idx = matches.index[0]
                
                stopa_qty = df_inventory.at[idx, 'stopaQuantity']
                external_qty = df_inventory.at[idx, 'externalQuantity']
                
                # Extraer Material y Espesor del INVENTARIO (Excel)
                if 'materialName' in df_inventory.columns:
                     result['materiel'] = df_inventory.at[idx, 'materialName']
                if 'materialType' in df_inventory.columns:
                     result['material_type'] = df_inventory.at[idx, 'materialType']
                if 'gauge' in df_inventory.columns:
                     result['epaisseur'] = df_inventory.at[idx, 'gauge']

                # Extraer Dimensiones (ya normalizadas en initialize_inventory)
                result['length'] = df_inventory.at[idx, 'length_val']
                result['width'] = df_inventory.at[idx, 'width_val']

                result['stopa_quantity'] = stopa_qty
                result['external_quantity'] = external_qty
                
                # Reglas de Negocio Opcionales
                rule_applied = False
                
                # Regla 1: Part # 10034
                if enabled_rules.get('rule_10034', True) and part_number == '10034':
                    result['clasificacion'] = 'S'
                    result['razon'] = 'Part # especial 10034'
                    rule_applied = True
                
                # Regla 2: Special Parts
                elif enabled_rules.get('rule_special_parts', True) and part_number in ['10089', '10093', '10098', '10016']:
                    result['clasificacion'] = 'M'
                    result['razon'] = f'Part # especial {part_number}'
                    rule_applied = True
                    
                # Regla 3: Low External Stock (pero no BO absoluto, ese es standard)
                # Esta regla es específica para cuando hay poco stock externo (1-2) y fuerza Manual?
                # La lógica original era: stopa <= 0 and (1 <= ext <= 2) and ext >= qte -> M
                elif enabled_rules.get('rule_external_low', True) and stopa_qty <= 0 and (1 <= external_qty <= 2) and external_qty >= qte_a_produire:
                    result['clasificacion'] = 'M'
                    result['razon'] = f'Stock externo bajo ({external_qty})'
                    # Consumir stock aunque sea manual? La logica original lo hacía:
                    df_inventory.at[idx, 'externalQuantity'] = external_qty - qte_a_produire
                    rule_applied = True

                # Lógica Estándar (Fallback si no se aplicó regla o no cumplió condición)
                if not rule_applied:
                    if stopa_qty <= 0 and external_qty <= 0:
                        result['clasificacion'] = 'BO'
                        result['razon'] = 'Sin stock disponible (BO)'
                    elif stopa_qty > 0 and stopa_qty >= qte_a_produire:
                        result['clasificacion'] = 'A'
                        result['razon'] = f'Stock interno suficiente'
                        df_inventory.at[idx, 'stopaQuantity'] = stopa_qty - qte_a_produire
                    elif stopa_qty == 0 and external_qty >= qte_a_produire:
                        result['clasificacion'] = 'C'
                        result['razon'] = f'Stock externo suficiente'
                        df_inventory.at[idx, 'externalQuantity'] = external_qty - qte_a_produire
                    else:
                        # CASO ESPECIAL: Stock Mixto (Interno + Externo cubre la demanda)
                        if stopa_qty + external_qty >= qte_a_produire:
                             result['clasificacion'] = 'C'
                             consumed_ext = qte_a_produire - stopa_qty
                             result['razon'] = f'Stock Mixto (Int: {stopa_qty}, Ext: {consumed_ext})'
                             
                             # Consumir todo el interno
                             df_inventory.at[idx, 'stopaQuantity'] = 0
                             # Consumir el resto del externo
                             df_inventory.at[idx, 'externalQuantity'] = external_qty - consumed_ext
                             
                        else:
                            # Verdadero BO (Ni sumando alcanza)
                            result['clasificacion'] = 'BO' 
                            result['razon'] = f'Stock insuficiente'
                            
                            # Consumo Parcial para que el siguiente análisis (ej: Laser) vea 0.
                            # 1. Consumir todo lo que haya en Stopa
                            consumed_stopa = 0
                            if stopa_qty > 0:
                                consumed_stopa = stopa_qty
                                df_inventory.at[idx, 'stopaQuantity'] = 0 # Deja en 0
                            
                            # 2. Si aún falta, ver si hay algo en Externo (aunque no alcance para todo)
                            remaining_need = qte_a_produire - consumed_stopa
                            
                            if remaining_need > 0 and external_qty > 0:
                                # Consumir lo que haya en externo
                                consumed_external = min(remaining_need, external_qty)
                                df_inventory.at[idx, 'externalQuantity'] = external_qty - consumed_external
            else:
                self.log(f"Item {part_number} no encontrado en inventario.", "warning")

            # Calcular déficit para automático (A) si no es A
            if result['clasificacion'] in ['C', 'BO', None] and result['encontrado_en_inventario']:
                # Cuántos faltan en Stock Interno para cubrir la demanda
                # Si tengo 0 y necesito 4, balance es -4.
                balance = result['stopa_quantity'] - result['qte_a_produire']
                if balance < 0:
                     result['deficit_internal'] = balance

            # Busqueda de SUSTITUTOS si está en BO y fue encontrado en inventario (tenemos sus datos)
            if result['clasificacion'] == 'BO' and result['encontrado_en_inventario']:
                # Calcular cuanto falta realmente
                # Si deficit_internal existe, es lo que falta. Si no, asumimos que falta todo (qte_a_produire) si no habia stock?
                # En logica BO, deficit_internal se calcula arriba: balance = stock - qte. Si balance < 0, deficit = balance (negativo)
                # Queremos la cantidad positiva que falta.
                missing_qty = 0
                if result.get('deficit_internal'):
                    missing_qty = abs(result['deficit_internal'])
                else:
                    # Si es BO y no se calculó déficit (raro con mi logica anterior, pero por seguridad)
                    # Si stock 0, falta todo.
                    current_stock = result['stopa_quantity'] + result['external_quantity']
                    missing_qty = result['qte_a_produire'] - current_stock
                
                if missing_qty > 0:
                    substitute_data = self.find_substitute(df_inventory, 
                                                      result.get('material_type'), 
                                                      result.get('epaisseur'), 
                                                      result.get('length', 0), 
                                                      result.get('width', 0),
                                                      part_number,
                                                      missing_qty)
                    
                    if substitute_data:
                        # substitute_data tiene 'index', 'part_number', etc.
                        sub_idx = substitute_data['index']
                        
                        # ACTUALIZAR RESERVA VIRTUAL
                        # Incrementamos reservedQuantity en el dataframe de trabajo
                        # para que el siguiente item vea menos stock libre.
                        current_reserved = df_inventory.at[sub_idx, 'reservedQuantity']
                        df_inventory.at[sub_idx, 'reservedQuantity'] = current_reserved + missing_qty
                        
                        result['possible_substitute'] = substitute_data['part_number']
                        result['substitute_info'] = substitute_data # Guardar objeto completo
                        
                        self.log(f"Asignado sustituto {substitute_data['part_number']} a {part_number}. Reserva aumentada en {missing_qty}", "info")

        except Exception as e:
            self.log(f"Error analizando item {part_number}: {str(e)}", "error")
            
        return result

    def find_substitute(self, df_inventory, material_type, gauge, req_length, req_width, original_part, needed_qty):
        """
        Busca un sustituto válido en el inventario.
        Criterios:
        - Mismo materialType
        - Mismo gauge (epaisseur)
        - Length >= req_length
        - Width >= req_width
        - Stock LIBRE (Total - Reservado) >= needed_qty
        - No ser el mismo item original
        """
        try:
            if not material_type or not gauge:
                return None

            # 1. Filtrar por Material Type y Gauge
            # Asegurar tipos
            g_str = str(gauge).strip().lower()
            mt_str = str(material_type).strip().lower()
            required_qty = float(needed_qty) if needed_qty else 0
            
            # Crear máscara base
            # Asumimos que las columnas ya fueron normalizadas o limpiadas en initialize_inventory
            # Pero para asegurar comparacion correcta usamos str.lower()
            
            # Filtro rapido iterando (menos eficiente pandas puro pero más seguro con datos sucios)
            candidates = []
            
            for idx, row in df_inventory.iterrows():
                # Skip self
                row_pn = str(row['partNumber_normalized']).strip()
                if row_pn == str(original_part):
                    continue
                
                # Check Stock
                st_qty = float(row['stopaQuantity']) if pd.notna(row['stopaQuantity']) else 0
                ext_qty = float(row['externalQuantity']) if pd.notna(row['externalQuantity']) else 0
                total_stock = st_qty + ext_qty
                
                # Check Reserved
                reserved_qty = float(row.get('reservedQuantity', 0)) if pd.notna(row.get('reservedQuantity', 0)) else 0
                
                # Stock Libre = Total - Reservado
                free_stock = total_stock - reserved_qty
                if free_stock < 0: free_stock = 0
                
                # El stock del sustituto debe ser suficiente para cubrir lo que falta
                if free_stock < required_qty:
                    continue
                
                # Check Material & Gauge
                row_mt = str(row.get('materialType', '')).strip().lower()
                row_g = str(row.get('gauge', '')).strip().lower()
                
                if row_mt != mt_str or row_g != g_str:
                    continue
                    
                # Check Dimensions
                # Dimensiones del candidato
                cand_len = float(row.get('length_val', 0))
                cand_wid = float(row.get('width_val', 0))
                
                # Dimensiones requeridas
                req_l = float(req_length)
                req_w = float(req_width)
                
                if cand_len >= req_l and cand_wid >= req_w:
                    # Devolver objeto con detalles
                    kanban_val = str(row.get('kanban', 'No')).strip()
                    
                    return {
                        'index': idx, # IMPORTANTE: Retornar índice para actualizar
                        'part_number': row_pn,
                        'kanban': kanban_val,
                        'reserved': reserved_qty,
                        'free': free_stock,
                        'total': total_stock # Optional
                    }
            
            # Si no encontró nada
            return None
                
        except Exception as e:
            # self.log(f"Error buscando sustituto: {e}", "warning") # Opcional log
            return None



    def get_summary_stats(self):
        if not self.last_results:
            return {}
        
        count_a = sum(1 for r in self.last_results if r.get('clasificacion') == 'A')
        count_c = sum(1 for r in self.last_results if r.get('clasificacion') == 'C')
        count_none = sum(1 for r in self.last_results if r.get('clasificacion') is None)
        total = len(self.last_results)
        
        return {
            'total': total,
            'count_a': count_a,
            'count_c': count_c,
            'count_none': count_none,
            # Calcular BO explícitamente como el resto o si tiene clasif BO
            'count_bo': sum(1 for r in self.last_results if r.get('clasificacion') == 'BO')
        }

    def get_inventory_summary(self):
        """
        Agrupa los resultados por Part Number para mostrar en el tab de Inventario.
        Calcula total requerido, stock inicial (detectado en el primer uso) y faltante global.
        """
        summary_map = {}
        
        for res in self.last_results:
            # Skip Stopa results or any result without part_number
            if res.get('origen') == 'Stopa':
                continue
                
            pn = res.get('part_number')
            if not pn: continue
            
            qte = res['qte_a_produire']
            
            # Obtener stock inicial reportado en la primera aparición de la pieza en este análisis
            current_snap_stock = (int(res.get('stopa_quantity', 0)) + int(res.get('external_quantity', 0)))
            
            if pn not in summary_map:
                summary_map[pn] = {
                    'part_number': pn,
                    'materiel': res.get('materiel', ''),
                    'material_type': res.get('material_type', ''),
                    'epaisseur': res.get('epaisseur', ''),
                    'length': res.get('length', 0),
                    'width': res.get('width', 0),
                    'total_required': 0,
                    'initial_stock': current_snap_stock, 
                    'missing': 0
                }
            
            summary_map[pn]['total_required'] += qte
            
        # Calcular lista final
        summary_list = []
        for pn, data in summary_map.items():
            req = data['total_required']
            stock = data['initial_stock']
            missing = req - stock
            if missing < 0:
                missing = 0
            
            data['missing'] = missing
            summary_list.append(data)
            
        # Ordenar por Part Number de menor a mayor
        def sort_key(item):
            pn = item['part_number']
            try:
                val = float(pn)
                return (0, val)
            except ValueError:
                return (1, pn)

        summary_list.sort(key=sort_key)
        
        return summary_list

    def load_stopa_excel(self, file_path):
        """Carga el Excel de reporte Stopa."""
        try:
            # Soportar xls y xlsx
            df = pd.read_excel(file_path)
            self.log(f"Excel Stopa cargado: {len(df)} filas.", "success")
            return {
                'file_path': file_path,
                'dataframe': df
            }
        except Exception as e:
            self.log(f"Error cargando Excel Stopa: {str(e)}", "error")
            return None

    def process_stopa_analysis(self, stopa_data, df_inventory):
        """
        Cruza la info de Stopa con el Inventario.
        Criterio: Stopa['Item'] == Inventory['stopaMaterialName']
        Objetivo: Traer el partNumber del inventario y asignarlo como 'part#' en el resultado.
        """
        results = []
        if not stopa_data or df_inventory is None:
            return results

        try:
            df_stopa = stopa_data['dataframe']
            
            # Normalizar columnas para evitar problemas de case/espacios
            df_stopa.columns = [str(c).strip() for c in df_stopa.columns]
            
            # Verificar columnas requeridas en Stopa
            # Se espera: part#, Item, Quantity
            col_map = {}
            for c in df_stopa.columns:
                lower_c = c.lower().strip()
                if lower_c == 'item': col_map['Item'] = c
                if 'quantity' in lower_c or 'cantidad' in lower_c: col_map['Quantity'] = c
                if 'part' in lower_c and '#' in lower_c: col_map['part#'] = c
            
            # Si no encontramos las columnas clave, intentamos usar las que hay o fallamos
            if 'Item' not in col_map:
                self.log(f"Columna 'Item' no encontrada en archivo Stopa. Columnas detectadas: {list(df_stopa.columns)}", "error")
                return []
                
            stopa_item_col = col_map['Item']
            
            # Preparar Inventario para cruce
            # Verificar si existe columna stopaMaterialName
            inv_stopa_col = None
            for c in df_inventory.columns:
                if str(c).strip() == 'stopaMaterialName':
                    inv_stopa_col = c
                    break
            
            if not inv_stopa_col:
                self.log("Columna 'stopaMaterialName' no encontrada en Inventario. No se puede cruzar.", "error")
                # Devolver datos crudos con aviso? Mejor devolver vacio o error.
                return []

            # Iterar y cruzar
            self.log("Iniciando cruce Stopa vs Inventario...", "process")
            
            # Crear diccionario de lookup para eficiencia: { stopaMaterialName : partNumber }
            # Asumimos que stopaMaterialName es único o tomamos el primero?
            # Si hay duplicados en inventario, tomamos el primero válido.
            lookup_dict = {}
            # Filtrar filas vacías
            valid_inv = df_inventory.dropna(subset=[inv_stopa_col])
            
            for idx, row in valid_inv.iterrows():
                mat_name = str(row[inv_stopa_col]).strip().upper()
                part_num = str(row['partNumber_normalized']).strip()
                if mat_name and mat_name not in lookup_dict:
                    lookup_dict[mat_name] = part_num
            
            for idx, row in df_stopa.iterrows():
                item_name = str(row[stopa_item_col]).strip().upper()
                
                # Buscar match
                matched_part = lookup_dict.get(item_name, "NO MATCH")
                
                # Extraer dimensiones si hubo match (o intentar buscarlas en inventory)
                length_val = 0
                width_val = 0
                
                if matched_part != "NO MATCH":
                    # Buscar la fila en inventario que corresponde a este part number
                    # Como lookup_dict solo guarda el part_number, busquemos en valid_inv
                    # Nota: Esto podría optimizarse creando un diccionario de datos completo en lugar de solo part_num
                    # Pero para mantener consistencia con el flujo actual:
                    mask = valid_inv['partNumber_normalized'] == matched_part
                    if any(mask):
                         inv_row = valid_inv.loc[mask].iloc[0]
                         length_val = inv_row.get('length_val', 0)
                         width_val = inv_row.get('width_val', 0)

                qty_val = 0
                if 'Quantity' in col_map:
                    try:
                        qty_val = float(row[col_map['Quantity']])
                    except:
                        qty_val = 0
                
                # Fila original del archivo Stopa (part# original si existe)
                original_part = ""
                if 'part#' in col_map:
                    original_part = str(row[col_map['part#']])

                results.append({
                    'origen': 'Stopa',
                    'stopa_item': item_name,     # Item del excel Stopa
                    'stopa_quantity': qty_val,   # Cantidad del excel Stopa
                    'original_part': original_part, # Lo que venía en el excel
                    'calculated_part_number': matched_part, # Lo que encontramos en Inventario
                    'length': length_val,
                    'width': width_val,
                    'full_row': row.to_dict()
                })
                
            self.log(f"Análisis Stopa completado. {len(results)} items procesados.", "success")
            
        except Exception as e:
            self.log(f"Error procesando Stopa: {str(e)}", "error")
            
        return results

    def run_full_analysis(self, punch_files, laser_files, inventory_data=None, stopa_data=None, metadata=None, enabled_rules=None, priority=None, punch_excluded=None, laser_excluded=None):
        """
        Ejecuta el flujo completo de análisis.
        
        :param punch_files: Lista de dicts con datos PDF de Punch (puede ser lista vacía)
        :param laser_files: Lista de dicts con datos PDF de Laser (puede ser lista vacía)
        :param inventory_data: Datos de Excel de inventario (opcional si ya hay uno en memoria)
        :param stopa_data: Datos de Excel Stopa (opcional)
        :param metadata: Metadatos del proyecto
        :param enabled_rules: Reglas de análisis activas
        :param priority: 'punch', 'laser' o None (sin prioridad → intercalado)
        
        Retorna: Lista plana de resultados, cada uno con 'pdf_label' identificando el origen.
        """
        results = []
        
        # Inicializar inventario solo si se provee nuevo, sino usa el existente
        should_reload = (inventory_data is not None)
        self.initialize_inventory(inventory_data, force_reload=should_reload)
        
        if self.df_inventory_working is None:
            self.log("No hay inventario cargado. Imposible analizar.", "error")
            return results

        # Mapas id→índice para aplicar exclusiones de filas por archivo
        punch_id_to_idx = {id(pdf): i for i, pdf in enumerate(punch_files) if pdf}
        laser_id_to_idx = {id(pdf): i for i, pdf in enumerate(laser_files) if pdf}

        # Determinar el orden de procesamiento según prioridad
        punch_entries = [(pdf, 'Punch') for pdf in punch_files if pdf]
        laser_entries = [(pdf, 'Laser') for pdf in laser_files if pdf]

        if priority == 'punch':
            # Punch completo primero, luego Laser completo
            ordered_entries = [('Punch', punch_entries), ('Laser', laser_entries)]
            processing_list = [
                (pdf_data, source)
                for group_name, entries in ordered_entries
                for pdf_data, source in entries
            ]
        elif priority == 'laser':
            # Laser completo primero, luego Punch completo
            ordered_entries = [('Laser', laser_entries), ('Punch', punch_entries)]
            processing_list = [
                (pdf_data, source)
                for group_name, entries in ordered_entries
                for pdf_data, source in entries
            ]
        else:
            # Sin prioridad: intercalar por índice (punch0, laser0, punch1, laser1, ...)
            max_len = max(len(punch_entries), len(laser_entries)) if (punch_entries or laser_entries) else 0
            processing_list = []
            for i in range(max_len):
                if i < len(punch_entries):
                    processing_list.append(punch_entries[i])
                if i < len(laser_entries):
                    processing_list.append(laser_entries[i])

        # Guardar el orden de archivos para reordenar la salida al final.
        # Usamos _display_name (nombre original sin prefijo numérico) y añadimos
        # un sufijo de copia " (2)", " (3)"... cuando el mismo nombre aparece más de una vez.
        file_order = []
        _label_count = {}  # nombre -> cuántas veces ha aparecido
        for pdf_data, source in processing_list:
            import os
            raw_name = pdf_data.get('_display_name') or os.path.basename(pdf_data.get('file_path', ''))
            pdf_label = raw_name if raw_name else f"{source}_pdf"
            _label_count[pdf_label] = _label_count.get(pdf_label, 0) + 1
            if _label_count[pdf_label] > 1:
                pdf_label = f"{pdf_label} ({_label_count[pdf_label]})"
            pdf_data['_pdf_label'] = pdf_label  # Guardar para el loop de procesamiento
            file_order.append(pdf_label)

        results_by_file = {}  # pdf_label -> lista de resultados

        for pdf_data, source_label in processing_list:
            # Usar la etiqueta ya calculada con sufijo de copia si es necesario
            pdf_label = pdf_data.get('_pdf_label', '')
            if not pdf_label:
                import os
                pdf_label = os.path.basename(pdf_data.get('file_path', '')) or f"{source_label}_pdf"

            self.log(f"Procesando {source_label}: {pdf_label}", "process")
            items = self.extract_pdf_items(pdf_data, source_label)

            # Aplicar exclusiones de filas seleccionadas por el usuario
            if source_label == 'Punch' and punch_excluded:
                file_idx = punch_id_to_idx.get(id(pdf_data))
                if file_idx is not None:
                    excl = punch_excluded.get(file_idx, set())
                    if excl:
                        items = [item for i, item in enumerate(items) if i not in excl]
                        self.log(f"Excluidas {len(excl)} filas del archivo Punch #{file_idx + 1}", "info")
            elif source_label == 'Laser' and laser_excluded:
                file_idx = laser_id_to_idx.get(id(pdf_data))
                if file_idx is not None:
                    excl = laser_excluded.get(file_idx, set())
                    if excl:
                        items = [item for i, item in enumerate(items) if i not in excl]
                        self.log(f"Excluidas {len(excl)} filas del archivo Laser #{file_idx + 1}", "info")

            # --- REGLA DE PRIORIDAD POR CANTIDAD PEQUEÑA ---
            # Guardamos el índice original (posición en el PDF) en cada item.
            for orig_idx, it in enumerate(items):
                it['_pdf_row_order'] = orig_idx

            # Ordenamos de MENOR a MAYOR qte_a_produire para que con stock limitado
            # se cubran primero los pedidos más pequeños (maximiza requisiciones cubiertas).
            items_sorted = sorted(items, key=lambda x: (x['part_number'], x['qte_a_produire']))

            file_results_by_order = {}
            for item in items_sorted:
                res = self.analyze_item(item, self.df_inventory_working, source_label, enabled_rules)
                res['pdf_label'] = pdf_label
                res['_pdf_row_order'] = item['_pdf_row_order']
                file_results_by_order[item['_pdf_row_order']] = res

            # Restaurar el orden original del PDF para la salida
            file_results = [file_results_by_order[i] for i in sorted(file_results_by_order.keys())]

            results_by_file[pdf_label] = file_results

        # Reordenar la salida según el orden original de los archivos subidos.
        # Cada archivo mantiene su bloque de resultados (orden de aparición en el PDF),
        # pero el orden entre archivos sigue el orden de subida del usuario.
        for pdf_label in file_order:
            if pdf_label in results_by_file:
                results.extend(results_by_file[pdf_label])

        # Stopa (no tiene prioridad, se procesa al final)
        if stopa_data:
            stopa_results = self.process_stopa_analysis(stopa_data, self.df_inventory_working)
            for r in stopa_results:
                r['pdf_label'] = 'Stopa'
            results.extend(stopa_results)
            
        self.last_results = results
        
        # Agregar al historial
        stats = self.get_summary_stats()
        
        # Generar nombres de archivo para log
        p_names = [p.get('file_path', 'N/A') for p in punch_files if p]
        l_names = [l.get('file_path', 'N/A') for l in laser_files if l]
        s_name = stopa_data['file_path'] if stopa_data else "N/A"
        
        history_entry = {
            "id": len(self.history) + 1,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "stats": stats,
            "punch_files": p_names,
            "laser_files": l_names,
            "stopa_file": s_name,
            "metadata": metadata or {},
            "rules_used": enabled_rules,
            "priority": priority
        }
        self.history.append(history_entry)
        
        return results
