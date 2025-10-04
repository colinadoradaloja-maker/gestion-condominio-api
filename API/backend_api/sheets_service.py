# backend_api/sheets_service.py
import gspread
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

# --- CONFIGURACIÓN DE CONEXIÓN SEGURA ---
CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_NAME = "gestion_condominio"

class SheetsService:
    
    def __init__(self):
        """Inicializa la conexión a Google Sheets usando credenciales de servicio."""
        if not CREDENTIALS_JSON:
            # En entorno de desarrollo local, carga el archivo 'colinadorada.json'
            cred_path = os.path.join(os.path.dirname(__file__), 'colinadorada.json')
            try:
                with open(cred_path, 'r') as f:
                    credentials_data = json.load(f)
                print(f"[INFO] Credenciales cargadas desde archivo local: {cred_path}")
            except FileNotFoundError:
                print(f"[ERROR] No se encontró el archivo de credenciales en: {cred_path}")
                raise ConnectionError(f"ERROR: Falta la variable GSPREAD_CREDENTIALS y el archivo local en {cred_path}.")
        else:
            credentials_data = json.loads(CREDENTIALS_JSON)
        
        # Conexión al cliente y a la hoja de cálculo
        self.gc = gspread.service_account_from_dict(credentials_data)
        try:
            self.sh = self.gc.open(SPREADSHEET_NAME)
        except gspread.exceptions.SpreadsheetNotFound:
            print(f"[ERROR] Hoja de cálculo '{SPREADSHEET_NAME}' no encontrada.")
            self.sh = None

    def get_sheet(self, sheet_title: str) -> gspread.Worksheet:
        """Obtiene una hoja por su título."""
        if not self.sh:
            raise ConnectionError("No se pudo conectar a la hoja de cálculo.")
        return self.sh.worksheet(sheet_title)

    def get_all_records(self, sheet_title: str) -> List[Dict[str, Any]]:
        """Obtiene todos los datos de una hoja como lista de diccionarios."""
        sheet = self.get_sheet(sheet_title)
        return sheet.get_all_records()

    def get_records_by_casa_id(self, sheet_title: str, id_casa: int) -> List[Dict[str, Any]]:
        """
        Obtiene todos los registros de una hoja filtrados por ID_CASA.
        """
        sheet = self.get_sheet(sheet_title)
        data = sheet.get_all_values()
        if not data:
            return []
            
        header = data[0]
        records = data[1:]
        
        try:
            casa_id_index = header.index('ID_CASA')
        except ValueError:
            raise ValueError(f"La hoja '{sheet_title}' no tiene la columna 'ID_CASA'.")
        
        filtered_list = []
        target_id_str = str(id_casa)
        
        for row in records:
            if len(row) > casa_id_index and str(row[casa_id_index]).strip() == target_id_str:
                record = dict(zip(header, row))
                filtered_list.append(record)
                
        return filtered_list

    # --- FUNCIÓN PARA LECTURA DE USUARIO ---
    def get_user_by_id_casa(self, id_casa: int) -> Optional[Dict[str, Any]]:
        """Busca y retorna el registro de usuario (incluyendo NOMBRE) para una casa."""
        try:
            # Usamos el mapa para una búsqueda más rápida si fuera necesario, 
            # pero mantenemos esta implementación simple para el estado de cuenta individual.
            usuarios_data = self.get_all_records('USUARIOS')
            for user in usuarios_data:
                # Usamos str() para asegurar la comparación correcta de tipos
                if user.get('ID_CASA') and str(user['ID_CASA']) == str(id_casa):
                    return user
            return None
        except Exception as e:
            print(f"[ERROR SHEETS] Error al obtener usuario por ID_CASA {id_casa}: {e}")
            return None

    # --- FUNCIÓN NUEVA: OBTENER MAPA DE USUARIOS (Para el Admin Panel) ---
    def get_all_users_map(self) -> Dict[str, Dict[str, Any]]:
        """
        Obtiene todos los usuarios y los mapea por ID_CASA para una búsqueda rápida,
        incluyendo Nombre, Email y Celular.
        """
        try:
            users_data = self.get_all_records('USUARIOS')
        except Exception:
            return {}
            
        user_map = {}
        for user in users_data:
            casa_id = str(user.get('ID_CASA'))
            if casa_id:
                user_map[casa_id] = {
                    'NOMBRE': user.get('NOMBRE', 'N/A'),
                    'EMAIL': user.get('EMAIL', 'N/A'),
                    'CELULAR': user.get('CELULAR', 'N/A')
                }
        return user_map

    # 🚨 FUNCIÓN CORREGIDA: get_all_casa_ids (Ahora dentro de la clase) 🚨
    def get_all_casa_ids(self) -> List[int]:
        """Obtiene una lista de todos los ID_CASA activos de la hoja USUARIOS."""
        
        try:
            records = self.get_all_records('USUARIOS')
            
            casa_ids = []
            for record in records:
                casa_id_str = str(record.get('ID_CASA', '')).strip()
                
                # Asumiendo un filtro de 'ESTADO' como "ACTIVO" si existe
                estado = str(record.get('ESTADO', 'ACTIVO')).upper().strip() 

                if casa_id_str and estado == 'ACTIVO':
                    try:
                        # Usamos float() primero para manejar valores como "17.0"
                        casa_id = int(float(casa_id_str)) 
                        if casa_id not in casa_ids:
                            casa_ids.append(casa_id)
                    except ValueError:
                        # Ignorar si no se puede convertir a número (ej. "Casa X")
                        continue
                        
            return sorted(casa_ids)
            
        except Exception as e:
            print(f"[ERROR SHEETS_SERVICE] Fallo al obtener todos los ID de casa: {e}")
            return []

    # MÉTODO DE ESCRITURA: Genera el ID en formato Mxxxx
    def generate_next_movement_id(self) -> str:
        """Genera el siguiente ID de movimiento (M0001, M0002, etc.)."""
        movimientos_sheet = self.get_sheet('MOVIMIENTOS')
        all_ids = movimientos_sheet.col_values(1)[1:] 
        
        if not all_ids:
            return "M0001"
        
        valid_ids = [uid for uid in all_ids if uid and uid.startswith('M') and uid[1:].isdigit()]
        
        last_number = 0
        if valid_ids:
            last_number = max([int(uid[1:]) for uid in valid_ids])
            
        next_number = last_number + 1
        return f"M{next_number:04d}"

    # MÉTODO DE ESCRITURA: Añade una fila
    def append_movement(self, data: List[Any]):
        """Añade una nueva fila al final de la hoja MOVIMIENTOS."""
        movimientos_sheet = self.get_sheet('MOVIMIENTOS')
        movimientos_sheet.append_row(data, value_input_option='USER_ENTERED')
        
    # ----------------------------------------------------------------------
    # --- MÉTODO ACTUALIZADO: ESCRITURA DE SEMÁFORO (6 COLUMNAS) ---
    # ----------------------------------------------------------------------
    def update_or_append_semaforo(self, id_casa: int, dias_atraso: int, saldo: float, estado: str, cuotas_pendientes: int) -> bool:
        """
        Busca ID_CASA en ALERTAS_SEMAFORO. Si existe, actualiza (6 columnas A:F); si no, añade.
        Orden: ID_CASA, DIAS_ATRASO, SALDO_PENDIENTE, ESTADO_SEMAFORO, FECHA_ACTUALIZACION, CUOTAS_PENDIENTES.
        """
        sheet = self.get_sheet('ALERTAS_SEMAFORO')
        data = sheet.get_all_values()
        
        records = data[1:] if len(data) > 1 else []
        
        target_id_str = str(id_casa)
        row_index_to_update = -1 # Índice base 1 (2 para la primera fila de datos)
        
        # 1. Buscar fila existente (asumiendo ID_CASA en la Columna A)
        for i, row in enumerate(records):
            if row and row[0].strip() == target_id_str: 
                row_index_to_update = i + 2
                break

        current_time = datetime.now().strftime('%Y-%m-%d %H:%M')
        # 2. Preparar nueva data (6 columnas)
        new_data = [
            target_id_str, # 1. ID_CASA
            str(dias_atraso), # 2. DIAS_ATRASO
            f"{saldo:.2f}", # 3. SALDO_PENDIENTE (Formato de moneda)
            estado, # 4. ESTADO_SEMAFORO
            current_time, # 5. FECHA_ACTUALIZACION
            str(cuotas_pendientes) # 6. CUOTAS_PENDIENTES (Columna F)
        ]
        
        try:
            # Rango de actualización ahora es A:F (6 columnas)
            if row_index_to_update != -1:
                # 3. Actualizar fila existente
                range_to_update = f"A{row_index_to_update}:F{row_index_to_update}"
                sheet.update(range_to_update, [new_data], value_input_option='USER_ENTERED')
            else:
                # 4. Añadir nueva fila
                sheet.append_row(new_data, value_input_option='USER_ENTERED')
            return True
        except Exception as e:
            print(f"Error al actualizar/añadir semáforo para casa {id_casa}: {e}")
            return False

    # ----------------------------------------------------------------------
    # --- MÉTODO NUEVO/ACTUALIZADO: LECTURA DE SEMÁFORO (6 COLUMNAS) ---
    # ----------------------------------------------------------------------
    def get_semaforo_by_casa(self, id_casa: int) -> Optional[Dict[str, Any]]:
        """
        Busca y retorna el estado del semáforo consolidado para una casa específica.
        Retorna un diccionario con los 6 campos.
        """
        sheet_name = 'ALERTAS_SEMAFORO'
        try:
            sheet = self.get_sheet(sheet_name)
            data = sheet.get_all_values()
            
            # Orden de las columnas: A: ID_CASA, B: DIAS_ATRASO, C: SALDO_PENDIENTE, D: ESTADO_SEMAFORO, E: FECHA_ACTUALIZACION, F: CUOTAS_PENDIENTES
            
            for row in data[1:]: # Ignora la fila de headers
                if not row or str(row[0]) != str(id_casa):
                    continue
                
                # Mapeo de las 6 columnas de datos
                if len(row) >= 6:
                    return {
                        "ID_CASA": row[0],
                        "DIAS_ATRASO": int(row[1]) if row[1] and row[1].isdigit() else 0,
                        "SALDO_PENDIENTE": float(row[2]) if row[2] else 0.0,
                        "ESTADO_SEMAFORO": row[3],
                        "FECHA_ACTUALIZACION": row[4],
                        "CUOTAS_PENDIENTES": int(row[5]) if row[5] and row[5].isdigit() else 0 # <-- NUEVO CAMPO LEÍDO (Índice 5/Columna F)
                    }
                else:
                    # Caso de registros antiguos con menos columnas
                    return {
                        "ID_CASA": row[0],
                        "DIAS_ATRASO": int(row[1]) if row[1] and row[1].isdigit() else 0,
                        "SALDO_PENDIENTE": float(row[2]) if row[2] else 0.0,
                        "ESTADO_SEMAFORO": row[3],
                        "FECHA_ACTUALIZACION": row[4],
                        "CUOTAS_PENDIENTES": 0 # Valor por defecto si la columna F no existe
                    }
            
            return None # Casa no encontrada
            
        except Exception as e:
            print(f"[ERROR SHEETS] Error al obtener el semáforo para la Casa {id_casa} de {sheet_name}: {e}")
            return None

# Instancia global para usar en FastAPI
try:
    # Usamos None si el objeto sh no se pudo crear en __init__
    sheets_service = SheetsService()
    if sheets_service.sh is None:
        sheets_service = None
except ConnectionError as e:
    print(f"ERROR DE CONEXIÓN GLOBAL: {e}")
    sheets_service = None