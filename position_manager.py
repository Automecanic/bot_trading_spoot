import json
import logging
import os
import time
import firestore_utils # Importa el nuevo módulo para Firestore

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre del archivo de posiciones local (se mantendrá como fallback o para la primera inicialización)
OPEN_POSITIONS_FILE = "open_positions.json"
# ID del documento en Firestore donde se guardarán las posiciones abiertas
FIRESTORE_POSITIONS_DOC_ID = "open_positions_data"
# Nombre de la colección en Firestore para los datos públicos (posiciones del bot)
# Siguiendo las reglas de seguridad: /artifacts/{appId}/public/data/bot_positions
FIRESTORE_POSITIONS_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/bot_positions"

# Variable para implementar el debounce en el guardado de posiciones
last_save_time = 0
SAVE_DEBOUNCE_INTERVAL = 5 # Guarda como máximo cada 5 segundos

def load_open_positions(stop_loss_porcentaje):
    """
    Carga las posiciones abiertas del bot. Intenta cargar desde Firestore primero.
    Si falla o no encuentra el documento, carga desde el archivo local (open_positions.json).
    Si el archivo local tampoco existe, devuelve un diccionario vacío.
    Inicializa 'sl_moved_to_breakeven' si no existe.
    """
    db = firestore_utils.get_firestore_db()
    if db:
        try:
            doc_ref = db.collection(FIRESTORE_POSITIONS_COLLECTION_PATH).document(FIRESTORE_POSITIONS_DOC_ID)
            doc = doc_ref.get()
            if doc.exists:
                positions = doc.to_dict()
                logging.info(f"✅ Posiciones cargadas desde Firestore: {FIRESTORE_POSITIONS_COLLECTION_PATH}/{FIRESTORE_POSITIONS_DOC_ID}")
                
                # Asegurar la inicialización de 'sl_moved_to_breakeven' y 'stop_loss_fijo_nivel_actual'
                for symbol, data in positions.items():
                    if 'sl_moved_to_breakeven' not in data:
                        data['sl_moved_to_breakeven'] = False
                    if 'stop_loss_fijo_nivel_actual' not in data:
                        data['stop_loss_fijo_nivel_actual'] = data['precio_compra'] * (1 - stop_loss_porcentaje)
                return positions
            else:
                logging.warning(f"⚠️ Documento de posiciones no encontrado en Firestore: {FIRESTORE_POSITIONS_COLLECTION_PATH}/{FIRESTORE_POSITIONS_DOC_ID}. Intentando cargar desde archivo local.")
        except Exception as e:
            logging.error(f"❌ Error al cargar posiciones desde Firestore: {e}", exc_info=True)
            logging.warning("⚠️ Fallback: Intentando cargar desde archivo local.")

    # Fallback a archivo local
    if os.path.exists(OPEN_POSITIONS_FILE):
        try:
            with open(OPEN_POSITIONS_FILE, 'r') as f:
                positions = json.load(f)
            logging.info(f"✅ Posiciones cargadas desde {OPEN_POSITIONS_FILE}.")
            # Asegurar la inicialización de 'sl_moved_to_breakeven' y 'stop_loss_fijo_nivel_actual'
            for symbol, data in positions.items():
                if 'sl_moved_to_breakeven' not in data:
                    data['sl_moved_to_breakeven'] = False
                if 'stop_loss_fijo_nivel_actual' not in data:
                    data['stop_loss_fijo_nivel_actual'] = data['precio_compra'] * (1 - stop_loss_porcentaje)
            return positions
        except json.JSONDecodeError as e:
            logging.error(f"❌ Error al decodificar JSON de {OPEN_POSITIONS_FILE}: {e}")
        except Exception as e:
            logging.error(f"❌ Error al cargar posiciones desde {OPEN_POSITIONS_FILE}: {e}")
    
    logging.warning("⚠️ No se encontró archivo de posiciones local o hubo un error. Devolviendo posiciones vacías.")
    return {}

def save_open_positions(positions):
    """
    Guarda las posiciones abiertas del bot. Intenta guardar en Firestore primero.
    Si falla, guarda en el archivo local (open_positions.json).
    """
    db = firestore_utils.get_firestore_db()
    if db:
        try:
            doc_ref = db.collection(FIRESTORE_POSITIONS_COLLECTION_PATH).document(FIRESTORE_POSITIONS_DOC_ID)
            doc_ref.set(positions)
            logging.info(f"✅ Posiciones abiertas guardadas en Firestore: {FIRESTORE_POSITIONS_COLLECTION_PATH}/{FIRESTORE_POSITIONS_DOC_ID}")
            return True
        except Exception as e:
            logging.error(f"❌ Error al guardar posiciones en Firestore: {e}", exc_info=True)
            logging.warning("⚠️ Fallback: Intentando guardar en archivo local.")

    # Fallback a archivo local
    try:
        with open(OPEN_POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=4)
        logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE}.")
        return True
    except IOError as e:
        logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE}: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ Error inesperado al guardar posiciones en {OPEN_POSITIONS_FILE}: {e}")
        return False

def save_open_positions_debounced(positions):
    """
    Guarda las posiciones abiertas, pero con un "debounce" para evitar escrituras excesivas.
    Solo guarda si ha pasado un cierto tiempo desde la última escritura.
    """
    global last_save_time
    current_time = time.time()
    if (current_time - last_save_time) >= SAVE_DEBOUNCE_INTERVAL:
        save_open_positions(positions)
        last_save_time = current_time
    else:
        logging.debug(f"⏳ Guardado de posiciones pospuesto (debounce). Próximo guardado en {SAVE_DEBOUNCE_INTERVAL - (current_time - last_save_time):.2f}s")

