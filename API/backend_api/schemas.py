from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import pytz # Necesario si quieres usar datetime aware objects en los modelos

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
    """Información básica del condómino (Nombre, Email, Celular)."""
    id_casa: str = Field(..., alias="ID_CASA") 
    nombre: str
    email: str
    celular: str 

class Movimiento(BaseModel):
    """
    Representa un registro en la hoja MOVIMIENTOS. 
    Nota: Se usa Optional[datetime] porque main.py los convierte a objetos datetime aware.
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
    Respuesta COMPLETA del estado de cuenta, flexible para Condómino y Admin.
    """
    # CAMPOS ADICIONALES PARA CONDOMINO ENDPOINT (Versión simplificada)
    id_casa: Optional[int] = Field(None)
    nombre_condomino: Optional[str] = Field(None)
    saldo_pendiente: Optional[float] = Field(None)
    estado_semaforo: Optional[str] = Field(None)
    dias_atraso: Optional[int] = Field(None)
    cuotas_pendientes: Optional[int] = Field(None)

    # CAMPOS PRINCIPALES (Para la respuesta ADMIN detallada)
    status: str = Field("success")
    condomino: Optional[CondominoInfo] = Field(None) 
    semaforo_actual: Optional[SemaforoResult] = Field(None) 
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
    # Campo MONTO_ALICUOTA ELIMINADO: Se obtiene de la hoja CONFIGURACION
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

# En la sección 3. Modelos de Creación (Input para el Admin)

# ... (Mantener PagoCreation, MultaCreation, AlicuotaCreation)

class TesoreriaCreation(BaseModel):
    """Modelo para registrar cualquier movimiento (Ingreso o Egreso) a la Tesorería (ID_CASA 0)."""
    TIPO_TRANSACCION: str = Field(..., description="Debe ser 'INGRESO' o 'EGRESO'.")
    MONTO: float = Field(..., gt=0.0, description="Monto en valor absoluto.")
    CONCEPTO: str
    
    @field_validator('TIPO_TRANSACCION')
    @classmethod
    def validate_tipo_transaccion(cls, v: str):
        clean_v = v.strip().upper() 
        if clean_v not in ['INGRESO', 'EGRESO']:
            raise ValueError("TIPO_TRANSACCION debe ser 'INGRESO' o 'EGRESO'.")
        return clean_v