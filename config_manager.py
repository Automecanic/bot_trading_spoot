import json # Importa el módulo json para trabajar con datos en formato JSON (serialización/deserialización).
import logging # Importa el módulo logging para registrar eventos y mensajes del bot.
import os # Importa el módulo os para interactuar con el sistema operativo, como acceder a variables de entorno.
import firestore_utils # Importa el nuevo módulo para Firestore, que permite la interacción con la base de datos Firestore.

# Configura el sistema de registro para este módulo.
# Esto asegura que los mensajes informativos, advertencias y errores se muestren en la consola del bot.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre del archivo de configuración local.
# Este archivo se mantiene como una opción de respaldo o para la inicialización inicial si Firestore no está disponible.
CONFIG_FILE = "config.json"
# ID del documento específico en Firestore donde se guardarán los parámetros del bot.
# Todos los parámetros del bot se almacenarán en un único documento para facilitar su gestión.
FIRESTORE_CONFIG_DOC_ID = "bot_parameters"
# Nombre de la colección en Firestore donde residirá el documento de configuración.
# La ruta sigue las reglas de seguridad de Firestore para datos públicos de la aplicación,
# utilizando '__app_id' que es una variable de entorno proporcionada por el entorno de Canvas/Railway.
FIRESTORE_CONFIG_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/bot_configs"


def load_parameters():
    """
    Carga los parámetros de configuración del bot.
    La función intenta cargar los parámetros desde Firestore primero, ya que es la fuente de verdad persistente.
    Si la carga desde Firestore falla (por ejemplo, no hay conexión o el documento no existe),
    entonces intenta cargar desde el archivo local (config.json) como un mecanismo de respaldo.
    Si ninguna de las fuentes tiene los parámetros, se cargan y guardan los valores por defecto.
    """
    # Intenta obtener una instancia de la base de datos Firestore.
    db = firestore_utils.get_firestore_db()
    if db: # Si la conexión a Firestore es exitosa (db no es None).
        try:
            # Obtiene una referencia al documento de configuración en Firestore.
            doc_ref = db.collection(FIRESTORE_CONFIG_COLLECTION_PATH).document(FIRESTORE_CONFIG_DOC_ID)
            doc = doc_ref.get() # Intenta obtener el documento.
            if doc.exists: # Si el documento existe en Firestore.
                params = doc.to_dict() # Convierte el documento de Firestore a un diccionario Python.
                # Registra que los parámetros se cargaron exitosamente desde Firestore, incluyendo el beneficio.
                logging.info(f"✅ Parámetros cargados desde Firestore: {FIRESTORE_CONFIG_COLLECTION_PATH}/{FIRESTORE_CONFIG_DOC_ID}. Beneficio cargado: {params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0):.2f} USDT")
                return params # Devuelve los parámetros cargados.
            else:
                # Si el documento no existe en Firestore, registra una advertencia e intenta el fallback local.
                logging.warning(f"⚠️ Documento de configuración no encontrado en Firestore: {FIRESTORE_CONFIG_COLLECTION_PATH}/{FIRESTORE_CONFIG_DOC_ID}. Intentando cargar desde archivo local.")
        except Exception as e:
            # Si ocurre cualquier error durante la carga desde Firestore, registra el error y el fallback.
            logging.error(f"❌ Error al cargar parámetros desde Firestore: {e}", exc_info=True)
            logging.warning("⚠️ Fallback: Intentando cargar desde archivo local.")

    # Fallback a archivo local: Si Firestore no estaba disponible o falló.
    if os.path.exists(CONFIG_FILE): # Verifica si el archivo de configuración local existe.
        try:
            with open(CONFIG_FILE, 'r') as f: # Abre el archivo en modo lectura.
                params = json.load(f) # Carga los parámetros del archivo JSON.
            # Registra que los parámetros se cargaron exitosamente desde el archivo local, incluyendo el beneficio.
            logging.info(f"✅ Parámetros cargados desde {CONFIG_FILE}. Beneficio cargado: {params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0):.2f} USDT")
            return params # Devuelve los parámetros cargados.
        except json.JSONDecodeError as e:
            # Si el archivo local no es un JSON válido, registra el error.
            logging.error(f"❌ Error al decodificar JSON de {CONFIG_FILE}: {e}")
        except Exception as e:
            # Si ocurre cualquier otro error durante la carga del archivo local, registra el error.
            logging.error(f"❌ Error al cargar parámetros desde {CONFIG_FILE}: {e}")
    
    # Si no se pudo cargar desde Firestore ni desde el archivo local, se cargan los parámetros por defecto.
    logging.warning("⚠️ No se encontró archivo de configuración local o hubo un error. Cargando parámetros por defecto.")
    # Definición de los parámetros por defecto del bot.
    default_params = {
        "INTERVALO": 900,  # Intervalo de tiempo en segundos entre cada ciclo de trading principal (15 minutos).
        "RIESGO_POR_OPERACION_PORCENTAJE": 0.01, # Porcentaje del capital total a arriesgar por operación (1%).
        "TAKE_PROFIT_PORCENTAJE": 0.05, # CAMBIO: Porcentaje de ganancia para cerrar una posición (Take Profit) (5%).
        "STOP_LOSS_PORCENTAJE": 0.03, # CAMBIO: Porcentaje de pérdida para cerrar una posición (Stop Loss fijo) (3%).
        "TRAILING_STOP_PORCENTAJE": 0.025, # CAMBIO: Porcentaje para activar el Trailing Stop Loss (2.5%).
        "EMA_PERIODO": 20, # Período para el cálculo de la Media Móvil Exponencial (EMA).
        "RSI_PERIODO": 14, # Período para el cálculo del Índice de Fuerza Relativa (RSI).
        "RSI_UMBRAL_SOBRECOMPRA": 70, # Umbral superior del RSI para identificar condiciones de sobrecompra.
        "TOTAL_BENEFICIO_ACUMULADO": 0.0, # Beneficio total acumulado por el bot desde su inicio (inicialmente 0.0).
        "BREAKEVEN_PORCENTAJE": 0.005 # Porcentaje de ganancia para mover el Stop Loss a Breakeven (0.5%).
    }
    # Guarda estos parámetros por defecto en Firestore (si está disponible) y también localmente,
    # para que la próxima vez que se inicie el bot, no se pierdan.
    save_parameters(default_params)
    return default_params # Devuelve los parámetros por defecto.

def save_parameters(params):
    """
    Guarda los parámetros del bot.
    La función intenta guardar los parámetros en Firestore primero para asegurar la persistencia.
    Si el guardado en Firestore falla, entonces intenta guardar en el archivo local (config.json)
    como un mecanismo de respaldo.
    """
    # Intenta obtener una instancia de la base de datos Firestore.
    db = firestore_utils.get_firestore_db()
    if db: # Si la conexión a Firestore es exitosa.
        try:
            # Registra el beneficio que se va a guardar en Firestore para depuración.
            logging.info(f"DEBUG: Guardando parámetros en Firestore. Beneficio a guardar: {params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0):.2f} USDT")
            # Obtiene una referencia al documento de configuración en Firestore.
            doc_ref = db.collection(FIRESTORE_CONFIG_COLLECTION_PATH).document(FIRESTORE_CONFIG_DOC_ID)
            doc_ref.set(params) # Guarda el diccionario de parámetros en el documento de Firestore.
            logging.info(f"✅ Parámetros guardados en Firestore: {FIRESTORE_CONFIG_COLLECTION_PATH}/{FIRESTORE_CONFIG_DOC_ID}")
            return True # Indica que el guardado fue exitoso.
        except Exception as e:
            # Si ocurre cualquier error durante el guardado en Firestore, registra el error y el fallback.
            logging.error(f"❌ Error al guardar parámetros en Firestore: {e}", exc_info=True)
            logging.warning("⚠️ Fallback: Intentando guardar en archivo local.")

    # Fallback a archivo local: Si Firestore no estaba disponible o falló.
    try:
        with open(CONFIG_FILE, 'w') as f: # Abre el archivo en modo escritura.
            json.dump(params, f, indent=4) # Guarda los parámetros en formato JSON con indentación para legibilidad.
        logging.info(f"✅ Parámetros guardados en {CONFIG_FILE}.")
        return True # Indica que el guardado fue exitoso.
    except IOError as e:
        # Si hay un error de entrada/salida al escribir el archivo local, registra el error.
        logging.error(f"❌ Error al escribir en el archivo {CONFIG_FILE}: {e}")
        return False # Indica que el guardado falló.
    except Exception as e:
        # Si ocurre cualquier otro error inesperado durante el guardado local, registra el error.
        logging.error(f"❌ Error inesperado al guardar parámetros en {CONFIG_FILE}: {e}")
        return False # Indica que el guardado falló.

