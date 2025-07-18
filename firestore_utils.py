import logging  # Importa el módulo logging para registrar eventos y mensajes informativos, de advertencia o error.
import os       # Importa el módulo os para interactuar con el sistema operativo, específicamente para acceder a variables de entorno.
import json     # Importa el módulo json para trabajar con datos en formato JSON, necesario para parsear las credenciales de Firebase.
# Importa las clases necesarias del SDK de Firebase Admin para Python.
from firebase_admin import credentials, initialize_app, firestore

# --- Configuración de Logging ---
# Configura el sistema de registro básico para este módulo.
# Los mensajes se mostrarán en la consola con un formato que incluye la fecha/hora, nivel y mensaje.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Variable global para almacenar la instancia de la base de datos Firestore.
# Se inicializa como None y se asignará la instancia de Firestore una vez que se inicialice.
db = None

def initialize_firestore():
    """
    Inicializa la aplicación Firebase y el cliente de Firestore.
    Esta función es el punto de entrada para conectar tu aplicación Python con Firebase.
    
    Se espera que las credenciales de Firebase se proporcionen a través
    de una variable de entorno llamada 'FIREBASE_CREDENTIALS_JSON'.
    Esta variable debe contener el contenido JSON completo de tu archivo de clave de servicio
    descargado desde la consola de Firebase.
    
    Retorna:
        La instancia del cliente de Firestore si la inicialización es exitosa, de lo contrario None.
    """
    global db  # Declara que se usará la variable global 'db'.
    if db is not None:
        # Si la instancia de Firestore ya existe, significa que ya se inicializó.
        # Se registra un mensaje y se devuelve la instancia existente para evitar duplicaciones.
        logging.info("Firestore ya está inicializado.")
        return db

    # Obtiene el contenido JSON de las credenciales de Firebase desde la variable de entorno.
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

    if not firebase_credentials_json:
        # Si la variable de entorno no está configurada, se registra un error crítico
        # y se devuelve None, ya que no se pueden inicializar las credenciales.
        logging.error("❌ La variable de entorno 'FIREBASE_CREDENTIALS_JSON' no está configurada. No se puede inicializar Firestore.")
        return None

    try:
        # Carga las credenciales de servicio desde la cadena JSON obtenida de la variable de entorno.
        # `json.loads()` convierte la cadena JSON en un diccionario Python.
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
        
        # Inicializa la aplicación Firebase con las credenciales proporcionadas.
        # Esto establece la conexión principal con tu proyecto de Firebase.
        initialize_app(cred)
        logging.info("✅ Firebase App inicializada con éxito.")
        
        # Obtiene la instancia del cliente de Firestore.
        # Este cliente es el objeto principal que usarás para interactuar con tu base de datos Firestore.
        db = firestore.client()
        logging.info("✅ Cliente de Firestore obtenido con éxito.")
        return db  # Devuelve la instancia del cliente de Firestore.
    except Exception as e:
        # Captura cualquier excepción que ocurra durante el proceso de inicialización.
        # Esto incluye errores en el formato JSON, problemas de conexión, permisos, etc.
        logging.error(f"❌ Error al inicializar Firebase o Firestore: {e}", exc_info=True)
        return None  # En caso de error, devuelve None.

def get_firestore_db():
    """
    Devuelve la instancia de la base de datos Firestore.
    Esta función es un wrapper conveniente para acceder a la instancia de Firestore.
    Si la base de datos no ha sido inicializada previamente, llama a `initialize_firestore()`
    para configurarla.
    
    Retorna:
        La instancia del cliente de Firestore.
    """
    global db  # Declara que se usará la variable global 'db'.
    if db is None:
        # Si la instancia de Firestore aún no está asignada (es None),
        # se llama a `initialize_firestore()` para intentar inicializarla.
        db = initialize_firestore()
    return db  # Devuelve la instancia (ya sea la recién inicializada o una existente).
