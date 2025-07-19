import json
import logging
import os
import firestore_utils # Importa el nuevo módulo para Firestore

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre del archivo de configuración local (se mantendrá como fallback o para la primera inicialización)
CONFIG_FILE = "config.json"
# ID del documento en Firestore donde se guardarán los parámetros del bot
FIRESTORE_CONFIG_DOC_ID = "bot_parameters"
# Nombre de la colección en Firestore para los datos públicos (configuración del bot)
# Siguiendo las reglas de seguridad: /artifacts/{appId}/public/data/bot_configs
FIRESTORE_CONFIG_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/bot_configs"


def load_parameters():
    """
    Carga los parámetros del bot. Intenta cargar desde Firestore primero.
    Si falla o no encuentra el documento, carga desde el archivo local (config.json).
    Si el archivo local tampoco existe, devuelve los parámetros por defecto.
    """
    db = firestore_utils.get_firestore_db()
    if db:
        try:
            doc_ref = db.collection(FIRESTORE_CONFIG_COLLECTION_PATH).document(FIRESTORE_CONFIG_DOC_ID)
            doc = doc_ref.get()
            if doc.exists:
                params = doc.to_dict()
                logging.info(f"✅ Parámetros cargados desde Firestore: {FIRESTORE_CONFIG_COLLECTION_PATH}/{FIRESTORE_CONFIG_DOC_ID}. Beneficio cargado: {params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0):.2f} USDT")
                return params
            else:
                logging.warning(f"⚠️ Documento de configuración no encontrado en Firestore: {FIRESTORE_CONFIG_COLLECTION_PATH}/{FIRESTORE_CONFIG_DOC_ID}. Intentando cargar desde archivo local.")
        except Exception as e:
            logging.error(f"❌ Error al cargar parámetros desde Firestore: {e}", exc_info=True)
            logging.warning("⚠️ Fallback: Intentando cargar desde archivo local.")

    # Fallback a archivo local
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                params = json.load(f)
            logging.info(f"✅ Parámetros cargados desde {CONFIG_FILE}. Beneficio cargado: {params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0):.2f} USDT")
            return params
        except json.JSONDecodeError as e:
            logging.error(f"❌ Error al decodificar JSON de {CONFIG_FILE}: {e}")
        except Exception as e:
            logging.error(f"❌ Error al cargar parámetros desde {CONFIG_FILE}: {e}")
    
    logging.warning("⚠️ No se encontró archivo de configuración local o hubo un error. Cargando parámetros por defecto.")
    # Parámetros por defecto si no se encuentra ningún archivo o hay errores.
    default_params = {
        "INTERVALO": 300,  # segundos
        "RIESGO_POR_OPERACION_PORCENTAJE": 0.01, # 1%
        "TAKE_PROFIT_PORCENTAJE": 0.03, # 3%
        "STOP_LOSS_PORCENTAJE": 0.02, # 2%
        "TRAILING_STOP_PORCENTAJE": 0.015, # 1.5%
        "EMA_PERIODO": 10,
        "RSI_PERIODO": 14,
        "RSI_UMBRAL_SOBRECOMPRA": 70,
        "TOTAL_BENEFICIO_ACUMULADO": 0.0,
        "BREAKEVEN_PORCENTAJE": 0.005 # 0.5%
    }
    # Guardar los parámetros por defecto en Firestore si está disponible, y localmente.
    save_parameters(default_params)
    return default_params

def save_parameters(params):
    """
    Guarda los parámetros del bot. Intenta guardar en Firestore primero.
    Si falla, guarda en el archivo local (config.json).
    """
    db = firestore_utils.get_firestore_db()
    if db:
        try:
            logging.info(f"DEBUG: Guardando parámetros en Firestore. Beneficio a guardar: {params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0):.2f} USDT")
            doc_ref = db.collection(FIRESTORE_CONFIG_COLLECTION_PATH).document(FIRESTORE_CONFIG_DOC_ID)
            doc_ref.set(params)
            logging.info(f"✅ Parámetros guardados en Firestore: {FIRESTORE_CONFIG_COLLECTION_PATH}/{FIRESTORE_CONFIG_DOC_ID}")
            return True
        except Exception as e:
            logging.error(f"❌ Error al guardar parámetros en Firestore: {e}", exc_info=True)
            logging.warning("⚠️ Fallback: Intentando guardar en archivo local.")

    # Fallback a archivo local
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(params, f, indent=4)
        logging.info(f"✅ Parámetros guardados en {CONFIG_FILE}.")
        return True
    except IOError as e:
        logging.error(f"❌ Error al escribir en el archivo {CONFIG_FILE}: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ Error inesperado al guardar parámetros en {CONFIG_FILE}: {e}")
        return False

