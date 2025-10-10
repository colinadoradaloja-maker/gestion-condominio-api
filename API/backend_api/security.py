# backend_api/security.py

from passlib.context import CryptContext
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import jwt, JWTError
from fastapi import HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends
from .schemas import TokenData 


# --- 1. Configuración de Hashing (BCRYPT) ---
# Usamos bcrypt para hashear contraseñas de forma segura
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hashea una contraseña para guardarla de forma segura."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña ingresada coincide con el hash almacenado."""
    return pwd_context.verify(plain_password, hashed_password)


# --- 2. Configuración de JWT (JSON Web Tokens) ---
# Clave Secreta: DEBE ser una cadena larga y aleatoria.
SECRET_KEY = "CLAVE_SECRETA_12345" # NOTA: Usar una variable de entorno en producción.
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30 # El token expira en 30 minutos

def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Crea un token de acceso JWT."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> Dict[str, Any]:
    """Decodifica y valida un token JWT."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as e:
        print(f"[ERROR] Fallo al decodificar token: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Credenciales de autenticación inválidas o token expirado. ({e})",
            headers={"WWW-Authenticate": "Bearer"},
        )
        

# --- 3. Dependencias de Autenticación y Autorización ---

# Define el esquema de seguridad OAuth2 (Bearer Token)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/login")


def get_current_user_payload(token: str = Depends(oauth2_scheme)) -> TokenData:
    """
    Decodifica el token JWT y extrae el payload (datos del usuario).
    """
    payload = decode_token(token)
    token_data = TokenData(**payload)

    if token_data.sub is None or token_data.ROL is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales de autenticación inválidas (token incompleto).",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token_data


# --- Dependencia para Requerir Roles (RoleChecker) ---
class RoleChecker:
    """Clase para verificar si el usuario tiene un rol o uno de los roles específicos."""
    # ACEPTA UNA LISTA DE ROLES
    def __init__(self, allowed_roles: List[str]):
        # Se asegura de que la lista sea de roles en MAYÚSCULAS para consistencia
        self.allowed_roles = [role.upper() for role in allowed_roles]

    def __call__(self, payload: TokenData = Depends(get_current_user_payload)):
        """Verifica si el rol del token está en los roles permitidos."""
        
        # Convierte el rol del payload a mayúsculas para la comparación
        user_role = payload.ROL.upper() 
        
        # LA VERIFICACIÓN CAMBIA: Verificar si el rol está DENTRO de la lista
        if user_role not in self.allowed_roles:
            # Puedes hacer la respuesta más específica para el usuario
            roles_str = ', '.join(self.allowed_roles)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso denegado. Se requiere uno de los roles: {roles_str}.",
            )
        return payload