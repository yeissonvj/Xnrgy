import tkinter as tk
from tkinter import filedialog, ttk
import pandas as pd
from pathlib import Path
from stock_analyzer import StockAnalyzer

class FileReaderInterface:
    def __init__(self, root):
        self.root = root
        self.root.title("Lector de Archivos - Punch, Laser e Inventario")
        self.root.geometry("700x1000")
        self.root.configure(bg="#f0f0f0")
        
        # Instanciar el analizador
        self.analyzer = StockAnalyzer(log_callback=self.log_message_adapter)
        
        # Variables para almacenar rutas (solo para UI)
        self.punch_pdf_path = None
        self.laser_pdf_path = None
        self.inventory_excel_path = None
        
        self.create_widgets()
    
    def log_message_adapter(self, message, msg_type="info"):
        """Adaptador para que StockAnalyzer use el sistema de logs de la GUI"""
        self.log_message(message, msg_type)

    def create_widgets(self):
        # Título principal
        title_label = tk.Label(
            self.root,
            text="Sistema de Carga de Archivos",
            font=("Arial", 18, "bold"),
            bg="#f0f0f0",
            fg="#333333"
        )
        title_label.pack(pady=20)
        
        # Canvas con scrollbar para hacer scrollable toda la interfaz
        canvas_container = tk.Frame(self.root, bg="#f0f0f0")
        canvas_container.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Scrollbar vertical
        main_scrollbar = tk.Scrollbar(canvas_container, orient="vertical")
        main_scrollbar.pack(side="right", fill="y")
        
        # Canvas
        self.main_canvas = tk.Canvas(
            canvas_container,
            bg="#f0f0f0",
            yscrollcommand=main_scrollbar.set,
            highlightthickness=0
        )
        self.main_canvas.pack(side="left", fill="both", expand=True)
        main_scrollbar.config(command=self.main_canvas.yview)
        
        # Frame principal dentro del canvas
        main_frame = tk.Frame(self.main_canvas, bg="#f0f0f0")
        canvas_window = self.main_canvas.create_window((0, 0), window=main_frame, anchor="nw")
        
        # Actualizar scroll region cuando cambie el tamaño
        def configure_scroll_region(event=None):
            self.main_canvas.configure(scrollregion=self.main_canvas.bbox("all"))
        
        main_frame.bind("<Configure>", configure_scroll_region)
        
        # Ajustar el ancho del frame al canvas
        def configure_canvas_width(event):
            canvas_width = event.width
            self.main_canvas.itemconfig(canvas_window, width=canvas_width)
        
        self.main_canvas.bind("<Configure>", configure_canvas_width)
        
        # Habilitar scroll con rueda del mouse
        def on_mousewheel(event):
            self.main_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        self.main_canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # ========== ENTRADA 1: PDF PUNCH ==========
        self.create_file_input(
            main_frame,
            row=0,
            label_text="1. PDF para Punch:",
            browse_command=self.load_punch_pdf,
            entry_var_name="punch_entry",
            browse_btn_name="punch_browse_btn",
            status_label_name="punch_status_label",
            enabled=True
        )
        
        # ========== ENTRADA 2: PDF LASER ==========
        self.create_file_input(
            main_frame,
            row=1,
            label_text="2. PDF para Laser:",
            browse_command=self.load_laser_pdf,
            entry_var_name="laser_entry",
            browse_btn_name="laser_browse_btn",
            status_label_name="laser_status_label",
            enabled=False
        )
        
        # ========== ENTRADA 3: EXCEL INVENTARIO ==========
        self.create_file_input(
            main_frame,
            row=2,
            label_text="3. Excel para Inventario:",
            browse_command=self.load_inventory_excel,
            entry_var_name="inventory_entry",
            browse_btn_name="inventory_browse_btn",
            status_label_name="inventory_status_label",
            enabled=False
        )
        
        # ========== BOTÓN DE ANÁLISIS ==========
        analysis_frame = tk.Frame(main_frame, bg="#f0f0f0")
        analysis_frame.grid(row=3, column=0, pady=20, sticky="ew")
        
        self.analysis_btn = tk.Button(
            analysis_frame,
            text="Ejecutar Análisis",
            command=self.run_analysis,
            font=("Arial", 12, "bold"),
            bg="#2196F3",
            fg="white",
            cursor="hand2",
            padx=20,
            pady=10
        )
        self.analysis_btn.pack(side="left", padx=10)
        
        # Botón Exportar (inicialmente deshabilitado)
        self.export_btn = tk.Button(
            analysis_frame,
            text="Exportar a Excel",
            command=self.export_results,
            font=("Arial", 12, "bold"),
            bg="#808080",  # Gris (deshabilitado)
            fg="white",
            cursor="arrow",
            state="disabled",
            padx=20,
            pady=10
        )
        self.export_btn.pack(side="left", padx=10)
        
        # ========== LOG DE PROCESOS ==========
        log_frame = tk.Frame(main_frame, bg="#f0f0f0")
        log_frame.grid(row=4, column=0, pady=(10, 0), sticky="nsew")
        main_frame.grid_rowconfigure(4, weight=1)
        
        # Label para el log
        log_label = tk.Label(
            log_frame,
            text="Registro de Procesos:",
            font=("Arial", 11, "bold"),
            bg="#f0f0f0",
            fg="#333333",
            anchor="w"
        )
        log_label.pack(anchor="w", pady=(0, 5))
        
        # Frame para listbox y scrollbar
        listbox_frame = tk.Frame(log_frame, bg="#f0f0f0")
        listbox_frame.pack(fill="both", expand=True)
        
        # Scrollbar vertical
        scrollbar_y = tk.Scrollbar(listbox_frame, orient="vertical")
        scrollbar_y.pack(side="right", fill="y")
        
        # Scrollbar horizontal
        scrollbar_x = tk.Scrollbar(listbox_frame, orient="horizontal")
        scrollbar_x.pack(side="bottom", fill="x")
        
        # Listbox para mostrar los logs
        self.log_listbox = tk.Listbox(
            listbox_frame,
            font=("Consolas", 9),
            bg="#ffffff",
            fg="#333333",
            selectbackground="#e3f2fd",
            yscrollcommand=scrollbar_y.set,
            xscrollcommand=scrollbar_x.set,
            height=8
        )
        self.log_listbox.pack(side="left", fill="both", expand=True)
        
        scrollbar_y.config(command=self.log_listbox.yview)
        scrollbar_x.config(command=self.log_listbox.xview)
        
        # ========== TABLA RESULTADOS PUNCH ==========
        punch_results_frame = tk.Frame(main_frame, bg="#f0f0f0")
        punch_results_frame.grid(row=5, column=0, pady=(15, 0), sticky="nsew")
        main_frame.grid_rowconfigure(5, weight=1)
        
        punch_label = tk.Label(
            punch_results_frame,
            text="Resultados PDF Punch:",
            font=("Arial", 11, "bold"),
            bg="#f0f0f0",
            fg="#333333",
            anchor="w"
        )
        punch_label.pack(anchor="w", pady=(0, 5))
        
        punch_listbox_frame = tk.Frame(punch_results_frame, bg="#f0f0f0")
        punch_listbox_frame.pack(fill="both", expand=True)
        
        punch_scrollbar_y = tk.Scrollbar(punch_listbox_frame, orient="vertical")
        punch_scrollbar_y.pack(side="right", fill="y")
        
        punch_scrollbar_x = tk.Scrollbar(punch_listbox_frame, orient="horizontal")
        punch_scrollbar_x.pack(side="bottom", fill="x")
        
        self.punch_results_listbox = tk.Listbox(
            punch_listbox_frame,
            font=("Consolas", 9),
            bg="#ffffff",
            fg="#333333",
            selectbackground="#e3f2fd",
            yscrollcommand=punch_scrollbar_y.set,
            xscrollcommand=punch_scrollbar_x.set,
            height=6
        )
        self.punch_results_listbox.pack(side="left", fill="both", expand=True)
        
        punch_scrollbar_y.config(command=self.punch_results_listbox.yview)
        punch_scrollbar_x.config(command=self.punch_results_listbox.xview)
        
        # ========== TABLA RESULTADOS LASER ==========
        laser_results_frame = tk.Frame(main_frame, bg="#f0f0f0")
        laser_results_frame.grid(row=6, column=0, pady=(15, 0), sticky="nsew")
        main_frame.grid_rowconfigure(6, weight=1)
        
        laser_label = tk.Label(
            laser_results_frame,
            text="Resultados PDF Laser:",
            font=("Arial", 11, "bold"),
            bg="#f0f0f0",
            fg="#333333",
            anchor="w"
        )
        laser_label.pack(anchor="w", pady=(0, 5))
        
        laser_listbox_frame = tk.Frame(laser_results_frame, bg="#f0f0f0")
        laser_listbox_frame.pack(fill="both", expand=True)
        
        laser_scrollbar_y = tk.Scrollbar(laser_listbox_frame, orient="vertical")
        laser_scrollbar_y.pack(side="right", fill="y")
        
        laser_scrollbar_x = tk.Scrollbar(laser_listbox_frame, orient="horizontal")
        laser_scrollbar_x.pack(side="bottom", fill="x")
        
        self.laser_results_listbox = tk.Listbox(
            laser_listbox_frame,
            font=("Consolas", 9),
            bg="#ffffff",
            fg="#333333",
            selectbackground="#e3f2fd",
            yscrollcommand=laser_scrollbar_y.set,
            xscrollcommand=laser_scrollbar_x.set,
            height=6
        )
        self.laser_results_listbox.pack(side="left", fill="both", expand=True)
        
        laser_scrollbar_y.config(command=self.laser_results_listbox.yview)
        laser_scrollbar_x.config(command=self.laser_results_listbox.xview)
    
    def create_file_input(self, parent, row, label_text, browse_command, 
                          entry_var_name, browse_btn_name, status_label_name, enabled):
        """Crea un conjunto de widgets para entrada de archivo"""
        
        # Frame para esta entrada
        frame = tk.Frame(parent, bg="#f0f0f0")
        frame.grid(row=row, column=0, pady=15, sticky="ew")
        parent.grid_columnconfigure(0, weight=1)
        
        # Label
        label = tk.Label(
            frame,
            text=label_text,
            font=("Arial", 12, "bold"),
            bg="#f0f0f0",
            fg="#333333",
            anchor="w"
        )
        label.pack(anchor="w", pady=(0, 5))
        
        # Frame para entrada y botón
        input_frame = tk.Frame(frame, bg="#f0f0f0")
        input_frame.pack(fill="x")
        
        # Entry para mostrar la ruta del archivo
        entry = tk.Entry(
            input_frame,
            font=("Arial", 10),
            state="readonly",
            readonlybackground="#ffffff" if enabled else "#e0e0e0"
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        setattr(self, entry_var_name, entry)
        
        # Botón de explorar
        browse_btn = tk.Button(
            input_frame,
            text="Explorar",
            command=browse_command,
            font=("Arial", 10),
            bg="#4CAF50" if enabled else "#cccccc",
            fg="white",
            cursor="hand2" if enabled else "arrow",
            state="normal" if enabled else "disabled",
            padx=20,
            pady=5
        )
        browse_btn.pack(side="right")
        setattr(self, browse_btn_name, browse_btn)
        
        # Label de estado (inicialmente vacío)
        status_label = tk.Label(
            frame,
            text="",
            font=("Arial", 10),
            bg="#f0f0f0",
            fg="#4CAF50"
        )
        status_label.pack(anchor="w", pady=(5, 0))
        setattr(self, status_label_name, status_label)
        
        # Listbox de preview de datos
        preview_label = tk.Label(
            frame,
            text="Vista previa de datos:",
            font=("Arial", 9, "bold"),
            bg="#f0f0f0",
            fg="#666666",
            anchor="w"
        )
        preview_label.pack(anchor="w", pady=(10, 2))
        
        preview_frame = tk.Frame(frame, bg="#f0f0f0")
        preview_frame.pack(fill="both", expand=True)
        
        preview_scrollbar = tk.Scrollbar(preview_frame, orient="vertical")
        preview_scrollbar.pack(side="right", fill="y")
        
        preview_listbox = tk.Listbox(
            preview_frame,
            font=("Consolas", 8),
            bg="#f9f9f9",
            fg="#333333",
            selectbackground="#e3f2fd",
            yscrollcommand=preview_scrollbar.set,
            height=4
        )
        preview_listbox.pack(side="left", fill="both", expand=True)
        preview_scrollbar.config(command=preview_listbox.yview)
        
        # Guardar referencia al preview listbox
        preview_name = entry_var_name.replace("_entry", "_preview")
        setattr(self, preview_name, preview_listbox)
    
    def load_punch_pdf(self):
        """Carga el PDF de Punch"""
        file_path = filedialog.askopenfilename(
            title="Seleccionar PDF para Punch",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        
        if file_path:
            # Usar Analyzer
            self.analyzer.punch_data = self.analyzer.load_pdf_data(file_path, "Punch")
            
            if self.analyzer.punch_data:
                # Update UI
                self.punch_pdf_path = file_path
                self.punch_entry.configure(state="normal")
                self.punch_entry.delete(0, tk.END)
                self.punch_entry.insert(0, Path(file_path).name)
                self.punch_entry.configure(state="readonly")
                
                rows = len(self.analyzer.punch_data['dataframe'])
                self.punch_status_label.config(
                    text=f"✓ Carga exitosa ({rows} filas)",
                    fg="#4CAF50"
                )
                
                self.show_pdf_preview(self.analyzer.punch_data, self.punch_preview)
                self.enable_laser_input()
            else:
                 self.punch_status_label.config(text="✗ Error al leer archivo", fg="#f44336")

    def load_laser_pdf(self):
        """Carga el PDF de Laser"""
        file_path = filedialog.askopenfilename(
            title="Seleccionar PDF para Laser",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        
        if file_path:
            # Usar Analyzer
            self.analyzer.laser_data = self.analyzer.load_pdf_data(file_path, "Laser")
            
            if self.analyzer.laser_data:
                # Update UI
                self.laser_pdf_path = file_path
                self.laser_entry.configure(state="normal")
                self.laser_entry.delete(0, tk.END)
                self.laser_entry.insert(0, Path(file_path).name)
                self.laser_entry.configure(state="readonly")
                
                rows = len(self.analyzer.laser_data['dataframe'])
                self.laser_status_label.config(
                    text=f"✓ Carga exitosa ({rows} filas)",
                    fg="#4CAF50"
                )
                
                self.show_pdf_preview(self.analyzer.laser_data, self.laser_preview)
                self.enable_inventory_input()
            else:
                 self.laser_status_label.config(text="✗ Error al leer archivo", fg="#f44336")

    def load_inventory_excel(self):
        """Carga el Excel de Inventario"""
        file_path = filedialog.askopenfilename(
            title="Seleccionar Excel para Inventario",
            filetypes=[("Excel files", "*.xlsx *.xls"), ("All files", "*.*")]
        )
        
        if file_path:
            # Usar Analyzer
            self.analyzer.inventory_data = self.analyzer.load_inventory_excel(file_path)
            
            if self.analyzer.inventory_data:
                self.inventory_excel_path = file_path
                self.inventory_entry.configure(state="normal")
                self.inventory_entry.delete(0, tk.END)
                self.inventory_entry.insert(0, Path(file_path).name)
                self.inventory_entry.configure(state="readonly")
                
                rows = self.analyzer.inventory_data['rows']
                self.inventory_status_label.config(
                    text=f"✓ Carga exitosa ({rows} filas)",
                    fg="#4CAF50"
                )
                
                self.show_excel_preview(self.analyzer.inventory_data, self.inventory_preview)
            else:
                self.inventory_status_label.config(text="✗ Error al leer archivo", fg="#f44336")
    
    def show_pdf_preview(self, pdf_data, preview_listbox):
        """Muestra preview de datos extraídos del PDF"""
        preview_listbox.delete(0, tk.END)
        try:
            df = pdf_data['dataframe']
            headers = pdf_data['headers']
            preview_listbox.insert(tk.END, f"Columnas: {list(df.columns)}")
            
            # Simple preview de las primeras 5 filas
            for idx, row in df.head(5).iterrows():
                preview_listbox.insert(tk.END, str(row.values))
        except Exception as e:
            preview_listbox.insert(tk.END, f"Error preview: {e}")
    
    def show_excel_preview(self, excel_data, preview_listbox):
        """Muestra preview de datos del Excel"""
        preview_listbox.delete(0, tk.END)
        try:
            df = excel_data['dataframe']
            preview_listbox.insert(tk.END, f"Columnas: {list(df.columns)}")
            for idx, row in df.head(5).iterrows():
                preview_listbox.insert(tk.END, str(row.values))
        except Exception as e:
            preview_listbox.insert(tk.END, f"Error preview: {e}")
    
    def log_message(self, message, msg_type="info"):
        """Agrega un mensaje al log con timestamp"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if msg_type == "error":
            prefix = "❌ ERROR"
        elif msg_type == "success":
            prefix = "✓ ÉXITO"
        elif msg_type == "warning":
            prefix = "⚠ ADVERTENCIA"
        elif msg_type == "process":
            prefix = "⚙ PROCESO"
        else:
            prefix = "ℹ INFO"
        
        log_entry = f"[{timestamp}] {prefix}: {message}"
        self.log_listbox.insert(tk.END, log_entry)
        self.log_listbox.see(tk.END)
        self.root.update_idletasks()
    
    def run_analysis(self):
        """Ejecuta el análisis de programación"""
        self.log_listbox.delete(0, tk.END)
        self.log_message("Iniciando análisis...", "process")
        
        if not self.analyzer.punch_data or not self.analyzer.laser_data or not self.analyzer.inventory_data:
            self.log_message("Faltan archivos por cargar.", "error")
            return

        # EJECUTAR ANÁLISIS EN EL ANALYZER
        results = self.analyzer.run_full_analysis(
            self.analyzer.punch_data,
            self.analyzer.laser_data,
            self.analyzer.inventory_data
        )
        
        # Display Stats
        stats = self.analyzer.get_summary_stats()
        self.log_message(f"Total: {stats.get('total')}, A: {stats.get('count_a')}, C: {stats.get('count_c')}", "success")
        
        # Habilitar export
        if results:
            self.export_btn.config(state="normal", bg="#4CAF50", cursor="hand2")
        
        # Mostrar tablas
        punch_results = [r for r in results if r['origen'] == 'Punch']
        laser_results = [r for r in results if r['origen'] == 'Laser']
        
        self.punch_results_listbox.delete(0, tk.END)
        self.display_results_table(punch_results, self.punch_results_listbox)
        
        self.laser_results_listbox.delete(0, tk.END)
        self.display_results_table(laser_results, self.laser_results_listbox)

    def display_results_table(self, results, listbox):
        """Muestra los resultados en formato de tabla en el listbox dado"""
        if not results:
            listbox.insert(tk.END, "No resultados.")
            return

        headers = ["Part #", "Qte", "StkInt", "StkExt", "Clasif"]
        # Formato simple para UI
        listbox.insert(tk.END, " | ".join(headers))
        listbox.insert(tk.END, "-" * 50)
        
        for r in results:
            line = f"{r['part_number']} | {r['qte_a_produire']} | {int(r['stopa_quantity'])} | {int(r['external_quantity'])} | {r['clasificacion']}"
            listbox.insert(tk.END, line)

    def export_results(self):
        """Exporta los resultados a un archivo Excel"""
        if not self.analyzer.last_results:
            return
            
        file_path = filedialog.asksaveasfilename(
            title="Guardar resultados en Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialfile="Resultados_Analisis.xlsx"
        )
        
        if file_path:
            try:
                # Reconstruir dataframe para exportar (lógica similar a la original pero simplificada)
                export_data = []
                for res in self.analyzer.last_results:
                    row = res.get('full_row', {}).copy()
                    row.update({
                        'Origen': res.get('origen'),
                        'Part #': res.get('part_number'),
                        'Qté à Produire': res.get('qte_a_produire'),
                        'Stock Interno': res.get('stopa_quantity'),
                        'Stock Externo': res.get('external_quantity'),
                        'Análisis': res.get('clasificacion'),
                        'Razón': res.get('razon')
                    })
                    export_data.append(row)
                
                df_export = pd.DataFrame(export_data)
                
                # Columnas prioritarias
                cols = df_export.columns.tolist()
                key_cols = ['Origen', 'Part #', 'Qté à Produire', 'Análisis', 'Razón', 'Stock Interno', 'Stock Externo']
                key_cols = [c for c in key_cols if c in cols]
                other_cols = [c for c in cols if c not in key_cols]
                df_export = df_export[key_cols + other_cols]
                
                df_export.to_excel(file_path, index=False)
                self.log_message(f"Exportado a {file_path}", "success")
            except Exception as e:
                self.log_message(f"Error exportando: {e}", "error")

    def enable_laser_input(self):
        self.laser_browse_btn.config(state="normal", bg="#4CAF50", cursor="hand2")
        self.laser_entry.configure(readonlybackground="#ffffff")
    
    def enable_inventory_input(self):
        self.inventory_browse_btn.config(state="normal", bg="#4CAF50", cursor="hand2")
        self.inventory_entry.configure(readonlybackground="#ffffff")

def main():
    root = tk.Tk()
    app = FileReaderInterface(root)
    root.mainloop()

if __name__ == "__main__":
    main()
