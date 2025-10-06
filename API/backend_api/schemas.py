# backend_api/schemas.py (FINAL, COMPLETO y CORREGIDO)

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime

# --------------------------------------------------------
# --- 1. Modelos de Autenticación y Usuarios ---
# --------------------------------------------------------

class LoginRequest(BaseModel):
    """Modelo para la solicitud de login."""
    dni: str
    password: str

class TokenResponse(BaseModel):
    """Modelo para la respuesta de login exitoso."""
    access_token: str
    token_type: str = "bearer"
    rol: str

class TokenData(BaseModel):
    """Datos internos que se almacenan en el payload del JWT (leído por security.py)."""
    sub: Optional[str] = None  # DNI del usuario (subject)
    ID_CASA: Optional[int] = None # Campo con nombre original de la hoja
    ROL: Optional[str] = None

class User(BaseModel):
    """Modelo del objeto Usuario que se pasa entre dependencias."""
    DNI: str
    ID_CASA: int
    ROL: str
    NOMBRE: Optional[str] = None

# --------------------------------------------------------
# --- 2. Modelos de Consulta Financiera (Output) ---
# --------------------------------------------------------

class CondominoInfo(BaseModel):
    """Información básica del condómino (Nombre, Email, Celular)."""
    id_casa: str = Field(..., alias="ID_CASA") 
    nombre: str
    email: str
    celular: str # Importante: Usamos str para aceptar números o cadenas de texto

class Movimiento(BaseModel):
    """Representa un registro en la hoja MOVIMIENTOS (adaptado para el admin)."""
    # Usamos alias en mayúsculas para mapear con los datos de Google Sheets
    id_movimiento: str = Field(..., alias="ID_MOVIMIENTO")
    # Los siguientes campos estaban en minúsculas en tu esquema original, los ajustamos al formato SHEET_COLUMN para la API
    tipo_movimiento: str = Field(..., alias="TIPO_MOVIMIENTO") 
    monto: float = Field(..., alias="MONTO")
    
    # 🚨 CORRECCIÓN CLAVE: Aceptar objetos datetime
    fecha_registro: datetime = Field(..., alias="FECHA_REGISTRO")
    fecha_vencimiento: Optional[datetime] = Field(None, alias="FECHA_VENCIMIENTO")
    
    # Adaptación para compatibilidad de campos que tenías en el esquema MOVIMIENTO (si existen en tu hoja)
    MES_PERIODO: Optional[str] = None
    CONCEPTO: Optional[str] = None
    TIPO_PAGO: Optional[str] = None


class SemaforoResult(BaseModel):
    # Campos de Identificación y Contacto (REVISADO)
    ID_CASA: str = Field(..., alias="ID_CASA")
    nombre_condomino: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    celular: Optional[str] = Field(None)

    # Campos de Estado de Cuenta (EXISTENTES)
    SALDO: float = Field(..., alias="SALDO")
    ESTADO_SEMAFORO: str = Field(..., alias="ESTADO_SEMAFORO")
    DIAS_ATRASO: int = Field(..., alias="DIAS_ATRASO")
    CUOTAS_PENDIENTES: int = Field(..., alias="CUOTAS_PENDIENTES") 

# 🚨 ESTE MODELO FUE VALIDADO COMO CORRECTO EN EL LOG 🚨
class EstadoCuentaResponse(BaseModel):
    """
    Respuesta COMPLETA del estado de cuenta, para la ruta /admin/estado-cuenta/{id_casa}.
    Contiene la info del condómino, el estado semáforo, y la lista detallada de movimientos.
    """
    status: str # Campo requerido que faltaba en el diccionario de la respuesta
    condomino: CondominoInfo # Campo requerido que faltaba en el diccionario de la respuesta
    semaforo_actual: SemaforoResult # Campo requerido que faltaba en el diccionario de la respuesta
    movimientos: List[Movimiento]

# --------------------------------------------------------
# --- 3. Modelos de Creación (Input para el Admin) ---
# --------------------------------------------------------

class PagoCreation(BaseModel):
    """Modelo para registrar un PAGO (Admin input)."""
    ID_CASA: int = Field(..., gt=0)
    MONTO: float = Field(..., gt=0.0)
    CONCEPTO: str
    TIPO_PAGO: str = Field(..., description="Efectivo, Transferencia, etc.")

    @field_validator('TIPO_PAGO')
    @classmethod
    def validate_tipo_pago(cls, v: str):
        clean_v = v.strip().upper() 
        if clean_v not in ['TRANSFERENCIA', 'EFECTIVO', 'CHEQUE']:
            raise ValueError('Tipo de pago debe ser Transferencia, Efectivo o Cheque.')
        return clean_v

class MultaCreation(BaseModel):
    """Modelo para registrar una MULTA (Admin input)."""
    ID_CASA: int = Field(..., gt=0)
    MONTO: float = Field(..., gt=0.0)
    CONCEPTO: str

class AlicuotaCreation(BaseModel):
    """Modelo para registrar la alícuota masiva (Admin input)."""
    MES_PERIODO: str = Field(..., description="Mes y año al que aplica el cargo (ej: 2025-04)")
    MONTO_ALICUOTA: float = Field(..., gt=0.0)
    CONCEPTO: str = "Cuota de Mantenimiento Ordinaria" 

    @field_validator('MES_PERIODO')
    @classmethod
    def validate_mes_periodo(cls, v: str):
        try:
            datetime.strptime(v, '%Y-%m')
        except ValueError:
            raise ValueError('MES_PERIODO debe tener el formato AAAA-MM (ej: 2025-04).')
        return v
    
class SemaforoUpdateResponse(BaseModel):
    """Respuesta del administrador al actualizar el semáforo."""
    status: str
    message: str
    results: List[SemaforoResult]

class SemaforoListResponse(BaseModel):
    """Modelo de respuesta para el listado del estado del semáforo."""
    status: str
    message: str
    results: List[SemaforoResult]

# --- EN API/backend_api/schemas.py  ---

class ConfigMap(BaseModel):
    """
    Representa el mapa de configuración del sistema (valores clave-valor).
    """
    VALOR_ALICUOTA: float = Field(..., description="Monto base de la alícuota mensual.")
    DIA_VENCIMIENTO: int = Field(..., description="Día del mes en que vencen las alícuotas.")
    PUNTOS_POR_PAGO_A_TIEMPO: int = Field(..., description="Puntos de recompensa por pagar a tiempo.")
    PORCENTAJE_DESCUENTO: float = Field(..., description="Porcentaje de descuento por pago anticipado/pronto pago (ej: 0.10 = 10%).")
