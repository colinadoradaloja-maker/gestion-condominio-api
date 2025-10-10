import gspread
import json
import os
import base64
from typing import List, Dict, Any, Optional
from datetime import datetime
import pytz 

# Importar las excepciones de gspread para un manejo de errores más claro
from gspread.exceptions import WorksheetNotFound, SpreadsheetNotFound 

# Definición de la zona horaria local (Guayaquil, Ecuador)
LOCAL_TIMEZONE = pytz.timezone('America/Guayaquil') 

# --- Definición de Errores ---
class ConnectionError(Exception):
    """Excepción para errores de conexión a Google Sheets."""
    pass

# --- CONFIGURACIÓN DE CONEXIÓN SEGURA ---
GSPREAD_CREDENTIALS_B64 = os.environ.get("GSPREAD_CREDENTIALS")
SPREADSHEET_NAME = "gestion_condominio" # Nombre de su hoja de cálculo

class SheetsService:
    
    MOVEMENTS_SHEET_NAME = 'MOVIMIENTOS'
    
    def __init__(self):
        """Inicializa la conexión a Google Sheets usando credenciales Base64 del entorno."""
        self.sh = None # Objeto Spreadsheet (Hoja de cálculo)
        self.gc = None # Objeto gspread.Client (Cliente)
        
        try:
            # 1. Verificar si la variable Base64 existe
            if not GSPREAD_CREDENTIALS_B64:
                raise ConnectionError("ERROR: La variable de entorno 'GSPREAD_CREDENTIALS' no está configurada o está vacía.")
            
            # 2. Decodificar la cadena Base64 a JSON
            try:
                creds_json_string = base64.b64decode(GSPREAD_CREDENTIALS_B64).decode('utf-8')
                credentials_data = json.loads(creds_json_string)
            except Exception as e:
                raise ConnectionError(f"ERROR: Falló la decodificación o el formato JSON de GSPREAD_CREDENTIALS. Causa: {e}")
            
            # 3. Conexión al cliente
            self.gc = gspread.service_account_from_dict(credentials_data)
            
            # 4. Conexión a la hoja de cálculo
            try:
                self.sh = self.gc.open(SPREADSHEET_NAME)
                print(f"[INFO] Conexión exitosa a Google Sheets: '{SPREADSHEET_NAME}'")
            except SpreadsheetNotFound:
                print(f"[ERROR] Hoja de cálculo '{SPREADSHEET_NAME}' no encontrada.")
                self.sh = None
                
        except ConnectionError as e:
            print(f"[ERROR DE CONEXIÓN]: {e}")
            self.sh = None
        except Exception as e:
            print(f"[ERROR INESPERADO al inicializar SheetsService]: {e}")
            self.sh = None

    # --- MÉTODOS EXISTENTES ---
    
    def get_sheet(self, sheet_title: str) -> gspread.Worksheet:
        """Obtiene una hoja por su título. Añade manejo de WorksheetNotFound."""
        if not self.sh:
            raise ConnectionError(f"No se pudo conectar a la hoja de cálculo: '{SPREADSHEET_NAME}'.")
        try:
            return self.sh.worksheet(sheet_title)
        except WorksheetNotFound:
            # Lanza una excepción personalizada con un mensaje claro
            raise ConnectionError(f"ERROR: Hoja de trabajo '{sheet_title}' no encontrada en el Spreadsheet.")

    def get_all_records(self, sheet_title: str) -> List[Dict[str, Any]]:
        """Obtiene todos los datos de una hoja como lista de diccionarios (usa la primera fila como cabecera)."""
        sheet = self.get_sheet(sheet_title)
        return sheet.get_all_records()

    def get_records_by_casa_id(self, sheet_title: str, id_casa: int) -> List[Dict[str, Any]]:
        """
        Obtiene todos los registros de una hoja filtrados por ID_CASA.
        Este método soporta ID_CASA = 0 para la Tesorería.
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

                new_record = {}
                for k, v in record.items():
                    if k in ['ID_CASA', 'DIAS_ATRASO', 'CUOTAS_PENDIENTES']:
                        try:
                            new_record[k] = int(float(v))
                        except (ValueError, TypeError):
                            new_record[k] = v
                    elif k in ['MONTO', 'SALDO_PENDIENTE', 'SALDO']:
                        try:
                            v_clean = v.replace(',', '.')
                            new_record[k] = float(v_clean)
                        except (ValueError, TypeError):
                            new_record[k] = v
                    else:
                        new_record[k] = v

                filtered_list.append(new_record)

        return filtered_list

    # --- FUNCIÓN CLAVE: LECTURA DE CONFIGURACIÓN ---
    def get_config_map(self) -> Dict[str, Any]:
        """
        Lee todos los pares clave-valor de la hoja CONFIGURACION y retorna un diccionario.
        Ajusta la conversión de tipos (int, float) para uso en main.py.
        """
        try:
            data = self.get_all_records('CONFIGURACION')
            config_map = {}
            
            for row in data:
                clave = str(row.get('CLAVE', '')).strip().upper()
                value = str(row.get('VALOR', '')).strip()
                
                if not clave: continue
                
                # Lógica de conversión de tipo
                try:
                    if '.' in value or ',' in value:
                        config_map[clave] = float(value.replace(',', '.'))
                    elif value.isdigit():
                        config_map[clave] = int(value)
                    else:
                        config_map[clave] = value 
                except ValueError:
                    config_map[clave] = value 
            
            return config_map

        except Exception as e:
            print(f"[ERROR SHEETS] No se pudo leer la hoja CONFIGURACION: {e}")
            # Retorna valores por defecto si falla la lectura (FALLBACK CRÍTICO)
            return {
                "VALOR_ALICUOTA": 50.00,
                "DIA_VENCIMIENTO": 5,
                "PUNTOS_POR_PAGO_A_TIEMPO": 10,
                "PORCENTAJE_DESCUENTO": 0.00 
            }

    # --- FUNCIÓN PARA LECTURA DE USUARIO ---
    def get_user_by_id_casa(self, id_casa: int) -> Optional[Dict[str, Any]]:
        """Busca y retorna el registro de usuario (incluyendo NOMBRE) para una casa. Soporta ID_CASA=0."""
        try:
            usuarios_data = self.get_all_records('USUARIOS')
            for user in usuarios_data:
                if user.get('ID_CASA') and str(user['ID_CASA']).strip() == str(id_casa):
                    return user
            return None
        except Exception as e:
            print(f"[ERROR SHEETS] Error al obtener usuario por ID_CASA {id_casa}: {e}")
            return None

    # --- FUNCIÓN: OBTENER MAPA DE USUARIOS (Para el Admin Panel) ---
    def get_all_users_map(self) -> Dict[str, Dict[str, Any]]:
        """Retorna un mapa de usuarios {ID_CASA: {DATOS_USUARIO}}. Incluye ID_CASA 0."""
        try:
            users_data = self.get_all_records('USUARIOS')
        except Exception:
            return {}
            
        user_map = {}
        for user in users_data:
            casa_id = str(user.get('ID_CASA')).strip()
            if casa_id:
                user_map[casa_id] = {
                    'NOMBRE': user.get('NOMBRE', 'N/A'),
                    'EMAIL': user.get('EMAIL', 'N/A'),
                    'CELULAR': user.get('CELULAR', 'N/A')
                }
        return user_map

    # --- FUNCIÓN: get_all_casa_ids ---
    def get_all_casa_ids(self) -> List[int]:
        """Obtiene una lista de todos los ID_CASA activos de la hoja USUARIOS. Incluye ID_CASA 0."""
        
        try:
            records = self.get_all_records('USUARIOS')
            
            casa_ids = []
            for record in records:
                casa_id_str = str(record.get('ID_CASA', '')).strip()
                estado = str(record.get('ESTADO', 'ACTIVO')).upper().strip() 

                if casa_id_str and estado == 'ACTIVO':
                    try:
                        casa_id = int(float(casa_id_str)) 
                        if casa_id not in casa_ids:
                            casa_ids.append(casa_id)
                    except ValueError:
                        continue
                        
            return sorted(casa_ids)
            
        except Exception as e:
            print(f"[ERROR SHEETS_SERVICE] Fallo al obtener todos los ID de casa: {e}")
            return []

    # MÉTODO DE ESCRITURA: Genera el ID en formato Mxxxx
    def generate_next_movement_id(self) -> str:
        """Genera el siguiente ID de movimiento (M0001, M0002, etc.)."""
        movimientos_sheet = self.get_sheet(self.MOVEMENTS_SHEET_NAME)
        # Leer la columna 1 (ID_MOVIMIENTO) a partir de la segunda fila
        all_ids = movimientos_sheet.col_values(1)[1:] 
        
        if not all_ids:
            return "M0001"
        
        # Filtra solo IDs válidos que comienzan con 'M' seguido de dígitos
        valid_ids = [uid for uid in all_ids if uid and uid.startswith('M') and uid[1:].isdigit()]
        
        last_number = 0
        if valid_ids:
            last_number = max([int(uid[1:]) for uid in valid_ids])
            
        next_number = last_number + 1
        return f"M{next_number:04d}" 

    # MÉTODO DE ESCRITURA: Añade una fila (CORREGIDO)
    def append_movement(self, data_row: list):
        """Añade una fila a la hoja MOVIMIENTOS usando el método simple de gspread."""
        
        try:
            # 1. Obtenemos la hoja de trabajo (Worksheet) usando get_sheet
            movimientos_sheet = self.get_sheet(self.MOVEMENTS_SHEET_NAME)
            
            # 2. **CORRECCIÓN APLICADA:** Usar el método nativo de gspread para añadir la fila
            result = movimientos_sheet.append_row(
                values=data_row,
                value_input_option='USER_ENTERED' # Para que los valores se interpreten correctamente
            )
            
            return result
        
        except ConnectionError as ce: # Manejo del error que get_sheet puede lanzar
             print(f"[ERROR gspread APPEND] Error de conexión/hoja: {ce}")
             raise ce
        except Exception as e:
            print(f"[ERROR gspread APPEND] Fallo al añadir fila a MOVIMIENTOS: {e}")
            raise e
    # ----------------------------------------------------------------------
    # --- MÉTODOS DE SEMÁFORO (USAN get_all_values() y update()) ---
    # ----------------------------------------------------------------------
    def update_or_append_semaforo(self, id_casa: int, dias_atraso: int, saldo: float, estado: str, cuotas_pendientes: int) -> bool:
        """
        Busca ID_CASA en ALERTAS_SEMAFORO. Si existe, actualiza (A:F); si no, añade.
        Ajustado para el orden de 6 columnas: ID_CASA, SALDO, DIAS_ATRASO, ESTADO, CUOTAS, FECHA
        """
        sheet = self.get_sheet('ALERTAS_SEMAFORO')
        data = sheet.get_all_values()
        
        records = data[1:] if len(data) > 1 else []
        
        target_id_str = str(id_casa)
        row_index_to_update = -1 
        
        # 1. Buscar fila existente (ID_CASA en la Columna A)
        for i, row in enumerate(records):
            if row and row[0].strip() == target_id_str: 
                row_index_to_update = i + 2 # +2 porque data[0] es cabecera y el índice de gspread es base 1
                break

        # CORRECCIÓN DE FECHA Y HORA: Usar la zona horaria de Guayaquil (GMT-5)
        current_time_local = datetime.now(LOCAL_TIMEZONE).strftime('%Y-%m-%d %H:%M') 
        
        # 2. Preparar nueva data (6 columnas A:F)
        # ORDEN DE COLUMNAS: A, B, C, D, E, F
        new_data = [
            target_id_str,           # 1. ID_CASA (A)
            f"{saldo:.2f}",          # 2. SALDO (B)
            str(dias_atraso),        # 3. DIAS_ATRASO (C)
            estado,                  # 4. ESTADO_SEMAFORO (D)
            str(cuotas_pendientes),  # 5. CUOTAS_PENDIENTES (E)
            current_time_local,      # 6. FECHA_ACTUALIZACION (F)
        ]
        
        try:
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

    def get_semaforo_by_casa(self, id_casa: int) -> Optional[Dict[str, Any]]:
        """
        Busca y retorna el estado del semáforo consolidado para una casa específica.
        Mapeo ajustado para el orden de 6 columnas.
        """
        sheet_name = 'ALERTAS_SEMAFORO'
        try:
            sheet = self.get_sheet(sheet_name)
            data = sheet.get_all_values()
            
            for row in data[1:]: # Ignora la fila de headers
                if not row or str(row[0]).strip() != str(id_casa):
                    continue
                
                # Mapeo de las 6 columnas de datos
                if len(row) >= 6:
                    return {
                        "ID_CASA": row[0],
                        "SALDO": float(row[1]) if row[1] else 0.0,
                        "DIAS_ATRASO": int(row[2]) if row[2].isdigit() else 0,
                        "ESTADO_SEMAFORO": row[3],
                        "CUOTAS_PENDIENTES": int(row[4]) if row[4].isdigit() else 0,
                        "FECHA_ACTUALIZACION": row[5]
                    }
                
            return None # Casa no encontrada
            
        except ConnectionError:
            # Si get_sheet lanza ConnectionError (hoja no existe), retornamos None
            return None
        except Exception as e:
            print(f"[ERROR SHEETS] Error al obtener el semáforo para la Casa {id_casa} de {sheet_name}: {e}")
            return None