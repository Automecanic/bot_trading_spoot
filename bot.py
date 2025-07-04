# Importar módulos necesarios
import os         # Para interactuar con el sistema operativo (variables de entorno)
import time       # Para pausas y funciones relacionadas con el tiempo
import json       # Para guardar y cargar el estado del bot en formato JSON
import logging    # Para registrar eventos y mensajes (útil para depuración y monitoreo)
import sys        # Para interactuar con el sistema (ej. salir del script)
import requests   # Para hacer peticiones HTTP (USADO PARA TELEGRAM)

# Importaciones específicas de la librería Binance
from binance.client import Client         # El cliente principal para interactuar con la API de Binance
from binance.exceptions import BinanceAPIException # Para manejar errores específicos de la API de Binance

# Cargar variables de entorno desde el archivo .env
from dotenv import load_dotenv
load_dotenv()

# Importaciones para análisis de datos e indicadores
import pandas as pd     # Para manipulación de datos en DataFrames (estructura tabular)
import pandas_ta as ta  # Extensión de Pandas para análisis técnico (RSI, SMA, etc.)

# --- Configuración del Logger ---
# Configura cómo el bot registrará la información (mensajes, errores, etc.)
logger = logging.getLogger(__name__) # Crea un logger para este módulo
logger.setLevel(logging.INFO)        # Nivel mínimo de mensajes a registrar (INFO, WARNING, ERROR, DEBUG)

# Handler para guardar logs en un archivo
file_handler = logging.FileHandler('bot.log', mode='a', encoding='utf-8') # Crea un archivo llamado bot.log
file_handler.setLevel(logging.INFO) # Nivel de log para el archivo

# Handler para mostrar logs en la consola
console_handler = logging.StreamHandler(sys.stdout) # Muestra los logs en la salida estándar (consola)
console_handler.setLevel(logging.INFO) # Nivel de log para la consola

# Formato de los mensajes del log (fecha, nivel, mensaje)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)    # Aplica el formato al handler del archivo
console_handler.setFormatter(formatter)  # Aplica el formato al handler de la consola

logger.addHandler(file_handler)     # Añade el handler de archivo al logger
logger.addHandler(console_handler)  # Añade el handler de consola al logger

# --- Variables de Entorno para Binance y Telegram ---
# Se obtienen las credenciales y IDs desde las variables de entorno
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
telegram_bot_token = os.getenv("TELEGRAM_TOKEN") # Asegúrate que esta variable se llama así
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")     # Asegúrate que esta variable se llama así

# --- Nombre del archivo de estado ---
# Archivo donde se guardará el estado de la posición del bot para persistencia
STATE_FILE = 'bot_state.json'

# --- Variables Globales para seguimiento de la posición ---
# Estas variables controlan el estado de la operación actual del bot
last_buy_price = 0.0      # Precio de la última compra (para calcular P&L)
last_buy_quantity = 0.0   # Cantidad comprada en la última operación
has_open_position = False # Booleano para saber si el bot tiene una posición abierta

# --- Variable para el polling de Telegram ---
# Usada para gestionar qué mensajes de Telegram ya se han procesado
last_telegram_update_id = 0

# Sección de Depuración y Verificación de Claves
# Se registran los últimos 4 caracteres de las claves para verificar que se cargan correctamente (ocultando el resto)
logger.info(f"DEBUG: API Key (últimos 4): {'****' + api_key[-4:] if api_key else 'None'}")
logger.info(f"DEBUG: API Secret (últimos 4): {'****' + api_secret[-4:] if api_secret else 'None'}")
logger.info(f"DEBUG: Telegram Token disponible: {bool(telegram_bot_token)}")
logger.info(f"DEBUG: Telegram Chat ID disponible: {bool(telegram_chat_id)}")

# Validación de que las claves de Binance están configuradas
if not api_key or not api_secret:
    logger.error("ERROR: Las variables de entorno BINANCE_TESTNET_API_KEY y/o BINANCE_TESTNET_API_SECRET no están configuradas.")
    send_telegram_message("🔴 ERROR: Claves API de Binance no configuradas\\. El bot no puede iniciar\\.")
    sys.exit(1) # Sale del script si las claves no están

# Advertencia si las variables de Telegram no están configuradas
if not telegram_bot_token or not telegram_chat_id:
    logger.warning("ADVERTENCIA: Las variables de entorno TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID no están configuradas. Las notificaciones por Telegram no funcionarán.")

# Inicializa el cliente de Binance para Testnet
client = Client(api_key, api_secret, testnet=True)

# Intenta sincronizar la hora del cliente con el servidor de Binance para evitar errores de timestamp
try:
    client.sync_time()
    logger.info("Hora del cliente sincronizada con el servidor de Binance.")
except Exception as e:
    logger.warning(f"ADVERTENCIA: No se pudo sincronizar la hora con Binance. Esto podría causar errores: {e}")
    send_telegram_message(f"⚠️ ADVERTENCIA: Error al sincronizar hora con Binance\\. Posibles problemas futuros: `{e}`")


### Función `send_telegram_message` (Implementación Final)

def send_telegram_message(message):
    """
    Envía un mensaje de texto a un chat de Telegram específico usando requests.
    Requiere TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID configurados como variables de entorno.
    """
    # Usamos directamente las variables globales aquí.
    if not telegram_bot_token or not telegram_chat_id:
        logger.warning("⚠️ No se puede enviar mensaje de Telegram: TOKEN o CHAT_ID no configurados.")
        return

    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){telegram_bot_token}/sendMessage"
    payload = {
        'chat_id': telegram_chat_id,
        'text': message,
        'parse_mode': 'MarkdownV2' # Usamos MarkdownV2 para mejor compatibilidad con el formato de logs
    }
    try:
        response = requests.post(url, json=payload) # Usar json=payload para enviar como JSON body
        response.raise_for_status() # Lanza excepción si el status no es 200 (error HTTP)
        # Puedes descomentar la siguiente línea si quieres loggear cada mensaje enviado,
        # pero para evitar ruido, está comentada por defecto.
        # logger.info(f"✅ Mensaje de Telegram enviado: {message.replace('*', '').replace('`', '')[:50]}...")
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error al enviar mensaje de Telegram: {e}")
    except Exception as e:
        logger.error(f"❌ Error inesperado al enviar mensaje de Telegram: {e}")

# --- Funciones para cargar y guardar el estado del bot ---
def load_bot_state():
    """
    Carga el estado del bot desde el archivo JSON (bot_state.json).
    Si el archivo no existe o está corrupto, inicializa el estado a valores predeterminados.
    """
    global last_buy_price, last_buy_quantity, has_open_position # Declara que se modificarán las variables globales
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f) # Carga el JSON
                last_buy_price = state.get('last_buy_price', 0.0)
                last_buy_quantity = state.get('last_buy_quantity', 0.0)
                has_open_position = state.get('has_open_position', False)
            logger.info(f"Estado del bot cargado desde {STATE_FILE}: last_buy_price={last_buy_price}, has_open_position={has_open_position}")
            send_telegram_message("🔄 *Estado del bot cargado*\\. Reanudando operaciones\\.")
        except json.JSONDecodeError as e:
            logger.error(f"ERROR: No se pudo decodificar el archivo de estado JSON: {e}")
            send_telegram_message(f"🔴 ERROR: Archivo de estado corrupto\\. Iniciando con estado limpio\\. `{e}`")
            # En caso de error, inicializa el estado a valores predeterminados
            last_buy_price = 0.0
            last_buy_quantity = 0.0
            has_open_position = False
        except Exception as e:
            logger.error(f"ERROR inesperado al cargar el estado del bot: {e}")
            send_telegram_message(f"🔴 ERROR inesperado al cargar el estado\\. Iniciando con estado limpio\\. `{e}`")
            last_buy_price = 0.0
            last_buy_quantity = 0.0
            has_open_position = False
    else:
        logger.info(f"Archivo de estado {STATE_FILE} no encontrado. Iniciando con estado limpio.")
        send_telegram_message("🆕 *Bot iniciado sin estado previo*\\. Iniciando con estado limpio\\.")

def save_bot_state():
    """
    Guarda el estado actual del bot (last_buy_price, last_buy_quantity, has_open_position)
    en el archivo JSON para que persista entre reinicios.
    """
    state = {
        'last_buy_price': last_buy_price,
        'last_buy_quantity': last_buy_quantity,
        'has_open_position': has_open_position
    }
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=4) # Guarda el estado en formato JSON con indentación para legibilidad
        logger.info(f"Estado del bot guardado en {STATE_FILE}.")
    except Exception as e:
        logger.error(f"ERROR al guardar el estado del bot: {e}")
        send_telegram_message(f"🔴 ERROR al guardar el estado del bot: `{e}`")

# --- Funciones de Utilidad del Bot ---

def mostrar_saldo():
    """
    Obtiene y registra los saldos de BTC y USDT de la cuenta del exchange.
    Retorna los saldos libres de BTC y USDT.
    """
    try:
        info = client.get_account() # Obtiene la información de la cuenta
        balances = info['balances'] # Accede a la lista de balances de activos
        btc = next((b for b in balances if b['asset'] == 'BTC'), None) # Busca el balance de BTC
        usdt = next((b for b in balances if b['asset'] == 'USDT'), None) # Busca el balance de USDT
        btc_free = float(btc['free']) if btc else 0.0 # Cantidad disponible de BTC
        usdt_free = float(usdt['free']) if usdt else 0.0 # Cantidad disponible de USDT
        logger.info(f"Saldo BTC: {btc_free:.8f}")
        logger.info(f"Saldo USDT: {usdt_free:.2f}")
        return btc_free, usdt_free
    except BinanceAPIException as e:
        logger.error(f"ERROR al obtener el saldo: {e}")
        send_telegram_message(f"🔴 ERROR al obtener saldo: `{e}`")
        return 0.0, 0.0
    except Exception as e:
        logger.error(f"ERROR inesperado al obtener el saldo: {e}")
        send_telegram_message(f"🔴 ERROR inesperado al obtener saldo: `{e}`")
        return 0.0, 0.0

def obtener_precio(simbolo="BTCUSDT"):
    """
    Obtiene el precio actual de un par de trading (ej. BTCUSDT).
    """
    try:
        ticker = client.get_symbol_ticker(symbol=simbolo) # Obtiene el ticker del símbolo
        return float(ticker['price']) # Retorna el precio como float
    except Exception as e:
        logger.error(f"ERROR al obtener el precio: {e}")
        return 0.0

def obtener_velas(symbol, interval, limit=100):
    """
    Obtiene datos históricos de velas (candlesticks) para un símbolo y un intervalo dados.
    Estos datos son fundamentales para calcular indicadores como RSI y SMA.
    """
    try:
        klines = client.get_historical_klines(symbol, interval, limit=limit) # Obtiene las velas históricas
        # Crea un DataFrame de Pandas a partir de los datos de las velas
        df = pd.DataFrame(klines, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_asset_volume', 'number_of_trades',
            'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'
        ])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms') # Convierte el timestamp a formato de fecha/hora
        df.set_index('timestamp', inplace=True) # Establece el timestamp como índice del DataFrame
        # Convierte las columnas numéricas a tipo float
        df[['open', 'high', 'low', 'close', 'volume']] = df[['open', 'high', 'low', 'close', 'volume']].astype(float)
        return df
    except Exception as e:
        logger.error(f"ERROR al obtener velas para {symbol}: {e}")
        return pd.DataFrame() # Retorna un DataFrame vacío en caso de error

def cancelar_todas_las_ordenes_abiertas(symbol):
    """
    Cancela todas las órdenes abiertas para un símbolo dado.
    Esto es útil antes de iniciar una nueva operación para evitar conflictos.
    Actualiza el estado 'has_open_position' si se detecta un cierre indirecto.
    """
    global has_open_position # Declara que se modificará la variable global
    try:
        open_orders = client.get_open_orders(symbol=symbol) # Obtiene la lista de órdenes abiertas
        if not open_orders:
            logger.info(f"No hay órdenes abiertas para {symbol} para cancelar.")
            # Si no hay órdenes abiertas, y el bot creía tener una posición, se asume que se cerró.
            if has_open_position:
                logger.info("Detectado que no hay órdenes abiertas y la posición estaba marcada como abierta. Actualizando estado.")
                send_telegram_message("ℹ️ Posición posiblemente cerrada: No se encontraron órdenes abiertas\\.")
                has_open_position = False
                save_bot_state() # Guarda el estado después de actualizar has_open_position
            return True

        logger.info(f"📝 Cancelando {len(open_orders)} órdenes abiertas para {symbol} antes de operar...")
        send_telegram_message(f"📝 Cancelando `{len(open_orders)}` órdenes abiertas para `{symbol}` antes de operar\\.")
        
        for order in open_orders:
            order_id = order['orderId']
            # Determina si es una orden OCO (One-Cancels-the-Other) o una orden regular
            if 'orderListId' in order and order['orderListId'] != -1: 
                logger.info(f"   Intentando cancelar OCO OrderListId: {order['orderListId']}")
                client.cancel_oco_order(symbol=symbol, orderListId=order['orderListId'])
            else: 
                logger.info(f"   Intentando cancelar orden regular OrderId: {order_id}")
                client.cancel_order(symbol=symbol, orderId=order_id)
            
            logger.info(f"   Orden {order_id} (o OCO) cancelada con éxito.")
        
        # Una vez canceladas todas las órdenes, si la posición estaba abierta, se asume cerrada.
        if has_open_position:
            send_telegram_message(f"✅ Todas las órdenes abiertas para `{symbol}` canceladas\\. Posición anterior considerada cerrada\\.")
            has_open_position = False
            save_bot_state() # Guarda el estado después de actualizar has_open_position
        else:
            send_telegram_message(f"✅ Todas las órdenes abiertas para `{symbol}` canceladas\\.")
        
        return True
    except BinanceAPIException as e:
        # Manejo de errores específicos de Binance API durante la cancelación
        if e.code == -2011: # Error si la orden ya no existe
            logger.warning(f"   ADVERTENCIA: La orden ya no existe o ya fue procesada: {e}")
            send_telegram_message(f"⚠️ ADVERTENCIA al cancelar órdenes: `Orden ya no existe: {e}`")
        else:
            logger.error(f"❌ ERROR de Binance API al cancelar órdenes para {symbol}: {e}")
            send_telegram_message(f"🔴 ERROR de Binance API al cancelar órdenes: `{e}`")
        return False
    except Exception as e:
        logger.error(f"❌ ERROR inesperado al cancelar órdenes abiertas para {symbol}: {e}")
        send_telegram_message(f"🔴 ERROR inesperado al cancelar órdenes: `{e}`")
        return False

def get_exchange_info(symbol):
    """
    Obtiene la información de los filtros de un símbolo de trading (como BTCUSDT).
    Esto incluye el tamaño mínimo de la orden (minQty), el tamaño del paso (stepSize)
    y el valor nocional mínimo (minNotional), crucial para cumplir con las reglas de Binance.
    """
    try:
        info = client.get_symbol_info(symbol) # Obtiene la información del símbolo
        if not info:
            logger.error(f"No se encontró información para el símbolo {symbol}")
            send_telegram_message(f"🔴 ERROR: No se encontró información para el símbolo `{symbol}`\\.")
            return None

        filters = {f['filterType']: f for f in info['filters']}
        
        min_notional = float(filters.get('MIN_NOTIONAL', {}).get('minNotional', 0))
        min_qty = float(filters.get('LOT_SIZE', {}).get('minQty', 0))
        step_size = float(filters.get('LOT_SIZE', {}).get('stepSize', 0))

        # --- NUEVOS LOGS DE DEPURACIÓN (GET_EXCHANGE_INFO) ---
        logger.info(f"DEBUG: Filtros de Exchange para {symbol}:")
        logger.info(f"   MIN_NOTIONAL: {min_notional}")
        logger.info(f"   LOT_SIZE (minQty): {min_qty}")
        logger.info(f"   LOT_SIZE (stepSize): {step_size}")
        send_telegram_message(
            f"ℹ️ *DEBUG Filtros de {symbol}:*\n"
            f"   `MIN_NOTIONAL`: `{min_notional:.2f}`\n"
            f"   `LOT_SIZE \\(minQty\\)`: `{min_qty:.8f}`\n"
            f"   `LOT_SIZE \\(stepSize\\)`: `{step_size:.8f}`"
        )
        # ----------------------------------------------------
        
        return {
            'min_notional': min_notional,
            'min_qty': min_qty,
            'step_size': step_size
        }
    except Exception as e:
        logger.error(f"Error al obtener información de exchange para {symbol}: {e}")
        send_telegram_message(f"🔴 ERROR al obtener info de exchange para `{symbol}`: `{e}`")
        return None

def establecer_orden_oco(symbol, quantity, current_price):
    """
    Establece una orden OCO (One-Cancels-the-Other) de venta para una posición comprada.
    Consiste en una orden Take Profit (límite) y una orden Stop Loss (stop-limit).
    Si una se ejecuta, la otra se cancela automáticamente.
    """
    try:
        take_profit_percentage = 0.005 # 0.5% de ganancia para Take Profit
        stop_loss_percentage = 0.002   # 0.2% de pérdida para Stop Loss
        stop_limit_buffer = 0.0005     # Pequeño buffer para el precio stop-limit (0.05%)

        take_profit_price = current_price * (1 + take_profit_percentage)
        stop_loss_price = current_price * (1 - stop_loss_percentage)
        stop_limit_price = stop_loss_price * (1 - stop_limit_buffer) # Precio de activación de la orden límite

        # Formateo de precios para Binance (2 decimales para USDT en BTC/USDT en testnet, puede variar en producción)
        # Es crucial que estos precios también se ajusten a los filtros PRICE_FILTER de Binance
        # Para BTCUSDT en Testnet, usualmente 2 decimales es suficiente para el precio.
        take_profit_price_str = f"{take_profit_price:.2f}"
        stop_loss_price_str = f"{stop_loss_price:.2f}"
        stop_limit_price_str = f"{stop_limit_price:.2f}"
        
        logger.info(f"\n📈 Estableciendo orden OCO para {symbol}:")
        logger.info(f"   Cantidad: {quantity:.8f}")
        logger.info(f"   Take Profit (Venta Límite): {take_profit_price_str}")
        logger.info(f"   Stop Loss (Stop Price): {stop_loss_price_str}")
        logger.info(f"   Stop Limit (Precio de Disparo): {stop_limit_price_str}")

        # --- NUEVOS LOGS DE DEPURACIÓN (OCO) ---
        send_telegram_message(
            f"ℹ️ *DEBUG OCO {symbol}:*\n"
            f"   Precio base: `{current_price:.2f}`\n"
            f"   TP \${take_profit_percentage*100:.2f}%\$: `{take_profit_price_str}`\n"
            f"   SL \${stop_loss_percentage*100:.2f}%\$: `{stop_loss_price_str}`\n"
            f"   SL Limit \${stop_limit_buffer*100:.2f}% buffer\$: `{stop_limit_price_str}`\n"
            f"   Cantidad: `{quantity:.8f}`"
        )
        # ---------------------------------------

        order_oco = client.create_oco_order( # Crea la orden OCO
            symbol=symbol,
            side='SELL',
            quantity=quantity,
            price=take_profit_price_str,      # Precio de la orden límite (Take Profit)
            stopPrice=stop_loss_price_str,    # Precio de activación del Stop Loss
            stopLimitPrice=stop_limit_price_str, # Precio límite del Stop Loss
            stopLimitTimeInForce='GTC'        # Good 'Til Cancelled (válida hasta ser cancelada)
        )
        logger.info("✅ Orden OCO enviada con éxito:")
        logger.info(f"   OrderListId: {order_oco.get('orderListId')}")
        logger.info(f"   Contiene {len(order_oco.get('orderReports', []))} órdenes.")
        
        msg = (
            f"✅ *OCO establecida para {symbol}*\n"
            f"   Cantidad: `{quantity:.8f}`\n"
            f"   TP: `{take_profit_price_str}`\n"
            f"   SL: `{stop_loss_price_str}`"
        )
        send_telegram_message(msg)
        return order_oco
    except BinanceAPIException as e:
        logger.error(f"❌ Error al establecer orden OCO para {symbol}: {e}")
        # Manejo de errores comunes para órdenes OCO
        if e.code == -2010: # ERROR_AMOUNT_TOO_SMALL, etc.
            logger.warning("   ADVERTENCIA: La cantidad o los precios de la orden OCO podrían ser demasiado pequeños (MIN_NOTIONAL).")
            send_telegram_message(f"⚠️ ADVERTENCIA OCO: Cantidad o precios muy pequeños: `{e}`")
        elif e.code == -1013: # FILTER_MIN_NOTIONAL o FILTER_PRICE_HALT
             logger.warning(f"   ADVERTENCIA: Error de filtro al establecer OCO: {e.message}")
             send_telegram_message(f"⚠️ ADVERTENCIA OCO: Error de filtro al establecer orden (ej. MIN_NOTIONAL/PRICE_HALT): `{e.message}`")
        else:
            send_telegram_message(f"🔴 ERROR Binance API al establecer OCO: `{e}`")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado al establecer orden OCO para {symbol}: {e}")
        send_telegram_message(f"🔴 ERROR inesperado al establecer OCO: `{e}`")
        return None

def comprar(simbolo="BTCUSDT", cantidad=0.0005):
    """
    Ejecuta una orden de compra a precio de mercado y, si tiene éxito, establece una orden OCO
    para gestionar la salida (Take Profit y Stop Loss).
    """
    global last_buy_price, last_buy_quantity, has_open_position
    try:
        logger.info(f"\nIntentando comprar {cantidad} de {simbolo} a precio de mercado...")
        
        exchange_info = get_exchange_info(simbolo)
        if not exchange_info:
            send_telegram_message("🔴 ERROR: No se pudo obtener información de exchange para la compra\\. Compra cancelada\\.")
            return None

        step_size = exchange_info['step_size']
        min_qty = exchange_info['min_qty']
        min_notional = exchange_info['min_notional']

        # --- NUEVOS LOGS DE DEPURACIÓN (COMPRA) ---
        debug_msg_buy_initial = (
            f"ℹ️ *DEBUG Compra {simbolo} - Inicial:*\n"
            f"   Cant\\. calculada por riesgo: `{cantidad:.8f}`"
        )
        send_telegram_message(debug_msg_buy_initial)
        logger.info(f"DEBUG Compra - Inicial: Cantidad calculada por riesgo: {cantidad:.8f}")
        # -----------------------------------------

        # Redondear la cantidad al step_size más cercano y asegurar que sea al menos min_qty
        # La función int() trunca los decimales, asegurando que la cantidad sea un múltiplo del step_size
        cantidad_a_ordenar = max(min_qty, float(int(cantidad / step_size) * step_size))
        
        # --- NUEVOS LOGS DE DEPURACIÓN (COMPRA) ---
        logger.info(f"DEBUG Compra: Cantidad tras ajuste LOT_SIZE/minQty: {cantidad_a_ordenar:.8f}")
        send_telegram_message(f"ℹ️ *DEBUG Compra {simbolo} - Ajustada:*\n   Cant\\. ajustada por filtros: `{cantidad_a_ordenar:.8f}`")
        # -----------------------------------------

        # Validar el valor nocional mínimo (cantidad * precio) antes de enviar la orden
        current_price_for_check = obtener_precio(simbolo)
        if current_price_for_check == 0:
            logger.error("No se pudo obtener el precio actual para la validación MIN_NOTIONAL.")
            send_telegram_message("🔴 ERROR: No se pudo obtener el precio para validar MIN_NOTIONAL\\. Compra cancelada\\.")
            return None

        # --- NUEVOS LOGS DE DEPURACIÓN (COMPRA) ---
        logger.info(f"DEBUG Compra: Precio actual para chequeo MIN_NOTIONAL: {current_price_for_check:.2f}")
        logger.info(f"DEBUG Compra: Valor nocional calculado: {cantidad_a_ordenar * current_price_for_check:.2f} USDT (Mínimo: {min_notional:.2f} USDT)")
        send_telegram_message(f"ℹ️ *DEBUG Compra {simbolo} - Pre-orden:*\n   Precio actual: `{current_price_for_check:.2f}`\n   Valor nocional de orden: `{cantidad_a_ordenar * current_price_for_check:.2f}` USDT")
        # -----------------------------------------

        if cantidad_a_ordenar * current_price_for_check < min_notional:
            logger.warning(f"La cantidad calculada {cantidad_a_ordenar:.8f} ({cantidad_a_ordenar * current_price_for_check:.2f} USDT) es menor que MIN_NOTIONAL {min_notional} USDT.")
            send_telegram_message(f"⚠️ ADVERTENCIA: Cantidad de compra `{cantidad_a_ordenar:.8f}` es menor que el mínimo permitido (MIN_NOTIONAL)\\_ No se puede ejecutar la orden\\.")
            return None

        logger.info(f"Cantidad final a ordenar después de ajustes: {cantidad_a_ordenar:.8f}")

        # Envía la orden de compra a mercado
        order = client.order_market_buy(symbol=simbolo, quantity=cantidad_a_ordenar)

        if order and order['status'] == 'FILLED': # Si la orden se ejecutó completamente
            executed_qty = float(order['executedQty'])           # Cantidad realmente comprada
            cummulative_quote_qty = float(order['cummulativeQuoteQty']) # Costo total en USDT
            avg_price = cummulative_quote_qty / executed_qty if executed_qty > 0 else 0 # Precio promedio de ejecución
            
            # Información de la comisión (si está disponible)
            commission_info = order['fills'][0] if order['fills'] else {}
            commission = float(commission_info.get('commission', 0))
            commission_asset = commission_info.get('commissionAsset', 'N/A')

            logger.info(f"✅ Compra EXITOSA para {order['symbol']} (ID: {order['orderId']}):")
            logger.info(f"   Cantidad comprada: {executed_qty:.8f}")
            logger.info(f"   Precio promedio: {avg_price:.2f} {order['symbol'].replace('BTC', '').replace('USDT', '')}")
            logger.info(f"   Costo total: {cummulative_quote_qty:.2f} {order['symbol'].replace('BTCUSDT', 'USDT')}")
            logger.info(f"   Comisión: {commission:.8f} {commission_asset}")

            # Actualiza el estado global del bot
            last_buy_price = avg_price
            last_buy_quantity = executed_qty
            has_open_position = True
            save_bot_state() # Guarda el estado después de una compra exitosa

            msg = (
                f"🟢 *Compra exitosa de {order['symbol']}*\n"
                f"   Cantidad: `{executed_qty:.8f}`\n"
                f"   Precio Promedio: `{avg_price:.2f}`\n"
                f"   Costo Total: `{cummulative_quote_qty:.2f}`\n"
                f"   _Posición ABIERTA, esperando OCO\\._"
            )
            send_telegram_message(msg)

            # Establece la orden OCO inmediatamente después de la compra exitosa
            if executed_qty > 0:
                oco_base_price = avg_price # El precio base para la OCO es el precio promedio de compra
                logger.info(f"Preparando orden OCO basada en precio de compra {oco_base_price:.2f}...")
                establecer_orden_oco(simbolo, executed_qty, oco_base_price)
        else:
            logger.warning(f"⚠️ La orden de compra para {simbolo} no fue FILLED o hubo un problema:")
            logger.warning(json.dumps(order, indent=2)) # Log de la respuesta completa de la orden
            send_telegram_message(f"🔴 ERROR: La compra de `{simbolo}` no fue FILLED\\. Estado: `{order.get('status', 'N/A')}`")
        return order
    except BinanceAPIException as e:
        logger.error(f"❌ Error en compra para {simbolo}: {e}")
        # Notificación más específica para errores comunes de Binance API
        if e.code == -1013: # Errores de filtro (cantidad, precio, etc.)
            send_telegram_message(f"🔴 ERROR Binance API al comprar (Filtro de Orden): `{e.message}`\\. Cantidad o valor no cumplen requisitos de Binance\\.")
        elif e.code == -2010: # Fondos insuficientes, cuenta deshabilitada, etc.
            send_telegram_message(f"🔴 ERROR Binance API al comprar (Fondos Insuficientes/Cuenta): `{e.message}`\\.")
        else:
            send_telegram_message(f"🔴 ERROR Binance API al comprar: `{e}`")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado al comprar {simbolo}: {e}")
        send_telegram_message(f"🔴 ERROR inesperado al comprar: `{e}`")
        return None

def vender(simbolo="BTCUSDT", cantidad=0.0005):
    """
    Ejecuta una orden de venta a precio de mercado y calcula la ganancia/pérdida (P&L)
    de la operación anterior si hay un precio de compra registrado.
    """
    global last_buy_price, last_buy_quantity, has_open_position
    try:
        logger.info(f"\nIntentando vender {cantidad} de {simbolo} a precio de mercado...")
        
        exchange_info = get_exchange_info(simbolo)
        if not exchange_info:
            send_telegram_message("🔴 ERROR: No se pudo obtener información de exchange para la venta\\. Venta cancelada\\.")
            return None

        step_size = exchange_info['step_size']
        min_qty = exchange_info['min_qty']
        min_notional = exchange_info['min_notional']

        # --- NUEVOS LOGS DE DEPURACIÓN (VENTA) ---
        debug_msg_sell_initial = (
            f"ℹ️ *DEBUG Venta {simbolo} - Inicial:*\n"
            f"   Cant\\. a vender: `{cantidad:.8f}`"
        )
        send_telegram_message(debug_msg_sell_initial)
        logger.info(f"DEBUG Venta - Inicial: Cantidad a vender: {cantidad:.8f}")
        # -----------------------------------------

        # Redondear la cantidad a vender al step_size más cercano y asegurar que sea al menos min_qty
        cantidad_a_ordenar = max(min_qty, float(int(cantidad / step_size) * step_size))

        # --- NUEVOS LOGS DE DEPURACIÓN (VENTA) ---
        logger.info(f"DEBUG Venta: Cantidad tras ajuste LOT_SIZE/minQty: {cantidad_a_ordenar:.8f}")
        send_telegram_message(f"ℹ️ *DEBUG Venta {simbolo} - Ajustada:*\n   Cant\\. ajustada por filtros: `{cantidad_a_ordenar:.8f}`")
        # -----------------------------------------

        # Validar el valor nocional mínimo antes de enviar la orden de venta
        current_price_for_check = obtener_precio(simbolo)
        if current_price_for_check == 0:
            logger.error("No se pudo obtener el precio actual para la validación MIN_NOTIONAL en venta.")
            send_telegram_message("🔴 ERROR: No se pudo obtener el precio para validar MIN_NOTIONAL en venta\\. Venta cancelada\\.")
            return None

        # --- NUEVOS LOGS DE DEPURACIÓN (VENTA) ---
        logger.info(f"DEBUG Venta: Precio actual para chequeo MIN_NOTIONAL: {current_price_for_check:.2f}")
        logger.info(f"DEBUG Venta: Valor nocional calculado: {cantidad_a_ordenar * current_price_for_check:.2f} USDT (Mínimo: {min_notional:.2f} USDT)")
        send_telegram_message(f"ℹ️ *DEBUG Venta {simbolo} - Pre-orden:*\n   Precio actual: `{current_price_for_check:.2f}`\n   Valor nocional de orden: `{cantidad_a_ordenar * current_price_for_check:.2f}` USDT")
        # -----------------------------------------

        if cantidad_a_ordenar * current_price_for_check < min_notional:
            logger.warning(f"La cantidad calculada para vender {cantidad_a_ordenar:.8f} ({cantidad_a_ordenar * current_price_for_check:.2f} USDT) es menor que MIN_NOTIONAL {min_notional} USDT.")
            send_telegram_message(f"⚠️ ADVERTENCIA: Cantidad de venta `{cantidad_a_ordenar:.8f}` es menor que el mínimo permitido (MIN_NOTIONAL)\\_ No se puede ejecutar la orden\\.")
            return None

        logger.info(f"Cantidad final a ordenar para venta después de ajustes: {cantidad_a_ordenar:.8f}")

        # Envía la orden de venta a mercado
        order = client.order_market_sell(symbol=simbolo, quantity=cantidad_a_ordenar)

        if order and order['status'] == 'FILLED': # Si la orden se ejecutó completamente
            executed_qty = float(order['executedQty'])           # Cantidad realmente vendida
            cummulative_quote_qty = float(order['cummulativeQuoteQty']) # Total recibido en USDT
            avg_price = cummulative_quote_qty / executed_qty if executed_qty > 0 else 0 # Precio promedio de ejecución
            
            # Información de la comisión (si está disponible)
            commission_info = order['fills'][0] if order['fills'] else {}
            commission = float(commission_info.get('commission', 0))
            commission_asset = commission_info.get('commissionAsset', 'N/A')

            profit_loss = 0.0
            # Calcula la ganancia o pérdida si hay un precio de compra anterior registrado
            if last_buy_price > 0 and executed_qty > 0:
                profit_loss = (avg_price - last_buy_price) * min(executed_qty, last_buy_quantity)
                logger.info(f"   Ganancia/Pérdida de la operación anterior: {profit_loss:.2f} USDT")

            logger.info(f"✅ Venta EXITOSA para {order['symbol']} (ID: {order['orderId']}):")
            logger.info(f"   Cantidad vendida: {executed_qty:.8f}")
            logger.info(f"   Precio promedio: {avg_price:.2f} {order['symbol'].replace('BTC', '').replace('USDT', '')}")
            logger.info(f"   Ganancia total (USDT): {cummulative_quote_qty:.2f}")
            logger.info(f"   Comisión: {commission:.8f} {commission_asset}")
            
            # Resetea el estado de la posición del bot
            last_buy_price = 0.0
            last_buy_quantity = 0.0
            has_open_position = False
            save_bot_state() # Guarda el estado después de una venta exitosa

            msg = (
                f"🔴 *Venta exitosa de {order['symbol']}*\n"
                f"   Cantidad: `{executed_qty:.8f}`\n"
                f"   Precio Promedio: `{avg_price:.2f}`\n"
                f"   Ganancia Bruta: `{cummulative_quote_qty:.2f}`"
            )
            if profit_loss != 0.0:
                msg += f"\n   *P\\&L de la operación:* `{profit_loss:.2f} USDT`" # Añade el P&L si se calculó
            send_telegram_message(msg)

        else:
            logger.warning(f"⚠️ La orden de venta para {simbolo} no fue FILLED o hubo un problema:")
            logger.warning(json.dumps(order, indent=2))
            send_telegram_message(f"🔴 ERROR: La venta de `{simbolo}` no fue FILLED\\. Estado: `{order.get('status', 'N/A')}`")
        return order
    except BinanceAPIException as e:
        logger.error(f"❌ Error en venta para {simbolo}: {e}")
        if e.code == -1013: 
            send_telegram_message(f"🔴 ERROR Binance API al vender (Filtro de Orden): `{e.message}`\\. Cantidad o valor no cumplen requisitos de Binance\\.")
        elif e.code == -2010: 
            send_telegram_message(f"🔴 ERROR Binance API al vender (Fondos Insuficientes/Cuenta): `{e.message}`\\.")
        else:
            send_telegram_message(f"🔴 ERROR Binance API al vender: `{e}`")
        return None
    except Exception as e:
        logger.error(f"❌ Error inesperado al vender {simbolo}: {e}")
        send_telegram_message(f"🔴 ERROR inesperado al vender: `{e}`")
        return None

# --- Función para obtener actualizaciones de Telegram ---
def get_telegram_updates(offset=None):
    """
    Obtiene las últimas actualizaciones (mensajes) de Telegram del bot.
    Usa 'offset' para indicar desde qué actualización empezar a buscar,
    evitando procesar mensajes ya leídos.
    """
    if not telegram_bot_token: # No intenta obtener actualizaciones si el token no está configurado
        return []
    
    url = f"[https://api.telegram.org/bot](https://api.telegram.org/bot){telegram_bot_token}/getUpdates"
    params = {'timeout': 30, 'offset': offset} # Añade un timeout para evitar que la petición bloquee mucho
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        updates = response.json().get('result', [])
        return updates
    except requests.exceptions.RequestException as e:
        logger.error(f"Error al obtener actualizaciones de Telegram: {e}")
        return []
    except Exception as e:
        logger.error(f"Error inesperado al procesar actualizaciones de Telegram: {e}")
        return []

# --- Función para enviar reporte de estado ---
def send_status_report(current_price, btc_saldo, usdt_saldo, current_rsi, current_sma_long=None):
    """
    Genera y envía un reporte de estado detallado a Telegram.
    Incluye información de saldos, precio actual, RSI y SMA (si está disponible).
    """
    report_msg = "*📊 Reporte de Estado del Bot:*\n"
    report_msg += f"Fecha: `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}`\n"
    report_msg += f"Precio Actual {trading_pair}: `{current_price:.2f} USDT`\n"
    report_msg += f"RSI Actual: `{current_rsi:.2f}`\n" # Incluimos el RSI en el reporte
    if current_sma_long is not None: # Si la SMA está disponible, la incluimos
        report_msg += f"SMA {sma_long_period} Periodos: `{current_sma_long:.2f}`\n"
    report_msg += f"Saldo BTC: `{btc_saldo:.8f}`\n"
    report_msg += f"Saldo USDT: `{usdt_saldo:.2f}`\n"

    # Verificar órdenes abiertas en Binance directamente para una vista más precisa
    open_orders_binance = []
    try:
        open_orders_binance = client.get_open_orders(symbol=trading_pair)
    except BinanceAPIException as e:
        logger.warning(f"No se pudieron obtener órdenes abiertas para el reporte: {e}")
        report_msg += "Estado de Órdenes: `Error al consultar`\n"
    
    if open_orders_binance:
        report_msg += f"Estado de Órdenes: `✅ {len(open_orders_binance)} órdenes abiertas`\n"
        for order in open_orders_binance:
            order_type = 'OCO' if 'orderListId' in order and order['orderListId'] != -1 else 'Limit'
            report_msg += f"  - ID: `{order.get('orderId')}` Tipo: `{order_type}` Lado: `{order.get('side')}` Precio: `{float(order.get('price')):.2f}` Qty: `{float(order.get('origQty')):.8f}`\n"
    else:
        report_msg += "Estado de Órdenes: `No hay órdenes abiertas en Binance`\n"

    # Información de la última operación/posición
    if has_open_position:
        report_msg += f"\n*📈 Posición Actual: ABIERTA*\n"
        report_msg += f"  Cantidad: `{last_buy_quantity:.8f} {symbol_base}`\n"
        report_msg += f"  Precio de Compra: `{last_buy_price:.2f} USDT`\n"
        # Calcular P&L flotante si hay una posición abierta
        current_pnl_usdt = (current_price - last_buy_price) * last_buy_quantity
        report_msg += f"  P\\&L Flotante: `{current_pnl_usdt:.2f} USDT`\n"
    else:
        report_msg += "\n*📉 Posición Actual: CERRADA*\n"
        if last_buy_price > 0 and last_buy_quantity > 0: # Si hay datos de la última operación cerrada
             report_msg += f"  Última Compra: `{last_buy_quantity:.8f} {symbol_base}` @ `{last_buy_price:.2f} USDT`\n"
        
    send_telegram_message(report_msg)


# --- Lógica Principal del Bot (Bucle de Operación) ---
if __name__ == "__main__":
    # Configuración de los parámetros de trading
    symbol_base = 'BTC'                        # Moneda base (la que se compra/vende)
    symbol_quote = 'USDT'                      # Moneda de cotización (con la que se opera)
    trading_pair = f"{symbol_base}{symbol_quote}" # Par de trading (ej. BTCUSDT)
    intervalo_velas = Client.KLINE_INTERVAL_1MINUTE # Intervalo de las velas (ej. 1 minuto)
    rsi_period = 14                             # Periodo para el cálculo del RSI
    sma_long_period = 200                       # Periodo para la Media Móvil Simple larga (NUEVO)
    telegram_polling_interval = 30              # Intervalo en segundos para revisar nuevos mensajes de Telegram

    # Porcentaje de riesgo por operación (ej. 0.01 = 1% de tu capital en riesgo por trade)
    # ¡AJUSTA ESTE VALOR SEGÚN TU TOLERANCIA AL RIESGO!
    risk_per_trade_percentage = 0.01 
    
    # El porcentaje de Stop Loss es fijo de la estrategia OCO (0.2% de pérdida)
    # Basado en la configuración de `establecer_orden_oco`
    stop_loss_percentage = 0.002 

    load_bot_state() # Carga el estado del bot al iniciar (si existe)

    logger.info("Iniciando Bot de Trading en Binance Testnet en bucle...")
    send_telegram_message("🚀 *Bot de Trading Iniciado en Binance Testnet*\\.") # Mensaje de inicio

    # Obtener el último update_id al iniciar para no procesar mensajes antiguos de Telegram
    updates_on_start = get_telegram_updates()
    if updates_on_start:
        last_telegram_update_id = updates_on_start[-1]['update_id'] + 1
        logger.info(f"Último update_id de Telegram al inicio: {last_telegram_update_id}")

    # Bucle principal de ejecución del bot
    while True:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        logger.info(f"\n--- Ciclo de Operación Iniciado ({timestamp}) ---")

        current_price = obtener_precio(trading_pair) # Obtiene el precio actual del par
        send_telegram_message(f"📈 *Precio actual de {trading_pair}:* `{current_price:.2f} USDT`") 
        logger.info(f"Precio actual {trading_pair}: {current_price:.2f}")

        # Obtenemos suficientes velas para calcular tanto el RSI como la SMA larga.
        # Se añaden 5 velas extra por si acaso, para asegurar que los indicadores tengan suficientes datos.
        df = obtener_velas(trading_pair, intervalo_velas, limit=max(rsi_period, sma_long_period) + 5)
        
        current_rsi = None       # Inicializamos el RSI a None
        current_sma_long = None  # Inicializamos la SMA a None

        # Procede solo si hay suficientes datos de velas para calcular ambos indicadores
        if not df.empty and len(df) >= max(rsi_period, sma_long_period):
            df.ta.rsi(close='close', length=rsi_period, append=True) # Calcula el RSI
            df.ta.sma(close='close', length=sma_long_period, append=True) # <-- NUEVO: Calcula la SMA
            
            current_rsi = df[f'RSI_{rsi_period}'].iloc[-1]           # Obtiene el último valor del RSI
            current_sma_long = df[f'SMA_{sma_long_period}'].iloc[-1] # <-- NUEVO: Obtiene el último valor de la SMA

            send_telegram_message(f"📊 *RSI actual ({rsi_period} periodos):* `{current_rsi:.2f}`\n📉 *SMA {sma_long_period} periodos:* `{current_sma_long:.2f}`")
            logger.info(f"RSI actual ({rsi_period} periodos, {intervalo_velas}): {current_rsi:.2f}")
            logger.info(f"SMA {sma_long_period} periodos: {current_sma_long:.2f}") # Log de la SMA

            btc_saldo, usdt_saldo = mostrar_saldo() # Obtiene los saldos de la cuenta

            # --- Control de posición abierta (verificación y actualización del estado) ---
            # Si el bot cree que tiene una posición abierta, verifica si las órdenes OCO siguen activas
            if has_open_position:
                open_orders_check = client.get_open_orders(symbol=trading_pair)
                if not open_orders_check: # Si no hay órdenes abiertas, significa que la OCO se ejecutó
                    logger.info("Detectado cierre de posición a través de OCO.")
                    send_telegram_message(f"🔔 *Posición cerrada por OCO* (Take Profit o Stop Loss alcanzado)\\. Verifique su saldo\\.")
                    # Resetea el estado de la posición
                    last_buy_price = 0.0
                    last_buy_quantity = 0.0
                    has_open_position = False
                    save_bot_state() # Guarda el nuevo estado
                else:
                    # Calcula el P&L flotante si la posición sigue abierta
                    current_pnl_usdt = (current_price - last_buy_price) * last_buy_quantity
                    logger.info(f"Posición ABIERTA. P&L flotante: {current_pnl_usdt:.2f} USDT")

            # --- Lógica de Compra:
            # Solo se intenta comprar si NO hay una posición abierta (`has_open_position` es False)
            if not has_open_position:
                logger.info(f"Verificando y cancelando órdenes abiertas para {trading_pair} antes de comprar...")
                if cancelar_todas_las_ordenes_abiertas(trading_pair): # Asegura que no hay órdenes pendientes
                    # <-- Condición de Compra ACTUALIZADA: RSI BAJO Y PRECIO SOBRE SMA Larga
                    if current_rsi is not None and current_rsi < 30 and \
                       current_sma_long is not None and current_price > current_sma_long: 
                        logger.info(f"Condición de compra por RSI y SMA cumplida (RSI: {current_rsi:.2f} < 30, Precio: {current_price:.2f} > SMA {current_sma_long:.2f}).")
                        send_telegram_message(f"✅ *Condición de compra cumplida:*\n   RSI `{current_rsi:.2f}` < 30\n   Precio `{current_price:.2f}` > SMA `{current_sma_long:.2f}`\\.")
                        
                        total_usdt_capital = usdt_saldo # Usa el saldo de USDT disponible como capital base

                        if current_price > 0 and stop_loss_percentage > 0:
                            # Calcula el monto máximo en USDT que se está dispuesto a arriesgar
                            max_risk_usdt = total_usdt_capital * risk_per_trade_percentage
                            
                            # Calcula la cantidad de BTC a comprar basándose en el riesgo máximo y el stop loss
                            # Formula: Riesgo Maximo / (Precio de Entrada * % de SL desde la entrada)
                            calculated_quantity_btc = max_risk_usdt / (current_price * stop_loss_percentage)
                            
                            logger.info(f"Capital USDT disponible: {total_usdt_capital:.2f}")
                            logger.info(f"Riesgo máximo por trade (USDT): {max_risk_usdt:.2f}")
                            logger.info(f"Cantidad de BTC calculada para operar: {calculated_quantity_btc:.8f}")

                            if calculated_quantity_btc > 0:
                                # Calcula el costo total estimado de la operación, añadiendo un pequeño buffer para comisiones/deslizamiento
                                cost_of_trade = calculated_quantity_btc * current_price * 1.001 
                                if usdt_saldo >= cost_of_trade: # Verifica si hay fondos suficientes
                                    send_telegram_message(f"ℹ️ *Calculando tamaño de posición:*\n   Capital: `{total_usdt_capital:.2f}` USDT\n   Riesgo: `{risk_per_trade_percentage*100:.2f}%`\n   Cantidad a operar: `{calculated_quantity_btc:.8f} BTC`")
                                    compra_result = comprar(cantidad=calculated_quantity_btc) # Ejecuta la compra
                                    if compra_result:
                                        time.sleep(5) # Espera un poco después de la operación
                                        mostrar_saldo() # Muestra los saldos actualizados
                                else:
                                    logger.warning(f"Fondos USDT insuficientes para la cantidad calculada ({cost_of_trade:.2f} USDT necesarios, {usdt_saldo:.2f} disponibles).")
                                    send_telegram_message(f"⚠️ *Fondos insuficientes:* Necesarios `{cost_of_trade:.2f}` USDT para la cantidad calculada\\. Disponibles `{usdt_saldo:.2f}` USDT\\.")
                            else:
                                logger.warning("La cantidad de BTC calculada para operar es cero o demasiado pequeña. No se puede comprar.")
                                send_telegram_message("⚠️ *Advertencia:* La cantidad de BTC calculada para operar es demasiado pequeña o cero\\. Compra cancelada\\.")

                        else:
                            logger.warning("El precio actual o el porcentaje de stop loss son cero, no se puede calcular la cantidad a operar.")
                            send_telegram_message("⚠️ *Advertencia:* El precio actual o el porcentaje de SL son cero\\. No se puede calcular la cantidad a operar\\.")
                    else:
                        logger.info(f"Condiciones de compra NO cumplidas (RSI: {current_rsi:.2f}, Precio: {current_price:.2f}, SMA: {current_sma_long:.2f}).")
                        send_telegram_message(f"❌ *Condición de compra NO cumplida:*\n   RSI `{current_rsi:.2f}` NO está sobrevendido (<30) O\n   Precio `{current_price:.2f}` NO está sobre SMA `{current_sma_long:.2f}`\\.")
                else:
                    logger.warning("No se pudieron cancelar las órdenes anteriores. Saltando la compra en este ciclo.")
                    send_telegram_message(f"⚠️ ADVERTENCIA: No se pudieron cancelar órdenes anteriores\\. Compra saltada\\.")

            # --- Lógica de Venta (sin cambios por la SMA, sigue el RSI o el OCO) ---
            # Solo se intenta vender si tenemos BTC para operar Y NO hay una posición abierta gestionada por OCO
            elif btc_saldo >= last_buy_quantity and not has_open_position: 
                open_orders_check = client.get_open_orders(symbol=trading_pair)
                if not open_orders_check: # Asegúrate de que no hay OCOs ya activas por algún motivo
                    if current_rsi is not None and current_rsi > 70:
                        logger.info(f"Condición de venta por RSI cumplida (RSI: {current_rsi:.2f} > 70) y no hay órdenes abiertas.")
                        send_telegram_message(f"✅ *Condición de venta cumplida:* RSI `{current_rsi:.2f}` > 70\\. Intentando vender\\.")
                        # Si `last_buy_quantity` es 0, deberías vender el `btc_saldo` disponible (o una parte)
                        # Pero para mantener la coherencia de la estrategia "por operación", se asume `last_buy_quantity`
                        venta_result = vender(cantidad=last_buy_quantity if last_buy_quantity > 0 else btc_saldo) 
                        if venta_result:
                            time.sleep(5)
                            mostrar_saldo()
                    else:
                        logger.info(f"RSI ({current_rsi:.2f}) no indica sobrecompra para vender.")
                        send_telegram_message(f"❌ *Condición de venta NO cumplida:* RSI `{current_rsi:.2f}` no está sobrecomprado (>70)\\.")
                else:
                    logger.info(f"Hay {len(open_orders_check)} órdenes abiertas para {trading_pair}. No se venderá por mercado para evitar interferir con el OCO.")
                    send_telegram_message(f"ℹ️ *No se vende:* Hay `{len(open_orders_check)}` órdenes abiertas para {trading_pair}\\. El bot no intervendrá con el OCO\\.")
            else:
                logger.info(f"Saldos insuficientes o ya tenemos BTC y una posición abierta: (BTC: {btc_saldo:.8f}, USDT: {usdt_saldo:.2f}).")
                if has_open_position:
                    send_telegram_message(f"ℹ️ *Manteniendo Posición:* Se tiene una posición abierta y se espera la ejecución de la OCO\\. Saldo BTC: `{btc_saldo:.8f}`, Saldo USDT: `{usdt_saldo:.2f}`\\.")
                else:
                    send_telegram_message(f"ℹ️ *Sin operación:* Saldos insuficientes o sin condiciones claras\\. Saldo BTC: `{btc_saldo:.8f}`, Saldo USDT: `{usdt_saldo:.2f}`\\.")
        else:
            logger.info("No hay suficientes datos de velas para calcular el RSI o la SMA, o el DataFrame está vacío.")
            send_telegram_message("⚠️ *Advertencia:* No hay suficientes datos de velas para calcular RSI/SMA\\. Operación pospuesta\\.")

        logger.info(f"--- Ciclo de Operación Finalizado ({timestamp}).")
        
        # --- Polling de Telegram para comandos ---
        logger.info(f"Revisando mensajes de Telegram... (offset: {last_telegram_update_id})")
        updates = get_telegram_updates(offset=last_telegram_update_id)
        for update in updates:
            # Asegurarse de que sea un mensaje de texto y del chat_id configurado
            if 'message' in update and 'text' in update['message'] and str(update['message']['chat']['id']) == telegram_chat_id:
                message_text = update['message']['text']
                logger.info(f"Comando de Telegram recibido: {message_text}")
                if message_text.lower() == '/status':
                    logger.info("Comando /status recibido. Enviando reporte.")
                    # Pasamos current_rsi y current_sma_long a la función de reporte
                    send_status_report(current_price, btc_saldo, usdt_saldo, current_rsi, current_sma_long)
            # Actualizar el offset para la próxima llamada, incluso si no era un comando válido
            last_telegram_update_id = update['update_id'] + 1
        
        logger.info(f"Esperando {telegram_polling_interval} segundos para el próximo ciclo...")
        time.sleep(telegram_polling_interval) # Pausa antes del siguiente ciclo de operación



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