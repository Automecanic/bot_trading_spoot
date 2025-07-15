import os # Módulo para interactuar con el sistema operativo, usado para verificar la existencia de archivos.
import json # Módulo para trabajar con archivos JSON, usado para guardar y cargar el estado de las posiciones.
import logging # Módulo para registrar eventos, errores y mensajes informativos.
import time # Módulo para funciones relacionadas con el tiempo, usado para el debounce.

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre del archivo donde se guardan las posiciones abiertas.
OPEN_POSITIONS_FILE = "open_positions.json"

# Variables para la gestión del debounce al guardar posiciones.
last_save_time_positions = 0
SAVE_POSITIONS_DEBOUNCE_INTERVAL = 60 # Intervalo mínimo (en segundos) entre escrituras del archivo de posiciones.

def load_open_positions(stop_loss_porcentaje):
    """
    Carga las posiciones abiertas desde el archivo OPEN_POSITIONS_FILE.
    Si el archivo no existe o hay un error de formato JSON, el bot inicia sin posiciones.
    Asegura que los valores numéricos se carguen como flotantes.
    También inicializa nuevas claves para compatibilidad con versiones anteriores del archivo.
    Requiere el stop_loss_porcentaje para inicializar 'stop_loss_fijo_nivel_actual' si es necesario.
    """
    if os.path.exists(OPEN_POSITIONS_FILE):
        try:
            with open(OPEN_POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                for symbol, pos in data.items():
                    pos['precio_compra'] = float(pos['precio_compra'])
                    pos['cantidad_base'] = float(pos['cantidad_base'])
                    pos['max_precio_alcanzado'] = float(pos['max_precio_alcanzado'])
                    # Inicializar 'sl_moved_to_breakeven' si no existe en el archivo cargado (para compatibilidad).
                    if 'sl_moved_to_breakeven' not in pos:
                        pos['sl_moved_to_breakeven'] = False
                    # Inicializar 'stop_loss_fijo_nivel_actual' si no existe.
                    if 'stop_loss_fijo_nivel_actual' not in pos:
                        # Usar el SL fijo inicial como valor por defecto si no se ha movido.
                        pos['stop_loss_fijo_nivel_actual'] = pos['precio_compra'] * (1 - stop_loss_porcentaje)
                logging.info(f"✅ Posiciones abiertas cargadas desde {OPEN_POSITIONS_FILE}.")
                return data
        except json.JSONDecodeError as e:
            logging.error(f"❌ Error al leer JSON del archivo {OPEN_POSITIONS_FILE}: {e}. Iniciando sin posiciones.")
            return {}
        except Exception as e:
            logging.error(f"❌ Error inesperado al cargar posiciones desde {OPEN_POSITIONS_FILE}: {e}. Iniciando sin posiciones.")
            return {}
    logging.info(f"Archivo de posiciones abiertas '{OPEN_POSITIONS_FILE}' no encontrado. Iniciando sin posiciones.")
    return {}

def save_open_positions_debounced(posiciones_dict):
    """
    Guarda las posiciones abiertas en el archivo OPEN_POSITIONS_FILE, aplicando un mecanismo de "debounce".
    Esto significa que la escritura real en el disco solo se realizará si ha pasado un tiempo mínimo
    (definido por SAVE_POSITIONS_DEBOUNCE_INTERVAL) desde la última escritura.
    Este enfoque reduce las operaciones de I/O de disco, lo que mejora el rendimiento del bot,
    especialmente en entornos de despliegue como Railway donde las operaciones de disco pueden ser más lentas.
    Las operaciones críticas (compra/venta) siguen guardando inmediatamente.
    """
    global last_save_time_positions # Accede a la variable global que rastrea la última vez que se guardó.
    current_time = time.time() # Obtiene el tiempo actual en segundos desde la época.

    # Comprueba si ha pasado suficiente tiempo desde el último guardado debounced.
    if (current_time - last_save_time_positions) >= SAVE_POSITIONS_DEBOUNCE_INTERVAL:
        try:
            with open(OPEN_POSITIONS_FILE, 'w') as f:
                json.dump(posiciones_dict, f, indent=4) # Sobrescribe el archivo con el estado actual del diccionario.
            logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (debounced).")
            last_save_time_positions = current_time # Actualiza la marca de tiempo del último guardado exitoso.
        except IOError as e:
            # Manejo de error si hay un problema al escribir el archivo.
            logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE}: {e}")
    else:
        # Si no ha pasado suficiente tiempo, se registra que el guardado fue pospuesto (para depuración).
        logging.debug(f"⏳ Guardado de posiciones pospuesto. Último guardado hace {current_time - last_save_time_positions:.2f}s.")

