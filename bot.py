import os
import time
import logging
import requests
import json
import csv
from binance.client import Client
from binance.enums import *
from datetime import datetime, timedelta

# --- Configuración de Logging ---
# Configura el sistema de registro (logging) para ver la actividad del bot.
# El nivel INFO mostrará mensajes generales, WARNING para advertencias y ERROR para problemas.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =================== CONFIGURACIÓN (Asegúrate de que estas variables de entorno estén configuradas) ===================

# Claves de API de Binance. ¡NO COMPARTAS ESTAS CLAVES!
# Es recomendable usar variables de entorno para mayor seguridad.
# Por ejemplo, en Linux/macOS: export BINANCE_API_KEY='tu_key'
# En Google Colab, puedes usar os.environ['BINANCE_API_KEY'] = 'tu_key' en una celda separada o Secrets.
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Token de tu bot de Telegram y Chat ID para enviar mensajes.
# Obtén tu TELEGRAM_BOT_TOKEN de BotFather en Telegram.
# Obtén tu TELEGRAM_CHAT_ID hablando con @userinfobot y usando el ID que te proporcione.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Archivo para guardar y cargar los parámetros del bot.
CONFIG_FILE = "config.json"

#==================Control de moviments 

OPEN_POSITIONS_FILE = "open_positions.json" # <--- ¡Añade esta línea!

# =================== FUNCIONES DE CARGA Y GUARDADO DE PARÁMETROS ===================

def load_parameters():
    """Carga los parámetros desde el archivo JSON. Si no existe, devuelve valores por defecto."""
    default_params = {
        "EMA_PERIODO": 10,
        "RSI_PERIODO": 14,
        "RSI_UMBRAL_SOBRECOMPRA": 70,
        "RIESGO_POR_OPERACION_PORCENTAJE": 0.01, # 1% de riesgo por operación
        "TAKE_PROFIT_PORCENTAJE": 0.03, # 3% de Take Profit
        "STOP_LOSS_PORCENTAJE": 0.02, # 2% de Stop Loss fijo
        "TRAILING_STOP_PORCENTAJE": 0.015, # 1.5% de Trailing Stop Loss
        "INTERVALO": 300, # Ciclo de trading principal cada 300 segundos (5 minutos)
        "TOTAL_BENEFICIO_ACUMULADO": 0.0
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

# ... (después de save_parameters) ...

# =================== FUNCIONES DE CARGA Y GUARDADO DE POSICIONES ABIERTAS ===================

def load_open_positions():
    """Carga las posiciones abiertas desde el archivo JSON."""
    if os.path.exists(OPEN_POSITIONS_FILE):
        try:
            with open(OPEN_POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                # Asegurarse de que los precios sean floats después de cargar
                for symbol, pos in data.items():
                    pos['precio_compra'] = float(pos['precio_compra'])
                    pos['cantidad_base'] = float(pos['cantidad_base'])
                    pos['max_precio_alcanzado'] = float(pos['max_precio_alcanzado'])
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

def save_open_positions(positions):
    """Guarda las posiciones abiertas en el archivo JSON."""
    try:
        with open(OPEN_POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=4)
        logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE}.")
    except IOError as e:
        logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE}: {e}")

# ... (resto de tu código) ...




# Cargar parámetros al inicio del bot
bot_params = load_parameters()

# Asignar los valores del diccionario cargado a tus variables globales
# Esta lista de símbolos es fija, pero podría hacerse configurable también.
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

# =================== INICIALIZACIÓN DE CLIENTES BINANCE Y TELEGRAM ===================

# Inicializa el cliente de Binance. Se usará la red de TESTNET si no se especifican claves reales.
# Para usar la red principal (MAINNET), asegúrate de que tus API_KEY y API_SECRET sean de MAINNET.
# client = Client(API_KEY, API_SECRET, tld='us') # Para Binance.us
# client = Client(API_KEY, API_SECRET) # Para Binance.com (MAINNET)
client = Client(API_KEY, API_SECRET, testnet=True) # Para Binance TESTNET (¡RECOMENDADO PARA PRUEBAS!)
client.API_URL = 'https://testnet.binance.vision/api'  # Usar testnet

# Diccionario para almacenar las posiciones abiertas.
# La clave es el símbolo (ej. "BTCUSDT") y el valor es un diccionario con 'precio_compra', 'cantidad_base', 'max_precio_alcanzado'.
posiciones_abiertas = load_open_positions()

# Variables para la gestión de Telegram
last_update_id = 0 # Para los comandos de Telegram (importante para no procesar mensajes repetidamente)
TELEGRAM_LISTEN_INTERVAL = 5 # Intervalo en segundos para revisar mensajes de Telegram (respuesta rápida)

# Variables para la gestión de informes diarios
transacciones_diarias = [] # Almacena los datos de las transacciones del día para el informe CSV
ultima_fecha_informe_enviado = None # Para controlar cuándo se envió el último informe diario
last_trading_check_time = 0 # Para controlar cuándo se ejecutó por última vez la lógica de trading pesada



# =================== FUNCIONES DE CARGA Y GUARDADO DE POSICIONES ABIERTAS ===================

def load_open_positions():
    """Carga las posiciones abiertas desde el archivo JSON."""
    if os.path.exists(OPEN_POSITIONS_FILE):
        try:
            with open(OPEN_POSITIONS_FILE, 'r') as f:
                data = json.load(f)
                # Asegurarse de que los precios sean floats después de cargar
                for symbol, pos in data.items():
                    pos['precio_compra'] = float(pos['precio_compra'])
                    pos['cantidad_base'] = float(pos['cantidad_base'])
                    pos['max_precio_alcanzado'] = float(pos['max_precio_alcanzado'])
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

def save_open_positions(positions):
    """Guarda las posiciones abiertas en el archivo JSON."""
    try:
        with open(OPEN_POSITIONS_FILE, 'w') as f:
            json.dump(positions, f, indent=4)
        logging.info(f"✅ Posiciones abiertas guardadas en {OPEN_POSITIONS_FILE}.")
    except IOError as e:
        logging.error(f"❌ Error al escribir en el archivo {OPEN_POSITIONS_FILE}: {e}")

# ... (resto de tu código) ...








# =================== FUNCIONES AUXILIARES DE UTILIDAD ===================

def send_telegram_message(message):
    """Envía un mensaje al chat de Telegram configurado."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.warning("⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': message,
        'parse_mode': 'HTML' # Permite usar HTML básico como <b> (negrita) y <code> (monospace)
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status() # Lanza una excepción para errores HTTP (4xx o 5xx)
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al enviar mensaje a Telegram: {e}")
        return False

def send_telegram_document(chat_id, file_path, caption=""):
    """Envía un documento (ej. CSV) a un chat de Telegram."""
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
    """Obtiene el saldo disponible de una moneda específica de tu cuenta de Binance."""
    try:
        balance = client.get_asset_balance(asset=asset)
        return float(balance['free'])
    except Exception as e:
        logging.error(f"❌ Error al obtener saldo de {asset}: {e}")
        return 0.0

def obtener_precio_actual(symbol):
    """Obtiene el precio de mercado actual de un símbolo."""
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except Exception as e:
        logging.error(f"❌ Error al obtener precio de {symbol}: {e}")
        return 0.0

def obtener_precio_eur():
    """Obtiene el tipo de cambio actual de USDT a EUR."""
    try:
        eur_usdt_price = client.get_avg_price(symbol='EURUSDT')
        return 1 / float(eur_usdt_price['price']) # Convertir a USDT/EUR si la base es USDT
    except Exception as e:
        logging.warning(f"⚠️ No se pudo obtener el precio de EURUSDT: {e}. Usando 0 para la conversión a EUR.")
        return 0.0

def obtener_saldos_formateados():
    """Formatea los saldos de USDT y el capital total estimado para el mensaje de Telegram."""
    try:
        saldo_usdt = obtener_saldo_moneda("USDT")
        capital_total_usdt = saldo_usdt
        
        # Sumar el valor de las posiciones abiertas
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
    """Calcula la Media Móvil Exponencial (EMA)."""
    if len(precios_cierre) < periodo:
        return None
    
    # Cálculo inicial de la EMA (SMA para el primer punto)
    ema = sum(precios_cierre[:periodo]) / periodo
    multiplier = 2 / (periodo + 1)
    
    # Iterar para calcular la EMA para los puntos restantes
    for i in range(periodo, len(precios_cierre)):
        ema = ((precios_cierre[i] - ema) * multiplier) + ema
    return ema

def calcular_rsi(precios_cierre, periodo):
    """Calcula el Índice de Fuerza Relativa (RSI)."""
    if len(precios_cierre) < periodo + 1: # Necesita al menos periodo + 1 datos para el primer cálculo
        return None

    # Calcular diferencias de precios
    precios_diff = [precios_cierre[i] - precios_cierre[i-1] for i in range(1, len(precios_cierre))]
    
    # Separar ganancias y pérdidas
    ganancias = [d if d > 0 else 0 for d in precios_diff]
    perdidas = [-d if d < 0 else 0 for d in precios_diff]

    # Calcular promedio inicial de ganancias y pérdidas
    avg_ganancia = sum(ganancias[:periodo]) / periodo
    avg_perdida = sum(perdidas[:periodo]) / periodo

    if avg_perdida == 0:
        return 100 # Evitar división por cero, caso de solo ganancias
    
    # Calcular RS y RSI inicial
    rs = avg_ganancia / avg_perdida
    rsi = 100 - (100 / (1 + rs))

    # Iterar para calcular RSI para los puntos restantes
    for i in range(periodo, len(ganancias)):
        avg_ganancia = ((avg_ganancia * (periodo - 1)) + ganancias[i]) / periodo
        avg_perdida = ((avg_perdida * (periodo - 1)) + perdidas[i]) / periodo
        
        if avg_perdida == 0:
            rsi = 100 # Si no hay pérdidas, RSI es 100
        else:
            rs = avg_ganancia / avg_perdida
            rsi = 100 - (100 / (1 + rs))
    return rsi

def calcular_ema_rsi(symbol, ema_periodo, rsi_periodo):
    """Obtiene datos de klines y calcula EMA y RSI."""
    try:
        # Obtener suficientes klines para ambos cálculos
        # Se obtiene 'max(ema_periodo, rsi_periodo) + algunos extra' para asegurar la cantidad necesaria.
        limit = max(ema_periodo, rsi_periodo) + 10 # 10 extra para margen
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=limit)
        
        precios_cierre = [float(kline[4]) for kline in klines]
        
        ema = calcular_ema(precios_cierre, ema_periodo)
        rsi = calcular_rsi(precios_cierre, rsi_periodo)
        
        return ema, rsi
    except Exception as e:
        logging.error(f"❌ Error al obtener klines o calcular indicadores para {symbol}: {e}")
        return None, None

def get_step_size(symbol):
    """Obtiene el 'stepSize' para un símbolo, necesario para la precisión de la cantidad."""
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                return float(f['stepSize'])
        # Valor predeterminado muy pequeño si no se encuentra (para evitar división por cero o errores)
        logging.warning(f"⚠️ No se encontró LOT_SIZE filter para {symbol}. Usando stepSize por defecto: 0.000001")
        return 0.000001
    except Exception as e:
        logging.error(f"❌ Error al obtener stepSize para {symbol}: {e}")
        return 0.000001

def ajustar_cantidad(cantidad, step_size):
    """
    Ajusta una cantidad para que sea un múltiplo exacto del step_size de Binance
    y con la precisión correcta en decimales.
    """
    if step_size == 0:
        logging.warning("⚠️ step_size es 0, no se puede ajustar la cantidad.")
        return 0.0

    # Determinar el número de decimales que requiere el step_size
    s_step_size = str(step_size)
    if '.' in s_step_size:
        # Contar decimales después del punto, eliminando ceros finales si step_size es "0.010"
        decimal_places = len(s_step_size.split('.')[1].rstrip('0'))
    else:
        decimal_places = 0 # No hay decimales si step_size es un entero (ej. 1.0)

    # Calcular la cantidad ajustada usando división de piso para evitar imprecisiones de float
    # y luego convertir a string con la precisión correcta antes de volver a float
    try:
        # Multiplica por 10^decimal_places, redondea, y luego divide
        # Esto es más robusto para manejar las precisiones
        factor = 10**decimal_places
        ajustada = (round(cantidad * factor / (step_size * factor)) * (step_size * factor)) / factor
        
        # Formatear a la cadena con la precisión exacta, luego convertir a float
        # Esto elimina cualquier rastro de imprecisión flotante.
        formatted_quantity_str = f"{ajustada:.{decimal_places}f}"
        return float(formatted_quantity_str)
    except Exception as e:
        logging.error(f"❌ Error al ajustar cantidad {cantidad} con step {step_size}: {e}")
        return 0.0

def calcular_cantidad_a_comprar(saldo_usdt, precio_actual, stop_loss_porcentaje, symbol):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el riesgo por operación
    y el stop loss definido.
    """
    if precio_actual <= 0:
        logging.warning("El precio actual es cero o negativo, no se puede calcular la cantidad a comprar.")
        return 0.0

    capital_total = saldo_usdt # Usamos solo el saldo USDT disponible para la base del capital
    riesgo_max_por_operacion_usdt = capital_total * RIESGO_POR_OPERACION_PORCENTAJE
    
    # Diferencia entre el precio de entrada y el stop loss (en USD por unidad)
    diferencia_precio_sl = precio_actual * stop_loss_porcentaje
    
    if diferencia_precio_sl <= 0:
        logging.warning("La diferencia de precio con el SL es cero o negativa, no se puede calcular la cantidad a comprar.")
        return 0.0

    # Cantidad de unidades que podemos comprar para arriesgar el riesgo_max_por_operacion_usdt
    cantidad_a_comprar = riesgo_max_por_operacion_usdt / diferencia_precio_sl

    step = get_step_size(symbol)
    min_notional = 10.0 # Valor mínimo de una orden en USDT para la mayoría de pares en Binance

    cantidad_ajustada = ajustar_cantidad(cantidad_a_comprar, step)
    
    # Verificar que la cantidad ajustada es suficiente para cumplir con el mínimo nocional de Binance
    if (cantidad_ajustada * precio_actual) < min_notional:
        logging.warning(f"La cantidad calculada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) es demasiado pequeña para el mínimo nocional de {min_notional} USDT.")
        # Intentar comprar el mínimo nocional si el saldo lo permite
        min_cantidad_ajustada = ajustar_cantidad(min_notional / precio_actual, step)
        if (min_cantidad_ajustada * precio_actual) <= saldo_usdt: # Asegurarse de que tenemos el saldo para el mínimo
            cantidad_ajustada = min_cantidad_ajustada
            logging.info(f"Ajustando a la cantidad mínima nocional permitida: {cantidad_ajustada:.6f} {symbol.replace('USDT', '')}")
        else:
            logging.warning(f"No hay suficiente saldo USDT para comprar la cantidad mínima nocional de {symbol}.")
            return 0.0 # No hay suficiente USDT para el mínimo nocional

    # Asegurarse de no comprar más de lo que el saldo USDT permite
    if (cantidad_ajustada * precio_actual) > saldo_usdt:
        logging.warning(f"La cantidad ajustada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) excede el saldo disponible en USDT. Reduciendo a lo máximo posible.")
        cantidad_max_posible = ajustar_cantidad(saldo_usdt / precio_actual, step)
        if (cantidad_max_posible * precio_actual) >= min_notional: # Asegurarse de que la cantidad reducida sigue siendo válida
            cantidad_ajustada = cantidad_max_posible
        else:
            logging.warning(f"El saldo restante no permite comprar ni la cantidad mínima nocional de {symbol}.")
            return 0.0 # No se puede comprar ni el mínimo nocional con el saldo restante

    return cantidad_ajustada

def comprar(symbol, cantidad):
    """Ejecuta una orden de compra en el mercado."""
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de compra de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        order = client.order_market_buy(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE COMPRA EXITOSA para {symbol}: {order}")
        
        # Registrar la transacción en la lista diaria
        if order and 'fills' in order and len(order['fills']) > 0:
            precio_ejecucion = float(order['fills'][0]['price'])
            qty_ejecutada = float(order['fills'][0]['qty'])

            # Almacena los detalles de la nueva posición abierta
            posiciones_abiertas[symbol] = {
                'precio_compra': precio_ejecucion,
                'cantidad_base': qty_ejecutada,
                'max_precio_alcanzado': precio_ejecucion # Inicializa el precio máximo alcanzado
            }
            save_open_positions(posiciones_abiertas) # <--- ¡Añade esta línea! Guarda la posición
            
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
        send_telegram_message(f"❌ Error en compra de {symbol}: {e}") # Notificar error por Telegram
        return None

def vender(symbol, cantidad, motivo_venta="Desconocido"):
    """Ejecuta una orden de venta en el mercado."""
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de venta de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        order = client.order_market_sell(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE VENTA EXITOSA para {symbol}: {order}")
        
        # Calcular ganancia/pérdida para el registro
        ganancia_perdida_usdt = 0.0
        precio_venta_ejecutada = float(order['fills'][0]['price']) if order and 'fills' in order and len(order['fills']) > 0 else 0.0

        if symbol in posiciones_abiertas: # Si la venta es de una posición que el bot gestionaba
            precio_compra = posiciones_abiertas[symbol]['precio_compra']
            ganancia_perdida_usdt = (precio_venta_ejecutada - precio_compra) * cantidad
            
            # Actualizar el beneficio acumulado
            global TOTAL_BENEFICIO_ACUMULADO # <--- ¡Necesario para modificar la global!
            TOTAL_BENEFICIO_ACUMULADO += ganancia_perdida_usdt
            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = TOTAL_BENEFICIO_ACUMULADO # Actualiza el diccionario de parámetros
            save_parameters(bot_params) # <--- ¡Guarda el cambio inmediatamente!

            posiciones_abiertas.pop(symbol) # <--- Elimina la posición
            save_open_positions(posiciones_abiertas) # <--- ¡Añade esta línea! Guarda el cambio

        # Registrar la transacción en la lista diaria
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
        send_telegram_message(f"❌ Error en venta de {symbol}: {e}") # Notificar error por Telegram
        return None

        # ... (después de la función vender y antes de MANEJADOR DE COMANDOS DE TELEGRAM) ...

def vender_por_comando(symbol):
    """
    Intenta vender una posición abierta para un símbolo específico,
    activada por un comando de Telegram.
    """
    if symbol not in posiciones_abiertas:
        send_telegram_message(f"❌ No hay una posición abierta para <b>{symbol}</b> que gestionar por comando.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero no hay posición abierta.")
        return

    base_asset = symbol.replace("USDT", "")
    cantidad_en_posicion = obtener_saldo_moneda(base_asset) # Obtener el saldo real disponible

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
        # Si la venta fue exitosa, la posición se eliminará en la función vender()
        # ya que se llama a transacciones_diarias.append() y luego posiciones_abiertas.pop(symbol)
        # en la función vender.
        #if symbol in posiciones_abiertas: # Debería ser False si la venta fue exitosa
         #   posiciones_abiertas.pop(symbol) # Asegurarse de eliminarla si no se hizo en vender() por algún motivo
        
        # El mensaje de éxito ya lo envía la función vender()
        # send_telegram_message(f"✅ Venta de {symbol} ejecutada con éxito por comando.")
        logging.info(f"Venta de {symbol} ejecutada con éxito por comando.")
        send_telegram_message(f"Venta de {symbol} ejecutada con éxito por comando.")
    else:
        send_telegram_message(f"❌ Fallo al ejecutar la venta de <b>{symbol}</b> por comando. Revisa los logs.")
        logging.error(f"Fallo al ejecutar la venta de {symbol} por comando.")

# ... (resto de tu código) ...

# =================== MANEJADOR DE COMANDOS DE TELEGRAM ===================

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
                    send_telegram_message(f"⚠️ Comando recibido de chat no autorizado: <code>{chat_id}</code>")
                    logging.warning(f"Comando de chat no autorizado: {chat_id}")
                    continue

                parts = text.split() # Divide el mensaje en partes (ej. "/set_tp 0.04")
                command = parts[0].lower() # El primer elemento es el comando (en minúsculas)
                
                logging.info(f"Comando Telegram recibido: {text}")

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
                    
                    elif command == "/csv":
                        send_telegram_message("Generando informe CSV. Esto puede tardar un momento...")
                        generar_y_enviar_csv_ahora()

                    elif command == "/help":
                        send_help_message()



                    # --- NUEVO COMANDO /vender ---
                    elif command == "/vender":
                        if len(parts) == 2:
                            symbol_to_sell = parts[1].upper() # Asegúrate de que el símbolo esté en mayúsculas
                            # Verificar si el símbolo es uno de los que el bot monitorea
                            if symbol_to_sell in SYMBOLS:
                                vender_por_comando(symbol_to_sell)
                            else:
                                send_telegram_message(f"❌ Símbolo <b>{symbol_to_sell}</b> no reconocido o no monitoreado por el bot.")
                        else:
                            send_telegram_message("❌ Uso: <code>/vender &lt;SIMBOLO_USDT&gt;</code> (ej. /vender BTCUSDT)")
                    # --- FIN NUEVO COMANDO ---
                    elif command == "/beneficio":
                        send_beneficio_message()

                    else:
                        send_telegram_message("Comando desconocido. Usa <code>/help</code> para ver los comandos disponibles.")

                except ValueError:
                    send_telegram_message("❌ Valor inválido. Asegúrate de introducir un número o porcentaje correcto.")
                except Exception as ex:
                    logging.error(f"Error procesando comando '{text}': {ex}", exc_info=True)
                    send_telegram_message(f"❌ Error interno al procesar comando: {ex}")

# =================== FUNCIONES DE INFORMES CSV ===================

def generar_y_enviar_csv_ahora():
    """
    Genera un archivo CSV con las transacciones registradas hasta el momento y lo envía por Telegram.
    Este se puede llamar bajo demanda con el comando /csv.
    """
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
    """
    Genera un archivo CSV con las transacciones registradas para el día y lo envía por Telegram.
    Este se ejecutará diariamente.
    """
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
    global TOTAL_BENEFICIO_ACUMULADO # Asegurarse de que accedemos a la variable global
    
    # Obtener el tipo de cambio actual para mostrar también en EUR
    eur_usdt_rate = obtener_precio_eur()
    beneficio_eur = TOTAL_BENEFICIO_ACUMULADO * eur_usdt_rate if eur_usdt_rate else 0.0

    message = (
        f"📈 <b>Beneficio Total Acumulado:</b>\n"
        f"   - <b>{TOTAL_BENEFICIO_ACUMULADO:.2f} USDT</b>\n"
        f"   - <b>{beneficio_eur:.2f} EUR</b>"
    )
    send_telegram_message(message)


# =================== FUNCIÓN DE AYUDA ===================

def send_help_message():
    """Envía un mensaje de ayuda con la lista de comandos disponibles."""
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
        " - <code>/set_intervalo &lt;segundos&gt;</code>: Establece el intervalo del ciclo principal del bot en segundos (ej. 300).\n\n"
        "<b>Informes:</b>\n"
        " - <code>/csv</code>: Genera y envía un archivo CSV con las transacciones del día hasta el momento.\n"
        " - <code>/beneficio</code>: Muestra el beneficio total acumulado por el bot.\n\n" # <--- ¡Añade esta línea!
        "<b>Ayuda:</b>\n"
        " - <code>/help</code>: Muestra este mensaje de ayuda.\n"
        " - <code>/vender &lt;SIMBOLO_USDT&gt;</code>: Vende una posición abierta de forma manual (ej. /vender BTCUSDT).\n\n" # <--- Asegúrate de que /vender esté aquí también.
        "<i>Recuerda usar valores decimales para porcentajes y enteros para períodos/umbrales.</i>"
    )
    send_telegram_message(help_message)


# =================== BUCLE PRINCIPAL DEL BOT ===================

# =================== CONFIGURACIÓN DEL MENÚ DE COMANDOS DE TELEGRAM ===================

def set_telegram_commands_menu():
    """
    Configura el menú de comandos que aparece cuando el usuario escribe '/' en Telegram.
    Se debe llamar una vez al inicio del bot o cuando los comandos cambien.
    """
    if not TELEGRAM_BOT_TOKEN:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede configurar el menú de comandos.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setMyCommands"
    
    # Define la lista de comandos con su descripción
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
        {"command": "csv", "description": "Genera y envía un informe CSV de transacciones"},
        {"command": "beneficio", "description": "Muestra el beneficio total acumulado"},
        {"command": "vender", "description": "Vende una posición manualmente (ej. /vender BTCUSDT)"},
        {"command": "help", "description": "Muestra este mensaje de ayuda"}
    ]

    payload = {'commands': json.dumps(commands)} # Convierte la lista de comandos a JSON string
    headers = {'Content-Type': 'application/json'} # Especifica el tipo de contenido

    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status() # Lanza una excepción para errores HTTP
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




        
set_telegram_commands_menu() # <--- ¡Añade esta línea aquí!


logging.info("Bot iniciado. Esperando comandos y monitoreando el mercado...")

while True:
    start_time_cycle = time.time()
    
    try:
        # --- Manejar comandos de Telegram (SE EJECUTA EN CADA CICLO CORTO para respuesta rápida) ---
        handle_telegram_commands()
        
        # --- Lógica del Informe Diario (se ejecuta UNA VEZ AL DÍA) ---
        hoy = time.strftime("%Y-%m-%d")

        if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
            if ultima_fecha_informe_enviado is not None: # Si ya se había enviado un informe antes (no es la primera ejecución)
                send_telegram_message(f"Preparando informe del día {ultima_fecha_informe_enviado}...")
                enviar_informe_diario() # Llama a tu función para generar y enviar el CSV diario
            
            ultima_fecha_informe_enviado = hoy # Actualiza la fecha del último informe enviado
            transacciones_diarias.clear() # Limpia las transacciones para el nuevo día

        # --- LÓGICA PRINCIPAL DE TRADING (SE EJECUTA CADA 'INTERVALO' SEGUNDOS) ---
        # Solo ejecuta la lógica de trading intensiva si ha pasado suficiente tiempo desde la última vez
        if (time.time() - last_trading_check_time) >= INTERVALO:
            logging.info(f"Iniciando ciclo de trading principal (cada {INTERVALO}s)...")
            general_message = "" # Reinicializa el mensaje general para este ciclo de trading

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
                if (saldo_usdt > 10 and # Asegura tener un mínimo de 10 USDT para operar
                    precio_actual > ema_valor and 
                    rsi_valor < RSI_UMBRAL_SOBRECOMPRA and 
                    symbol not in posiciones_abiertas):
                    
                    cantidad = calcular_cantidad_a_comprar(saldo_usdt, precio_actual, STOP_LOSS_PORCENTAJE, symbol)
                    
                    if cantidad > 0:
                        orden = comprar(symbol, cantidad)
                        if orden and 'fills' in orden and len(orden['fills']) > 0:
                            precio_compra = float(orden['fills'][0]['price'])
                            cantidad_comprada_real = float(orden['fills'][0]['qty'])
                            
                            posiciones_abiertas[symbol] = {
                                'precio_compra': precio_compra,
                                'cantidad_base': cantidad_comprada_real,
                                'max_precio_alcanzado': precio_actual
                            }
                            mensaje_simbolo += f"\n✅ COMPRA ejecutada a {precio_compra:.2f} USDT"
                            
                            capital_invertido_usd = precio_compra * cantidad_comprada_real
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

                # --- LÓGICA DE VENTA (Take Profit, Stop Loss, Trailing Stop Loss) ---
                elif symbol in posiciones_abiertas:
                    posicion = posiciones_abiertas[symbol]
                    precio_compra = posicion['precio_compra']
                    cantidad_en_posicion = posicion['cantidad_base']
                    max_precio_alcanzado = posicion['max_precio_alcanzado']

                    if precio_actual > max_precio_alcanzado:
                        posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                        max_precio_alcanzado = precio_actual # Actualiza la variable local para el ciclo actual.
                        save_open_positions(posiciones_abiertas) # <--- ¡Añade esta línea! Guarda el cambio

                    take_profit_nivel = precio_compra * (1 + TAKE_PROFIT_PORCENTAJE)
                    stop_loss_fijo_nivel = precio_compra * (1 - STOP_LOSS_PORCENTAJE)
                    trailing_stop_nivel = max_precio_alcanzado * (1 - TRAILING_STOP_PORCENTAJE)

                    eur_usdt_conversion_rate = obtener_precio_eur()
                    saldo_invertido_usdt = precio_compra * cantidad_en_posicion
                    saldo_invertido_eur = saldo_invertido_usdt * eur_usdt_conversion_rate if eur_usdt_conversion_rate else 0

                    mensaje_simbolo += (
                        f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                        f"TP: {take_profit_nivel:.2f} | SL Fijo: {stop_loss_fijo_nivel:.2f}\n"
                        f"Max Alcanzado: {max_precio_alcanzado:.2f} | TSL: {trailing_stop_nivel:.2f}\n"
                        f"Saldo USDT Invertido (Entrada): {saldo_invertido_usdt:.2f}\n"
                        f"SEI: {saldo_invertido_eur:.2f}"
                    )

                    vender_ahora = False
                    motivo_venta = ""

                    if precio_actual >= take_profit_nivel:
                        vender_ahora = True
                        motivo_venta = "TAKE PROFIT alcanzado"
                    elif precio_actual <= stop_loss_fijo_nivel:
                        vender_ahora = True
                        motivo_venta = "STOP LOSS FIJO alcanzado"
                    elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra): 
                        vender_ahora = True
                        motivo_venta = "TRAILING STOP LOSS activado"
                    
                    if vender_ahora:
                        step = get_step_size(symbol)
                        cantidad_a_vender_real = ajustar_cantidad(obtener_saldo_moneda(base), step) 
                        
                        if cantidad_a_vender_real > 0:
                            orden = vender(symbol, cantidad_a_vender_real, motivo_venta=motivo_venta) # Pasa el motivo de venta
                            if orden and 'fills' in orden and len(orden['fills']) > 0:
                                salida = float(orden['fills'][0]['price'])
                                ganancia = (salida - precio_compra) * cantidad_a_vender_real
                                mensaje_simbolo += (
                                    f"\n✅ VENTA ejecutada por {motivo_venta} a {salida:.2f} USDT\n"
                                    f"Ganancia/Pérdida: {ganancia:.2f} USDT"
                                )
                                posiciones_abiertas.pop(symbol)
                            else:
                                mensaje_simbolo += f"\n❌ VENTA fallida para {symbol}."
                        else:
                            mensaje_simbolo += f"\n⚠️ No hay {base} disponible para vender o cantidad muy pequeña."
                    
                mensaje_simbolo += "\n" + obtener_saldos_formateados() 
                general_message += mensaje_simbolo + "\n\n"

            send_telegram_message(general_message) # Envía el mensaje acumulado de todos los símbolos a Telegram.
            
            last_trading_check_time = time.time() # Actualiza el tiempo de la última ejecución completa de trading

        # --- GESTIÓN DEL TIEMPO ENTRE CICLOS ---
        # Calcula el tiempo transcurrido en este ciclo de ejecución general.
        time_elapsed_overall = time.time() - start_time_cycle
        # Calcula el tiempo que queda por esperar para cumplir con el TELEGRAM_LISTEN_INTERVAL.
        # Esto permite que el bot se "despierte" y revise comandos con mucha más frecuencia.
        sleep_duration = max(0, TELEGRAM_LISTEN_INTERVAL - time_elapsed_overall) 
        print(f"⏳ Próxima revisión en {sleep_duration:.0f} segundos (Revisando comandos cada {TELEGRAM_LISTEN_INTERVAL}s)...\n")
        time.sleep(sleep_duration)

    except Exception as e:
        logging.error(f"Error general en el bot: {e}", exc_info=True) 
        send_telegram_message(f"❌ Error general en el bot: {e}\n\n{obtener_saldos_formateados()}") 
        print(f"❌ Error general en el bot: {e}")
        time.sleep(INTERVALO) # En caso de un error general, espera el intervalo completo antes de reintentar el bucle.
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