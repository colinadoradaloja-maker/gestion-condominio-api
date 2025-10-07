from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
import pytz # Necesario si quieres usar datetime aware objects en los modelos

# Definir la zona horaria: Guayaquil = GTM-5 (UTC-5)
# Aunque no se usa directamente aquí, es buena práctica mantener la referencia si se necesita validar fechas.
LOCAL_TIMEZONE = pytz.timezone('America/Guayaquil') 


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
    sub: Optional[str] = None # DNI del usuario (subject)
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
    """Información básica del condómino o de Tesorería (ID_CASA=0)."""
    id_casa: str = Field(..., alias="ID_CASA") 
    nombre: str
    email: str
    celular: str 
    
    class Config:
        populate_by_name = True

class Movimiento(BaseModel):
    """
    Representa un registro en la hoja MOVIMIENTOS. 
    """
    id_movimiento: str = Field(..., alias="ID_MOVIMIENTO")
    mes_periodo: Optional[str] = Field(None, alias="MES_PERIODO")
    tipo_movimiento: str = Field(..., alias="TIPO_MOVIMIENTO") 
    concepto: Optional[str] = Field(None, alias="CONCEPTO")
    monto: float = Field(..., alias="MONTO")
    
    # TIPADO CORREGIDO: datetime (incluye la hora y la zona horaria)
    fecha_vencimiento: Optional[datetime] = Field(None, alias="FECHA_VENCIMIENTO")
    tipo_pago: Optional[str] = Field(None, alias="TIPO_PAGO")
    fecha_registro: Optional[datetime] = Field(None, alias="FECHA_REGISTRO")

    class Config:
        populate_by_name = True


class SemaforoResult(BaseModel):
    """Estado consolidado del semáforo para una casa, incluyendo datos de contacto."""
    ID_CASA: str = Field(..., alias="ID_CASA")
    nombre_condomino: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    celular: Optional[str] = Field(None)

    SALDO: float = Field(..., alias="SALDO")
    ESTADO_SEMAFORO: str = Field(..., alias="ESTADO_SEMAFORO")
    DIAS_ATRASO: int = Field(..., alias="DIAS_ATRASO")
    CUOTAS_PENDIENTES: int = Field(..., alias="CUOTAS_PENDIENTES") 
    
    class Config:
        populate_by_name = True


class EstadoCuentaResponse(BaseModel):
    """
    Respuesta COMPLETA del estado de cuenta, unificada para Condómino y Admin.
    
    NOTA: El endpoint de Condómino usa solo los campos sueltos (id_casa, saldo_pendiente, etc.) 
    mientras que el de Admin usa la estructura completa (condomino, semaforo_actual).
    """
    # CAMPOS PRINCIPALES (Para la respuesta ADMIN detallada y el resumen del Condómino)
    status: str = Field("success")
    movimientos: List[Movimiento]
    
    # Detalle de la Casa/Tesorería (Usado en el endpoint ADMIN)
    condomino: Optional[CondominoInfo] = Field(None) 
    
    # Estado Consolidado (Usado en el endpoint ADMIN)
    semaforo_actual: Optional[SemaforoResult] = Field(None) 
    
    # Campos sueltos (Usados principalmente en el endpoint CONDOMINO por simplicidad)
    id_casa: Optional[int] = Field(None)
    nombre_condomino: Optional[str] = Field(None)
    saldo_pendiente: Optional[float] = Field(None)
    estado_semaforo: Optional[str] = Field(None)
    dias_atraso: Optional[int] = Field(None)
    cuotas_pendientes: Optional[int] = Field(None)
    

# --------------------------------------------------------
# --- 3. Modelos de Creación (Input para el Admin) ---
# --------------------------------------------------------

class PagoCreation(BaseModel):
    """Modelo para registrar un PAGO (Admin input)."""
    ID_CASA: int = Field(..., gt=0, description="ID de la casa que realiza el pago.")
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
    ID_CASA: int = Field(..., gt=0, description="ID de la casa que recibe la multa.")
    MONTO: float = Field(..., gt=0.0)
    CONCEPTO: str

class AlicuotaCreation(BaseModel):
    """Modelo para registrar la alícuota masiva (Admin input)."""
    MES_PERIODO: str = Field(..., description="Mes y año al que aplica el cargo (ej: 2025-04)")
    CONCEPTO: str = "Cuota de Mantenimiento Ordinaria" 

    @field_validator('MES_PERIODO')
    @classmethod
    def validate_mes_periodo(cls, v: str):
        try:
            datetime.strptime(v, '%Y-%m')
        except ValueError:
            raise ValueError('MES_PERIODO debe tener el formato AAAA-MM (ej: 2025-04).')
        return v
    
class TesoreriaCreation(BaseModel):
    """Modelo para registrar cualquier movimiento (Ingreso o Egreso) a la Tesorería (ID_CASA 0)."""
    TIPO_TRANSACCION: Literal["INGRESO", "EGRESO"] = Field(..., description="Debe ser 'INGRESO' o 'EGRESO'.")
    MONTO: float = Field(..., gt=0.0, description="Monto en valor absoluto.")
    CONCEPTO: str
    
    # Se elimina el validator redundante ya que usamos Literal
    
# --------------------------------------------------------
# --- 4. Modelos de Respuesta de Procesos y Tesorería ---
# --------------------------------------------------------

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

class TesoreriaEstadoResponse(BaseModel):
    """Modelo de respuesta para el saldo de la Tesorería (ID_CASA=0)."""
    status: str = "success"
    message: str = "Saldo calculado con éxito."
    saldo_disponible: float