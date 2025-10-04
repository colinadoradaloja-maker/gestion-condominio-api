# generate_hash.py

from passlib.context import CryptContext
import getpass
import os

# Configuración del contexto de hashing (la misma que usarás en security.py)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    """Hashea una contraseña usando bcrypt."""
    return pwd_context.hash(password)

def main():
    """Función principal para solicitar la contraseña y mostrar el hash."""
    
    # Limpia la consola para mayor privacidad antes de solicitar la contraseña
    os.system('cls' if os.name == 'nt' else 'clear')
    
    print("-------------------------------------------------------")
    print("  🔑 GENERADOR DE HASH BCRYPT PARA GOOGLE SHEETS 🔑")
    print("-------------------------------------------------------")
    print("Ingresa la contraseña para hashear. No se mostrará en pantalla.")
    
    # Usamos getpass para que la contraseña no se muestre mientras se escribe
    password = getpass.getpass("Contraseña: ")
    
    if not password:
        print("\n¡Error! La contraseña no puede estar vacía.")
        return

    hashed_pw = hash_password(password)
    
    print("\n-------------------------------------------------------")
    print("✅ HASH GENERADO EXITOSAMENTE (COPIAR Y PEGAR):")
    print("-------------------------------------------------------")
    print(hashed_pw)
    print("-------------------------------------------------------")
    print("\n⚠️  COPIA este hash y pégalo en la columna PASSWORD_HASH de tu hoja 'USUARIOS'.")
    print("   NUNCA uses la contraseña original en la hoja.")


if __name__ == "__main__":
    main()