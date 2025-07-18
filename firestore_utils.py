import logging
import os # Necesario para os.getenv
import json # Necesario para json.loads
from firebase_admin import credentials, initialize_app, firestore

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Variable global para almacenar la instancia de la base de datos Firestore
db = None

def initialize_firestore():
    """
    Inicializa la aplicación Firebase y el cliente de Firestore.
    Se espera que las credenciales de Firebase se proporcionen a través
    de una variable de entorno como 'FIREBASE_CREDENTIALS_JSON'
    que contenga el contenido JSON de tu archivo de clave de servicio.
    """
    global db
    if db is not None:
        logging.info("Firestore ya está inicializado.")
        return db

    # Obtener las credenciales de Firebase desde una variable de entorno
    firebase_credentials_json = os.getenv("FIREBASE_CREDENTIALS_JSON")

    if not firebase_credentials_json:
        logging.error("❌ La variable de entorno 'FIREBASE_CREDENTIALS_JSON' no está configurada. No se puede inicializar Firestore.")
        return None

    try:
        # Cargar las credenciales desde la cadena JSON
        cred = credentials.Certificate(json.loads(firebase_credentials_json))
        
        # Inicializar la aplicación Firebase
        initialize_app(cred)
        logging.info("✅ Firebase App inicializada con éxito.")
        
        # Obtener la instancia de Firestore
        db = firestore.client()
        logging.info("✅ Cliente de Firestore obtenido con éxito.")
        return db
    except Exception as e:
        logging.error(f"❌ Error al inicializar Firebase o Firestore: {e}", exc_info=True)
        return None

def get_firestore_db():
    """
    Devuelve la instancia de la base de datos Firestore.
    Si no está inicializada, intenta inicializarla.
    """
    global db
    if db is None:
        db = initialize_firestore()
    return db