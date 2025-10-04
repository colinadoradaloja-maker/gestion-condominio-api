# Gestión Condominio

Este proyecto incluye un backend con FastAPI y un frontend con Streamlit para la gestión de condominios usando Google Sheets como base de datos.

## Estructura
- **backend_api/**: API REST con FastAPI, autenticación JWT y conexión a Google Sheets.
- **frontend_app/**: Interfaz de usuario con Streamlit.

## Ejecución

### Backend
```bash
cd gestion-condominio/backend_api
python -m venv ../.venv
source ../.venv/bin/activate  # En Windows: ../.venv/Scripts/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

### Frontend
```bash
cd gestion-condominio/frontend_app
pip install -r requirements.txt
streamlit run app.py
```

## Credenciales
Coloca tu archivo `credentials.json` en la carpeta `backend_api/` para la conexión con Google Sheets.
