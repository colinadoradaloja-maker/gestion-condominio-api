import traceback
import pytz 
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, HTTPException, Depends, status

# --- Importaciones Consolidadas ---
from API.backend_api import schemas
from API.backend_api.sheets_service import sheets_service
from API.backend_api.security import (
    verify_password, 
    create_access_token, 
    get_current_user_payload, 
    RoleChecker
)

# ----------------------------------------------------------------------
# ----------------- CONFIGURACIÓN DE ZONA HORARIA Y UTILIDADES -----------------
# ----------------------------------------------------------------------

app = FastAPI(title="Backend Condominio FastAPI")

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
def login_for_access_token(request: schemas.LoginRequest):
    """
    Autentica al usuario usando DNI y Contraseña. Retorna un token JWT.
    """
    if sheets_service is None:
        print("[ERROR] Servicio de base de datos no disponible.")
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")

    try:
        users_data: List[Dict[str, Any]] = sheets_service.get_all_records('USUARIOS')
    except Exception as e:
        print("[ERROR] al cargar datos de usuarios:", e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error al cargar datos de usuarios: {e}")

    # 2. Buscar al usuario por DNI
    user_record = next((user for user in users_data if str(user['DNI']) == request.dni), None)

    if not user_record or not verify_password(request.password, user_record['PASSWORD_HASH']):
        raise HTTPException(status_code=401, detail="DNI o contraseña incorrectos.")

    # 3. Éxito: Generar Token JWT
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
    payload: schemas.TokenData = Depends(get_current_user_payload)
):
    """
    Consulta el historial de movimientos, el saldo pendiente, el estado del semáforo y las cuotas pendientes.
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        # Aseguramos que casa_id sea un entero para la lógica interna y búsqueda
        casa_id = int(payload.ID_CASA) 
        
        # A. Obtener nombre del condómino
        user_info = sheets_service.get_user_by_id_casa(casa_id) 
        nombre_condomino = user_info['NOMBRE'] if user_info and 'NOMBRE' in user_info else "Condómino Desconocido"
        
    except (ValueError, TypeError) as e:
        print(f"[ERROR] ID de Casa inválido en el token: {e}")
        raise HTTPException(status_code=400, detail="ID de Casa inválido en el token.")
    except Exception as e:
        print(f"[ERROR] No se pudo obtener info de usuario para Casa ID {casa_id}: {e}")
        nombre_condomino = "Condómino Desconocido"


    try:
        # B. Obtener movimientos
        movimientos_data = sheets_service.get_records_by_casa_id('MOVIMIENTOS', casa_id)
        
        # C. Obtener el estado del semáforo consolidado (6 campos)
        semaforo_data = sheets_service.get_semaforo_by_casa(id_casa=casa_id)

        # D. Calcular Saldo Pendiente y Formatear Movimientos
        saldo_pendiente = 0.0
        movimientos_list: List[schemas.Movimiento] = []
        
        for record in movimientos_data:
            try:
                monto = float(record.get('MONTO', 0.0))
                saldo_pendiente += monto
                
                # Formateo y validación de fechas para el esquema Movimiento
                fecha_venc_str = record.get('FECHA_VENCIMIENTO', '')
                fecha_reg_str = record.get('FECHA_REGISTRO', '')
                
                # Parsea fecha de vencimiento si existe y tiene el formato correcto
                fecha_vencimiento: Optional[datetime] = None
                if fecha_venc_str:
                    try:
                        fecha_vencimiento = datetime.strptime(fecha_venc_str, '%Y-%m-%d') 
                        # Agregar la zona horaria para ser consistente con el esquema Movimiento
                        fecha_vencimiento = LOCAL_TIMEZONE.localize(fecha_vencimiento.replace(tzinfo=None))
                    except ValueError:
                        pass
                
                # Parsea la fecha de registro (ajustado para manejar 'AAAA-MM-DD HH:MM')
                fecha_registro: Optional[datetime] = None
                if fecha_reg_str and fecha_reg_str.split():
                    try:
                        fecha_registro = datetime.strptime(fecha_reg_str, '%Y-%m-%d %H:%M')
                        # Asignar la zona horaria GTM-5 para que Pydantic lo reconozca como aware datetime
                        fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                    except ValueError:
                        # Intenta solo con la fecha si falla el formato completo
                        fecha_registro = datetime.strptime(fecha_reg_str.split()[0], '%Y-%m-%d')
                        # Asignar la zona horaria GTM-5
                        fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                
                
                movimientos_list.append(schemas.Movimiento(
                    ID_MOVIMIENTO=record['ID_MOVIMIENTO'],
                    MES_PERIODO=record['MES_PERIODO'],
                    TIPO_MOVIMIENTO=record['TIPO_MOVIMIENTO'],
                    CONCEPTO=record['CONCEPTO'],
                    MONTO=monto,
                    FECHA_VENCIMIENTO=fecha_vencimiento,
                    TIPO_PAGO=record.get('TIPO_PAGO', None) or None,
                    FECHA_REGISTRO=fecha_registro
                ))
            except (ValueError, KeyError, TypeError) as e:
                print(f"[ERROR DATA] Registro fallido: {record}. Causa: {e}")
                continue 
        
        # E. Asignar datos del Semáforo o valores por defecto
        if semaforo_data and semaforo_data.get('ESTADO_SEMAFORO'):
            estado_semaforo = semaforo_data.get('ESTADO_SEMAFORO', "VERDE")
            dias_atraso = semaforo_data.get('DIAS_ATRASO', 0)
            cuotas_pendientes = semaforo_data.get('CUOTAS_PENDIENTES', 0)
        else:
            estado_semaforo = "NO_INFO"
            dias_atraso = 0
            cuotas_pendientes = 0
            
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
def register_pago(pago_data: schemas.PagoCreation, payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Registra un PAGO. El monto es NEGATIVO (disminuye la deuda de la casa, aumenta el efectivo de Tesorería).
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        next_id = sheets_service.generate_next_movement_id()
        # USANDO HORA LOCAL CORREGIDA
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
        
        sheets_service.append_movement(new_row)
        
        return {"status": "success", "message": f"Pago registrado correctamente. ID: {next_id}", "ID_MOVIMIENTO": next_id}
        
    except Exception as e:
        print(f"[ERROR ESCRITURA PAGO]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar el pago en la base de datos.")


@app.post("/admin/multas", tags=["Admin"], 
             dependencies=[Depends(require_admin)])
def register_multa(multa_data: schemas.MultaCreation, payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Registra una MULTA. El monto es POSITIVO (aumenta la deuda de la casa).
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        next_id = sheets_service.generate_next_movement_id()
        # USANDO HORA LOCAL CORREGIDA
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
            "", # TIPO_PAGO (Vacío)
            fecha_registro
        ]
        
        sheets_service.append_movement(new_row)
        
        return {"status": "success", "message": f"Multa registrada correctamente. ID: {next_id}", "ID_MOVIMIENTO": next_id}
        
    except Exception as e:
        print(f"[ERROR ESCRITURA MULTA]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar la multa en la base de datos.")


@app.post("/admin/alicuotas", tags=["Admin"], 
             dependencies=[Depends(require_admin)])
def register_alicuotas_masivas(
    alicuota_data: schemas.AlicuotaCreation, 
    payload: schemas.TokenData = Depends(get_current_user_payload)
):
    """
    Registra masivamente la alícuota mensual (Orden de Pago) para todas las casas activas.
    Utiliza la hoja CONFIGURACION para obtener el MONTO y el DÍA DE VENCIMIENTO.
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        # A. OBTENER CONFIGURACIÓN DEL SISTEMA
        config_map = sheets_service.get_config_map()
        
        # OBTENER VALORES DINÁMICOS DESDE LA CONFIGURACIÓN (usando valores por defecto seguros)
        monto_alicuota = config_map.get("VALOR_ALICUOTA", 50.00) 
        dia_vencimiento = config_map.get("DIA_VENCIMIENTO", 5)
        
        # B. CÁLCULO DE LA FECHA DE VENCIMIENTO (USANDO EL DÍA CONFIGURABLE)
        try:
            mes_anio = datetime.strptime(alicuota_data.MES_PERIODO, '%Y-%m')
            # Establece la fecha de vencimiento al día configurable del mes del período
            fecha_vencimiento = date(mes_anio.year, mes_anio.month, int(dia_vencimiento)).strftime('%Y-%m-%d')
        except Exception:
            raise HTTPException(status_code=400, detail="Formato de MES_PERIODO inválido. Use AAAA-MM.")
            
        # C. Leer todas las casas
        casa_ids = sheets_service.get_all_casa_ids()
        
        if not casa_ids:
            return {"status": "warning", "message": "No se encontraron casas activas para registrar alícuotas."}

        # D. Generar y escribir movimientos para cada casa
        # **USANDO HORA LOCAL CORREGIDA**
        fecha_registro = get_local_datetime().strftime('%Y-%m-%d %H:%M')
        
        for casa_id in casa_ids:
            next_id = sheets_service.generate_next_movement_id() 
            
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
            
            sheets_service.append_movement(new_row)
            
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
def actualizar_semaforo(payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Consolida todos los movimientos, calcula el saldo, determina la mora y actualiza la hoja ALERTAS_SEMAFORO.
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        # 1. Obtener datos para consolidación (MÁXIMO DE LECTURAS)
        # Se incluye ID_CASA 0 en get_all_casa_ids(), pero se excluye en el cálculo de mora/semáforo
        casa_ids = [id for id in sheets_service.get_all_casa_ids() if id != 0] 
        movimientos_data = sheets_service.get_all_records('MOVIMIENTOS')
        user_map = sheets_service.get_all_users_map() # Optimizador: Lee todos los usuarios de golpe
        
        if not casa_ids:
            return schemas.SemaforoUpdateResponse(status="warning", message="No hay casas registradas (excluyendo Tesorería).", results=[])
        
        results = []
        hoy = date.today()
        
        for casa_id in casa_ids:
            casa_id_str = str(casa_id) # Convertir a str una sola vez
            movimientos_casa = [m for m in movimientos_data if str(m.get('ID_CASA')) == casa_id_str]
            
            # A. OBTENER INFORMACIÓN DE USUARIO (USANDO EL MAPA EN MEMORIA)
            user_info = user_map.get(casa_id_str, {})
            nombre = user_info.get('NOMBRE', f'N/A (Casa {casa_id_str})')
            email = user_info.get('EMAIL', 'N/A')
            # Casting explícito a str para evitar error Pydantic
            celular = str(user_info.get('CELULAR', 'N/A'))

            # b. Calcular Saldo total
            saldo = 0.0
            for m in movimientos_casa:
                try:
                    saldo += float(m.get('MONTO', 0.0))
                except (ValueError, TypeError):
                    continue
            
            # c. Determinar Mora, Días de Atraso y Cuotas Pendientes
            estado_semaforo = "VERDE"
            dias_atraso = 0
            cuotas_pendientes = 0 
            
            if saldo > 0.01: 
                
                cargos_vencidos = []
                for m in movimientos_casa:
                    tipo = m.get('TIPO_MOVIMIENTO', '').upper()
                    monto = 0.0
                    try:
                        monto = float(m.get('MONTO', 0.0))
                    except (ValueError, TypeError):
                        continue
                        
                    fecha_venc_str = m.get('FECHA_VENCIMIENTO', '')
                    
                    # Solo evaluamos ALICUOTA como deuda morosa
                    if tipo == 'ALICUOTA' and monto > 0 and fecha_venc_str:
                        try:
                            fecha_vencimiento = datetime.strptime(fecha_venc_str, '%Y-%m-%d').date()
                            
                            if fecha_vencimiento <= hoy:
                                cargos_vencidos.append((fecha_vencimiento, m.get('ID_MOVIMIENTO')))
                                
                        except ValueError:
                            continue
                            
                if cargos_vencidos:
                    cuotas_pendientes = len(cargos_vencidos) 
                    
                    cargos_vencidos.sort(key=lambda x: x[0])
                    fecha_mora = cargos_vencidos[0][0]
                    dias_atraso = (hoy - fecha_mora).days
                    
                    if dias_atraso >= 30:
                        estado_semaforo = "ROJO"
                    else:
                        estado_semaforo = "AMARILLO"
                else:
                    # Caso de saldo > 0.01 pero sin alícuotas vencidas (Ej: solo tiene multas recientes no vencidas)
                    estado_semaforo = "AMARILLO" 
            
            
            # d. Actualizar la hoja ALERTAS_SEMAFORO (1 SOLA ESCRITURA POR CASA)
            sheets_service.update_or_append_semaforo(
                casa_id, 
                dias_atraso, 
                round(saldo, 2), 
                estado_semaforo,
                cuotas_pendientes 
            )
            
            # e. Preparar el resultado JSON para la respuesta
            results.append(schemas.SemaforoResult(
                ID_CASA=casa_id_str, 
                SALDO=round(saldo, 2),
                ESTADO_SEMAFORO=estado_semaforo,
                DIAS_ATRASO=dias_atraso,
                CUOTAS_PENDIENTES=cuotas_pendientes,
                nombre_condomino=nombre,
                email=email,
                celular=celular
            ).model_dump(by_alias=True)) 
            
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
def get_semaforo_list(payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Panel de Control: Obtiene y lista el estado consolidado de la hoja ALERTAS_SEMAFORO, 
    incluyendo nombre, email y celular del condómino para fines de reporte y contacto.
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        # 1. Obtener el mapa de usuarios (NOMBRE, EMAIL y CELULAR) para búsqueda rápida (O(1))
        user_map = sheets_service.get_all_users_map()
        
        # 2. Obtener datos consolidados del semáforo
        # Usamos get_all_records() porque los datos ya están consolidados
        semaforo_data = sheets_service.get_all_records('ALERTAS_SEMAFORO')
        
        if not semaforo_data:
            return schemas.SemaforoListResponse(
                status="success", 
                message="No hay registros consolidados en ALERTAS_SEMAFORO.", 
                results=[]
            )
            
        results = []
        for record in semaforo_data:
            # 3. Mapear y validar tipos de datos del Semáforo
            try:
                # Asegurando que los valores clave se interpreten correctamente
                id_casa = str(record.get('ID_CASA', ''))
                # Omitir el ID_CASA 0 de la lista visible del semáforo (no es un condómino deudor)
                if id_casa == '0':
                    continue 
                    
                dias_atraso = int(record.get('DIAS_ATRASO', 0) or 0)
                saldo = float(record.get('SALDO_PENDIENTE', 0.0) or 0.0)
                cuotas_pendientes = int(record.get('CUOTAS_PENDIENTES', 0) or 0)

                # 4. Integrar Nombre, Email y Celular desde el mapa de usuarios
                user_info = user_map.get(id_casa, {})
                nombre = user_info.get('NOMBRE', f'N/A (Casa {id_casa})')
                email = user_info.get('EMAIL', 'N/A')
                
                # CORRECCIÓN: Convertir explícitamente a str para evitar error Pydantic
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
                # Esto maneja registros corruptos en la hoja ALERTAS_SEMAFORO y errores de mapeo
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
def get_estado_cuenta(id_casa: int, payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Obtiene el estado completo de una casa (o Tesorería), incluyendo:
    1. Información del condómino (Contacto).
    2. Estado actual del semáforo.
    3. Lista de todos sus movimientos (cargos y abonos).
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        # 1. Obtener la información del usuario
        user_info = sheets_service.get_user_by_id_casa(id_casa)
        if not user_info:
            raise HTTPException(status_code=404, detail=f"Casa {id_casa} no encontrada en la base de datos de usuarios.")
        
        # 2. Obtener el estado del semáforo consolidado (solo para casas > 0)
        semaforo_info = sheets_service.get_semaforo_by_casa(id_casa) if id_casa != 0 else {}
        
        if not semaforo_info and id_casa != 0:
            # Si no hay semáforo consolidado, se inicializa con valores seguros
            semaforo_info = {
                "ID_CASA": str(id_casa),
                "DIAS_ATRASO": 0,
                "SALDO_PENDIENTE": 0.0,
                "ESTADO_SEMAFORO": "VERDE",
                "CUOTAS_PENDIENTES": 0,
                "FECHA_ACTUALIZACION": get_local_datetime().strftime('%Y-%m-%d %H:%M') # USANDO HORA LOCAL CORREGIDA
            }
        
        # 3. Obtener todos los movimientos (cargos y abonos)
        movimientos_data = sheets_service.get_records_by_casa_id('MOVIMIENTOS', id_casa)
        
        # Mapear los movimientos al esquema
        movimientos_list = []
        saldo_calculado = 0.0 # Calcular saldo aquí para Tesorería (ID_CASA=0)
        for m in movimientos_data:
            monto_val = float(m.get('MONTO', 0.0) or 0.0) 
            saldo_calculado += monto_val # Suma el saldo para el reporte (cargos POS, pagos NEG)
            
            # Formateo y validación de fechas
            fecha_vencimiento: Optional[datetime] = None
            if m.get('FECHA_VENCIMIENTO'):
                try:
                    fecha_vencimiento = datetime.strptime(m['FECHA_VENCIMIENTO'], '%Y-%m-%d') 
                    # Asignar la zona horaria GTM-5 para que Pydantic lo reconozca como aware datetime
                    fecha_vencimiento = LOCAL_TIMEZONE.localize(fecha_vencimiento.replace(tzinfo=None))
                except ValueError:
                    pass
            
            fecha_registro: Optional[datetime] = None
            if m.get('FECHA_REGISTRO') and m['FECHA_REGISTRO'].split():
                try:
                    # Asume que el formato de registro es siempre AAAA-MM-DD HH:MM
                    fecha_registro = datetime.strptime(m['FECHA_REGISTRO'], '%Y-%m-%d %H:%M')
                    # Asignar la zona horaria GTM-5
                    fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
                except ValueError:
                    # Intenta solo con la fecha si falla el formato completo
                    fecha_registro = datetime.strptime(m['FECHA_REGISTRO'].split()[0], '%Y-%m-%d')
                    # Asignar la zona horaria GTM-5
                    fecha_registro = LOCAL_TIMEZONE.localize(fecha_registro.replace(tzinfo=None))
            
            # Nota: usamos el nombre de las columnas de Sheets para mapear
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
            
        # 4. Construir la respuesta CondominoInfo (Contacto)
        celular_str = str(user_info.get('CELULAR', 'N/A'))
        
        condomino_data = schemas.CondominoInfo(
            ID_CASA=str(id_casa),
            nombre=user_info.get('NOMBRE', 'N/A'),
            email=user_info.get('EMAIL', 'N/A'),
            celular=celular_str,
        )
        
        # Reusar el SemáforoResult para la estructura de estado consolidado (Solo si no es Tesorería)
        if id_casa != 0:
            semaforo_result = schemas.SemaforoResult(
                ID_CASA=str(id_casa),
                SALDO=round(semaforo_info.get('SALDO_PENDIENTE', 0.0), 2),
                ESTADO_SEMAFORO=semaforo_info.get('ESTADO_SEMAFORO', 'VERDE'),
                DIAS_ATRASO=semaforo_info.get('DIAS_ATRASO', 0),
                CUOTAS_PENDIENTES=semaforo_info.get('CUOTAS_PENDIENTES', 0),
                nombre_condomino=condomino_data.nombre,
                email=condomino_data.email,
                celular=condomino_data.celular
            )
            saldo_final = semaforo_result.SALDO
        else:
            # Para la Tesorería, el 'semaforo_actual' es la información del usuario
            semaforo_result = schemas.SemaforoResult(
                ID_CASA="0",
                SALDO=round(saldo_calculado, 2), # El saldo real de Tesorería se calcula aquí
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
             dependencies=[Depends(require_admin_or_tesoreria)]) # <--- DEPENDENCIA ACTUALIZADA
def register_tesoreria_transaccion(
    data: schemas.TesoreriaCreation, 
    payload: schemas.TokenData = Depends(get_current_user_payload)
):
    """
    Registra un Ingreso (donación, extra) o un Egreso (gasto) de la administración (ID_CASA=0).
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")
    
    try:
        next_id = sheets_service.generate_next_movement_id()
        fecha_registro = get_local_datetime().strftime('%Y-%m-%d %H:%M')
        mes_periodo = get_local_datetime().strftime('%Y-%m')
        
        tipo_mov = data.TIPO_TRANSACCION.upper()
        
        # El monto se invierte si es un EGRESO (debe ser negativo en la hoja)
        if tipo_mov == 'EGRESO':
            monto = -abs(data.MONTO)
        else: # INGRESO (debe ser positivo)
            monto = abs(data.MONTO)

        # ORDEN DE COLUMNAS: ID, ID_CASA, MES_PERIODO, TIPO_MOV, CONCEPTO, MONTO, FECHA_VENCIMIENTO, TIPO_PAGO, FECHA_REGISTRO
        new_row = [
            next_id, 
            0, # <-- ID_CASA de la ADMINISTRACIÓN (Tesorería)
            mes_periodo,
            tipo_mov, 
            data.CONCEPTO, 
            monto, 
            "", # FECHA_VENCIMIENTO (Vacío)
            "", # TIPO_PAGO (Vacío)
            fecha_registro 
        ]
        
        sheets_service.append_movement(new_row)
        
        return {"status": "success", "message": f"{tipo_mov} de Tesorería registrado. ID: {next_id}", "ID_MOVIMIENTO": next_id}
        
    except Exception as e:
        print(f"[ERROR ESCRITURA TESORERIA]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error al registrar la transacción de Tesorería.")


@app.get("/admin/tesoreria/estado", tags=["Admin", "Tesorería"], 
             dependencies=[Depends(require_admin_or_tesoreria)], # <--- DEPENDENCIA ACTUALIZADA
             response_model=schemas.TesoreriaEstadoResponse) # <--- RESPONSE_MODEL AÑADIDO
def get_tesoreria_estado(payload: schemas.TokenData = Depends(get_current_user_payload)):
    """
    Calcula el saldo real del fondo de Tesorería del condominio (ID_CASA=0).
    """
    if sheets_service is None:
        raise HTTPException(status_code=503, detail="Servicio de base de datos no disponible.")

    try:
        # 1. Obtener solo los movimientos de la Tesorería (ID_CASA=0)
        movimientos_data = sheets_service.get_records_by_casa_id('MOVIMIENTOS', 0)
        
        saldo_disponible = 0.0
        
        for record in movimientos_data:
            try:
                # Suma/resta todos los movimientos de la Tesorería.
                # 'PAGO', 'INGRESO' son positivos (dinero entrando al fondo).
                # 'EGRESO' es negativo (dinero saliendo del fondo).
                saldo_disponible += float(record.get('MONTO', 0.0))
            except (ValueError, KeyError, TypeError):
                continue
        
        return schemas.TesoreriaEstadoResponse(
            status="success",
            message="Saldo calculado con éxito.",
            saldo_disponible=round(saldo_disponible, 2)
        )
        
    except Exception as e:
        print(f"[ERROR FATAL ESTADO TESORERIA]: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Error interno al calcular el estado de Tesorería.")