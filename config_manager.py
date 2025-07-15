import os # Módulo para interactuar con el sistema operativo, usado para verificar la existencia de archivos.
import json # Módulo para trabajar con archivos JSON, usado para guardar y cargar configuraciones.
import logging # Módulo para registrar eventos, errores y mensajes informativos.

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre del archivo de configuración para los parámetros del bot.
CONFIG_FILE = "config.json"

def load_parameters():
    """
    Carga los parámetros de configuración del bot desde el archivo CONFIG_FILE.
    Si el archivo no existe o hay un error al leerlo (ej. JSON mal formado),
    devuelve un conjunto de parámetros por defecto.
    Si el archivo no existe, lo crea con los valores por defecto para futuras ejecuciones.
    """
    # Define un diccionario con los parámetros por defecto del bot.
    # Estos valores se usarán si no se encuentra un archivo de configuración o si este está vacío/corrupto.
    default_params = {
        "EMA_PERIODO": 10, # Período para el cálculo de la Media Móvil Exponencial (EMA).
        "RSI_PERIODO": 14, # Período para el cálculo del Índice de Fuerza Relativa (RSI).
        "RSI_UMBRAL_SOBRECOMPRA": 70, # Umbral del RSI por encima del cual se considera que un activo está sobrecomprado.
        "RIESGO_POR_OPERACION_PORCENTAJE": 0.01, # Porcentaje del capital total a arriesgar por cada operación (ej. 0.01 = 1%).
        "TAKE_PROFIT_PORCENTAJE": 0.03, # Porcentaje de ganancia objetivo para cerrar una posición (ej. 0.03 = 3%).
        "STOP_LOSS_PORCENTAJE": 0.02, # Porcentaje de pérdida máxima para cerrar una posición (ej. 0.02 = 2%).
        "TRAILING_STOP_PORCENTAJE": 0.015, # Porcentaje de retroceso desde el máximo para activar el Trailing Stop (ej. 0.015 = 1.5%).
        "INTERVALO": 300, # Intervalo en segundos entre cada ciclo principal de trading del bot (ej. 300s = 5 minutos).
        "TOTAL_BENEFICIO_ACUMULADO": 0.0, # Beneficio/pérdida total acumulado por todas las operaciones cerradas.
        "BREAKEVEN_PORCENTAJE": 0.005 # Porcentaje de ganancia que, una vez alcanzado, mueve el Stop Loss al punto de equilibrio.
    }
    # Comprueba si el archivo de configuración existe en la ruta actual.
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded_params = json.load(f) # Carga los parámetros desde el archivo JSON.
                # Fusiona los parámetros por defecto con los cargados.
                # Los valores cargados sobrescriben los por defecto si existen en el archivo.
                return {**default_params, **loaded_params}
        except json.JSONDecodeError as e:
            # Manejo de error si el archivo JSON está mal formado.
            logging.error(f"❌ Error al leer JSON del archivo {CONFIG_FILE}: {e}. Usando parámetros por defecto.")
            return default_params
        except IOError as e:
            # Manejo de error si hay un problema de I/O al leer el archivo.
            logging.error(f"❌ Error de I/O al leer el archivo {CONFIG_FILE}: {e}. Usando parámetros por defecto.")
            return default_params
    else:
        # Si el archivo de configuración no existe, se crea con los valores por defecto.
        logging.info(f"Archivo de configuración '{CONFIG_FILE}' no encontrado. Creando con parámetros por defecto.")
        save_parameters(default_params) # Llama a la función para guardar los parámetros por defecto.
        return default_params

def save_parameters(params):
    """
    Guarda los parámetros de configuración actuales del bot en el archivo CONFIG_FILE.
    Esta función se llama cada vez que un parámetro es modificado.
    """
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(params, f, indent=4) # Guarda el diccionario de parámetros en formato JSON legible (indent=4).
        logging.info(f"✅ Parámetros guardados en {CONFIG_FILE}.")
    except IOError as e:
        # Manejo de error si hay un problema al escribir el archivo.
        logging.error(f"❌ Error al escribir en el archivo {CONFIG_FILE}: {e}")


