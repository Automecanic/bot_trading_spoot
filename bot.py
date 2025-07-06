import os # Importa el módulo 'os' para interactuar con el sistema operativo (ej. variables de entorno).
import time # Importa el módulo 'time' para funciones relacionadas con el tiempo (ej. pausas).
import logging # Importa el módulo 'logging' para registrar eventos y mensajes del bot.
import requests # Importa el módulo 'requests' para hacer peticiones HTTP (ej. a la API de Telegram).
import json # importa el modulo json para leer y eddribir jsom
from binance.client import Client # Importa la clase 'Client' del paquete python-binance para interactuar con la API de Binance.
from binance.exceptions import BinanceAPIException # Importa excepciones específicas de la API de Binance para un mejor manejo de errores.
from binance.enums import * # Importa todas las constantes de enumeración de Binance (ej. KLINE_INTERVAL_1MINUTE, SIDE_BUY).
from statistics import mean # Importa la función 'mean' para calcular el promedio (aunque ahora usamos EMA de pandas_ta).

# --- LIBRERÍAS PARA CÁLCULOS DE INDICADORES TÉCNICOS ---
# Este bloque intenta importar pandas y pandas_ta, que son cruciales para el análisis técnico.
# Si la importación falla, se considera un error crítico y el bot se detiene.
try:
    import pandas as pd # Importa 'pandas' para manipulación de datos, especialmente DataFrames.
    import pandas_ta as ta # Importa 'pandas_ta' para el cálculo de indicadores técnicos (EMA, RSI).
except ImportError as e: # Captura el error si las librerías no se pueden importar.
    # Registra un mensaje de error crítico en el sistema de logging.
    logging.error(f"❌ ERROR CRÍTICO: No se pudieron importar las librerías de trading (pandas/pandas_ta). "
                  f"Asegúrate de que estén en requirements.txt y el despliegue fue exitoso. Error: {e}")
    # Imprime el mismo mensaje de error en la consola para visibilidad inmediata.
    print(f"❌ ERROR CRÍTICO: No se pudieron importar las librerías de trading (pandas/pandas_ta). "
          f"Por favor, instala: pip install pandas pandas_ta. Error: {e}")
    exit(1) # Termina la ejecución del script con un código de error (1), ya que el bot no puede funcionar sin ellas.

# --- CONFIGURACIÓN DEL BOT ---
# Estas variables son fundamentales para el funcionamiento del bot y deben ser configuradas.
# Se recomienda encarecidamente cargarlas como variables de entorno por seguridad.

API_KEY = os.getenv("BINANCE_API_KEY")       # Obtiene la clave API de Binance de las variables de entorno.
API_SECRET = os.getenv("BINANCE_API_SECRET") # Obtiene el secreto API de Binance de las variables de entorno.

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")       # Obtiene el token de tu bot de Telegram de las variables de entorno.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")       # Obtiene el ID del chat/grupo de Telegram de las variables de entorno.
#prova bot https://api.telegram.org/bot7614530491:AAGf7GZWjUEm3Ccudj6zeoREuCsJglst_Qc/getUpdates


# ... (después de TELEGRAM_CHAT_ID) ...

CONFIG_FILE = "config.json" # Define el nombre del archivo de configuración

# --- Funciones para cargar/guardar parámetros ---
def load_parameters():
    """Carga los parámetros desde el archivo JSON. Si no existe, devuelve valores por defecto."""
    default_params = {
        "EMA_PERIODO": 10,
        "RSI_PERIODO": 14,
        "RSI_UMBRAL_SOBRECOMPRA": 70,
        "RIESGO_POR_OPERACION_PORCENTAJE": 0.01,
        "TAKE_PROFIT_PORCENTAJE": 0.03,
        "STOP_LOSS_PORCENTAJE": 0.02,
        "TRAILING_STOP_PORCENTAJE": 0.015,
        "INTERVALO": 300
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                loaded_params = json.load(f)
                # Unir los parámetros cargados con los por defecto, priorizando los cargados
                return {**default_params, **loaded_params}
        except json.JSONDecodeError as e:
            logging.error(f"❌ Error al leer JSON del archivo {CONFIG_FILE}: {e}. Usando parámetros por defecto.")
            return default_params
    else:
        logging.info(f"Archivo de configuración '{CONFIG_FILE}' no encontrado. Creando con parámetros por defecto.")
        save_parameters(default_params) # Crea el archivo con los valores por defecto
        return default_params

def save_parameters(params):
    """Guarda los parámetros en el archivo JSON."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump(params, f, indent=4) # 'indent=4' para un formato legible
    except IOError as e:
        logging.error(f"❌ Error al escribir en el archivo {CONFIG_FILE}: {e}")

# Cargar parámetros al inicio del bot
bot_params = load_parameters()

# Asignar los valores del diccionario cargado a tus variables globales
# ¡Esto reemplazará tus definiciones anteriores de estos parámetros fijos!
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"] # Esta lista sigue siendo fija
INTERVALO = bot_params["INTERVALO"]
RIESGO_POR_OPERACION_PORCENTAJE = bot_params["RIESGO_POR_OPERACION_PORCENTAJE"]
TAKE_PROFIT_PORCENTAJE = bot_params["TAKE_PROFIT_PORCENTAJE"]
STOP_LOSS_PORCENTAJE = bot_params["STOP_LOSS_PORCENTAJE"]
TRAILING_STOP_PORCENTAJE = bot_params["TRAILING_STOP_PORCENTAJE"]
EMA_PERIODO = bot_params["EMA_PERIODO"]
RSI_PERIODO = bot_params["RSI_PERIODO"]
RSI_UMBRAL_SOBRECOMPRA = bot_params["RSI_UMBRAL_SOBRECOMPRA"]


# --- INICIALIZACIÓN DEL CLIENTE DE BINANCE Y CONFIGURACIÓN DEL LOGGING ---

# Crea una instancia del cliente de Binance usando las claves API.
client = Client(API_KEY, API_SECRET)
# Configura la URL de la API de Binance para usar la Testnet (entorno de prueba con dinero ficticio).
# Esto es CRUCIAL para evitar operar con dinero real durante el desarrollo y las pruebas.
client.API_URL = 'https://testnet.binance.vision/api'

# Configura el sistema de registro (logging) del bot.
logging.basicConfig(
    filename='trading_bot.log', # Especifica el nombre del archivo donde se guardarán los mensajes de log.
    level=logging.INFO,         # Establece el nivel mínimo de mensajes a registrar (INFO, WARNING, ERROR, DEBUG, etc.).
    format='%(asctime)s - %(levelname)s - %(message)s' # Define el formato de cada línea de log: fecha/hora - nivel - mensaje.
)

# --- FUNCIONES AUXILIARES ---
# Colección de funciones que encapsulan operaciones comunes y reutilizables.

def send_telegram_message(message):
    """
    Envía un mensaje de texto al chat de Telegram configurado.
    El mensaje puede contener formato HTML básico.
    """
    # Verifica que el token del bot y el ID del chat estén configurados.
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes de notificación.")
        return # Sale de la función si la configuración es incompleta.

    # Construye la URL de la API de Telegram para enviar mensajes.
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Define el payload (datos a enviar) con el ID del chat, el texto y el modo de parseo (HTML).
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}

    try:
        response = requests.post(url, json=payload) # Envía la petición POST a la API de Telegram.
        response.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        return True
    except Exception as e: # Captura cualquier error que ocurra durante el envío.
        print(f"❌ Error enviando mensaje Telegram: {e}") # Imprime el error en consola.
        logging.error(f"❌ Error enviando mensaje Telegram: {e}") # Registra el error en el log.
        return False
def obtener_precio_actual(symbol):
    """
    Obtiene el último precio de mercado para un par de trading (símbolo) de Binance.
    """
    ticker = client.get_symbol_ticker(symbol=symbol) # Realiza una petición para obtener el ticker del símbolo.
    return float(ticker["price"]) # Convierte el precio a flotante y lo retorna.

def obtener_saldo_moneda(moneda):
    """
    Obtiene el saldo disponible ('free' balance) de una moneda específica en la cuenta de Binance.
    """
    cuenta = client.get_account() # Obtiene el estado actual de la cuenta del usuario.
    for asset in cuenta['balances']: # Itera sobre la lista de activos en la cuenta.
        if asset['asset'] == moneda: # Si encuentra la moneda deseada.
            return float(asset['free']) # Retorna el saldo disponible para operar.
    return 0.0 # Si la moneda no se encuentra en el balance, retorna 0.0.

def get_step_size(symbol):
    """
    Obtiene el 'step size' (tamaño de paso mínimo) para las cantidades de un símbolo en Binance.
    Binance requiere que las cantidades de órdenes sean múltiplos de este valor para ser válidas.
    """
    info = client.get_symbol_info(symbol) # Obtiene información detallada sobre el símbolo.
    for f in info['filters']: # Itera sobre los filtros de trading del símbolo.
        if f['filterType'] == 'LOT_SIZE': # Busca el filtro que define el tamaño del lote.
            return float(f['stepSize'])   # Retorna el 'stepSize' como flotante.
    return 0.000001 # Retorna un valor por defecto muy pequeño si el filtro no se encuentra (caso inusual).

def ajustar_cantidad(cantidad, step_size):
    """
    Ajusta una cantidad de criptomoneda para que sea un múltiplo exacto del 'step_size' del símbolo.
    Esto es crucial para evitar errores 'INVALID_QUANTITY' de la API de Binance.
    """
    # Resta el remanente de la división para alinear la cantidad al step_size.
    # Se redondea a 6 decimales para mantener la precisión y evitar problemas de coma flotante.
    return round(cantidad - (cantidad % step_size), 6)

def calcular_cantidad_a_comprar(capital_total, precio_actual, stop_loss_porcentaje, symbol):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el porcentaje de riesgo por operación
    y la distancia al Stop Loss. Esta es la esencia de la gestión de capital basada en riesgo.
    """
    # Validaciones iniciales para evitar divisiones por cero o cálculos inválidos.
    if precio_actual == 0 or stop_loss_porcentaje == 0:
        logging.warning(f"⚠️ Parámetros inválidos para calcular cantidad de compra en {symbol}. Precio actual o SL porcentaje es cero.")
        return 0.0

    # Calcula el precio en el que se activaría el Stop Loss.
    stop_loss_precio = precio_actual * (1 - stop_loss_porcentaje)

    # Calcula la diferencia entre el precio actual y el precio del Stop Loss.
    # Esta es la cantidad de USDT que se perdería por CADA unidad de la cripto si el SL se activa.
    distancia_stop_loss = precio_actual - stop_loss_precio
    
    # Si la distancia al Stop Loss es cero o negativa (lo que no debería ocurrir con un SL_PORCENTAJE positivo),
    # se retorna 0 para evitar divisiones por cero y errores.
    if distancia_stop_loss <= 0:
        logging.warning(f"⚠️ Distancia al Stop Loss no válida o cero para {symbol}. Distancia: {distancia_stop_loss}. No se puede calcular la cantidad.")
        return 0.0

    # Calcula el monto máximo de USDT que el bot está dispuesto a perder en esta operación individual.
    # Esto se basa en el capital total disponible y el porcentaje de riesgo definido.
    riesgo_max_usd = capital_total * RIESGO_POR_OPERACION_PORCENTAJE

    # Calcula la cantidad de unidades de la cripto a comprar.
    # Se divide el riesgo máximo aceptable por operación entre la pérdida por unidad.
    cantidad = riesgo_max_usd / distancia_stop_loss
    
    # Obtiene el step_size para el símbolo actual y ajusta la cantidad calculada.
    step = get_step_size(symbol)
    return ajustar_cantidad(cantidad, step)

def comprar(symbol, cantidad):
    """
    Envía una orden de compra de mercado a Binance para el símbolo y la cantidad especificados.
    """
    # Verifica que la cantidad sea positiva.
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de compra de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        logging.info(f"✅ Intentando comprar {cantidad} de {symbol}") # Registra el intento de compra.
        order = client.order_market_buy(symbol=symbol, quantity=cantidad) # Ejecuta la orden de compra.
        logging.info(f"✅ Compra de {symbol} exitosa: {order}") # Registra el éxito de la orden.
        return order # Retorna el objeto de la orden si es exitosa.
    except BinanceAPIException as e: # Captura errores específicos de la API de Binance.
        logging.error(f"❌ Error en compra de {symbol} (Binance API): {e}") # Registra el error detallado.
        send_telegram_message(f"❌ Error en compra de {symbol}: {e}") # Notifica por Telegram.
        return None # Retorna None si la compra falla.
    except Exception as e: # Captura cualquier otro tipo de error inesperado.
        logging.error(f"❌ Error inesperado en compra de {symbol}: {e}")
        send_telegram_message(f"❌ Error inesperado en compra de {symbol}: {e}")
        return None

def vender(symbol, cantidad):
    """
    Envía una orden de venta de mercado a Binance para el símbolo y la cantidad especificados.
    """
    # Verifica que la cantidad sea positiva.
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de venta de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        logging.info(f"✅ Intentando vender {cantidad} de {symbol}") # Registra el intento de venta.
        order = client.order_market_sell(symbol=symbol, quantity=cantidad) # Ejecuta la orden de venta.
        logging.info(f"✅ Venta de {symbol} exitosa: {order}") # Registra el éxito de la orden.
        return order # Retorna el objeto de la orden si es exitosa.
    except BinanceAPIException as e: # Captura errores específicos de la API de Binance.
        logging.error(f"❌ Error en venta de {symbol} (Binance API): {e}")
        send_telegram_message(f"❌ Error en venta de {symbol}: {e}")
        return None
    except Exception as e: # Captura cualquier otro tipo de error inesperado.
        logging.error(f"❌ Error inesperado en venta de {symbol}: {e}")
        send_telegram_message(f"❌ Error inesperado en venta de {symbol}: {e}")
        return None

def obtener_datos_ohlcv(symbol, interval, limit):
    """
    Obtiene datos históricos de velas (Open, High, Low, Close, Volume) de Binance.
    Estos datos son la base para calcular los indicadores técnicos.
    """
    # Realiza una petición para obtener los datos de velas (kline data) para el símbolo, intervalo y límite especificados.
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    # Convierte la lista de datos de velas a un DataFrame de Pandas.
    # Se especifican los nombres de las columnas para mayor claridad.
    df = pd.DataFrame(klines, columns=['open_time', 'open', 'high', 'low', 'close', 'volume',
                                       'close_time', 'quote_asset_volume', 'number_of_trades',
                                       'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
    df['close'] = pd.to_numeric(df['close']) # Convierte la columna 'close' (precio de cierre) a un tipo numérico flotante.
    return df # Retorna el DataFrame con los datos históricos.

def calcular_ema_rsi(symbol, ema_period, rsi_period):
    """
    Calcula la Media Móvil Exponencial (EMA) y el Índice de Fuerza Relativa (RSI) para un símbolo.
    Requiere un DataFrame de Pandas con datos de precios de cierre.
    """
    # Obtiene un número suficiente de velas para asegurar que los cálculos de EMA y RSI sean precisos.
    # El 'max(ema_period, rsi_period) + 50' asegura un búfer de datos.
    df = obtener_datos_ohlcv(symbol, KLINE_INTERVAL_1MINUTE, max(ema_period, rsi_period) + 50)
    
    # Verifica si se obtuvieron datos o si hay suficientes datos para los cálculos.
    if df.empty or len(df) < max(ema_period, rsi_period) + 1: 
        logging.warning(f"No hay suficientes datos históricos para calcular EMA/RSI para {symbol}. Se necesitan al menos {max(ema_period, rsi_period) + 1} velas.")
        return None, None # Retorna None si no hay datos suficientes, indicando que no se pudo calcular.

    df['EMA'] = ta.ema(df['close'], length=ema_period) # Calcula la EMA utilizando la columna 'close' del DataFrame.
    df['RSI'] = ta.rsi(df['close'], length=rsi_period) # Calcula el RSI utilizando la columna 'close' del DataFrame.

    # Retorna el último valor calculado de EMA y RSI (corresponden a la vela más reciente).
    return df['EMA'].iloc[-1], df['RSI'].iloc[-1]

def obtener_precio_eur():
    """
    Obtiene el precio de conversión de USDT a EUR utilizando el par EURUSDT en Binance.
    Esto es necesario para mostrar los saldos y montos invertidos en euros.
    """
    try:
        ticker = client.get_symbol_ticker(symbol="EURUSDT") # Intenta obtener el precio del par EURUSDT.
        return 1 / float(ticker["price"]) # Retorna la relación USDT/EUR (cuántos EUR por 1 USDT).
    except Exception as e: # Captura cualquier error si el par no está disponible o la petición falla.
        logging.warning(f"⚠️ No se pudo obtener el precio EURUSDT: {e}. Los saldos en EUR no se mostrarán correctamente.")
        return None # Retorna None si no se puede obtener la tasa de conversión.

def obtener_saldos_formateados():
    """
    Obtiene el saldo actual de USDT y lo convierte a EUR para mostrar un resumen de capital.
    """
    saldo_usdt = obtener_saldo_moneda("USDT") # Obtiene el saldo disponible de USDT.
    eur_usdt = obtener_precio_eur() # Obtiene la tasa de conversión de USDT a EUR.
    saldo_eur = saldo_usdt * eur_usdt if eur_usdt else 0 # Calcula el saldo en EUR; si no hay tasa, es 0.

    # Retorna una cadena de texto formateada en HTML para el mensaje de Telegram.
    return (
        f"💰 <b>Saldos Actuales:</b>\n"
        f" - USDT: {saldo_usdt:.2f}\n"
        f" - EUR: {saldo_eur:.2f}"
    )

# --- ESTRATEGIA PRINCIPAL DEL BOT ---
# El corazón del bot, donde se implementa la lógica de trading y el ciclo de ejecución.

# Diccionario para almacenar el estado de las posiciones abiertas por símbolo.
# Cada entrada contiene el precio de compra, la cantidad de la cripto, y el precio máximo alcanzado
# para el cálculo del Trailing Stop Loss.
# Ejemplo: { 'BTCUSDT': { 'precio_compra': 30000.50, 'cantidad_base': 0.0123, 'max_precio_alcanzado': 30500.00 } }
posiciones_abiertas = {} 
# ... (después de tus funciones auxiliares) ...

# =================== MANEJADOR DE COMANDOS DE TELEGRAM ===================

last_update_id = 0 # Variable global para llevar el seguimiento del último mensaje procesado

def get_telegram_updates(offset=None):
    """
    Obtiene actualizaciones (mensajes) del bot de Telegram usando long polling.
    El 'offset' evita procesar mensajes antiguos repetidamente.
    """
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
    params = {'timeout': 30, 'offset': offset} # Timeout más largo para long polling
    try:
        response = requests.get(url, params=params)
        response.raise_for_status() # Lanza un error si la petición HTTP no fue exitosa (4xx o 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al obtener actualizaciones de Telegram: {e}")
        return None

def handle_telegram_commands():
    """
    Procesa los comandos recibidos por Telegram.
    Actualiza las variables globales de los parámetros del bot y los guarda.
    """
    global last_update_id, RIESGO_POR_OPERACION_PORCENTAJE, TAKE_PROFIT_PORCENTAJE, \
           STOP_LOSS_PORCENTAJE, TRAILING_STOP_PORCENTAJE, EMA_PERIODO, RSI_PERIODO, \
           RSI_UMBRAL_SOBRECOMPRA, INTERVALO, bot_params # Necesitamos acceso global a estas variables

    updates = get_telegram_updates(last_update_id + 1) # Obtener solo los mensajes nuevos

    if updates and updates['ok']:
        for update in updates['result']:
            last_update_id = update['update_id'] # Actualizar el ID del último mensaje procesado

            # Asegúrate de que el mensaje contiene texto y viene del chat autorizado
            if 'message' in update and 'text' in update['message']:
                chat_id = str(update['message']['chat']['id']) # Convertir a string para comparar
                text = update['message']['text'].strip() # Eliminar espacios en blanco
                
                # Solo procesar comandos del CHAT_ID autorizado
                if chat_id != TELEGRAM_CHAT_ID:
                    send_telegram_message(f"⚠️ Comando recibido de chat no autorizado: {chat_id}")
                    logging.warning(f"Comando de chat no autorizado: {chat_id}")
                    continue

                parts = text.split() # Divide el mensaje en partes (ej. "/set_tp 0.04")
                command = parts[0].lower() # El primer elemento es el comando (en minúsculas)
                
                # Puedes enviar una confirmación de que el comando fue recibido
                # send_telegram_message(f"<i>Comando recibido:</i> <code>{text}</code>") 

                try:
                    if command == "/set_tp":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            TAKE_PROFIT_PORCENTAJE = new_value
                            bot_params['TAKE_PROFIT_PORCENTAJE'] = new_value # Actualiza el diccionario
                            save_parameters(bot_params) # Guarda el cambio en el archivo
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
                            new_value = int(parts[1]) # Periodos suelen ser enteros
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

                    elif command == "/get_params":
                        # Muestra todos los parámetros actuales
                        current_params_msg = "<b>Parámetros Actuales:</b>\n"
                        for key, value in bot_params.items():
                            # Formatear porcentajes para mayor claridad
                            if isinstance(value, float) and 'PORCENTAJE' in key.upper():
                                current_params_msg += f"- {key}: {value:.4f}\n"
                            else:
                                current_params_msg += f"- {key}: {value}\n"
                        send_telegram_message(current_params_msg)

                    else:
                        send_telegram_message("Comando desconocido. Usa <code>/help</code> para ver los comandos disponibles.")

                except ValueError:
                    send_telegram_message("❌ Valor inválido. Asegúrate de introducir un número o porcentaje correcto.")
                except Exception as ex:
                    logging.error(f"Error procesando comando '{text}': {ex}", exc_info=True)
                    send_telegram_message(f"❌ Error interno al procesar comando: {ex}")

last_update_id = 0 

while True: # El bucle principal del bot, se ejecuta indefinidamente para monitorear el mercado.
    start_time_cycle = time.time() # Marca el inicio del ciclo actual para calcular su duración.
    try:
        handle_telegram_commands()
        general_message = "" # Inicializa una cadena para acumular todos los mensajes de Telegram de este ciclo.

        # Itera sobre cada símbolo configurado para el trading.
        for symbol in SYMBOLS:
            base = symbol.replace("USDT", "") # Extrae la moneda base (ej., "BTC" de "BTCUSDT").
            
            # Obtiene el saldo de la moneda base. Importante para las verificaciones de venta.
            saldo_base = obtener_saldo_moneda(base) 
            precio_actual = obtener_precio_actual(symbol) # Obtiene el precio actual del mercado para el símbolo.
            
            # Calcula los valores de EMA y RSI para el símbolo.
            ema_valor, rsi_valor = calcular_ema_rsi(symbol, EMA_PERIODO, RSI_PERIODO)

            # Si los indicadores no se pudieron calcular (ej. por falta de datos), se omite este símbolo y se pasa al siguiente.
            if ema_valor is None or rsi_valor is None:
                logging.warning(f"⚠️ No se pudieron calcular EMA o RSI para {symbol}. Saltando este símbolo en este ciclo.")
                continue # Pasa a la siguiente iteración del bucle 'for'.

            # Prepara el mensaje de estado inicial para el símbolo.
            mensaje_simbolo = (
                f"📊 <b>{symbol}</b>\n"
                f"Precio actual: {precio_actual:.2f} USDT\n"
                f"EMA ({EMA_PERIODO}m): {ema_valor:.2f}\n"
                f"RSI ({RSI_PERIODO}m): {rsi_valor:.2f}"
            )

            # --- LÓGICA DE COMPRA ---
            # Condiciones para abrir una nueva posición:
            # 1. Saldo suficiente en USDT (más de 10 USDT para cubrir mínimos y comisiones).
            # 2. El precio actual está por encima de la EMA (indica una tendencia alcista, señal de compra).
            # 3. El RSI no está en zona de sobrecompra (evita comprar cuando el precio ya está muy alto).
            # 4. No hay una posición abierta para este símbolo (evita abrir múltiples posiciones en el mismo activo).
            saldo_usdt = obtener_saldo_moneda("USDT") # Actualiza el saldo de USDT en cada iteración del símbolo.
            if (saldo_usdt > 10 and 
                precio_actual > ema_valor and 
                rsi_valor < RSI_UMBRAL_SOBRECOMPRA and 
                symbol not in posiciones_abiertas):
                
                # Calcula la cantidad de criptomoneda a comprar utilizando la lógica de gestión de riesgo.
                # Se pasa el saldo_usdt total, el precio actual y el porcentaje de Stop Loss.
                cantidad = calcular_cantidad_a_comprar(saldo_usdt, precio_actual, STOP_LOSS_PORCENTAJE, symbol)
                
                if cantidad > 0: # Si la cantidad calculada es válida (mayor que cero).
                    orden = comprar(symbol, cantidad) # Intenta ejecutar la orden de compra.
                    if orden and 'fills' in orden and len(orden['fills']) > 0: # Si la orden se ejecutó y tiene detalles de fills.
                        precio_compra = float(orden['fills'][0]['price']) # Obtiene el precio promedio de ejecución de la compra.
                        cantidad_comprada_real = float(orden['fills'][0]['qty']) # Obtiene la cantidad exacta comprada.
                        
                        # Almacena los detalles de la nueva posición abierta en el diccionario 'posiciones_abiertas'.
                        posiciones_abiertas[symbol] = {
                            'precio_compra': precio_compra,
                            'cantidad_base': cantidad_comprada_real,
                            'max_precio_alcanzado': precio_actual # Inicializa el precio máximo alcanzado con el precio de compra.
                        }
                        mensaje_simbolo += f"\n✅ COMPRA ejecutada a {precio_compra:.2f} USDT"
                        
                        # Calcula y añade la información sobre el capital invertido y el riesgo asumido en este trade.
                        capital_invertido_usd = precio_compra * cantidad_comprada_real
                        riesgo_max_trade_usd = saldo_usdt * RIESGO_POR_OPERACION_PORCENTAJE
                        mensaje_simbolo += (
                            f"\nCantidad comprada: {cantidad_comprada_real:.6f} {base}"
                            f"\nInversión en este trade: {capital_invertido_usd:.2f} USDT"
                            f"\nRiesgo Máx. Permitido por Trade: {riesgo_max_trade_usd:.2f} USDT"
                        )
                    else:
                         mensaje_simbolo += f"\n❌ COMPRA fallida para {symbol}." # Mensaje si la orden no se procesa correctamente.
                else:
                    mensaje_simbolo += f"\n⚠️ No hay suficiente capital o cantidad mínima para comprar {symbol} con el riesgo definido." # Mensaje si no se puede calcular una cantidad válida.

            # --- LÓGICA DE VENTA (Take Profit, Stop Loss, Trailing Stop Loss) ---
            # Se activa solo si ya existe una posición abierta para el símbolo.
            elif symbol in posiciones_abiertas:
                posicion = posiciones_abiertas[symbol] # Obtiene los detalles de la posición abierta.
                precio_compra = posicion['precio_compra'] # Precio al que se compró el activo.
                cantidad_en_posicion = posicion['cantidad_base'] # Cantidad de la cripto que se posee.
                max_precio_alcanzado = posicion['max_precio_alcanzado'] # El precio más alto que ha alcanzado el activo desde la compra.

                # Actualiza el precio máximo alcanzado si el precio actual es un nuevo máximo.
                if precio_actual > max_precio_alcanzado:
                    posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                    max_precio_alcanzado = precio_actual # Actualiza la variable local para el ciclo actual.

                # Calcula los precios de activación para las condiciones de venta.
                take_profit_nivel = precio_compra * (1 + TAKE_PROFIT_PORCENTAJE) # Nivel para Take Profit.
                stop_loss_fijo_nivel = precio_compra * (1 - STOP_LOSS_PORCENTAJE) # Nivel para Stop Loss fijo.
                trailing_stop_nivel = max_precio_alcanzado * (1 - TRAILING_STOP_PORCENTAJE) # Nivel para Trailing Stop Loss.

                # --- Cálculo del Saldo Euros Invertidos (SEI) para la posición actual ---
                eur_usdt_conversion_rate = obtener_precio_eur() # Obtiene la tasa de conversión USDT a EUR.
                saldo_invertido_usdt = precio_compra * cantidad_en_posicion # Valor de la inversión inicial en USDT.
                # Calcula el valor de la inversión inicial en EUR.
                saldo_invertido_eur = saldo_invertido_usdt * eur_usdt_conversion_rate if eur_usdt_conversion_rate else 0

                # Añade toda la información de la posición y los niveles de salida al mensaje.
                mensaje_simbolo += (
                    f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                    f"TP: {take_profit_nivel:.2f} | SL Fijo: {stop_loss_fijo_nivel:.2f}\n"
                    f"Max Alcanzado: {max_precio_alcanzado:.2f} | TSL: {trailing_stop_nivel:.2f}\n"
                    f"Saldo USDT Invertido (Entrada): {saldo_invertido_usdt:.2f}\n" # Muestra la inversión inicial en USDT.
                    f"SEI: {saldo_invertido_eur:.2f}" # Muestra el Saldo Euros Invertidos (SEI).
                )

                vender_ahora = False # Bandera para indicar si se debe realizar una venta.
                motivo_venta = "" # Cadena para almacenar el motivo de la venta.

                # Evalúa las condiciones de venta en orden de prioridad:
                # 1. Si el precio actual alcanza o supera el Take Profit.
                if precio_actual >= take_profit_nivel:
                    vender_ahora = True
                    motivo_venta = "TAKE PROFIT alcanzado"
                # 2. Si el precio actual cae por debajo o iguala el Stop Loss fijo.
                elif precio_actual <= stop_loss_fijo_nivel:
                    vender_ahora = True
                    motivo_venta = "STOP LOSS FIJO alcanzado"
                # 3. Si el precio actual cae por debajo o iguala el Trailing Stop Loss, y estamos en ganancias (precio_actual > precio_compra).
                # La condición 'precio_actual > precio_compra' asegura que el TSL protege ganancias, no acelera pérdidas iniciales.
                elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra): 
                    vender_ahora = True
                    motivo_venta = "TRAILING STOP LOSS activado"
                
                if vender_ahora: # Si alguna condición de venta se cumple.
                    step = get_step_size(symbol) # Obtiene el step_size para la venta.
                    # Obtiene el saldo actual de la moneda base para asegurarse de vender lo que realmente se tiene.
                    cantidad_a_vender_real = ajustar_cantidad(obtener_saldo_moneda(base), step) 
                    
                    if cantidad_a_vender_real > 0: # Si hay cantidad válida para vender.
                        orden = vender(symbol, cantidad_a_vender_real) # Intenta ejecutar la orden de venta.
                        if orden and 'fills' in orden and len(orden['fills']) > 0: # Si la venta fue exitosa.
                            salida = float(orden['fills'][0]['price']) # Precio real de ejecución de la venta.
                            ganancia = (salida - precio_compra) * cantidad_a_vender_real # Calcula la ganancia/pérdida.
                            mensaje_simbolo += (
                                f"\n✅ VENTA ejecutada por {motivo_venta} a {salida:.2f} USDT\n"
                                f"Ganancia/Pérdida: {ganancia:.2f} USDT"
                            )
                            posiciones_abiertas.pop(symbol) # Elimina el símbolo de las posiciones abiertas ya que la operación se cerró.
                        else:
                            mensaje_simbolo += f"\n❌ VENTA fallida para {symbol}." # Mensaje si la venta falla.
                    else:
                        mensaje_simbolo += f"\n⚠️ No hay {base} disponible para vender o cantidad muy pequeña." # Mensaje si no hay suficiente para vender.
            
            # Al final de la evaluación de cada símbolo (compra o venta), añade el resumen de saldos globales.
            mensaje_simbolo += "\n" + obtener_saldos_formateados() 
            general_message += mensaje_simbolo + "\n\n" # Añade el mensaje completo del símbolo al mensaje general.

        send_telegram_message(general_message) # Envía el mensaje acumulado de todos los símbolos a Telegram.

        # --- GESTIÓN DEL TIEMPO ENTRE CICLOS ---
        # Calcula cuánto tiempo ha tomado el ciclo de ejecución actual.
        elapsed_time = time.time() - start_time_cycle
        # Calcula el tiempo que queda por esperar para cumplir con el INTERVALO total.
        # 'max(0, ...)' asegura que el tiempo de espera no sea negativo si el ciclo tardó más que el intervalo.
        sleep_duration = max(0, INTERVALO - elapsed_time) 
        print(f"⏳ Esperando {sleep_duration:.0f} segundos (aprox. {sleep_duration // 60} minutos)...\n") # Imprime el tiempo de espera en consola.
        time.sleep(sleep_duration) # Pausa la ejecución del bot por la duración calculada.

    except Exception as e: # Maneja cualquier error inesperado que ocurra fuera de las funciones específicas.
        # Registra el error completo en el log, incluyendo el 'stack trace' para depuración.
        logging.error(f"Error general en el bot: {e}", exc_info=True) 
        # Envía una notificación de error a Telegram, incluyendo los saldos actuales.
        send_telegram_message(f"❌ Error general en el bot: {e}\n\n{obtener_saldos_formateados()}") 
        print(f"❌ Error general en el bot: {e}") # Imprime el error en la consola.
        time.sleep(INTERVALO) # En caso de un error general, espera el intervalo completo antes de reintentar el bucle.


"""import os
import time
import logging
import requests
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException
import ta  # Librería para indicadores técnicos

# =================== CONFIGURACIÓN ===================
API_KEY = os.getenv("BINANCE_API_KEY")  # API Key Binance
API_SECRET = os.getenv("BINANCE_API_SECRET")  # Secret Key Binance
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")  # Token bot Telegram
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Chat ID Telegram

SYMBOL = "BTCUSDT"  # Símbolo a tradear
INTERVALO = 300  # Intervalo en segundos (5 min)
PORCENTAJE_CAPITAL = 0.1  # % capital a usar por operación

# =====================================================

# Inicializar cliente Binance
client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'  # Usar testnet

# Logger para errores y operaciones
logging.basicConfig(
    filename='trading_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def send_telegram_message(message):
    #Envía mensaje a Telegram con API requests
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram token o chat ID no configurados.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"✅ Mensaje Telegram enviado: {message}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error enviando mensaje Telegram: {e}")

def obtener_candles(symbol, interval, limit=50):
    #Obtiene datos OHLCV de Binance para cálculo indicadores
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_asset_volume', 'number_of_trades',
        'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
    ])
    df['close'] = df['close'].astype(float)
    df['open'] = df['open'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    df['volume'] = df['volume'].astype(float)
    return df

def calcular_indicadores(df):
    #Calcula EMA20 y RSI sobre dataframe
    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['RSI'] = ta.momentum.rsi(df['close'], window=14)
    return df

def obtener_saldos():
    #Obtiene saldo libre de BTC y USDT
    cuenta = client.get_account()
    saldo_btc = float(next(asset['free'] for asset in cuenta['balances'] if asset['asset'] == 'BTC'))
    saldo_usdt = float(next(asset['free'] for asset in cuenta['balances'] if asset['asset'] == 'USDT'))
    return saldo_btc, saldo_usdt

def get_step_size(symbol):
    #Obtiene step size para ajustar cantidad de orden
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001

def ajustar_cantidad(cantidad, step_size):
    #Ajusta cantidad a múltiplo de step_size (evita errores lot size)
    return round(cantidad - (cantidad % step_size), 6)

def comprar_btc(cantidad):
    #Orden de compra mercado
    try:
        orden = client.order_market_buy(symbol=SYMBOL, quantity=cantidad)
        return orden
    except BinanceAPIException as e:
        logging.error(f"Error en compra: {e}")
        send_telegram_message(f"❌ Error en compra: {e}")
        return None

def vender_btc(cantidad):
    #Orden de venta mercado
    try:
        orden = client.order_market_sell(symbol=SYMBOL, quantity=cantidad)
        return orden
    except BinanceAPIException as e:
        logging.error(f"Error en venta: {e}")
        send_telegram_message(f"❌ Error en venta: {e}")
        return None

def main():
    precio_entrada = None  # Precio de entrada para calcular ganancias
    step_size = get_step_size(SYMBOL)  # Ajuste lote
    
    while True:
        try:
            # Obtener datos OHLC para indicadores
            df = obtener_candles(SYMBOL, Client.KLINE_INTERVAL_5MINUTE)
            df = calcular_indicadores(df)
            ultima_fila = df.iloc[-1]

            precio_actual = ultima_fila['close']
            ema20 = ultima_fila['EMA20']
            rsi = ultima_fila['RSI']

            saldo_btc, saldo_usdt = obtener_saldos()

            print(f"\n📊 Precio: {precio_actual:.2f} | EMA20: {ema20:.2f} | RSI: {rsi:.2f}")
            print(f"Saldo BTC: {saldo_btc:.6f} | Saldo USDT: {saldo_usdt:.2f}")

            # Condiciones para comprar
            if saldo_usdt > 10 and precio_actual > ema20 and rsi < 30:
                cantidad_btc = ajustar_cantidad((saldo_usdt * PORCENTAJE_CAPITAL) / precio_actual, step_size)
                if cantidad_btc > 0:
                    print("Intentando comprar BTC...")
                    orden_compra = comprar_btc(cantidad_btc)
                    if orden_compra:
                        precio_entrada = float(orden_compra['fills'][0]['price'])
                        mensaje = (
                            f"✅ <b>COMPRA REALIZADA</b>:\n"
                            f"Símbolo: {SYMBOL}\n"
                            f"Cantidad: {cantidad_btc:.6f} BTC\n"
                            f"Precio compra: {precio_entrada:.2f} USDT"
                        )
                        send_telegram_message(mensaje)
                else:
                    print("Cantidad a comprar demasiado pequeña, se ignora.")

            # Condiciones para vender
            elif saldo_btc > 0 and (precio_actual < ema20 or rsi > 70):
                cantidad_vender = ajustar_cantidad(saldo_btc * PORCENTAJE_CAPITAL, step_size)
                if cantidad_vender > 0:
                    print("Intentando vender BTC...")
                    orden_venta = vender_btc(cantidad_vender)
                    if orden_venta:
                        precio_salida = float(orden_venta['fills'][0]['price'])
                        ganancia = (precio_salida - precio_entrada) * cantidad_vender if precio_entrada else 0
                        ganancia = round(ganancia, 2)
                        mensaje = (
                            f"✅ <b>VENTA REALIZADA</b>:\n"
                            f"Símbolo: {SYMBOL}\n"
                            f"Cantidad: {cantidad_vender:.6f} BTC\n"
                            f"Precio venta: {precio_salida:.2f} USDT\n"
                            f"Ganancia estimada: {ganancia} USDT"
                        )
                        send_telegram_message(mensaje)
                        precio_entrada = None
                else:
                    print("Cantidad a vender demasiado pequeña, se ignora.")

            else:
                print("No se cumplen condiciones para operar.")

            print(f"⏳ Esperando {INTERVALO // 60} minutos...\n")
            time.sleep(INTERVALO)

        except Exception as e:
            logging.error(f"Error general: {e}")
            send_telegram_message(f"❌ Error general: {e}")
            time.sleep(INTERVALO)

if __name__ == "__main__":"""
    #main()


"""from binance.client import Client
#client.API_URL = 'https://testnet.binance.vision/api'


API_KEY = 'MyvGrDW2265mVJPSnutjfQI30iDeXRlIfpOvukmMr2nkfGmtLoqFBnAMeAarEtmG'
API_SECRET = 'TzL96pBfVixnjSe4hcjfAIPZcqvhHDS61mHxVjZjenlMgG7cnVSvbQlufe0q2xrH5'

client = Client(API_KEY, API_SECRET, testnet=True)

try:
    ticker = client.get_symbol_ticker(symbol='BTCUSDT')
    print("Precio BTC/USDT:", ticker['price'])
except Exception as e:
    print("Error:", e)


import time
import os
from dotenv import load_dotenv
from binance.client import Client
from binance.enums import *

# === CARGAR VARIABLES DE ENTORNO ===
load_dotenv()
api_key = os.getenv('API_KEY')  # Tu clave API
api_secret = os.getenv('API_SECRET')  # Tu clave secreta

symbol = 'BTCUSDT'  # Par de trading
quantity = 0.001  # Cantidad de BTC a comprar/vender
espera = 10  # Tiempo de espera entre ciclos (segundos)

# === INICIALIZAR CLIENTE BINANCE (TESTNET) ===
client = Client(api_key, api_secret)
client.API_URL = 'https://testnet.binance.vision'  # URL de la testnet Spot

# === ESTADO DEL BOT ===
last_price = float(client.get_symbol_ticker(symbol=symbol)['price'])  # Precio inicial
position_open = False  # Estado de posición
entry_price = None  # Precio de entrada de la última compra

print(f"Precio inicial de {symbol}: {last_price:.2f}")

# === LOOP PRINCIPAL ===
while True:
    try:
        current_price = float(client.get_symbol_ticker(symbol=symbol)['price'])  # Precio actual
        change = (current_price - last_price) / last_price  # Variación porcentual

        print(f"[{time.strftime('%H:%M:%S')}] Precio actual: {current_price:.2f} | Cambio: {change*100:.2f}%")

        # === COMPRA ===
        if not position_open and change <= -0.01:  # Si no hay posición y el precio cae > 1%
            print(">> Ejecutando COMPRA")

            # Orden de compra a mercado
            order = client.create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            entry_price = current_price  # Guardar precio de compra
            position_open = True  # Marcar posición como abierta
            print("Orden de compra ejecutada")

            # === TAKE PROFIT ===
            tp_price = round(entry_price * 1.02, 2)  # Precio de take-profit (+2%)
            client.create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                price=str(tp_price)
            )
            print(f">> Take-Profit colocado a {tp_price}")

            # === STOP LOSS ===
            sl_price = round(entry_price * 0.99, 2)  # Precio de stop-loss (-1%)
            client.create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_STOP_LOSS_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                stopPrice=str(sl_price),
                price=str(sl_price)
            )
            print(f">> Stop-Loss colocado a {sl_price}")

        # === VENTA ===
        if not position_open and change >= 0.01:  # Si no hay posición y el precio sube > 1%
            print(">> Ejecutando VENTA")

            # Orden de venta a mercado (requiere tener BTC previamente)
            order = client.create_order(
                symbol=symbol,
                side=SIDE_SELL,
                type=ORDER_TYPE_MARKET,
                quantity=quantity
            )
            entry_price = current_price  # Guardar precio de venta
            position_open = True
            print("Orden de venta ejecutada")

            # === TAKE PROFIT VENTA ===
            tp_price = round(entry_price * 0.98, 2)  # Take-profit bajista (-2%)
            client.create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                price=str(tp_price)
            )
            print(f">> Take-Profit (venta) colocado a {tp_price}")

            # === STOP LOSS VENTA ===
            sl_price = round(entry_price * 1.01, 2)  # Stop-loss alcista (+1%)
            client.create_order(
                symbol=symbol,
                side=SIDE_BUY,
                type=ORDER_TYPE_STOP_LOSS_LIMIT,
                timeInForce=TIME_IN_FORCE_GTC,
                quantity=quantity,
                stopPrice=str(sl_price),
                price=str(sl_price)
            )
            print(f">> Stop-Loss (venta) colocado a {sl_price}")

        # === VERIFICAR SI SE CERRÓ POSICIÓN ===
        if position_open:
            btc_balance = float(client.get_asset_balance(asset='BTC')['free'])  # Balance de BTC disponible
            usdt_balance = float(client.get_asset_balance(asset='USDT')['free'])  # Balance de USDT disponible

            if btc_balance < quantity and usdt_balance < quantity * entry_price:
                print(">> Posición cerrada. Reseteando estado.")
                position_open = False
                last_price = current_price
                entry_price = None

        time.sleep(espera)  # Esperar antes de la siguiente iteración

    except Exception as e:
        print("❌ Error:", e)  # Mostrar error
        time.sleep(espera)  # Esperar antes de reintentar

"""