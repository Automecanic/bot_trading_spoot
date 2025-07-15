import os # Módulo para interactuar con el sistema operativo, usado para leer variables de entorno y verificar la existencia de archivos.
import time # Módulo para funciones relacionadas con el tiempo, como pausas (sleep) y medición de la duración de los ciclos.
import logging # Módulo para registrar eventos, errores y mensajes informativos del bot, útil para depuración y monitoreo.
import requests # Módulo para realizar solicitudes HTTP, usado para interactuar con la API de Telegram.
import json # Módulo para trabajar con archivos JSON, usado para guardar y cargar configuraciones y el estado de las posiciones.
import csv # Módulo para trabajar con archivos CSV, usado para generar informes de transacciones.
from binance.client import Client # Cliente oficial de la API de Binance para interactuar con el exchange.
from binance.enums import * # Importa enumeraciones de Binance (ej. KLINE_INTERVAL_1MINUTE) para intervalos de tiempo y otros parámetros.
from datetime import datetime, timedelta # Módulo para manejar fechas y horas, usado en informes diarios y marcas de tiempo.

# --- Configuración de Logging ---
# Configura el sistema de registro (logging) para ver la actividad del bot en la consola o en los logs del servidor.
# level=logging.INFO: Mostrará mensajes informativos, advertencias y errores. Puedes cambiarlo a logging.DEBUG para más detalle.
# format: Define el formato de los mensajes de log (marca de tiempo, nivel de log, mensaje).
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =================== CONFIGURACIÓN (Asegúrate de que estas variables de entorno estén configuradas) ===================

# Claves de API de Binance. ¡NO COMPARTAS ESTAS CLAVES!
# Es CRÍTICO usar variables de entorno (os.getenv) para almacenar estas claves.
# Esto evita que las claves queden expuestas directamente en el código fuente.
# Debes configurar estas variables en tu entorno de ejecución (ej. Railway, Google Colab, terminal local).
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Token de tu bot de Telegram y Chat ID para enviar mensajes.
# TELEGRAM_BOT_TOKEN: Obtén este token único de BotFather en Telegram al crear tu bot.
# TELEGRAM_CHAT_ID: Obtén tu ID de chat hablando con @userinfobot en Telegram.
# Al igual que las claves de Binance, estas también deben configurarse como variables de entorno por seguridad.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Archivos para guardar y cargar los parámetros de configuración y el estado de las posiciones del bot.
# CONFIG_FILE: Almacena los parámetros de la estrategia (TP, SL, EMA, RSI, etc.) de forma persistente.
# OPEN_POSITIONS_FILE: Almacena las posiciones que el bot tiene abiertas y está gestionando, también de forma persistente.
CONFIG_FILE = "config.json"
OPEN_POSITIONS_FILE = "open_positions.json"

# =================== FUNCIONES DE CARGA Y GUARDADO DE PARÁMETROS ===================

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
    else:
        # Si el archivo de configuración no existe, se crea con los valores por defecto.
        logging.info(f"Archivo de configuración '{CONFIG_FILE}' no encontrado. Creando con parámetros por defecto.")
        save_parameters(default_params) # Llama a la función para guardar los parámetros por defecto.
        return default_params

def save_parameters(params):
    """
    Guarda los parámetros de configuración actuales del bot en el archivo CONFIG_FILE.
    Esta función se llama cada vez que un parámetro es modificado (ej. a través de un comando de Telegram).
    """
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(params, f, indent=4) # Guarda el diccionario de parámetros en formato JSON legible (indent=4).
    except IOError as e:
        # Manejo de error si hay un problema al escribir el archivo.
        logging.error(f"❌ Error al escribir en el archivo {CONFIG_FILE}: {e}")

# Cargar parámetros al inicio del bot.
bot_params = load_parameters()

# Asignar los valores del diccionario de parámetros cargado a las variables globales del bot.
# Esto hace que los parámetros sean accesibles en todo el script y asegura que el bot use la configuración persistente.
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT","XRPUSDT", "DOGEUSDT", "MATICUSDT"] # Lista de pares de trading a monitorear.
INTERVALO = bot_params["INTERVALO"]
RIESGO_POR_OPERACION_PORCENTAJE = bot_params["RIESGO_POR_OPERACION_PORCENTAJE"]
TAKE_PROFIT_PORCENTAJE = bot_params["TAKE_PROFIT_PORCENTAJE"]
STOP_LOSS_PORCENTAJE = bot_params["STOP_LOSS_PORCENTAJE"]
TRAILING_STOP_PORCENTAJE = bot_params["TRAILING_STOP_PORCENTAJE"]
EMA_PERIODO = bot_params["EMA_PERIODO"]
RSI_PERIODO = bot_params["RSI_PERIODO"]
RSI_UMBRAL_SOBRECOMPRA = bot_params["RSI_UMBRAL_SOBRECOMPRA"]
TOTAL_BENEFICIO_ACUMULADO = bot_params["TOTAL_BENEFICIO_ACUMULADO"]
BREAKEVEN_PORCENTAJE = bot_params["BREAKEVEN_PORCENTAJE"]

# =================== INICIALIZACIÓN DE CLIENTES BINANCE Y TELEGRAM ===================

# Inicializa el cliente de la API de Binance.
# Se conecta a la red de prueba (testnet=True) para operaciones seguras sin riesgo real.
# client.API_URL se ajusta explícitamente a la URL de la Testnet de Binance.
client = Client(API_KEY, API_SECRET, testnet=True)
client.API_URL = 'https://testnet.binance.vision/api'

# Diccionario para almacenar las posiciones que el bot tiene abiertas y está gestionando.
# La clave es el símbolo (ej. "ETHUSDT") y el valor es un diccionario con detalles de la posición.
# Se inicializará llamando a load_open_positions() más abajo para cargar el estado persistente.
posiciones_abiertas = {}

# Variables para la gestión de la comunicación con Telegram.
last_update_id = 0 # Rastrea el ID del último mensaje procesado para evitar procesar mensajes duplicados.
TELEGRAM_LISTEN_INTERVAL = 5 # Frecuencia (en segundos) con la que el bot revisa nuevos mensajes de Telegram.

# Variables para la gestión de informes diarios de transacciones.
transacciones_diarias = [] # Lista temporal que almacena las transacciones del día actual para el informe CSV.
ultima_fecha_informe_enviado = None # Almacena la fecha del último informe diario enviado para controlar el envío.
last_trading_check_time = 0 # Marca de tiempo de la última ejecución del ciclo de trading principal.

# Variables para la gestión de la persistencia de posiciones abiertas en disco.
last_save_time_positions = 0 # Marca de tiempo de la última vez que se guardó el archivo OPEN_POSITIONS_FILE.
SAVE_POSITIONS_DEBOUNCE_INTERVAL = 60 # Intervalo mínimo (en segundos) entre escrituras del archivo de posiciones.
                                    # Esto reduce las operaciones de I/O de disco para mejorar el rendimiento.

# =================== FUNCIONES DE CARGA Y GUARDADO DE POSICIONES ABIERTAS ===================

def load_open_positions():
    """
    Carga las posiciones abiertas desde el archivo OPEN_POSITIONS_FILE.
    Si el archivo no existe o hay un error de formato JSON, el bot inicia sin posiciones.
    Asegura que todos los valores numéricos importantes se carguen como flotantes.
    También inicializa nuevas claves para compatibilidad con versiones anteriores del archivo.
    """
    if os.path.exists(OPEN_POSITIONS_FILE):
        try:
            with open(OPEN_POSITIONS_FILE, 'r') as f:
                data = json.load(f) # Carga los datos JSON del archivo.
                for symbol, pos in data.items():
                    # Asegurarse de que los valores numéricos sean flotantes.
                    pos['precio_compra'] = float(pos['precio_compra'])
                    pos['cantidad_base'] = float(pos['cantidad_base'])
                    pos['max_precio_alcanzado'] = float(pos['max_precio_alcanzado'])
                    
                    # Inicializar 'sl_moved_to_breakeven' si no existe en el archivo cargado (para compatibilidad).
                    if 'sl_moved_to_breakeven' not in pos:
                        pos['sl_moved_to_breakeven'] = False
                    # Inicializar 'stop_loss_fijo_nivel_actual' si no existe.
                    # Esto asegura que el bot tenga un SL inicial si la posición fue cargada de una versión anterior.
                    if 'stop_loss_fijo_nivel_actual' not in pos:
                        pos['stop_loss_fijo_nivel_actual'] = pos['precio_compra'] * (1 - STOP_LOSS_PORCENTAJE)
                logging.info(f"✅ Posiciones abiertas cargadas desde {OPEN_POSITIONS_FILE}.")
                return data
        except json.JSONDecodeError as e:
            # Manejo de error si el archivo JSON de posiciones está mal formado.
            logging.error(f"❌ Error al leer JSON del archivo {OPEN_POSITIONS_FILE}: {e}. Iniciando sin posiciones.")
            return {}
        except Exception as e:
            # Manejo de cualquier otro error inesperado durante la carga.
            logging.error(f"❌ Error inesperado al cargar posiciones desde {OPEN_POSITIONS_FILE}: {e}. Iniciando sin posiciones.")
            return {}
    logging.info(f"Archivo de posiciones abiertas '{OPEN_POSITIONS_FILE}' no encontrado. Iniciando sin posiciones.")
    return {}

def save_open_positions_debounced():
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
                json.dump(posiciones_abiertas, f, indent=4) # Sobrescribe el archivo con el estado actual del diccionario.
            logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (debounced).")
            last_save_time_positions = current_time # Actualiza la marca de tiempo del último guardado exitoso.
        except IOError as e:
            # Manejo de error si hay un problema al escribir el archivo.
            logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE}: {e}")
    else:
        # Si no ha pasado suficiente tiempo, se registra que el guardado fue pospuesto (para depuración).
        logging.debug(f"⏳ Guardado de posiciones pospuesto. Último guardado hace {current_time - last_save_time_positions:.2f}s.")


# Cargar posiciones abiertas al inicio del bot. Esta es la primera acción de persistencia.
posiciones_abiertas = load_open_positions()

# =================== FUNCIONES AUXILIARES DE UTILIDAD ===================

def send_telegram_message(message):
    """
    Envía un mensaje de texto al chat de Telegram configurado.
    Permite formato HTML básico (ej. <b> para negrita, <code> para código) para mejorar la legibilidad.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes.")
        return False # Retorna False si la configuración de Telegram no está completa.

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML' # Habilita el formato HTML en el mensaje.
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status() # Lanza una excepción para códigos de estado HTTP de error (4xx o 5xx).
        return True # Retorna True si el mensaje se envió con éxito.
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al enviar mensaje a Telegram: {e}")
        return False

def send_telegram_document(chat_id, file_path, caption=""):
    """
    Envía un documento (ej. un archivo CSV de transacciones) a un chat de Telegram específico.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se pueden enviar documentos.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(file_path, 'rb') as doc: # Abre el archivo en modo binario para lectura ('rb').
            files = {'document': doc} # Prepara el archivo para ser enviado en la solicitud multipart/form-data.
            payload = {'chat_id': chat_id, 'caption': caption} # Parámetros adicionales (chat_id, descripción del documento).
            response = requests.post(url, data=payload, files=files) # Envía la solicitud POST.
            response.raise_for_status()
            logging.info(f"✅ Documento {file_path} enviado con éxito a Telegram.")
            return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error enviando documento Telegram '{file_path}': {e}")
        send_telegram_message(f"❌ Error enviando documento: {e}") # Notifica al usuario por Telegram si falla el envío.
        return False
    except Exception as e:
        logging.error(f"❌ Error inesperado en send_telegram_document: {e}")
        send_telegram_message(f"❌ Error inesperado enviando documento: {e}")
        return False

def obtener_saldo_moneda(asset):
    """
    Obtiene el saldo disponible (free balance) de una moneda específica de tu cuenta de Binance.
    'free' balance es la cantidad que no está bloqueada en órdenes abiertas.
    """
    try:
        balance = client.get_asset_balance(asset=asset)
        return float(balance['free'])
    except Exception as e:
        logging.error(f"❌ Error al obtener saldo de {asset}: {e}")
        return 0.0

def obtener_precio_actual(symbol):
    """
    Obtiene el precio de mercado actual de un par de trading (símbolo) de Binance.
    """
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except Exception as e:
        logging.error(f"❌ Error al obtener precio de {symbol}: {e}")
        return 0.0

def obtener_precio_eur():
    """
    Obtiene el tipo de cambio actual de USDT a EUR desde Binance (usando el par EURUSDT).
    Útil para mostrar el capital total en euros en los informes.
    """
    try:
        eur_usdt_price = client.get_avg_price(symbol='EURUSDT')
        return 1 / float(eur_usdt_price['price']) # Convierte de EUR/USDT a USDT/EUR.
    except Exception as e:
        logging.warning(f"⚠️ No se pudo obtener el precio de EURUSDT: {e}. Usando 0 para la conversión a EUR.")
        return 0.0 # Retorna 0.0 si no se puede obtener el precio para evitar errores.

def obtener_saldos_formateados():
    """
    Formatea un mensaje con los saldos de USDT disponibles y el capital total estimado (en USDT y EUR).
    El capital total incluye el USDT disponible y el valor actual de todas las posiciones abiertas.
    """
    try:
        saldo_usdt = obtener_saldo_moneda("USDT") # Saldo de USDT disponible.
        capital_total_usdt = saldo_usdt # Inicializa el capital total con el USDT disponible.
        
        # Sumar el valor actual de todas las posiciones abiertas al capital total.
        for symbol, pos in posiciones_abiertas.items():
            precio_actual = obtener_precio_actual(symbol)
            capital_total_usdt += pos['cantidad_base'] * precio_actual # Valor de la posición = cantidad * precio actual.
        
        eur_usdt_rate = obtener_precio_eur() # Obtiene el tipo de cambio para la conversión a EUR.
        capital_total_eur = capital_total_usdt * eur_usdt_rate if eur_usdt_rate else 0 # Convierte a EUR si el tipo de cambio es válido.

        return (f"💰 Saldo USDT: {saldo_usdt:.2f}\n"
                f"💲 Capital Total (USDT): {capital_total_usdt:.2f}\n"
                f"💶 Capital Total (EUR): {capital_total_eur:.2f}")
    except Exception as e:
        logging.error(f"❌ Error al obtener saldos formateados: {e}")
        return "❌ Error al obtener saldos."

def calcular_ema(precios_cierre, periodo):
    """
    Calcula la Media Móvil Exponencial (EMA) para una lista de precios de cierre.
    periodo: Número de períodos para el cálculo de la EMA (ej. 10 para EMA de 10 períodos).
    """
    if len(precios_cierre) < periodo:
        return None # No hay suficientes datos para calcular la EMA.
    
    # Cálculo inicial de la EMA: Se usa el promedio simple (SMA) de los primeros 'periodo' datos.
    ema = sum(precios_cierre[:periodo]) / periodo
    multiplier = 2 / (periodo + 1) # Factor de suavizado para la EMA, que da más peso a los datos recientes.
    
    # Iterar para calcular la EMA para los puntos restantes usando la fórmula exponencial.
    for i in range(periodo, len(precios_cierre)):
        ema = ((precios_cierre[i] - ema) * multiplier) + ema
    return ema

def calcular_rsi(precios_cierre, periodo):
    """
    Calcula el Índice de Fuerza Relativa (RSI) para una lista de precios de cierre.
    El RSI es un oscilador de momentum que mide la velocidad y el cambio de los movimientos de los precios.
    periodo: Número de períodos para el cálculo del RSI (ej. 14 para RSI de 14 períodos).
    """
    if len(precios_cierre) < periodo + 1: # Se necesita al menos 'periodo + 1' datos para el primer cálculo del RSI.
        return None

    # Calcular las diferencias de precios entre velas consecutivas.
    precios_diff = [precios_cierre[i] - precios_cierre[i-1] for i in range(1, len(precios_cierre))]
    
    # Separar las ganancias (diferencias positivas) y pérdidas (diferencias negativas).
    ganancias = [d if d > 0 else 0 for d in precios_diff]
    perdidas = [-d if d < 0 else 0 for d in precios_diff] # Las pérdidas se guardan como valores positivos.

    # Calcular el promedio inicial de ganancias y pérdidas para el primer 'periodo'.
    avg_ganancia = sum(ganancias[:periodo]) / periodo
    avg_perdida = sum(perdidas[:periodo]) / periodo

    if avg_perdida == 0:
        return 100 # Si no hay pérdidas en el período inicial, el RSI es 100 (evita división por cero).
    
    # Calcular RS (Relative Strength) y RSI inicial.
    rs = avg_ganancia / avg_perdida
    rsi = 100 - (100 / (1 + rs))

    # Iterar para calcular el RSI para los puntos restantes (fórmula de suavizado exponencial).
    for i in range(periodo, len(ganancias)):
        avg_ganancia = ((avg_ganancia * (periodo - 1)) + ganancias[i]) / periodo
        avg_perdida = ((avg_perdida * (periodo - 1)) + perdidas[i]) / periodo
        
        if avg_perdida == 0:
            rsi = 100 # Si no hay pérdidas en el período actual, RSI es 100.
        else:
            rs = avg_ganancia / avg_perdida
            rsi = 100 - (100 / (1 + rs))
    return rsi

def calcular_ema_rsi(symbol, ema_periodo, rsi_periodo):
    """
    Obtiene los datos de las velas (klines) de Binance para un símbolo dado
    y luego calcula la EMA y el RSI utilizando esos datos.
    """
    try:
        # Obtener suficientes klines para ambos cálculos, más un margen extra para asegurar datos completos.
        limit = max(ema_periodo, rsi_periodo) + 10
        # Solicita klines de 1 minuto.
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=limit)
        
        # Extraer solo los precios de cierre de las velas.
        precios_cierre = [float(kline[4]) for kline in klines]
        
        ema = calcular_ema(precios_cierre, ema_periodo)
        rsi = calcular_rsi(precios_cierre, rsi_periodo)
        
        return ema, rsi
    except Exception as e:
        logging.error(f"❌ Error al obtener klines o calcular indicadores para {symbol}: {e}")
        return None, None # Retorna None si hay un error para indicar que los cálculos fallaron.

def get_step_size(symbol):
    """
    Obtiene el 'stepSize' para un símbolo de Binance.
    El 'stepSize' es el incremento mínimo permitido para la cantidad de una orden (ej. 0.001 BTC).
    Es crucial para ajustar las cantidades de compra/venta y evitar errores de precisión de la API (-1111).
    """
    try:
        info = client.get_symbol_info(symbol) # Obtiene información detallada del símbolo.
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE': # Busca el filtro LOT_SIZE, que contiene el stepSize.
                return float(f['stepSize'])
        logging.warning(f"⚠️ No se encontró LOT_SIZE filter para {symbol}. Usando stepSize por defecto: 0.000001")
        return 0.000001 # Valor predeterminado muy pequeño si no se encuentra (para evitar división por cero o errores).
    except Exception as e:
        logging.error(f"❌ Error al obtener stepSize para {symbol}: {e}")
        return 0.000001

def ajustar_cantidad(cantidad, step_size):
    """
    Ajusta una cantidad dada para que sea un múltiplo exacto del 'step_size' de Binance
    y con la precisión correcta en decimales. Esto es vital para evitar el error -1111 de Binance.
    """
    if step_size == 0:
        logging.warning("⚠️ step_size es 0, no se puede ajustar la cantidad.")
        return 0.0

    # Determinar el número de decimales que requiere el step_size.
    # Ej: step_size = 0.001 -> decimal_places = 3
    s_step_size = str(step_size)
    if '.' in s_step_size:
        # Contar decimales después del punto, eliminando ceros finales si step_size es "0.010" para obtener la precisión real.
        decimal_places = len(s_step_size.split('.')[1].rstrip('0'))
    else:
        decimal_places = 0 # No hay decimales si step_size es un entero (ej. 1.0).

    try:
        # Multiplica la cantidad y el step_size por una potencia de 10 para trabajar con enteros,
        # luego redondea al múltiplo más cercano del step_size y finalmente divide.
        # Esto minimiza los problemas de precisión de punto flotante.
        factor = 10**decimal_places
        ajustada = (round(cantidad * factor / (step_size * factor)) * (step_size * factor)) / factor
        
        # Formatear la cantidad ajustada a una cadena con la precisión exacta requerida,
        # y luego convertirla de nuevo a float. Esto elimina cualquier "cola" de decimales no deseada.
        formatted_quantity_str = f"{ajustada:.{decimal_places}f}"
        return float(formatted_quantity_str)
    except Exception as e:
        logging.error(f"❌ Error al ajustar cantidad {cantidad} con step {step_size}: {e}")
        return 0.0

def calcular_cantidad_a_comprar(saldo_usdt, precio_actual, stop_loss_porcentaje, symbol):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el riesgo por operación
    definido y el porcentaje de stop loss. También considera el mínimo nocional de Binance
    y el saldo USDT disponible.
    """
    if precio_actual <= 0:
        logging.warning("El precio actual es cero o negativo, no se puede calcular la cantidad a comprar.")
        return 0.0

    capital_total = saldo_usdt # El riesgo se calcula sobre el saldo USDT disponible.
    riesgo_max_por_operacion_usdt = capital_total * RIESGO_POR_OPERACION_PORCENTAJE
    
    # Calcula la diferencia de precio en USDT por unidad si se activa el stop loss.
    diferencia_precio_sl = precio_actual * stop_loss_porcentaje
    
    if diferencia_precio_sl <= 0:
        logging.warning("La diferencia de precio con el SL es cero o negativa, no se puede calcular la cantidad a comprar.")
        return 0.0

    # Calcula la cantidad de unidades que se pueden comprar para no exceder el riesgo máximo por operación.
    cantidad_a_comprar = riesgo_max_por_operacion_usdt / diferencia_precio_sl

    step = get_step_size(symbol) # Obtiene el stepSize para la precisión.
    min_notional = 10.0 # Valor nocional mínimo de una orden en USDT para la mayoría de pares en Binance.

    cantidad_ajustada = ajustar_cantidad(cantidad_a_comprar, step)
    
    # Verificar si la cantidad calculada es demasiado pequeña para el mínimo nocional de Binance.
    if (cantidad_ajustada * precio_actual) < min_notional:
        logging.warning(f"La cantidad calculada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) es demasiado pequeña para el mínimo nocional de {min_notional} USDT.")
        # Si es demasiado pequeña, intenta ajustar a la cantidad mínima nocional permitida por Binance.
        min_cantidad_ajustada = ajustar_cantidad(min_notional / precio_actual, step)
        if (min_cantidad_ajustada * precio_actual) <= saldo_usdt:
            cantidad_ajustada = min_cantidad_ajustada
            logging.info(f"Ajustando a la cantidad mínima nocional permitida: {cantidad_ajustada:.6f} {symbol.replace('USDT', '')}")
        else:
            logging.warning(f"No hay suficiente saldo USDT para comprar la cantidad mínima nocional de {symbol}.")
            return 0.0 # No se puede comprar ni la cantidad mínima.

    # Asegurarse de no comprar más de lo que el saldo USDT disponible permite.
    if (cantidad_ajustada * precio_actual) > saldo_usdt:
        logging.warning(f"La cantidad ajustada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) excede el saldo disponible en USDT. Reduciendo a lo máximo posible.")
        cantidad_max_posible = ajustar_cantidad(saldo_usdt / precio_actual, step)
        if (cantidad_max_posible * precio_actual) >= min_notional: # Asegura que la cantidad máxima posible aún cumpla el mínimo nocional.
            cantidad_ajustada = cantidad_max_posible
        else:
            logging.warning(f"El saldo restante no permite comprar ni la cantidad mínima nocional de {symbol}.")
            return 0.0 # No se puede comprar.

    return cantidad_ajustada

def comprar(symbol, cantidad):
    """
    Ejecuta una orden de compra de mercado en Binance para un símbolo y cantidad dados.
    Registra la operación en los logs y en la lista de transacciones diarias.
    Además, guarda la nueva posición en el archivo de persistencia (OPEN_POSITIONS_FILE).
    """
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de compra de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        # Ejecuta la orden de compra de mercado.
        order = client.order_market_buy(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE COMPRA EXITOSA para {symbol}: {order}")
        
        # Procesa la respuesta de la orden si fue exitosa.
        if order and 'fills' in order and len(order['fills']) > 0:
            precio_ejecucion = float(order['fills'][0]['price']) # Precio real al que se ejecutó la orden.
            qty_ejecutada = float(order['fills'][0]['qty']) # Cantidad real que se compró.
            
            # Almacena los detalles de la nueva posición abierta en el diccionario en memoria.
            posiciones_abiertas[symbol] = {
                'precio_compra': precio_ejecucion,
                'cantidad_base': qty_ejecutada,
                'max_precio_alcanzado': precio_ejecucion, # Inicializa el precio máximo alcanzado con el precio de compra.
                'sl_moved_to_breakeven': False, # Inicializa el estado del Stop Loss a breakeven para esta nueva posición.
                'stop_loss_fijo_nivel_actual': precio_ejecucion * (1 - STOP_LOSS_PORCENTAJE) # Inicializa el SL actual.
            }
            # Guardar inmediatamente las posiciones en el archivo después de una compra exitosa.
            # Esto asegura que el estado de la posición se persista inmediatamente después de la operación crítica.
            try:
                with open(OPEN_POSITIONS_FILE, 'w') as f:
                    json.dump(posiciones_abiertas, f, indent=4)
                logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (después de compra).")
            except IOError as e:
                logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE} después de compra: {e}")
            
            # Registrar la transacción en la lista diaria para el informe CSV.
            transacciones_diarias.append({
                'FechaHora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'Símbolo': symbol,
                'Tipo': 'COMPRA',
                'Precio': precio_ejecucion,
                'Cantidad': qty_ejecutada,
                'GananciaPerdidaUSDT': 0.0, # En la compra no hay ganancia/pérdida inmediata.
                'Motivo': 'Condiciones de entrada'
            })
        return order
    except Exception as e:
        logging.error(f"❌ FALLO DE ORDEN DE COMPRA para {symbol} (Cantidad: {cantidad}): {e}")
        send_telegram_message(f"❌ Error en compra de {symbol}: {e}") # Notifica al usuario por Telegram si la compra falla.
        return None

def vender(symbol, cantidad, motivo_venta="Desconocido"):
    """
    Ejecuta una orden de venta de mercado en Binance para un símbolo y cantidad dados.
    Calcula la ganancia/pérdida de la operación, actualiza el beneficio total acumulado,
    elimina la posición del registro en memoria y guarda el estado en el archivo de persistencia.
    """
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de venta de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        # Ejecuta la orden de venta de mercado.
        order = client.order_market_sell(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE VENTA EXITOSA para {symbol}: {order}")
        
        ganancia_perdida_usdt = 0.0
        # Obtiene el precio real de ejecución de la venta.
        precio_venta_ejecutada = float(order['fills'][0]['price']) if order and 'fills' in order and len(order['fills']) > 0 else 0.0

        if symbol in posiciones_abiertas:
            precio_compra = posiciones_abiertas[symbol]['precio_compra']
            # Calcula la ganancia o pérdida de la operación.
            ganancia_perdida_usdt = (precio_venta_ejecutada - precio_compra) * cantidad
            
            # Actualizar el beneficio total acumulado y guardarlo en config.json.
            global TOTAL_BENEFICIO_ACUMULADO # Accede a la variable global.
            TOTAL_BENEFICIO_ACUMULADO += ganancia_perdida_usdt # Suma la ganancia/pérdida de esta operación.
            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = TOTAL_BENEFICIO_ACUMULADO # Actualiza el diccionario de parámetros.
            save_parameters(bot_params) # Guarda los parámetros (incluido el beneficio total).

            # Eliminar la posición del diccionario en memoria, ya que ha sido cerrada.
            posiciones_abiertas.pop(symbol)
            # Guardar inmediatamente las posiciones en el archivo después de una venta exitosa.
            # Esto asegura que el estado de la posición se persista inmediatamente después de la operación crítica.
            try:
                with open(OPEN_POSITIONS_FILE, 'w') as f:
                    json.dump(posiciones_abiertas, f, indent=4)
                logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (después de venta).")
            except IOError as e:
                logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE} después de venta: {e}")

        # Registrar la transacción en la lista diaria para el informe CSV.
        transacciones_diarias.append({
            'FechaHora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'Símbolo': symbol,
            'Tipo': 'VENTA',
            'Precio': precio_venta_ejecutada,
            'Cantidad': float(order['fills'][0]['qty']) if order and 'fills' in order and len(order['fills']) > 0 else 0.0,
            'GananciaPerdidaUSDT': ganancia_perdida_usdt,
            'Motivo': motivo_venta
        })
        return order
    except Exception as e:
        logging.error(f"❌ FALLO DE ORDEN DE VENTA para {symbol} (Cantidad: {cantidad}): {e}")
        send_telegram_message(f"❌ Error en venta de {symbol}: {e}")
        return None

def vender_por_comando(symbol):
    """
    Intenta vender una posición abierta para un símbolo específico,
    activada por un comando de Telegram (ej. /vender BTCUSDT).
    Verifica si el bot tiene una posición registrada y si hay saldo real en Binance para vender.
    """
    # Comprueba si el símbolo está registrado como una posición abierta en el bot.
    if symbol not in posiciones_abiertas:
        send_telegram_message(f"❌ No hay una posición abierta para <b>{symbol}</b> que gestionar por comando.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero no hay posición abierta.")
        return

    base_asset = symbol.replace("USDT", "") # Extrae la moneda base (ej. "BTC" de "BTCUSDT").
    cantidad_en_posicion = obtener_saldo_moneda(base_asset) # Obtiene el saldo real disponible de esa moneda en Binance.

    if cantidad_en_posicion <= 0:
        send_telegram_message(f"❌ No hay saldo disponible de <b>{base_asset}</b> para vender.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero el saldo es 0.")
        return

    step = get_step_size(symbol) # Obtiene el stepSize para ajustar la cantidad.
    cantidad_a_vender_ajustada = ajustar_cantidad(cantidad_en_posicion, step) # Ajusta la cantidad al stepSize.

    if cantidad_a_vender_ajustada <= 0:
        send_telegram_message(f"❌ La cantidad de <b>{base_asset}</b> a vender es demasiado pequeña o inválida.")
        logging.warning(f"Cantidad a vender ajustada para {symbol} es <= 0: {cantidad_a_vender_ajustada}")
        return

    send_telegram_message(f"⚙️ Intentando vender <b>{cantidad_a_vender_ajustada:.6f} {base_asset}</b> de <b>{symbol}</b> por comando...")
    logging.info(f"Comando de venta manual recibido para {symbol}. Cantidad a vender: {cantidad_a_vender_ajustada}")

    # Llama a la función 'vender' principal para ejecutar la orden.
    orden = vender(symbol, cantidad_a_vender_ajustada, motivo_venta="Venta manual por comando")

    if orden:
        logging.info(f"Venta de {symbol} ejecutada con éxito por comando.")
    else:
        send_telegram_message(f"❌ Fallo al ejecutar la venta de <b>{symbol}</b> por comando. Revisa los logs.")
        logging.error(f"Fallo al ejecutar la venta de {symbol} por comando.")

# =================== MANEJADOR DE COMANDOS DE TELEGRAM ===================

def get_telegram_updates(offset=None):
    """
    Obtiene actualizaciones (mensajes) del bot de Telegram usando el método long polling.
    El parámetro 'offset' es crucial para que el bot solo procese mensajes nuevos
    y evite procesar mensajes que ya fueron manejados en iteraciones anteriores.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {'timeout': 30, 'offset': offset} # 'timeout' para long polling: espera hasta 30 segundos por actualizaciones.
    try:
        response = requests.get(url, params=params)
        response.raise_for_status() # Lanza una excepción para códigos de estado HTTP de error (4xx o 5xx).
        return response.json() # Devuelve la respuesta JSON de la API de Telegram.
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al obtener actualizaciones de Telegram: {e}")
        return None

def handle_telegram_commands():
    """
    Procesa los comandos recibidos por Telegram en cada ciclo de escucha.
    Analiza el texto del mensaje, identifica el comando y ejecuta la función correspondiente.
    También actualiza las variables globales de los parámetros del bot y los guarda si son modificados.
    """
    global last_update_id, RIESGO_POR_OPERACION_PORCENTAJE, TAKE_PROFIT_PORCENTAJE, \
           STOP_LOSS_PORCENTAJE, TRAILING_STOP_PORCENTAJE, EMA_PERIODO, RSI_PERIODO, \
           RSI_UMBRAL_SOBRECOMPRA, INTERVALO, bot_params, TOTAL_BENEFICIO_ACUMULADO, BREAKEVEN_PORCENTAJE

    updates = get_telegram_updates(last_update_id + 1) # Obtiene solo los mensajes nuevos (desde last_update_id + 1).

    if updates and updates['ok']: # Si hay actualizaciones y la respuesta de la API es exitosa.
        for update in updates['result']: # Itera sobre cada actualización (mensaje).
            last_update_id = update['update_id'] # Actualiza el ID del último mensaje procesado.

            if 'message' in update and 'text' in update['message']: # Asegura que la actualización es un mensaje de texto.
                chat_id = str(update['message']['chat']['id']) # Obtiene el ID del chat de donde proviene el mensaje.
                text = update['message']['text'].strip() # Obtiene el texto del mensaje y elimina espacios extra.
                
                # Medida de seguridad: solo procesar comandos del CHAT_ID autorizado.
                if chat_id != TELEGRAM_CHAT_ID:
                    send_telegram_message(f"⚠️ Comando recibido de chat no autorizado: <code>{chat_id}</code>")
                    logging.warning(f"Comando de chat no autorizado: {chat_id}")
                    continue # Ignora el mensaje y pasa al siguiente.

                parts = text.split() # Divide el mensaje en partes (ej. "/set_tp", "0.04").
                command = parts[0].lower() # El primer elemento es el comando (convertido a minúsculas para flexibilidad).
                
                logging.info(f"Comando Telegram recibido: {text}") # Registra el comando recibido.

                try:
                    # --- Comandos para mostrar/ocultar el teclado personalizado de Telegram ---
                    if command == "/start" or command == "/menu":
                        send_keyboard_menu(chat_id, "¡Hola! Soy tu bot de trading. Selecciona una opción del teclado o usa /help.")
                    elif command == "/hide_menu":
                        remove_keyboard_menu(chat_id)
                    
                    # --- Comandos para establecer parámetros de estrategia (modifican config.json) ---
                    elif command == "/set_tp":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            TAKE_PROFIT_PORCENTAJE = new_value
                            bot_params['TAKE_PROFIT_PORCENTAJE'] = new_value
                            save_parameters(bot_params) # Guarda el parámetro actualizado en config.json.
                            send_telegram_message(f"✅ TP establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_tp &lt;porcentaje_decimal_ej_0.03&gt;</code>")
                    elif command == "/set_sl_fijo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            STOP_LOSS_PORCENTAJE = new_value
                            bot_params['STOP_LOSS_PORCENTAJE'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ SL Fijo establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_sl_fijo &lt;porcentaje_decimal_ej_0.02&gt;</code>")
                    elif command == "/set_tsl":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            TRAILING_STOP_PORCENTAJE = new_value
                            bot_params['TRAILING_STOP_PORCENTAJE'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ TSL establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_tsl &lt;porcentaje_decimal_ej_0.015&gt;</code>")
                    elif command == "/set_riesgo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            RIESGO_POR_OPERACION_PORCENTAJE = new_value
                            bot_params['RIESGO_POR_OPERACION_PORCENTAJE'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ Riesgo por operación establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_riesgo &lt;porcentaje_decimal_ej_0.01&gt;</code>")
                    elif command == "/set_ema_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            EMA_PERIODO = new_value
                            bot_params['EMA_PERIODO'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ Período EMA establecido en: <b>{new_value}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_ema_periodo &lt;numero_entero_ej_10&gt;</code>")
                    elif command == "/set_rsi_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            RSI_PERIODO = new_value
                            bot_params['RSI_PERIODO'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ Período RSI establecido en: <b>{new_value}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_rsi_periodo &lt;numero_entero_ej_14&gt;</code>")
                    elif command == "/set_rsi_umbral":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            RSI_UMBRAL_SOBRECOMPRA = new_value
                            bot_params['RSI_UMBRAL_SOBRECOMPRA'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ Umbral RSI sobrecompra establecido en: <b>{new_value}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_rsi_umbral &lt;numero_entero_ej_70&gt;</code>")
                    elif command == "/set_intervalo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            INTERVALO = new_value
                            bot_params['INTERVALO'] = new_value
                            save_parameters(bot_params)
                            send_telegram_message(f"✅ Intervalo del ciclo establecido en: <b>{new_value}</b> segundos")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_intervalo &lt;segundos_ej_300&gt;</code>")
                    elif command == "/set_breakeven_porcentaje": # Comando para establecer el porcentaje de Breakeven.
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            BREAKEVEN_PORCENTAJE = new_value # Actualiza la variable global.
                            bot_params['BREAKEVEN_PORCENTAJE'] = new_value # Actualiza el diccionario de parámetros.
                            save_parameters(bot_params) # Guarda el parámetro actualizado.
                            send_telegram_message(f"✅ Porcentaje de Breakeven establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_breakeven_porcentaje &lt;porcentaje_decimal_ej_0.005&gt;</code>")
                    
                    # --- Comandos de información y utilidades ---
                    elif command == "/get_params":
                        # Muestra todos los parámetros de configuración actuales del bot.
                        current_params_msg = "<b>Parámetros Actuales:</b>\n"
                        for key, value in bot_params.items():
                            # Formatear porcentajes a 4 decimales para mayor claridad.
                            if isinstance(value, float) and 'PORCENTAJE' in key.upper():
                                current_params_msg += f"- {key}: {value:.4f}\n"
                            else:
                                current_params_msg += f"- {key}: {value}\n"
                        send_telegram_message(current_params_msg)
                    elif command == "/csv":
                        send_telegram_message("Generando informe CSV. Esto puede tardar un momento...")
                        generar_y_enviar_csv_ahora() # Llama a la función para generar y enviar el CSV bajo demanda.
                    elif command == "/help":
                        send_help_message() # Muestra el mensaje de ayuda.
                        send_keyboard_menu(chat_id, "Aquí tienes los comandos disponibles. También puedes usar el teclado de abajo:") # Muestra el teclado.
                    elif command == "/vender":
                        if len(parts) == 2:
                            symbol_to_sell = parts[1].upper() # Convierte el símbolo a mayúsculas (ej. "btcusdt" a "BTCUSDT").
                            # Verifica si el símbolo es uno de los que el bot monitorea.
                            if symbol_to_sell in SYMBOLS:
                                vender_por_comando(symbol_to_sell) # Llama a la función de venta manual.
                            else:
                                send_telegram_message(f"❌ Símbolo <b>{symbol_to_sell}</b> no reconocido o no monitoreado por el bot.")
                        else:
                            send_telegram_message("❌ Uso: <code>/vender &lt;SIMBOLO_USDT&gt;</code> (ej. /vender BTCUSDT)")
                    elif command == "/beneficio":
                        send_beneficio_message() # Muestra el beneficio total acumulado.
                    elif command == "/get_positions_file":
                        send_positions_file_content() # Muestra el contenido del archivo de posiciones abiertas (para depuración).
                    else:
                        send_telegram_message("Comando desconocido. Usa <code>/help</code> para ver los comandos disponibles.")

                except ValueError:
                    # Manejo de error si el valor proporcionado no es un número válido.
                    send_telegram_message("❌ Valor inválido. Asegúrate de introducir un número o porcentaje correcto.")
                except Exception as ex:
                    # Manejo de cualquier otra excepción inesperada durante el procesamiento de comandos.
                    logging.error(f"Error procesando comando '{text}': {ex}", exc_info=True) # Registra el error completo.
                    send_telegram_message(f"❌ Error interno al procesar comando: {ex}") # Notifica al usuario.

# =================== FUNCIONES DE INFORMES CSV ===================

def generar_y_enviar_csv_ahora():
    """
    Genera un archivo CSV con las transacciones registradas en la lista 'transacciones_diarias' hasta el momento.
    Este informe se puede solicitar bajo demanda con el comando /csv.
    """
    if not transacciones_diarias:
        send_telegram_message("🚫 No hay transacciones registradas para generar el CSV.")
        return

    fecha_actual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") # Formato de fecha y hora para el nombre del archivo.
    nombre_archivo_csv = f"transacciones_historico_{fecha_actual}.csv"

    try:
        with open(nombre_archivo_csv, 'w', newline='', encoding='utf-8') as csvfile:
            # Define los nombres de las columnas del CSV.
            fieldnames = ['FechaHora', 'Símbolo', 'Tipo', 'Precio', 'Cantidad', 'GananciaPerdidaUSDT', 'Motivo']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames) # Crea un objeto DictWriter para escribir diccionarios.

            writer.writeheader() # Escribe la fila de encabezados en el CSV.
            for transaccion in transacciones_diarias:
                writer.writerow(transaccion) # Escribe cada diccionario de transacción como una fila.

        send_telegram_document(TELEGRAM_CHAT_ID, nombre_archivo_csv, f"📊 Informe de transacciones generado: {fecha_actual}")
        
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el CSV bajo demanda: {e}", exc_info=True)
        send_telegram_message(f"❌ Error al generar o enviar el CSV: {e}")
    finally:
        # Asegurarse de eliminar el archivo local después de enviarlo para no acumular archivos.
        if os.path.exists(nombre_archivo_csv):
            os.remove(nombre_archivo_csv)

def enviar_informe_diario():
    """
    Genera un archivo CSV con las transacciones registradas para el día y lo envía por Telegram.
    Esta función se ejecuta automáticamente una vez al día al cambio de fecha.
    """
    if not transacciones_diarias:
        send_telegram_message("🚫 No hay transacciones registradas para el día de hoy.")
        return

    fecha_diario = datetime.now().strftime("%Y-%m-%d") # Formato de fecha para el informe diario.
    nombre_archivo_diario_csv = f"transacciones_diarias_{fecha_diario}.csv"
    
    try:
        with open(nombre_archivo_diario_csv, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['FechaHora', 'Símbolo', 'Tipo', 'Precio', 'Cantidad', 'GananciaPerdidaUSDT', 'Motivo']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for transaccion in transacciones_diarias:
                writer.writerow(transaccion)
        send_telegram_document(TELEGRAM_CHAT_ID, nombre_archivo_diario_csv, f"📊 Informe diario de transacciones para {fecha_diario}")
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el informe diario CSV: {e}", exc_info=True)
        send_telegram_message(f"❌ Error al generar o enviar el informe diario CSV: {e}")
    finally:
        if os.path.exists(nombre_archivo_diario_csv):
            os.remove(nombre_archivo_diario_csv)
    transacciones_diarias.clear() # Limpia las transacciones para el nuevo día después de enviar el informe.

# =================== FUNCIÓN DE BENEFICIO TOTAL ===================

def send_beneficio_message():
    """
    Envía el beneficio total acumulado por el bot a Telegram.
    Este beneficio incluye la suma de ganancias y pérdidas de todas las operaciones cerradas
    desde que el bot tiene registro persistente.
    """
    global TOTAL_BENEFICIO_ACUMULADO # Accede a la variable global del beneficio acumulado.
    
    eur_usdt_rate = obtener_precio_eur() # Obtiene el tipo de cambio actual para la conversión a EUR.
    beneficio_eur = TOTAL_BENEFICIO_ACUMULADO * eur_usdt_rate if eur_usdt_rate else 0.0 # Calcula el beneficio en EUR.

    message = (
        f"📈 <b>Beneficio Total Acumulado:</b>\n"
        f"   - <b>{TOTAL_BENEFICIO_ACUMULADO:.2f} USDT</b>\n"
        f"   - <b>{beneficio_eur:.2f} EUR</b>"
    )
    send_telegram_message(message)

# =================== FUNCIONES DE TECLADO PERSONALIZADO DE TELEGRAM ===================

def send_keyboard_menu(chat_id, message_text="Selecciona una opción:"):
    """
    Envía un mensaje a Telegram que incluye un teclado personalizado con botones.
    Este teclado aparece en lugar del teclado normal del dispositivo del usuario.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede enviar el teclado personalizado.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # Define la estructura del teclado. 'keyboard' es una lista de listas de botones.
    # Cada lista interna representa una fila de botones.
    keyboard = {
        'keyboard': [
            [{'text': '/beneficio'}, {'text': '/get_params'}], # Fila 1: Beneficio y Parámetros.
            [{'text': '/csv'}, {'text': '/help'}], # Fila 2: CSV y Ayuda.
            [{'text': '/vender BTCUSDT'}] # Fila 3: Ejemplo de comando con argumento. El usuario puede editarlo antes de enviar.
        ],
        'resize_keyboard': True, # Hace que el teclado sea más compacto y se ajuste al tamaño de la pantalla.
        'one_time_keyboard': False # Si es True, el teclado desaparece después de un uso. False lo mantiene visible.
    }

    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'reply_markup': json.dumps(keyboard) # Convierte el diccionario del teclado a una cadena JSON.
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info("✅ Teclado personalizado enviado con éxito.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al enviar teclado personalizado a Telegram: {e}")
        return False

def remove_keyboard_menu(chat_id, message_text="Teclado oculto."):
    """
    Oculta el teclado personalizado de Telegram, volviendo al teclado normal del dispositivo.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede ocultar el teclado.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    # 'remove_keyboard' es una instrucción especial para Telegram para ocultar el teclado actual.
    remove_keyboard = {
        'remove_keyboard': True
    }

    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'reply_markup': json.dumps(remove_keyboard)
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info("✅ Teclado personalizado ocultado con éxito.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al ocultar teclado personalizado: {e}")
        return False

# =================== CONFIGURACIÓN DEL MENÚ DE COMANDOS DE TELEGRAM ===================

def set_telegram_commands_menu():
    """
    Configura el menú de comandos que aparece cuando el usuario escribe '/' en el campo de texto de Telegram.
    Esta función debe ser llamada una vez al inicio del bot para registrar los comandos con la API de Telegram.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede configurar el menú de comandos.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    
    # Define la lista de comandos con su nombre y una breve descripción.
    # Estas descripciones aparecerán en el menú desplegable de Telegram.
    commands = [
        {"command": "get_params", "description": "Muestra los parámetros actuales del bot"},
        {"command": "set_tp", "description": "Establece el Take Profit (ej. /set_tp 0.03)"},
        {"command": "set_sl_fijo", "description": "Establece el Stop Loss Fijo (ej. /set_sl_fijo 0.02)"},
        {"command": "set_tsl", "description": "Establece el Trailing Stop Loss (ej. /set_tsl 0.015)"},
        {"command": "set_riesgo", "description": "Establece el riesgo por operación (ej. /set_riesgo 0.01)"},
        {"command": "set_ema_periodo", "description": "Establece el período de la EMA (ej. /set_ema_periodo 10)"},
        {"command": "set_rsi_periodo", "description": "Establece el período del RSI (ej. /set_rsi_periodo 14)"},
        {"command": "set_rsi_umbral", "description": "Establece el umbral de sobrecompra del RSI (ej. /set_rsi_umbral 70)"},
        {"command": "set_intervalo", "description": "Establece el intervalo del ciclo (ej. /set_intervalo 300)"},
        {"command": "set_breakeven_porcentaje", "description": "Mueve SL a breakeven (ej. /set_breakeven_porcentaje 0.005)"},
        {"command": "csv", "description": "Genera y envía un informe CSV de transacciones"},
        {"command": "beneficio", "description": "Muestra el beneficio total acumulado"},
        {"command": "vender", "description": "Vende una posición manualmente (ej. /vender BTCUSDT)"},
        {"command": "get_positions_file", "description": "Muestra el contenido del archivo de posiciones abiertas (para depuración)"},
        {"command": "menu", "description": "Muestra el teclado de comandos principal"},
        {"command": "hide_menu", "description": "Oculta el teclado de comandos"},
        {"command": "help", "description": "Muestra este mensaje de ayuda"}
    ]

    payload = {'commands': json.dumps(commands)}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result['ok']:
            logging.info("✅ Menú de comandos de Telegram configurado con éxito.")
            return True
        else:
            logging.error(f"❌ Fallo al configurar el menú de comandos: {result.get('description', 'Error desconocido')}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error de red al configurar el menú de comandos: {e}")
        return False

# =================== FUNCIONES DE DEPURACIÓN Y VERIFICACIÓN ===================

def send_positions_file_content():
    """
    Lee el contenido del archivo OPEN_POSITIONS_FILE y lo envía al chat de Telegram.
    Esta función es muy útil para depurar y verificar el estado de persistencia
    de las posiciones abiertas en entornos de despliegue como Railway, donde no hay acceso directo al sistema de archivos.
    """
    if not os.path.exists(OPEN_POSITIONS_FILE):
        send_telegram_message(f"❌ Archivo de posiciones abiertas (<code>{OPEN_POSITIONS_FILE}</code>) no encontrado.")
        logging.warning(f"Intento de leer {OPEN_POSITIONS_FILE}, pero no existe.")
        return

    try:
        with open(OPEN_POSITIONS_FILE, 'r') as f:
            content = f.read() # Lee todo el contenido del archivo.
        
        # Envía el contenido como un mensaje de código para facilitar la lectura en Telegram.
        message = (
            f"📄 Contenido de <code>{OPEN_POSITIONS_FILE}</code>:\n\n"
            f"<code>{content}</code>"
        )
        send_telegram_message(message)
        logging.info(f"Contenido de {OPEN_POSITIONS_FILE} enviado a Telegram.")
    except Exception as e:
        send_telegram_message(f"❌ Error al leer o enviar el contenido de <code>{OPEN_POSITIONS_FILE}</code>: {e}")
        logging.error(f"❌ Error al leer o enviar {OPEN_POSITIONS_FILE}: {e}", exc_info=True)

# =================== FUNCIÓN DE AYUDA ===================

def send_help_message():
    """
    Envía un mensaje de ayuda detallado a Telegram con la lista de todos los comandos disponibles
    y su uso, incluyendo ejemplos.
    """
    help_message = (
        "🤖 <b>Comandos disponibles:</b>\n\n"
        "<b>Parámetros de Estrategia:</b>\n"
        " - <code>/get_params</code>: Muestra los parámetros actuales del bot.\n"
        " - <code>/set_tp &lt;valor&gt;</code>: Establece el porcentaje de Take Profit (ej. 0.03).\n"
        " - <code>/set_sl_fijo &lt;valor&gt;</code>: Establece el porcentaje de Stop Loss Fijo (ej. 0.02).\n"
        " - <code>/set_tsl &lt;valor&gt;</code>: Establece el porcentaje de Trailing Stop Loss (ej. 0.015).\n"
        " - <code>/set_riesgo &lt;valor&gt;</code>: Establece el porcentaje de riesgo por operación (ej. 0.01).\n"
        " - <code>/set_ema_periodo &lt;valor&gt;</code>: Establece el período de la EMA (ej. 10).\n"
        " - <code>/set_rsi_periodo &lt;valor&gt;</code>: Establece el período del RSI (ej. 14).\n"
        " - <code>/set_rsi_umbral &lt;valor&gt;</code>: Establece el umbral de sobrecompra del RSI (ej. 70).\n"
        " - <code>/set_intervalo &lt;segundos&gt;</code>: Establece el intervalo del ciclo principal del bot en segundos (ej. 300).\n"
        " - <code>/set_breakeven_porcentaje &lt;valor&gt;</code>: Establece el porcentaje de ganancia para mover SL a breakeven (ej. 0.005).\n\n"
        "<b>Informes:</b>\n"
        " - <code>/csv</code>: Genera y envía un archivo CSV con las transacciones del día hasta el momento.\n"
        " - <code>/beneficio</code>: Muestra el beneficio total acumulado por el bot.\n\n"
        "<b>Utilidades:</b>\n"
        " - <code>/vender &lt;SIMBOLO_USDT&gt;</code>: Vende una posición abierta de forma manual (ej. /vender BTCUSDT).\n"
        " - <code>/get_positions_file</code>: Muestra el contenido del archivo de posiciones abiertas (para depuración).\n"
        " - <code>/menu</code>: Muestra el teclado de comandos principal.\n"
        " - <code>/hide_menu</code>: Oculta el teclado de comandos.\n\n"
        "<b>Ayuda:</b>\n"
        " - <code>/help</code>: Muestra este mensaje de ayuda.\n\n"
        "<i>Recuerda usar valores decimales para porcentajes y enteros para períodos/umbrales.</i>"
    )
    send_telegram_message(help_message)


# =================== BUCLE PRINCIPAL DEL BOT ===================

# Configurar el menú de comandos de Telegram al inicio del bot.
# Esto asegura que los comandos estén disponibles en la interfaz de Telegram cuando el bot se inicia.
set_telegram_commands_menu()

logging.info("Bot iniciado. Esperando comandos y monitoreando el mercado...")

# Bucle infinito que mantiene el bot en funcionamiento continuo.
# Este bucle se ejecuta repetidamente para monitorear el mercado y los comandos de Telegram.
while True:
    start_time_cycle = time.time() # Marca el inicio de cada iteración del bucle principal para medir su duración.
    
    try:
        # --- Manejar comandos de Telegram ---
        # Esta función se ejecuta en cada ciclo corto (cada TELEGRAM_LISTEN_INTERVAL segundos)
        # para asegurar una respuesta rápida a los comandos del usuario.
        handle_telegram_commands()
        
        # --- Lógica del Informe Diario ---
        # Comprueba si la fecha actual es diferente a la última fecha en que se envió el informe diario.
        # Si es un nuevo día, se envía el informe del día anterior y se reinicia la lista de transacciones.
        hoy = time.strftime("%Y-%m-%d")

        if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
            if ultima_fecha_informe_enviado is not None: # Si ya se había enviado un informe antes (no es la primera ejecución del bot).
                send_telegram_message(f"Preparando informe del día {ultima_fecha_informe_enviado}...")
                enviar_informe_diario() # Llama a la función para generar y enviar el CSV diario.
            
            ultima_fecha_informe_enviado = hoy # Actualiza la fecha del último informe enviado a la fecha actual.
            transacciones_diarias.clear() # Limpia la lista de transacciones para empezar a registrar las del nuevo día.

        # --- LÓGICA PRINCIPAL DE TRADING ---
        # Esta sección se ejecuta con una frecuencia controlada por 'INTERVALO' (ej. cada 5 minutos).
        # Esto reduce la carga en la API de Binance y el consumo de recursos del bot.
        if (time.time() - last_trading_check_time) >= INTERVALO:
            logging.info(f"Iniciando ciclo de trading principal (cada {INTERVALO}s)...")
            general_message = "" # Variable para construir un único mensaje con el estado de todos los símbolos.

            for symbol in SYMBOLS: # Itera a través de cada par de trading configurado en la lista SYMBOLS.
                base = symbol.replace("USDT", "") # Extrae la moneda base del par (ej. "BTC" de "BTCUSDT").
                saldo_base = obtener_saldo_moneda(base) # Obtiene el saldo de la moneda base en tu cuenta de Binance.
                precio_actual = obtener_precio_actual(symbol) # Obtiene el precio actual del par de Binance.
                ema_valor, rsi_valor = calcular_ema_rsi(symbol, EMA_PERIODO, RSI_PERIODO) # Calcula los indicadores técnicos.

                if ema_valor is None or rsi_valor is None:
                    logging.warning(f"⚠️ No se pudieron calcular EMA o RSI para {symbol}. Saltando este símbolo en este ciclo.")
                    continue # Pasa al siguiente símbolo si los indicadores no se pudieron calcular.

                # Construye la primera parte del mensaje de estado para el símbolo actual.
                mensaje_simbolo = (
                    f"📊 <b>{symbol}</b>\n"
                    f"Precio actual: {precio_actual:.2f} USDT\n"
                    f"EMA ({EMA_PERIODO}m): {ema_valor:.2f}\n"
                    f"RSI ({RSI_PERIODO}m): {rsi_valor:.2f}"
                )

                # --- LÓGICA DE COMPRA ---
                saldo_usdt = obtener_saldo_moneda("USDT") # Obtiene el saldo disponible de USDT para nuevas compras.
                # Condiciones de entrada para una nueva compra:
                # 1. Suficiente USDT disponible (más de 10 USDT para cumplir el mínimo nocional de Binance).
                # 2. Precio actual por encima de la EMA (señal alcista).
                # 3. RSI por debajo del umbral de sobrecompra (indica que no está excesivamente caro).
                # 4. No hay una posición abierta ya para este símbolo.
                if (saldo_usdt > 10 and 
                    precio_actual > ema_valor and 
                    rsi_valor < RSI_UMBRAL_SOBRECOMPRA and 
                    symbol not in posiciones_abiertas):
                    
                    # Calcula la cantidad de criptomoneda a comprar basándose en la gestión de riesgo.
                    cantidad = calcular_cantidad_a_comprar(saldo_usdt, precio_actual, STOP_LOSS_PORCENTAJE, symbol)
                    
                    if cantidad > 0: # Si la cantidad calculada es válida (mayor que cero).
                        orden = comprar(symbol, cantidad) # Intenta ejecutar la orden de compra.
                        if orden: # Si la orden de compra fue exitosa.
                            precio_ejecucion = float(orden['fills'][0]['price'])
                            cantidad_comprada_real = float(orden['fills'][0]['qty'])
                            
                            mensaje_simbolo += f"\n✅ COMPRA ejecutada a {precio_ejecucion:.2f} USDT"
                            
                            capital_invertido_usd = precio_ejecucion * cantidad_comprada_real
                            riesgo_max_trade_usd = saldo_usdt * RIESGO_POR_OPERACION_PORCENTAJE
                            mensaje_simbolo += (
                                f"\nCantidad comprada: {cantidad_comprada_real:.6f} {base}"
                                f"\nInversión en este trade: {capital_invertido_usd:.2f} USDT"
                                f"\nRiesgo Máx. Permitido por Trade: {riesgo_max_trade_usd:.2f} USDT"
                            )
                        else:
                            mensaje_simbolo += f"\n❌ COMPRA fallida para {symbol}."
                    else:
                        mensaje_simbolo += f"\n⚠️ No hay suficiente capital o cantidad mínima para comprar {symbol} con el riesgo definido."

                # --- LÓGICA DE VENTA (Take Profit, Stop Loss Fijo, Trailing Stop Loss, Breakeven) ---
                elif symbol in posiciones_abiertas: # Si ya hay una posición abierta para este símbolo.
                    posicion = posiciones_abiertas[symbol] # Obtiene los detalles de la posición desde el diccionario en memoria.
                    precio_compra = posicion['precio_compra']
                    cantidad_en_posicion = posicion['cantidad_base']
                    max_precio_alcanzado = posicion['max_precio_alcanzado']

                    # Actualiza el precio máximo alcanzado si el precio actual es un nuevo máximo para esta posición.
                    if precio_actual > max_precio_alcanzado:
                        posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                        max_precio_alcanzado = precio_actual # Actualiza la variable local para el ciclo actual.
                        # Guarda la posición con debounce, ya que solo es una actualización del máximo alcanzado.
                        save_open_positions_debounced()

                    # --- Lógica de Stop Loss a Breakeven ---
                    # Calcula el nivel de breakeven: precio de entrada más un pequeño margen (BREAKEVEN_PORCENTAJE) para cubrir comisiones.
                    breakeven_nivel_real = precio_compra * (1 + BREAKEVEN_PORCENTAJE)

                    # Si el precio actual ha alcanzado o superado el nivel de breakeven
                    # Y el Stop Loss aún no se ha movido a breakeven para esta posición.
                    if (precio_actual >= breakeven_nivel_real and
                        not posicion['sl_moved_to_breakeven']):
                        
                        # Mueve el Stop Loss fijo al nivel de breakeven.
                        # Se usa 'max' para asegurar que el nuevo SL no sea inferior al SL fijo original si el breakeven es más bajo.
                        posiciones_abiertas[symbol]['stop_loss_fijo_nivel_actual'] = max(stop_loss_fijo_nivel, breakeven_nivel_real)
                        posiciones_abiertas[symbol]['sl_moved_to_breakeven'] = True # Marca que el SL ya se movió a breakeven.
                        send_telegram_message(f"🔔 SL de <b>{symbol}</b> movido a Breakeven: <b>{breakeven_nivel_real:.2f}</b>")
                        logging.info(f"SL de {symbol} movido a Breakeven: {breakeven_nivel_real:.2f}")
                        save_open_positions_debounced() # Guarda el estado actualizado de la posición.

                    # --- Cálculo de Niveles de Salida ---
                    # El nivel de Stop Loss actual será el SL fijo original o el SL movido a breakeven.
                    # 'posicion.get' se usa para obtener 'stop_loss_fijo_nivel_actual' si existe, si no, usa el SL fijo inicial.
                    current_stop_loss_level = posicion.get('stop_loss_fijo_nivel_actual', precio_compra * (1 - STOP_LOSS_PORCENTAJE))

                    take_profit_nivel = precio_compra * (1 + TAKE_PROFIT_PORCENTAJE) # Nivel de Take Profit.
                    trailing_stop_nivel = max_precio_alcanzado * (1 - TRAILING_STOP_PORCENTAJE) # Nivel de Trailing Stop.

                    eur_usdt_conversion_rate = obtener_precio_eur()
                    saldo_invertido_usdt = precio_compra * cantidad_en_posicion
                    saldo_invertido_eur = saldo_invertido_usdt * eur_usdt_conversion_rate if eur_usdt_conversion_rate else 0

                    # Añade información detallada de la posición al mensaje del símbolo.
                    mensaje_simbolo += (
                        f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                        f"TP: {take_profit_nivel:.2f} | SL Fijo: {current_stop_loss_level:.2f}\n" # Muestra el SL actual (fijo o breakeven).
                        f"Max Alcanzado: {max_precio_alcanzado:.2f} | TSL: {trailing_stop_nivel:.2f}\n"
                        f"Saldo USDT Invertido (Entrada): {saldo_invertido_usdt:.2f}\n"
                        f"SEI: {saldo_invertido_eur:.2f}"
                    )

                    vender_ahora = False
                    motivo_venta = ""

                    # --- Condiciones para vender ---
                    if precio_actual >= take_profit_nivel:
                        vender_ahora = True
                        motivo_venta = "TAKE PROFIT alcanzado"
                    elif precio_actual <= current_stop_loss_level: # Comprueba si el precio actual ha tocado el SL (fijo o breakeven).
                        vender_ahora = True
                        motivo_venta = "STOP LOSS FIJO alcanzado (o Breakeven)" # Mensaje actualizado para reflejar el SL a breakeven.
                    elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra): 
                        # El TSL solo se activa si el precio actual cae por debajo del nivel TSL,
                        # Y si el precio actual sigue estando por encima del precio de compra (para asegurar ganancias o breakeven).
                        vender_ahora = True
                        motivo_venta = "TRAILING STOP LOSS activado"
                    
                    if vender_ahora:
                        step = get_step_size(symbol)
                        cantidad_a_vender_real = ajustar_cantidad(obtener_saldo_moneda(base), step) 
                        
                        if cantidad_a_vender_real > 0:
                            orden = vender(symbol, cantidad_a_vender_real, motivo_venta=motivo_venta) # Ejecuta la venta.
                            if orden:
                                salida = float(orden['fills'][0]['price'])
                                ganancia = (salida - precio_compra) * cantidad_a_vender_real
                                mensaje_simbolo += (
                                    f"\n✅ VENTA ejecutada por {motivo_venta} a {salida:.2f} USDT\n"
                                    f"Ganancia/Pérdida: {ganancia:.2f} USDT"
                                )
                            else:
                                mensaje_simbolo += f"\n❌ VENTA fallida para {symbol}."
                        else:
                            mensaje_simbolo += f"\n⚠️ No hay {base} disponible para vender o cantidad muy pequeña."
                    
                mensaje_simbolo += "\n" + obtener_saldos_formateados() # Añade los saldos generales al final del mensaje del símbolo.
                general_message += mensaje_simbolo + "\n\n" # Acumula el mensaje de cada símbolo para el envío final.

            send_telegram_message(general_message) # Envía el mensaje consolidado de todos los símbolos a Telegram.
            last_trading_check_time = time.time() # Actualiza la marca de tiempo de la última ejecución del ciclo de trading.

        # --- GESTIÓN DEL TIEMPO ENTRE CICLOS ---
        # Calcula el tiempo transcurrido en la iteración actual del bucle.
        time_elapsed_overall = time.time() - start_time_cycle
        # Calcula el tiempo que el bot debe esperar para cumplir con TELEGRAM_LISTEN_INTERVAL (5 segundos).
        # Esto asegura que el bot revise comandos de Telegram con mucha más frecuencia que el ciclo de trading principal.
        sleep_duration = max(0, TELEGRAM_LISTEN_INTERVAL - time_elapsed_overall) 
        print(f"⏳ Próxima revisión en {sleep_duration:.0f} segundos (Revisando comandos cada {TELEGRAM_LISTEN_INTERVAL}s)...\n")
        time.sleep(sleep_duration) # Pausa el bot por la duración calculada.

    except Exception as e:
        # Manejo de errores general para capturar cualquier excepción no controlada en el bucle principal.
        logging.error(f"Error general en el bot: {e}", exc_info=True) # Registra el error completo en los logs.
        send_telegram_message(f"❌ Error general en el bot: {e}\n\n{obtener_saldos_formateados()}") # Notifica al usuario por Telegram.
        print(f"❌ Error general en el bot: {e}") # Imprime el error en la consola.
        time.sleep(INTERVALO) # En caso de un error general, espera el intervalo completo antes de reintentar el bucle.
