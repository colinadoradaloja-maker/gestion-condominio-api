import traceback
import pytz 
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, status, APIRouter

# --- Importaciones Consolidadas ---
from API.backend_api import schemas
#from API.backend_api.sheets_service import sheets_service # GLOBAL: COMENTADA
from API.backend_api.sheets_service import SheetsService # <<-- AJUSTE FINAL: Importamos la CLASE
#from API.backend_api.dependencies import get_sheets_service # ELIMINADA: La definimos aquí.

from API.backend_api.security import (
    verify_password, 
    create_access_token, 
    get_current_user_payload, 
    RoleChecker
)

# ----------------------------------------------------------------------
# ----------------- CONFIGURACIÓN DE ZONA HORARIA Y UTILIDADES -----------------
# ----------------------------------------------------------------------

# Inicialización de la aplicación FastAPI y el router
app = FastAPI(title="Backend Condominio FastAPI")
router = APIRouter() # Usamos un router para la estructura si el archivo es grande

# Definir la zona horaria: Guayaquil = GTM-5 (UTC-5)
LOCAL_TIMEZONE = pytz.timezone('America/Guayaquil') 

def get_local_datetime() -> datetime:
    """
    Retorna la hora actual en la zona horaria local (GTM-5) de forma robusta.
    Corrige el problema del reloj base UTC del servidor.
    """
    # 1. Obtener la hora UTC actual del servidor y asignarle la zona UTC (aware datetime)
    utc_now = datetime.utcnow().replace(tzinfo=pytz.utc)
    
    # 2. Convertir esa hora UTC a la zona horaria local deseada
    return utc_now.astimezone(LOCAL_TIMEZONE)

# ----------------------------------------------------------------------
# ----------------- FUNCIÓN DE INYECCIÓN DE DEPENDENCIA (SheetsService) -----------------
# ----------------------------------------------------------------------
def get_sheets_service():
    """
    Generador de dependencia para obtener una instancia de SheetsService.
    Utiliza try/except/finally para manejar el ciclo de vida de la conexión.
    """
    sheets = None
    try:
        # Inicializa la conexión real al servicio de Google Sheets.
        sheets = SheetsService() 
        yield sheets # El objeto 'sheets' se inyecta en los endpoints
    except Exception as e:
        # Si la inicialización falla (ej. credenciales faltantes), lanza un error 503.
        print(f"[ERROR INYECCION SHEETS]: Error al inicializar SheetsService. {e}")
        raise HTTPException(
            status_code=503, 
            detail="Servicio de base de datos no disponible (Sheets Service Init Failed)."
        )
    finally:
        # Lógica de limpieza si es necesaria (FastAPI la ejecuta después de la respuesta).
        pass

# --- DEPENDENCIAS DE ROL ---
require_condomino = RoleChecker(required_role="CONDOMINO")
require_admin = RoleChecker(required_role="ADMIN")

# NUEVA DEPENDENCIA: Permite acceso a roles ADMIN o TESORERIA
def require_admin_or_tesoreria(payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Dependencia que verifica si el usuario tiene rol ADMIN o TESORERIA.
    """
    if payload.ROL.upper() not in ["ADMIN", "TESORERIA"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado. Se requiere el rol: ADMIN o TESORERIA."
        )
    return True # Permiso concedido

# ----------------------------------------------------------------------
# ----------------- 1. ENDPOINT PRINCIPAL: AUTENTICACIÓN -----------------
# ----------------------------------------------------------------------

@app.post("/login", response_model=schemas.TokenResponse, tags=["Autenticación"])
def login_for_access_token(
    request: schemas.LoginRequest,
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Autentica al usuario usando DNI y Contraseña. Retorna un token JWT.
    """
    try:
        users_data: List[Dict[str, Any]] = sheets.get_all_records('USUARIOS')
    except Exception as e:
        print("[ERROR] al cargar datos de usuarios:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al cargar datos de usuarios: {e}")

    user_record = next((user for user in users_data if str(user['DNI']) == request.dni), None)

    if not user_record or not verify_password(request.password, user_record['PASSWORD_HASH']):
        raise HTTPException(status_code=401, detail="DNI o contraseña incorrectos.")

    access_token = create_access_token(
        data={
            "sub": str(user_record['DNI']),
            "ID_CASA": user_record['ID_CASA'],
            "ROL": user_record['ROL']
        }
    )
    return schemas.TokenResponse(
        access_token=access_token,
        rol=user_record['ROL']
    )
# ----------------------------------------------------------------------
# ----------------- 2. ENDPOINTS DE CONSULTA (CONDÓMINO) -----------------
# ----------------------------------------------------------------------

@app.get("/condomino/estado_cuenta", response_model=schemas.EstadoCuentaResponse, tags=["Condómino"],
             dependencies=[Depends(require_condomino)])
def get_condomino_estado_cuenta(
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Consulta el historial de movimientos, el saldo pendiente, el estado del semáforo y las cuotas pendientes.
    """
    try:
        casa_id = int(payload.ID_CASA) 
        user_info = sheets.get_user_by_id_casa(casa_id) 
        nombre_condomino = user_info['NOMBRE'] if user_info and 'NOMBRE' in user_info else "Condómino Desconocido"
    except (ValueError, TypeError) as e:
        print(f"[ERROR] ID de Casa inválido en el token: {e}")
        raise HTTPException(status_code=400, detail="ID de Casa inválido en el token.")
    except Exception as e:
        print(f"[ERROR] No se pudo obtener info de usuario para Casa ID {casa_id}: {e}")
        nombre_condomino = "Condómino Desconocido"

    try:
        movimientos_data = sheets.get_records_by_casa_id('MOVIMIENTOS', casa_id)
        semaforo_data = sheets.get_semaforo_by_casa(id_casa=casa_id)
        
        # ... (lógica interna del endpoint)
        movimientos_list = []
        saldo_pendiente = 0.0
        
        # Lógica de mapeo y cálculo...
        for m in movimientos_data:
            # Lógica de cálculo y mapeo
            monto_val = float(m.get('MONTO', 0.0) or 0.0)
            saldo_pendiente += monto_val
            
            fecha_vencimiento: Optional[datetime] = None
            if m.get('FECHA_VENCIMIENTO'):
                try:
                    fecha_vencimiento = datetime.strptime(m['FECHA_VENCIMIENTO'], '%Y-%m-%d')
                    fecha_vencimiento = LOCAL_TIMEZONE.localize(fecha_vencimiento.replace(tzinfo=None))
                except ValueError:
                    pass
            
            fecha_registro: Optional[datetime] = None
            if m.get('FECHA_REGISTRO') and m['FECHA_REGISTRO'].split():
                try:
                    fecha_registro = datetime.strptime(m['FECHA_REGISTRO'], '%Y-%m-%d %H:%M')
                    fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                except ValueError:
                    try:
                        fecha_registro = datetime.strptime(m['FECHA_REGISTRO'].split()[0], '%Y-%m-%d')
                        fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                    except ValueError:
                        pass
                        
            movimientos_list.append(schemas.Movimiento(
                ID_MOVIMIENTO=m.get('ID_MOVIMIENTO', 'N/A'),
                TIPO_MOVIMIENTO=m.get('TIPO_MOVIMIENTO', 'N/A'),
                MONTO=monto_val,
                FECHA_REGISTRO=fecha_registro,
                FECHA_VENCIMIENTO=fecha_vencimiento,
                MES_PERIODO=m.get('MES_PERIODO', None),
                CONCEPTO=m.get('CONCEPTO', None),
                TIPO_PAGO=m.get('TIPO_PAGO', None)
            ))

        # Lógica del semáforo:
        estado_semaforo = semaforo_data.get('ESTADO_SEMAFORO', 'VERDE') if semaforo_data else 'VERDE'
        dias_atraso = int(semaforo_data.get('DIAS_ATRASO', 0) or 0) if semaforo_data else 0
        cuotas_pendientes = int(semaforo_data.get('CUOTAS_PENDIENTES', 0) or 0) if semaforo_data else 0
        
        # F. Retornar la respuesta final
        return schemas.EstadoCuentaResponse(
            id_casa=casa_id, 
            nombre_condomino=nombre_condomino,
            movimientos=movimientos_list,
            saldo_pendiente=round(saldo_pendiente, 2),
            estado_semaforo=estado_semaforo,
            dias_atraso=dias_atraso,
            cuotas_pendientes=cuotas_pendientes
        )
        
    except Exception as e:
        print(f"[ERROR FATAL] Error procesando estado de cuenta para Casa ID {casa_id}: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error interno al procesar su estado de cuenta.")
# ----------------------------------------------------------------------
# ----------------- 3. ENDPOINTS DE ESCRITURA (ADMIN) -----------------
# ----------------------------------------------------------------------
@app.post("/admin/pagos", tags=["Admin"], 
             dependencies=[Depends(require_admin)])
def register_pago(
    pago_data: schemas.PagoCreation, 
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Registra un PAGO. El monto es NEGATIVO (disminuye la deuda de la casa, aumenta el efectivo de Tesorería).
    """
    try:
        next_id = sheets.generate_next_movement_id()
        fecha_registro = get_local_datetime().strftime('%Y-%m-%d %H:%M')
        mes_periodo = get_local_datetime().strftime('%Y-%m') 
        monto_negativo = -abs(pago_data.MONTO) 
        
        # ORDEN DE COLUMNAS: ID, ID_CASA, MES_PERIODO, TIPO_MOV, CONCEPTO, MONTO, FECHA_VENCIMIENTO, TIPO_PAGO, FECHA_REGISTRO
        new_row = [
            next_id, 
            pago_data.ID_CASA, 
            mes_periodo,
            "PAGO", 
            pago_data.CONCEPTO, 
            monto_negativo, 
            "", # FECHA_VENCIMIENTO (Vacío para pagos)
            pago_data.TIPO_PAGO.upper(), 
            fecha_registro 
        ]
        
        sheets.append_movement(new_row)
        
        return {"status": "success", "message": f"Pago registrado correctamente. ID: {next_id}", "ID_MOVIMIENTO": next_id}
        
    except Exception as e:
        print(f"[ERROR ESCRITURA PAGO]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar el pago en la base de datos.")

@app.post("/admin/multas", tags=["Admin"], 
             dependencies=[Depends(require_admin)])
def register_multa(
    multa_data: schemas.MultaCreation, 
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Registra una MULTA. El monto es POSITIVO (aumenta la deuda de la casa).
    """
    try:
        next_id = sheets.generate_next_movement_id()
        fecha_registro = get_local_datetime().strftime('%Y-%m-%d %H:%M')
        mes_periodo = get_local_datetime().strftime('%Y-%m')
        monto_positivo = abs(multa_data.MONTO) 
        
        # ORDEN DE COLUMNAS: ID, ID_CASA, MES_PERIODO, TIPO_MOV, CONCEPTO, MONTO, FECHA_VENCIMIENTO, TIPO_PAGO, FECHA_REGISTRO
        new_row = [
            next_id, 
            multa_data.ID_CASA, 
            mes_periodo,
            "MULTA", 
            multa_data.CONCEPTO, 
            monto_positivo, 
            "", # FECHA_VENCIMIENTO (Vacío para multas)
            "", # TIPO_PAGO (Vacío, no aplica a una multa inicial)
            fecha_registro
        ]
        
        sheets.append_movement(new_row)
        
        return {"status": "success", "message": f"Multa registrada correctamente. ID: {next_id}", "ID_MOVIMIENTO": next_id}
        
    except Exception as e:
        print(f"[ERROR ESCRITURA MULTA]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar la multa en la base de datos.")

@app.post("/admin/alicuotas", tags=["Admin"], 
             dependencies=[Depends(require_admin)])
def register_alicuotas_masivas(
    alicuota_data: schemas.AlicuotaCreation, 
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Registra masivamente la alícuota mensual (Orden de Pago) para todas las casas activas.
    Utiliza la hoja CONFIGURACION para obtener el MONTO y el DÍA DE VENCIMIENTO.
    """
    try:
        # A. OBTENER CONFIGURACIÓN DEL SISTEMA
        config_map = sheets.get_config_map()
        
        # OBTENER VALORES DINÁMICOS DESDE LA CONFIGURACIÓN (usando valores por defecto seguros)
        monto_alicuota = float(config_map.get("VALOR_ALICUOTA", 50.00) or 50.00)
        dia_vencimiento = int(config_map.get("DIA_VENCIMIENTO", 5) or 5)
        
        # B. CÁLCULO DE LA FECHA DE VENCIMIENTO (USANDO EL DÍA CONFIGURABLE)
        try:
            mes_anio = datetime.strptime(alicuota_data.MES_PERIODO, '%Y-%m')
            # Establece la fecha de vencimiento al día configurable del mes del período
            fecha_vencimiento = date(mes_anio.year, mes_anio.month, dia_vencimiento).strftime('%Y-%m-%d')
        except Exception:
            raise HTTPException(status_code=400, detail="Formato de MES_PERIODO inválido. Use AAAA-MM.")
            
        # C. Leer todas las casas
        casa_ids = sheets.get_all_casa_ids()
        
        if not casa_ids:
            return {"status": "warning", "message": "No se encontraron casas activas para registrar alícuotas."}

        # D. Generar y escribir movimientos para cada casa
        fecha_registro = get_local_datetime().strftime('%Y-%m-%d %H:%M')
        
        for casa_id in casa_ids:
            next_id = sheets.generate_next_movement_id() 
            
            # ORDEN DE COLUMNAS: ID, ID_CASA, MES_PERIODO, TIPO_MOV, CONCEPTO, MONTO, FECHA_VENCIMIENTO, TIPO_PAGO, FECHA_REGISTRO
            new_row = [
                next_id, 
                casa_id, 
                alicuota_data.MES_PERIODO, 
                "ALICUOTA", 
                alicuota_data.CONCEPTO, 
                monto_alicuota, # <--- MONTO DINÁMICO DESDE CONFIGURACIÓN
                fecha_vencimiento, # FECHA DE VENCIMIENTO DINÁMICA
                "", # TIPO_PAGO (Vacío)
                fecha_registro 
            ]
            
            sheets.append_movement(new_row)
            
        return {
            "status": "success", 
            "message": f"Órdenes de Pago (Alícuotas) registradas para {len(casa_ids)} casas.",
            "periodo": alicuota_data.MES_PERIODO
        }
        
    except Exception as e:
        print(f"[ERROR ESCRITURA ALICUOTAS]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar alícuotas masivas.")

# ----------------------------------------------------------------------
# ----------------- 4. ENDPOINTS DE CONSOLIDACIÓN (SEMAFORO) -----------------
# ----------------------------------------------------------------------

@app.post("/admin/actualizar_semaforo", tags=["Admin"], 
             dependencies=[Depends(require_admin)],
             response_model=schemas.SemaforoUpdateResponse)
def actualizar_semaforo(
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Consolida todos los movimientos, calcula el saldo, determina la mora y actualiza la hoja ALERTAS_SEMAFORO.
    """
    try:
        # 1. Obtener datos para consolidación (MÁXIMO DE LECTURAS)
        casa_ids = [id for id in sheets.get_all_casa_ids() if id != 0] 
        movimientos_data = sheets.get_all_records('MOVIMIENTOS')
        user_map = sheets.get_all_users_map() # Optimizador: Lee todos los usuarios de golpe
        
        if not casa_ids:
            return schemas.SemaforoUpdateResponse(status="warning", message="No hay casas registradas (excluyendo Tesorería).", results=[])
        
        results = []
        hoy = date.today()
        
        for casa_id in casa_ids:
            # Lógica de cálculo (omitida por brevedad)
            saldo = 0.0
            dias_atraso = 0
            cuotas_pendientes = 0
            estado_semaforo = 'VERDE'
            
            # 1. Filtrar movimientos y calcular saldo
            casa_movs = [m for m in movimientos_data if str(m.get('ID_CASA', '')) == str(casa_id)]
            for m in casa_movs:
                saldo += float(m.get('MONTO', 0.0) or 0.0)

            # 2. Determinar el estado del semáforo
            if saldo > 0:
                # Buscar el movimiento más antiguo no pagado (el cargo con fecha de vencimiento)
                alicuotas_pendientes = sorted([
                    m for m in casa_movs 
                    if m.get('TIPO_MOVIMIENTO') == 'ALICUOTA' and m.get('MONTO') > 0
                ], key=lambda x: x.get('FECHA_VENCIMIENTO', '9999-12-31'))
                
                if alicuotas_pendientes:
                    cuotas_pendientes = len(alicuotas_pendientes)
                    try:
                        fecha_vencimiento_antigua = datetime.strptime(alicuotas_pendientes[0]['FECHA_VENCIMIENTO'], '%Y-%m-%d').date()
                        dias_atraso = (hoy - fecha_vencimiento_antigua).days
                        
                        if dias_atraso >= 30:
                            estado_semaforo = 'ROJO'
                        elif dias_atraso >= 15:
                            estado_semaforo = 'AMARILLO'
                        else:
                            estado_semaforo = 'VERDE'
                    except Exception:
                        dias_atraso = 0
                        estado_semaforo = 'VERDE'
                else:
                    estado_semaforo = 'VERDE'
                    
            # 3. Mapeo del contacto
            user_info = user_map.get(casa_id, {})
            nombre = user_info.get('NOMBRE', f'N/A (Casa {casa_id})')
            email = user_info.get('EMAIL', 'N/A')
            celular = str(user_info.get('CELULAR', 'N/A'))
            
            # d. Actualizar la hoja ALERTAS_SEMAFORO (1 SOLA ESCRITURA POR CASA)
            sheets.update_or_append_semaforo(
                casa_id, 
                dias_atraso, 
                round(saldo, 2), 
                estado_semaforo,
                cuotas_pendientes 
            )
            
            # e. Preparar el resultado JSON para la respuesta
            results.append(schemas.SemaforoResult(
                ID_CASA=casa_id,
                nombre_condomino=nombre,
                email=email,
                celular=celular,
                SALDO=round(saldo, 2),
                ESTADO_SEMAFORO=estado_semaforo,
                DIAS_ATRASO=dias_atraso,
                CUOTAS_PENDIENTES=cuotas_pendientes
            ))
            
        return schemas.SemaforoUpdateResponse(
            status="success", 
            message=f"Semáforo actualizado para {len(casa_ids)} casas. Total de escrituras: {len(casa_ids)}.",
            results=results
        )
        
    except Exception as e:
        print(f"[ERROR FATAL CONSOLIDACION]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error interno al procesar la consolidación del semáforo.")

#-------------------------------------------------------
# ----------------- 5. ENDPOINT DE CONSULTA (ADMIN) -----------------
# ----------------------------------------------------------------------

@app.get("/admin/semaforo", tags=["Admin"], 
             dependencies=[Depends(require_admin)],
             response_model=schemas.SemaforoListResponse)
def get_semaforo_list(
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Panel de Control: Obtiene y lista el estado consolidado de la hoja ALERTAS_SEMAFORO, 
    incluyendo nombre, email y celular del condómino para fines de reporte y contacto.
    """
    try:
        user_map = sheets.get_all_users_map()
        semaforo_data = sheets.get_all_records('ALERTAS_SEMAFORO')
        
        if not semaforo_data:
            return schemas.SemaforoListResponse(
                status="success", 
                message="No hay registros consolidados en ALERTAS_SEMAFORO.", 
                results=[]
            )
            
        results = []
        for record in semaforo_data:
            try:
                id_casa = str(record.get('ID_CASA', ''))
                if id_casa == '0':
                    continue 
                    
                dias_atraso = int(record.get('DIAS_ATRASO', 0) or 0)
                saldo = float(record.get('SALDO_PENDIENTE', 0.0) or 0.0)
                cuotas_pendientes = int(record.get('CUOTAS_PENDIENTES', 0) or 0)

                user_info = user_map.get(id_casa, {})
                nombre = user_info.get('NOMBRE', f'N/A (Casa {id_casa})')
                email = user_info.get('EMAIL', 'N/A')
                celular = str(user_info.get('CELULAR', 'N/A'))
                
                results.append(schemas.SemaforoResult(
                    ID_CASA=id_casa,
                    nombre_condomino=nombre,
                    email=email,
                    celular=celular,
                    SALDO=round(saldo, 2),
                    ESTADO_SEMAFORO=record.get('ESTADO_SEMAFORO', 'NO_INFO'),
                    DIAS_ATRASO=dias_atraso,
                    CUOTAS_PENDIENTES=cuotas_pendientes
                ))
            except (ValueError, TypeError, KeyError) as e:
                print(f"[ERROR MAPPING] Error mapeando registro de semáforo: {record}. Causa: {e}")
                continue
                
        return schemas.SemaforoListResponse(
            status="success", 
            message=f"Panel de control actualizado para {len(results)} casas con información de contacto completa.",
            results=results
        )
        
    except Exception as e:
        print(f"[ERROR FATAL LISTADO SEMAFORO]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error interno al listar el estado del semáforo.")

# ----------------------------------------------------------------------
# ----------------- 6. ENDPOINT DE REPORTE INDIVIDUAL: ESTADO DE CUENTA -----------------
# ----------------------------------------------------------------------

@app.get("/admin/estado-cuenta/{id_casa}", tags=["Admin"], 
             dependencies=[Depends(require_admin)],
             response_model=schemas.EstadoCuentaResponse)
def get_estado_cuenta(
    id_casa: int, 
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    """
    Obtiene el estado completo de una casa (o Tesorería), incluyendo:
    1. Información del condómino (Contacto).
    2. Estado actual del semáforo.
    3. Lista de todos sus movimientos (cargos y abonos).
    """
    try:
        user_info = sheets.get_user_by_id_casa(id_casa)
        if not user_info:
            raise HTTPException(status_code=404, detail=f"Casa {id_casa} no encontrada en la base de datos de usuarios.")
        
        semaforo_info = sheets.get_semaforo_by_casa(id_casa) if id_casa != 0 else {}
        
        if not semaforo_info and id_casa != 0:
            semaforo_info = {
                "ID_CASA": str(id_casa),
                "DIAS_ATRASO": 0,
                "SALDO_PENDIENTE": 0.0,
                "ESTADO_SEMAFORO": "VERDE",
                "CUOTAS_PENDIENTES": 0,
                "FECHA_ACTUALIZACION": get_local_datetime().strftime('%Y-%m-%d %H:%M')
            }
        
        movimientos_data = sheets.get_records_by_casa_id('MOVIMIENTOS', id_casa)
        
        # Mapear los movimientos al esquema
        movimientos_list = []
        saldo_calculado = 0.0 
        for m in movimientos_data:
            # Lógica de cálculo y mapeo
            monto_val = float(m.get('MONTO', 0.0) or 0.0) 
            saldo_calculado += monto_val
            
            fecha_vencimiento: Optional[datetime] = None
            if m.get('FECHA_VENCIMIENTO'):
                try:
                    fecha_vencimiento = datetime.strptime(m['FECHA_VENCIMIENTO'], '%Y-%m-%d') 
                    fecha_vencimiento = LOCAL_TIMEZONE.localize(fecha_vencimiento.replace(tzinfo=None))
                except ValueError:
                    pass
            
            fecha_registro: Optional[datetime] = None
            if m.get('FECHA_REGISTRO') and m['FECHA_REGISTRO'].split():
                try:
                    fecha_registro = datetime.strptime(m['FECHA_REGISTRO'], '%Y-%m-%d %H:%M')
                    fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                except ValueError:
                    try:
                        fecha_registro = datetime.strptime(m['FECHA_REGISTRO'].split()[0], '%Y-%m-%d')
                        fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                    except ValueError:
                        pass
            
            movimientos_list.append(schemas.Movimiento(
                ID_MOVIMIENTO=m.get('ID_MOVIMIENTO', 'N/A'),
                TIPO_MOVIMIENTO=m.get('TIPO_MOVIMIENTO', 'N/A'),
                MONTO=monto_val,
                FECHA_REGISTRO=fecha_registro,
                FECHA_VENCIMIENTO=fecha_vencimiento,
                MES_PERIODO=m.get('MES_PERIODO', None),
                CONCEPTO=m.get('CONCEPTO', None),
                TIPO_PAGO=m.get('TIPO_PAGO', None)
            ))
            
        celular_str = str(user_info.get('CELULAR', 'N/A'))
        
        condomino_data = schemas.CondominoInfo(
            ID_CASA=str(id_casa),
            nombre=user_info.get('NOMBRE', 'N/A'),
            email=user_info.get('EMAIL', 'N/A'),
            celular=celular_str,
        )
        
        if id_casa != 0:
            semaforo_result = schemas.SemaforoResult(
                ID_CASA=str(id_casa),
                SALDO=round(semaforo_info.get('SALDO_PENDIENTE', 0.0) or 0.0, 2),
                ESTADO_SEMAFORO=semaforo_info.get('ESTADO_SEMAFORO', 'VERDE'),
                DIAS_ATRASO=int(semaforo_info.get('DIAS_ATRASO', 0) or 0),
                CUOTAS_PENDIENTES=int(semaforo_info.get('CUOTAS_PENDIENTES', 0) or 0),
                nombre_condomino=condomino_data.nombre,
                email=condomino_data.email,
                celular=condomino_data.celular
            )
            saldo_final = semaforo_result.SALDO
        else:
            semaforo_result = schemas.SemaforoResult(
                ID_CASA="0",
                SALDO=round(saldo_calculado, 2),
                ESTADO_SEMAFORO="N/A",
                DIAS_ATRASO=0,
                CUOTAS_PENDIENTES=0,
                nombre_condomino="Tesorería/Administración",
                email=condomino_data.email,
                celular=condomino_data.celular
            )
            saldo_final = semaforo_result.SALDO
        
        # 5. Respuesta final
        return schemas.EstadoCuentaResponse(
            status="success",
            condomino=condomino_data,
            semaforo_actual=semaforo_result,
            movimientos=movimientos_list,
            saldo_pendiente=round(saldo_final, 2)
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"[ERROR FATAL ESTADO CUENTA]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error interno al obtener el estado de cuenta.")
# ----------------------------------------------------------------------
# ----------------- 7. ENDPOINTS DE TESORERÍA (ADMIN/TESORERIA) -----------------
# ----------------------------------------------------------------------
@app.post("/admin/tesoreria/transaccion", tags=["Admin", "Tesorería"], 
    dependencies=[Depends(require_admin_or_tesoreria)])
def register_tesoreria_transaccion(
    data: schemas.TesoreriaCreation, 
    payload: schemas.TokenData = Depends(get_current_user_payload),
    sheets: SheetsService = Depends(get_sheets_service) # <<-- OK
):
    try:
        next_id = sheets.generate_next_movement_id()
        fecha_registro = get_local_datetime().strftime('%Y-%m-%d %H:%M') 
        mes_periodo = get_local_datetime().strftime('%Y-%m') 
        
        #1. Determinar el MONTO final con el signo correcto
        monto_final = abs(data.MONTO)
        if data.TIPO_MOVIMIENTO_FINANCIERO.upper() == "EGRESO":
            monto_final = -abs(data.MONTO) 
        #2. Datos a escribir en la hoja MOVIMIENTOS (¡10 COLUMNAS!)
        #ORDEN: ID, ID_CASA, MES, TIPO_MOV, CONCEPTO, MONTO, FECHA_VENCIMIENTO, TIPO_PAGO, FECHA_REGISTRO, TIPO_MOV_FINANCIERO
        new_row = [
            next_id, # Columna 1
            "0", # Columna 2: ID_CASA
            mes_periodo, # Columna 3: MES_PERIODO
            data.TIPO_MOVIMIENTO.upper(), # Columna 4: TIPO_MOVIMIENTO (Negocio)
            data.CONCEPTO, # Columna 5: CONCEPTO
            monto_final, # Columna 6: MONTO (con signo)
            "", # Columna 7: FECHA_VENCIMIENTO (Vacío para Tesorería)
            data.TIPO_PAGO.upper(), # Columna 8: TIPO_PAGO
            fecha_registro, # Columna 9: FECHA_REGISTRO
            data.TIPO_MOVIMIENTO_FINANCIERO.upper() # Columna 10: TIPO_MOVIMIENTO_FINANCIERO
        ]

        sheets.append_movement(new_row)
        return {"status": "success", "message": f"Transacción registrada correctamente. ID: {next_id}", "ID_MOVIMIENTO": next_id}
    except Exception as e:
        print(f"[ERROR TESORERIA TRANSACCION]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar la transacción de tesorería.")
# ----------------- FIN DE ENDPOINTS -----------------
# ----------------------------------------------------------------------