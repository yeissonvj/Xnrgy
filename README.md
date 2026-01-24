# Xnergy Stock Analysis System

Sistema de análisis de inventario y programación de producción para XNRGY. Permite verificar la disponibilidad de materiales (Punch y Laser) contra el inventario existente, clasificando automáticamente los requerimientos.

## 🚀 Características

- **Análisis Automático**: Procesa archivos PDF (Punch/Laser) y Excel (Inventario) para determinar disponibilidad.
- **Clasificación Inteligente**:
  - **A (Automático)**: Stock interno suficiente.
  - **C (Externo)**: Stock externo suficiente (Interno 0).
  - **M (Manual)**: Stock mixto o reglas especiales (Part # específicos).
  - **BO (BackOrder)**: Stock insuficiente.
- **Persistencia de Stock**: Permite ejecuciones secuenciales descontando stock en memoria.
- **Cálculo de Déficit**: Muestra cuánto falta en stock interno para lograr clasificación automática.
- **Historial de Sesión**: Visualización de ejecuciones previas con metadatos del proyecto.
- **Doble Interfaz**:
  - **Web**: Interfaz moderna basada en Flask (lista para Vercel).
  - **Escritorio**: Interfaz clásica Tkinter (legacy support).

## 🛠 Arquitectura y Tecnologías

El proyecto sigue una arquitectura modular donde la lógica de negocio está desacoplada de la interfaz de usuario.

### Estructura
- **`stock_analyzer.py` (Core)**: Contiene toda la lógica de extracción de PDFs, reglas de negocio, gestión de inventario en memoria y cálculo de estadísticas. Es agnóstico a la interfaz.
- **`app.py` (Web Backend)**: Servidor Flask que gestiona sesiones de usuario, subida de archivos y sirve las plantillas HTML.
- **`file_reader_interface.py` (Desktop Frontend)**: Aplicación GUI legacy usando Tkinter, refactorizada para consumir `stock_analyzer.py`.

### Tecnologías Clave
- **Lenguaje**: Python 3.10+
- **Web Framework**: Flask
- **Procesamiento de Datos**: 
  - `pandas`: Manipulación de DataFrames y Excel.
  - `pdfplumber`: Extracción precisa de tablas en PDFs.
- **Frontend Web**: HTML5, CSS3 (Variables, Flexbox/Grid), JavaScript Vanilla.
- **Despliegue**: Configurado para Vercel (Serverless).

## 📦 Instalación y Uso

### Prerrequisitos
- Python 3.x
- pip

### 1. Clonar el repositorio
```bash
git clone https://github.com/yeissonvj/Xnrgy.git
cd Xnrgy
```

### 2. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3. Configurar Entorno
Crear un archivo `.env` en la raíz (ver `.env.example` si existiera, o usar credenciales por defecto):
```
FLASK_USER=usuario
FLASK_PASSWORD=contraseña
FLASK_SECRET_KEY=clave_secreta
```

### 4. Ejecutar Aplicación Web
```bash
python app.py
```
Acceder a `http://localhost:5000`.

### 5. Ejecutar Aplicación de Escritorio
```bash
python file_reader_interface.py
```

## ☁ Despliegue en Vercel

El proyecto incluye `vercel.json` para despliegue inmediato.
1. Instalar Vercel CLI: `npm i -g vercel`
2. Ejecutar `vercel` en la raíz.
3. Configurar variables de entorno en el dashboard de Vercel.

---
Desarrollado para XNRGY.
