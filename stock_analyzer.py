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

    def initialize_inventory(self, inventory_data):
        """
        Inicializa el inventario de trabajo SI NO EXISTE.
        Si ya existe, se mantiene el actual (con consumos previos).
        """
        if self.df_inventory_working is not None:
             self.log("Usando inventario existente en memoria.", "info")
             return self.df_inventory_working

        if not inventory_data:
            return None
            
        df_inventory = inventory_data['dataframe']
        self.df_inventory_working = df_inventory.copy()
        
        # Normalizar y limpiar
        self.df_inventory_working['partNumber_normalized'] = self.df_inventory_working['partNumber'].astype(str).str.strip()
        self.df_inventory_working['stopaQuantity'] = pd.to_numeric(self.df_inventory_working['stopaQuantity'], errors='coerce').fillna(0)
        self.df_inventory_working['externalQuantity'] = pd.to_numeric(self.df_inventory_working['externalQuantity'], errors='coerce').fillna(0)
        
        self.log("Inventario de trabajo inicializado.", "info")
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
                            items.append({
                                'part_number': part_num,
                                'qte_a_produire': qte,
                                'source': source_name,
                                'full_row': row.to_dict()
                            })
                    except (ValueError, TypeError):
                        continue
            
            self.log(f"Total items extraídos de {source_name}: {len(items)}", "success")

        except Exception as e:
            self.log(f"Error extrayendo items de {source_name}: {str(e)}", "error")
        
        return items

    def analyze_item(self, item, df_inventory, source):
        """Analiza un item individual contra el inventario."""
        part_number = str(item['part_number']).strip()
        qte_a_produire = item['qte_a_produire']
        
        result = {
            'origen': source,
            'part_number': part_number,
            'qte_a_produire': qte_a_produire,
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
                
                result['stopa_quantity'] = stopa_qty
                result['external_quantity'] = external_qty
                
                # Reglas de Negocio
                if part_number == '10034':
                    result['clasificacion'] = 'S'
                    result['razon'] = 'Part # especial 10034'
                elif part_number in ['10089', '10093', '10098', '10016']:
                    result['clasificacion'] = 'M'
                    result['razon'] = f'Part # especial {part_number}'
                elif stopa_qty <= 0 and external_qty <= 0:
                    result['clasificacion'] = 'BO'
                    result['razon'] = 'Sin stock disponible (BO)'
                elif stopa_qty <= 0 and (1 <= external_qty <= 2) and external_qty >= qte_a_produire:
                    result['clasificacion'] = 'M'
                    result['razon'] = f'Stock externo bajo ({external_qty})'
                    df_inventory.at[idx, 'externalQuantity'] = external_qty - qte_a_produire
                elif stopa_qty > 0 and stopa_qty >= qte_a_produire:
                    result['clasificacion'] = 'A'
                    result['razon'] = f'Stock interno suficiente'
                    df_inventory.at[idx, 'stopaQuantity'] = stopa_qty - qte_a_produire
                elif stopa_qty == 0 and external_qty >= qte_a_produire:
                    result['clasificacion'] = 'C'
                    result['razon'] = f'Stock externo suficiente'
                    df_inventory.at[idx, 'externalQuantity'] = external_qty - qte_a_produire
                else:
                    result['clasificacion'] = 'BO' 
                    result['razon'] = f'Stock insuficiente'
            else:
                self.log(f"Item {part_number} no encontrado en inventario.", "warning")

            # Calcular déficit para automático (A) si no es A
            if result['clasificacion'] in ['C', 'BO', None] and result['encontrado_en_inventario']:
                # Cuántos faltan en Stock Interno para cubrir la demanda
                # Si tengo 0 y necesito 4, balance es -4.
                balance = result['stopa_quantity'] - result['qte_a_produire']
                if balance < 0:
                     result['deficit_internal'] = balance

        except Exception as e:
            self.log(f"Error analizando item {part_number}: {str(e)}", "error")
            
        return result

    def run_full_analysis(self, punch_data, laser_data, inventory_data=None, metadata=None):
        """
        Ejecuta el flujo completo de análisis.
        Si inventory_data es None, intenta usar el existente.
        :param metadata: Diccionario con info extra (project, model, module)
        """
        results = []
        
        # Inicializar inventario solo si se provee nuevo, sino usa el existente
        if inventory_data:
             self.initialize_inventory(inventory_data)
        
        if self.df_inventory_working is None:
            self.log("No hay inventario cargado. Imposible analizar.", "error")
            return results

        # 1. Punch
        punch_items = self.extract_pdf_items(punch_data, "Punch")
        for item in punch_items:
            res = self.analyze_item(item, self.df_inventory_working, "Punch")
            results.append(res)
            
        # 2. Laser
        laser_items = self.extract_pdf_items(laser_data, "Laser")
        for item in laser_items:
            res = self.analyze_item(item, self.df_inventory_working, "Laser")
            results.append(res)
            
        self.last_results = results
        
        # Agregar al historial
        stats = self.get_summary_stats()
        history_entry = {
            "id": len(self.history) + 1,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "stats": stats,
            "punch_file": punch_data['file_path'] if punch_data else "N/A",
            "laser_file": laser_data['file_path'] if laser_data else "N/A",
            "metadata": metadata or {}
        }
        self.history.append(history_entry)
        
        return results

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
