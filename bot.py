import os
import time
import logging
import requests
import json
import csv
from binance.client import Client
from binance.enums import *
from datetime import datetime, timedelta

# Importa el nuevo módulo para la gestión de la configuración
import config_manager # <--- NUEVO: Importa config_manager

# --- Configuración de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =================== CONFIGURACIÓN (Asegúrate de que estas variables de entorno estén configuradas) ===================

# Claves de API de Binance. ¡NO COMPARTAS ESTAS CLAVES!
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Token de tu bot de Telegram y Chat ID para enviar mensajes.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Archivos para guardar y cargar las posiciones del bot.
# El CONFIG_FILE ahora se gestiona dentro de config_manager.py
OPEN_POSITIONS_FILE = "open_positions.json"

# =================== CARGA DE PARÁMETROS DESDE config_manager ===================

# Cargar parámetros al inicio del bot utilizando el nuevo módulo.
bot_params = config_manager.load_parameters() # <--- MODIFICADO: Carga desde config_manager

# Asignar los valores del diccionario cargado a las variables globales del bot.
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT","XRPUSDT", "DOGEUSDT", "MATICUSDT"]
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
client = Client(API_KEY, API_SECRET, testnet=True)
client.API_URL = 'https://testnet.binance.vision/api'

# Diccionario para almacenar las posiciones que el bot tiene abiertas y está gestionando.
posiciones_abiertas = {}

# Variables para la gestión de la comunicación con Telegram
last_update_id = 0
TELEGRAM_LISTEN_INTERVAL = 5

# Variables para la gestión de informes diarios
transacciones_diarias = []
ultima_fecha_informe_enviado = None
last_trading_check_time = 0

# Variables para la gestión de la persistencia de posiciones
last_save_time_positions = 0
SAVE_POSITIONS_DEBOUNCE_INTERVAL = 60

# =================== FUNCIONES DE CARGA Y GUARDADO DE POSICIONES ABIERTAS ===================

def load_open_positions():
    """
    Carga las posiciones abiertas desde el archivo OPEN_POSITIONS_FILE.
    Si el archivo no existe o hay un error de formato JSON, el bot inicia sin posiciones.
    Asegura que los valores numéricos se carguen como flotantes.
    También inicializa nuevas claves para compatibilidad con versiones anteriores del archivo.
    """
    if os.path.exists(OPEN_POSITIONS_FILE):
        try:
            with open(OPEN_POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                for symbol, pos in data.items():
                    pos['precio_compra'] = float(pos['precio_compra'])
                    pos['cantidad_base'] = float(pos['cantidad_base'])
                    pos['max_precio_alcanzado'] = float(pos['max_precio_alcanzado'])
                    if 'sl_moved_to_breakeven' not in pos:
                        pos['sl_moved_to_breakeven'] = False
                    if 'stop_loss_fijo_nivel_actual' not in pos:
                        pos['stop_loss_fijo_nivel_actual'] = pos['precio_compra'] * (1 - STOP_LOSS_PORCENTAJE)
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

def save_open_positions_debounced():
    """
    Guarda las posiciones abiertas en el archivo OPEN_POSITIONS_FILE, aplicando un mecanismo de "debounce".
    Esto significa que la escritura real en el disco solo se realizará si ha pasado un tiempo mínimo
    (definido por SAVE_POSITIONS_DEBOUNCE_INTERVAL) desde la última escritura.
    Este enfoque reduce las operaciones de I/O de disco, lo que mejora el rendimiento del bot,
    especialmente en entornos de despliegue como Railway donde las operaciones de disco pueden ser más lentas.
    Las operaciones críticas (compra/venta) siguen guardando inmediatamente.
    """
    global last_save_time_positions
    current_time = time.time()

    if (current_time - last_save_time_positions) >= SAVE_POSITIONS_DEBOUNCE_INTERVAL:
        try:
            with open(OPEN_POSITIONS_FILE, 'w') as f:
                json.dump(posiciones_abiertas, f, indent=4)
            logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (debounced).")
            last_save_time_positions = current_time
        except IOError as e:
            logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE}: {e}")
    else:
        logging.debug(f"⏳ Guardado de posiciones pospuesto. Último guardado hace {current_time - last_save_time_positions:.2f}s.")


# Cargar posiciones abiertas al inicio del bot.
posiciones_abiertas = load_open_positions()

# =================== FUNCIONES AUXILIARES DE UTILIDAD ===================

def send_telegram_message(message):
    """
    Envía un mensaje de texto al chat de Telegram configurado.
    Permite formato HTML básico (ej. <b> para negrita, <code> para código) para mejorar la legibilidad.
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return True
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
        with open(file_path, 'rb') as doc:
            files = {'document': doc}
            payload = {'chat_id': chat_id, 'caption': caption}
            response = requests.post(url, data=payload, files=files)
            response.raise_for_status()
            logging.info(f"✅ Documento {file_path} enviado con éxito a Telegram.")
            return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error enviando documento Telegram '{file_path}': {e}")
        send_telegram_message(f"❌ Error enviando documento: {e}")
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
        return 1 / float(eur_usdt_price['price'])
    except Exception as e:
        logging.warning(f"⚠️ No se pudo obtener el precio de EURUSDT: {e}. Usando 0 para la conversión a EUR.")
        return 0.0

def obtener_saldos_formateados():
    """
    Formatea un mensaje con los saldos de USDT disponibles y el capital total estimado (en USDT y EUR).
    El capital total incluye el USDT disponible y el valor actual de todas las posiciones abiertas.
    """
    try:
        saldo_usdt = obtener_saldo_moneda("USDT")
        capital_total_usdt = saldo_usdt
        
        for symbol, pos in posiciones_abiertas.items():
            precio_actual = obtener_precio_actual(symbol)
            capital_total_usdt += pos['cantidad_base'] * precio_actual
        
        eur_usdt_rate = obtener_precio_eur()
        capital_total_eur = capital_total_usdt * eur_usdt_rate if eur_usdt_rate else 0

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
        return None
    
    ema = sum(precios_cierre[:periodo]) / periodo
    multiplier = 2 / (periodo + 1)
    
    for i in range(periodo, len(precios_cierre)):
        ema = ((precios_cierre[i] - ema) * multiplier) + ema
    return ema

def calcular_rsi(precios_cierre, periodo):
    """
    Calcula el Índice de Fuerza Relativa (RSI) para una lista de precios de cierre.
    El RSI es un oscilador de momentum que mide la velocidad y el cambio de los movimientos de los precios.
    periodo: Número de períodos para el cálculo del RSI (ej. 14 para RSI de 14 períodos).
    """
    if len(precios_cierre) < periodo + 1:
        return None

    precios_diff = [precios_cierre[i] - precios_cierre[i-1] for i in range(1, len(precios_cierre))]
    
    ganancias = [d if d > 0 else 0 for d in precios_diff]
    perdidas = [-d if d < 0 else 0 for d in precios_diff]

    avg_ganancia = sum(ganancias[:periodo]) / periodo
    avg_perdida = sum(perdidas[:periodo]) / periodo

    if avg_perdida == 0:
        return 100
    
    rs = avg_ganancia / avg_perdida
    rsi = 100 - (100 / (1 + rs))

    for i in range(periodo, len(ganancias)):
        avg_ganancia = ((avg_ganancia * (periodo - 1)) + ganancias[i]) / periodo
        avg_perdida = ((avg_perdida * (periodo - 1)) + perdidas[i]) / periodo
        
        if avg_perdida == 0:
            rsi = 100
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
        limit = max(ema_periodo, rsi_periodo) + 10
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=limit)
        
        precios_cierre = [float(kline[4]) for kline in klines]
        
        ema = calcular_ema(precios_cierre, ema_periodo)
        rsi = calcular_rsi(precios_cierre, rsi_periodo)
        
        return ema, rsi
    except Exception as e:
        logging.error(f"❌ Error al obtener klines o calcular indicadores para {symbol}: {e}")
        return None, None

def get_step_size(symbol):
    """
    Obtiene el 'stepSize' para un símbolo de Binance.
    El 'stepSize' es el incremento mínimo permitido para la cantidad de una orden (ej. 0.001 BTC).
    Es crucial para ajustar las cantidades de compra/venta y evitar errores de precisión de la API (-1111).
    """
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                return float(f['stepSize'])
        logging.warning(f"⚠️ No se encontró LOT_SIZE filter para {symbol}. Usando stepSize por defecto: 0.000001")
        return 0.000001
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

    s_step_size = str(step_size)
    if '.' in s_step_size:
        decimal_places = len(s_step_size.split('.')[1].rstrip('0'))
    else:
        decimal_places = 0

    try:
        factor = 10**decimal_places
        ajustada = (round(cantidad * factor / (step_size * factor)) * (step_size * factor)) / factor
        
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

    capital_total = saldo_usdt
    riesgo_max_por_operacion_usdt = capital_total * RIESGO_POR_OPERACION_PORCENTAJE
    
    diferencia_precio_sl = precio_actual * stop_loss_porcentaje
    
    if diferencia_precio_sl <= 0:
        logging.warning("La diferencia de precio con el SL es cero o negativa, no se puede calcular la cantidad a comprar.")
        return 0.0

    cantidad_a_comprar = riesgo_max_por_operacion_usdt / diferencia_precio_sl

    step = get_step_size(symbol)
    min_notional = 10.0

    cantidad_ajustada = ajustar_cantidad(cantidad_a_comprar, step)
    
    if (cantidad_ajustada * precio_actual) < min_notional:
        logging.warning(f"La cantidad calculada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) es demasiado pequeña para el mínimo nocional de {min_notional} USDT.")
        min_cantidad_ajustada = ajustar_cantidad(min_notional / precio_actual, step)
        if (min_cantidad_ajustada * precio_actual) <= saldo_usdt:
            cantidad_ajustada = min_cantidad_ajustada
            logging.info(f"Ajustando a la cantidad mínima nocional permitida: {cantidad_ajustada:.6f} {symbol.replace('USDT', '')}")
        else:
            logging.warning(f"No hay suficiente saldo USDT para comprar la cantidad mínima nocional de {symbol}.")
            return 0.0

    if (cantidad_ajustada * precio_actual) > saldo_usdt:
        logging.warning(f"La cantidad ajustada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) excede el saldo disponible en USDT. Reduciendo a lo máximo posible.")
        cantidad_max_posible = ajustar_cantidad(saldo_usdt / precio_actual, step)
        if (cantidad_max_posible * precio_actual) >= min_notional:
            cantidad_ajustada = cantidad_max_posible
        else:
            logging.warning(f"El saldo restante no permite comprar ni la cantidad mínima nocional de {symbol}.")
            return 0.0

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
        order = client.order_market_buy(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE COMPRA EXITOSA para {symbol}: {order}")
        
        if order and 'fills' in order and len(order['fills']) > 0:
            precio_ejecucion = float(order['fills'][0]['price'])
            qty_ejecutada = float(order['fills'][0]['qty'])
            
            posiciones_abiertas[symbol] = {
                'precio_compra': precio_ejecucion,
                'cantidad_base': qty_ejecutada,
                'max_precio_alcanzado': precio_ejecucion,
                'sl_moved_to_breakeven': False,
                'stop_loss_fijo_nivel_actual': precio_ejecucion * (1 - STOP_LOSS_PORCENTAJE)
            }
            try:
                with open(OPEN_POSITIONS_FILE, 'w') as f:
                    json.dump(posiciones_abiertas, f, indent=4)
                logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (después de compra).")
            except IOError as e:
                logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE} después de compra: {e}")
            
            transacciones_diarias.append({
                'FechaHora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'Símbolo': symbol,
                'Tipo': 'COMPRA',
                'Precio': precio_ejecucion,
                'Cantidad': qty_ejecutada,
                'GananciaPerdidaUSDT': 0.0,
                'Motivo': 'Condiciones de entrada'
            })
        return order
    except Exception as e:
        logging.error(f"❌ FALLO DE ORDEN DE COMPRA para {symbol} (Cantidad: {cantidad}): {e}")
        send_telegram_message(f"❌ Error en compra de {symbol}: {e}")
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
        order = client.order_market_sell(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE VENTA EXITOSA para {symbol}: {order}")
        
        ganancia_perdida_usdt = 0.0
        precio_venta_ejecutada = float(order['fills'][0]['price']) if order and 'fills' in order and len(order['fills']) > 0 else 0.0

        if symbol in posiciones_abiertas:
            precio_compra = posiciones_abiertas[symbol]['precio_compra']
            ganancia_perdida_usdt = (precio_venta_ejecutada - precio_compra) * cantidad
            
            global TOTAL_BENEFICIO_ACUMULADO
            TOTAL_BENEFICIO_ACUMULADO += ganancia_perdida_usdt
            # MODIFICADO: Usa config_manager para guardar los parámetros
            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = TOTAL_BENEFICIO_ACUMULADO
            config_manager.save_parameters(bot_params) # <--- MODIFICADO: Llama a config_manager.save_parameters

            posiciones_abiertas.pop(symbol)
            try:
                with open(OPEN_POSITIONS_FILE, 'w') as f:
                    json.dump(posiciones_abiertas, f, indent=4)
                logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE} (después de venta).")
            except IOError as e:
                logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE} después de venta: {e}")

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
    if symbol not in posiciones_abiertas:
        send_telegram_message(f"❌ No hay una posición abierta para <b>{symbol}</b> que gestionar por comando.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero no hay posición abierta.")
        return

    base_asset = symbol.replace("USDT", "")
    cantidad_en_posicion = obtener_saldo_moneda(base_asset)

    if cantidad_en_posicion <= 0:
        send_telegram_message(f"❌ No hay saldo disponible de <b>{base_asset}</b> para vender.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero el saldo es 0.")
        return

    step = get_step_size(symbol)
    cantidad_a_vender_ajustada = ajustar_cantidad(cantidad_en_posicion, step)

    if cantidad_a_vender_ajustada <= 0:
        send_telegram_message(f"❌ La cantidad de <b>{base_asset}</b> a vender es demasiado pequeña o inválida.")
        logging.warning(f"Cantidad a vender ajustada para {symbol} es <= 0: {cantidad_a_vender_ajustada}")
        return

    send_telegram_message(f"⚙️ Intentando vender <b>{cantidad_a_vender_ajustada:.6f} {base_asset}</b> de <b>{symbol}</b> por comando...")
    logging.info(f"Comando de venta manual recibido para {symbol}. Cantidad a vender: {cantidad_a_vender_ajustada}")

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
    params = {'timeout': 30, 'offset': offset}
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
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

    updates = get_telegram_updates(last_update_id + 1)

    if updates and updates['ok']:
        for update in updates['result']:
            last_update_id = update['update_id']

            if 'message' in update and 'text' in update['message']:
                chat_id = str(update['message']['chat']['id'])
                text = update['message']['text'].strip()
                
                if chat_id != TELEGRAM_CHAT_ID:
                    send_telegram_message(f"⚠️ Comando recibido de chat no autorizado: <code>{chat_id}</code>")
                    logging.warning(f"Comando de chat no autorizado: {chat_id}")
                    continue

                parts = text.split()
                command = parts[0].lower()
                
                logging.info(f"Comando Telegram recibido: {text}")

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
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ TP establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_tp &lt;porcentaje_decimal_ej_0.03&gt;</code>")
                    elif command == "/set_sl_fijo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            STOP_LOSS_PORCENTAJE = new_value
                            bot_params['STOP_LOSS_PORCENTAJE'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ SL Fijo establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_sl_fijo &lt;porcentaje_decimal_ej_0.02&gt;</code>")
                    elif command == "/set_tsl":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            TRAILING_STOP_PORCENTAJE = new_value
                            bot_params['TRAILING_STOP_PORCENTAJE'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ TSL establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_tsl &lt;porcentaje_decimal_ej_0.015&gt;</code>")
                    elif command == "/set_riesgo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            RIESGO_POR_OPERACION_PORCENTAJE = new_value
                            bot_params['RIESGO_POR_OPERACION_PORCENTAJE'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ Riesgo por operación establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_riesgo &lt;porcentaje_decimal_ej_0.01&gt;</code>")
                    elif command == "/set_ema_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            EMA_PERIODO = new_value
                            bot_params['EMA_PERIODO'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ Período EMA establecido en: <b>{new_value}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_ema_periodo &lt;numero_entero_ej_10&gt;</code>")
                    elif command == "/set_rsi_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            RSI_PERIODO = new_value
                            bot_params['RSI_PERIODO'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ Período RSI establecido en: <b>{new_value}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_rsi_periodo &lt;numero_entero_ej_14&gt;</code>")
                    elif command == "/set_rsi_umbral":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            RSI_UMBRAL_SOBRECOMPRA = new_value
                            bot_params['RSI_UMBRAL_SOBRECOMPRA'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ Umbral RSI sobrecompra establecido en: <b>{new_value}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_rsi_umbral &lt;numero_entero_ej_70&gt;</code>")
                    elif command == "/set_intervalo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            INTERVALO = new_value
                            bot_params['INTERVALO'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ Intervalo del ciclo establecido en: <b>{new_value}</b> segundos")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_intervalo &lt;segundos_ej_300&gt;</code>")
                    elif command == "/set_breakeven_porcentaje":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            BREAKEVEN_PORCENTAJE = new_value
                            bot_params['BREAKEVEN_PORCENTAJE'] = new_value
                            config_manager.save_parameters(bot_params) # <--- MODIFICADO
                            send_telegram_message(f"✅ Porcentaje de Breakeven establecido en: <b>{new_value:.4f}</b>")
                        else:
                            send_telegram_message("❌ Uso: <code>/set_breakeven_porcentaje &lt;porcentaje_decimal_ej_0.005&gt;</code>")
                    
                    # --- Comandos de información y utilidades ---
                    elif command == "/get_params":
                        current_params_msg = "<b>Parámetros Actuales:</b>\n"
                        for key, value in bot_params.items():
                            if isinstance(value, float) and 'PORCENTAJE' in key.upper():
                                current_params_msg += f"- {key}: {value:.4f}\n"
                            else:
                                current_params_msg += f"- {key}: {value}\n"
                        send_telegram_message(current_params_msg)
                    elif command == "/csv":
                        send_telegram_message("Generando informe CSV. Esto puede tardar un momento...")
                        generar_y_enviar_csv_ahora()
                    elif command == "/help":
                        send_help_message()
                        send_keyboard_menu(chat_id, "Aquí tienes los comandos disponibles. También puedes usar el teclado de abajo:")
                    elif command == "/vender":
                        if len(parts) == 2:
                            symbol_to_sell = parts[1].upper()
                            if symbol_to_sell in SYMBOLS:
                                vender_por_comando(symbol_to_sell)
                            else:
                                send_telegram_message(f"❌ Símbolo <b>{symbol_to_sell}</b> no reconocido o no monitoreado por el bot.")
                        else:
                            send_telegram_message("❌ Uso: <code>/vender &lt;SIMBOLO_USDT&gt;</code> (ej. /vender BTCUSDT)")
                    elif command == "/beneficio":
                        send_beneficio_message()
                    elif command == "/get_positions_file":
                        send_positions_file_content()
                    else:
                        send_telegram_message("Comando desconocido. Usa <code>/help</code> para ver los comandos disponibles.")

                except ValueError:
                    send_telegram_message("❌ Valor inválido. Asegúrate de introducir un número o porcentaje correcto.")
                except Exception as ex:
                    logging.error(f"Error procesando comando '{text}': {ex}", exc_info=True)
                    send_telegram_message(f"❌ Error interno al procesar comando: {ex}")

# =================== FUNCIONES DE INFORMES CSV ===================

def generar_y_enviar_csv_ahora():
    """Genera un archivo CSV con las transacciones registradas hasta el momento y lo envía por Telegram."""
    if not transacciones_diarias:
        send_telegram_message("🚫 No hay transacciones registradas para generar el CSV.")
        return

    fecha_actual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nombre_archivo_csv = f"transacciones_historico_{fecha_actual}.csv"

    try:
        with open(nombre_archivo_csv, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['FechaHora', 'Símbolo', 'Tipo', 'Precio', 'Cantidad', 'GananciaPerdidaUSDT', 'Motivo']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for transaccion in transacciones_diarias:
                writer.writerow(transaccion)

        send_telegram_document(TELEGRAM_CHAT_ID, nombre_archivo_csv, f"📊 Informe de transacciones generado: {fecha_actual}")
        
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el CSV bajo demanda: {e}", exc_info=True)
        send_telegram_message(f"❌ Error al generar o enviar el CSV: {e}")
    finally:
        if os.path.exists(nombre_archivo_csv):
            os.remove(nombre_archivo_csv)

def enviar_informe_diario():
    """Genera un archivo CSV con las transacciones registradas para el día y lo envía por Telegram."""
    if not transacciones_diarias:
        send_telegram_message("🚫 No hay transacciones registradas para el día de hoy.")
        return

    fecha_diario = datetime.now().strftime("%Y-%m-%d")
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
    transacciones_diarias.clear()

# =================== FUNCIÓN DE BENEFICIO TOTAL ===================

def send_beneficio_message():
    """Envía el beneficio total acumulado por el bot a Telegram."""
    global TOTAL_BENEFICIO_ACUMULADO
    
    eur_usdt_rate = obtener_precio_eur()
    beneficio_eur = TOTAL_BENEFICIO_ACUMULADO * eur_usdt_rate if eur_usdt_rate else 0.0

    message = (
        f"📈 <b>Beneficio Total Acumulado:</b>\n"
        f"   - <b>{TOTAL_BENEFICIO_ACUMULADO:.2f} USDT</b>\n"
        f"   - <b>{beneficio_eur:.2f} EUR</b>"
    )
    send_telegram_message(message)

# =================== FUNCIONES DE TECLADO PERSONALIZADO DE TELEGRAM ===================

def send_keyboard_menu(chat_id, message_text="Selecciona una opción:"):
    """
    Envía un mensaje con un teclado personalizado de Telegram.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede enviar el teclado personalizado.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    keyboard = {
        'keyboard': [
            [{'text': '/beneficio'}, {'text': '/get_params'}],
            [{'text': '/csv'}, {'text': '/help'}],
            [{'text': '/vender BTCUSDT'}]
        ],
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'reply_markup': json.dumps(keyboard)
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
    Oculta el teclado personalizado de Telegram.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede ocultar el teclado.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
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
    
    commands = [
        {"command": "get_params", "description": "Muestra los parámetros actuales del bot"},
        {"command": "set_tp", "description": "Establece el Take Profit (ej. /set_tp 0.03)"},
        {"command": "set_sl_fijo", "description": "Establece el Stop Loss Fijo (ej. /set_sl_fijo 0.02)"},
        {"command": "set_tsl", "description": "Establece el Trailing Stop Loss (ej. /set_tsl 0.015)"},
        {"command": "set_riesgo", "description": "Establece el riesgo por operación (ej. /set_riesgo 0.01)"},
        {"command": "set_ema_periodo", "description": "Establece el período de la EMA (ej. /set_ema_periodo 10)"},
        {"command": "set_rsi_periodo", "description": "Establece el período del RSI (ej. /set_rsi_periodo 14)"},
        {"command": "set_rsi_umbral", "description": "Establece el umbral de sobrecompra del RSI (ej. 70)"},
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
    """Lee el contenido del archivo OPEN_POSITIONS_FILE y lo envía al chat de Telegram."""
    if not os.path.exists(OPEN_POSITIONS_FILE):
        send_telegram_message(f"❌ Archivo de posiciones abiertas (<code>{OPEN_POSITIONS_FILE}</code>) no encontrado.")
        logging.warning(f"Intento de leer {OPEN_POSITIONS_FILE}, pero no existe.")
        return

    try:
        with open(OPEN_POSITIONS_FILE, 'r') as f:
            content = f.read()
        
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
    """Envía un mensaje de ayuda detallado con la lista de todos los comandos disponibles."""
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
set_telegram_commands_menu()

logging.info("Bot iniciado. Esperando comandos y monitoreando el mercado...")

while True:
    start_time_cycle = time.time()
    
    try:
        # --- Manejar comandos de Telegram ---
        handle_telegram_commands()
        
        # --- Lógica del Informe Diario ---
        hoy = time.strftime("%Y-%m-%d")

        if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
            if ultima_fecha_informe_enviado is not None:
                send_telegram_message(f"Preparando informe del día {ultima_fecha_informe_enviado}...")
                enviar_informe_diario()
            
            ultima_fecha_informe_enviado = hoy
            transacciones_diarias.clear()

        # --- LÓGICA PRINCIPAL DE TRADING ---
        if (time.time() - last_trading_check_time) >= INTERVALO:
            logging.info(f"Iniciando ciclo de trading principal (cada {INTERVALO}s)...")
            general_message = ""

            for symbol in SYMBOLS:
                base = symbol.replace("USDT", "")
                saldo_base = obtener_saldo_moneda(base) 
                precio_actual = obtener_precio_actual(symbol)
                ema_valor, rsi_valor = calcular_ema_rsi(symbol, EMA_PERIODO, RSI_PERIODO)

                if ema_valor is None or rsi_valor is None:
                    logging.warning(f"⚠️ No se pudieron calcular EMA o RSI para {symbol}. Saltando este símbolo en este ciclo.")
                    continue

                mensaje_simbolo = (
                    f"📊 <b>{symbol}</b>\n"
                    f"Precio actual: {precio_actual:.2f} USDT\n"
                    f"EMA ({EMA_PERIODO}m): {ema_valor:.2f}\n"
                    f"RSI ({RSI_PERIODO}m): {rsi_valor:.2f}"
                )

                # --- LÓGICA DE COMPRA ---
                saldo_usdt = obtener_saldo_moneda("USDT")
                if (saldo_usdt > 10 and 
                    precio_actual > ema_valor and 
                    rsi_valor < RSI_UMBRAL_SOBRECOMPRA and 
                    symbol not in posiciones_abiertas):
                    
                    cantidad = calcular_cantidad_a_comprar(saldo_usdt, precio_actual, STOP_LOSS_PORCENTAJE, symbol)
                    
                    if cantidad > 0:
                        orden = comprar(symbol, cantidad)
                        if orden:
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
                elif symbol in posiciones_abiertas:
                    posicion = posiciones_abiertas[symbol]
                    precio_compra = posicion['precio_compra']
                    cantidad_en_posicion = posicion['cantidad_base']
                    max_precio_alcanzado = posicion['max_precio_alcanzado']

                    stop_loss_fijo_nivel = precio_compra * (1 - STOP_LOSS_PORCENTAJE)

                    if precio_actual > max_precio_alcanzado:
                        posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                        max_precio_alcanzado = precio_actual
                        save_open_positions_debounced()

                    # --- Lógica de Stop Loss a Breakeven ---
                    breakeven_nivel_real = precio_compra * (1 + BREAKEVEN_PORCENTAJE)

                    if (precio_actual >= breakeven_nivel_real and
                        not posicion['sl_moved_to_breakeven']):
                        
                        posiciones_abiertas[symbol]['stop_loss_fijo_nivel_actual'] = max(stop_loss_fijo_nivel, breakeven_nivel_real)
                        posiciones_abiertas[symbol]['sl_moved_to_breakeven'] = True
                        send_telegram_message(f"🔔 SL de <b>{symbol}</b> movido a Breakeven: <b>{breakeven_nivel_real:.2f}</b>")
                        logging.info(f"SL de {symbol} movido a Breakeven: {breakeven_nivel_real:.2f}")
                        save_open_positions_debounced()

                    # --- Niveles de Salida ---
                    current_stop_loss_level = posicion.get('stop_loss_fijo_nivel_actual', stop_loss_fijo_nivel)

                    take_profit_nivel = precio_compra * (1 + TAKE_PROFIT_PORCENTAJE)
                    trailing_stop_nivel = max_precio_alcanzado * (1 - TRAILING_STOP_PORCENTAJE)

                    eur_usdt_conversion_rate = obtener_precio_eur()
                    saldo_invertido_usdt = precio_compra * cantidad_en_posicion
                    saldo_invertido_eur = saldo_invertido_usdt * eur_usdt_conversion_rate if eur_usdt_conversion_rate else 0

                    mensaje_simbolo += (
                        f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                        f"TP: {take_profit_nivel:.2f} | SL Fijo: {current_stop_loss_level:.2f}\n"
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
                    elif precio_actual <= current_stop_loss_level:
                        vender_ahora = True
                        motivo_venta = "STOP LOSS FIJO alcanzado (o Breakeven)"
                    elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra): 
                        vender_ahora = True
                        motivo_venta = "TRAILING STOP LOSS activado"
                    
                    if vender_ahora:
                        step = get_step_size(symbol)
                        cantidad_a_vender_real = ajustar_cantidad(obtener_saldo_moneda(base), step) 
                        
                        if cantidad_a_vender_real > 0:
                            orden = vender(symbol, cantidad_a_vender_real, motivo_venta=motivo_venta)
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
                    
                mensaje_simbolo += "\n" + obtener_saldos_formateados() 
                general_message += mensaje_simbolo + "\n\n"

            send_telegram_message(general_message)
            last_trading_check_time = time.time()

        # --- GESTIÓN DEL TIEMPO ENTRE CICLOS ---
        time_elapsed_overall = time.time() - start_time_cycle
        sleep_duration = max(0, TELEGRAM_LISTEN_INTERVAL - time_elapsed_overall) 
        print(f"⏳ Próxima revisión en {sleep_duration:.0f} segundos (Revisando comandos cada {TELEGRAM_LISTEN_INTERVAL}s)...\n")
        time.sleep(sleep_duration)

    except Exception as e:
        logging.error(f"Error general en el bot: {e}", exc_info=True) 
        send_telegram_message(f"❌ Error general en el bot: {e}\n\n{obtener_saldos_formateados()}") 
        print(f"❌ Error general en el bot: {e}")
        time.sleep(INTERVALO)
