import os
import time
import logging
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException
from binance.enums import *
from statistics import mean

# Para cálculos de indicadores
try:
    import pandas as pd # Importa pandas primero
    import pandas_ta as ta # Luego pandas_ta, que depende de pandas
except ImportError as e:
    # Si la importación falla, loguea el error y termina la ejecución.
    # Esto asegura que el bot no intente operar sin sus indicadores clave.
    logging.error(f"❌ ERROR CRÍTICO: No se pudieron importar las librerías de trading (pandas/pandas_ta). "
                  f"Asegúrate de que estén en requirements.txt y el despliegue fue exitoso. Error: {e}")
    print(f"❌ ERROR CRÍTICO: No se pudieron importar las librerías de trading (pandas/pandas_ta). "
          f"Por favor, instala: pip install pandas pandas_ta. Error: {e}")
    # Es recomendable salir si las dependencias clave no están disponibles
    exit(1) # Sale del programa con un código de error

# =================== CONFIGURACIÓN ===================

API_KEY = os.getenv("BINANCE_API_KEY")       # Tu clave API de Binance
API_SECRET = os.getenv("BINANCE_API_SECRET") # Tu secreto API de Binance

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")       # Token de tu bot de Telegram
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")       # ID de tu chat de Telegram

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]   # Criptomonedas a operar
INTERVALO = 300     # Espera entre ciclos (en segundos)
PORCENTAJE_CAPITAL = 0.1   # % del capital a invertir en cada operación

TAKE_PROFIT_PORCENTAJE = 0.03   # 3% de ganancia (Objetivo inicial)
STOP_LOSS_PORCENTAJE = 0.02     # 2% de pérdida (Stop Loss fijo inicial)
TRAILING_STOP_PORCENTAJE = 0.015 # 1.5% de trailing (El TSL seguirá el precio con este % de distancia)

# Parámetros para indicadores técnicos
EMA_PERIODO = 10    # Período para la Media Móvil Exponencial (EMA)
RSI_PERIODO = 14    # Período para el Índice de Fuerza Relativa (RSI)
RSI_UMBRAL_SOBRECOMPRA = 70 # Umbral superior del RSI para considerar sobrecompra (evitar compras)

# =================== INICIALIZACIÓN ===================

client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'   # Usa la testnet de Binance

logging.basicConfig(
    filename='trading_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# =================== FUNCIONES AUXILIARES ===================

def send_telegram_message(message):
    """Envía un mensaje a Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TOKEN o CHAT_ID no configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}

    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"❌ Error enviando mensaje Telegram: {e}")

def obtener_precio_actual(symbol):
    """Obtiene el precio actual de mercado de una cripto."""
    ticker = client.get_symbol_ticker(symbol=symbol)
    return float(ticker["price"])

def obtener_saldo_moneda(moneda):
    """Obtiene el saldo disponible de una moneda específica."""
    cuenta = client.get_account()
    for asset in cuenta['balances']:
        if asset['asset'] == moneda:
            return float(asset['free'])
    return 0.0

def get_step_size(symbol):
    """Obtiene el tamaño de paso permitido por Binance para el símbolo."""
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001

def ajustar_cantidad(cantidad, step_size):
    """Ajusta la cantidad al step_size para evitar errores de Binance."""
    return round(cantidad - (cantidad % step_size), 6)

def calcular_cantidad_a_comprar(symbol, precio, saldo_usdt):
    """Calcula cuántas unidades comprar de una cripto según el capital disponible."""
    cantidad_usdt = saldo_usdt * PORCENTAJE_CAPITAL
    if precio == 0: return 0.0 # Evitar división por cero
    cantidad = cantidad_usdt / precio
    step = get_step_size(symbol)
    return ajustar_cantidad(cantidad, step)

def comprar(symbol, cantidad):
    """Ejecuta una orden de compra de mercado."""
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de compra de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        logging.info(f"✅ Intentando comprar {cantidad} de {symbol}")
        order = client.order_market_buy(symbol=symbol, quantity=cantidad)
        logging.info(f"✅ Compra de {symbol} exitosa: {order}")
        return order
    except BinanceAPIException as e:
        logging.error(f"❌ Error en compra de {symbol}: {e}")
        send_telegram_message(f"❌ Error en compra de {symbol}: {e}")
        return None
    except Exception as e:
        logging.error(f"❌ Error inesperado en compra de {symbol}: {e}")
        send_telegram_message(f"❌ Error inesperado en compra de {symbol}: {e}")
        return None

def vender(symbol, cantidad):
    """Ejecuta una orden de venta de mercado."""
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de venta de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        logging.info(f"✅ Intentando vender {cantidad} de {symbol}")
        order = client.order_market_sell(symbol=symbol, quantity=cantidad)
        logging.info(f"✅ Venta de {symbol} exitosa: {order}")
        return order
    except BinanceAPIException as e:
        logging.error(f"❌ Error en venta de {symbol}: {e}")
        send_telegram_message(f"❌ Error en venta de {symbol}: {e}")
        return None
    except Exception as e:
        logging.error(f"❌ Error inesperado en venta de {symbol}: {e}")
        send_telegram_message(f"❌ Error inesperado en venta de {symbol}: {e}")
        return None

def obtener_datos_ohlcv(symbol, interval, limit):
    """Obtiene datos históricos OHLCV (Open, High, Low, Close, Volume)."""
    if pd is None: # Comprobar si pandas está disponible
        logging.error("Pandas no está instalado. No se pueden obtener datos OHLCV.")
        return pd.DataFrame() # Retornar DataFrame vacío si pandas no está
        
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=['open_time', 'open', 'high', 'low', 'close', 'volume',
                                       'close_time', 'quote_asset_volume', 'number_of_trades',
                                       'taker_buy_base_asset_volume', 'taker_buy_quote_asset_volume', 'ignore'])
    df['close'] = pd.to_numeric(df['close'])
    return df

def calcular_ema_rsi(symbol, ema_period, rsi_period):
    """Calcula la EMA y el RSI para un símbolo."""
    if ta is None or pd is None: # Comprobar si pandas_ta y pandas están disponibles
        logging.error("Pandas_ta o Pandas no están instalados. No se pueden calcular EMA/RSI.")
        return None, None

    df = obtener_datos_ohlcv(symbol, KLINE_INTERVAL_1MINUTE, max(ema_period, rsi_period) + 50)
    
    if df.empty or len(df) < max(ema_period, rsi_period) + 1: # Asegurarse de tener suficientes datos para el cálculo
        logging.warning(f"No hay suficientes datos para calcular EMA/RSI para {symbol}.")
        return None, None

    # Calcular EMA
    df['EMA'] = ta.ema(df['close'], length=ema_period)
    
    # Calcular RSI
    df['RSI'] = ta.rsi(df['close'], length=rsi_period)

    # Devolver el último valor de EMA y RSI
    return df['EMA'].iloc[-1], df['RSI'].iloc[-1]

def obtener_precio_eur():
    """Convierte el precio de USDT a EUR usando el par EURUSDT."""
    try:
        ticker = client.get_symbol_ticker(symbol="EURUSDT")
        return 1 / float(ticker["price"])
    except Exception as e:
        logging.warning(f"⚠️ No se pudo obtener EURUSDT: {e}")
        return None

def obtener_saldos_formateados():
    """Obtiene y formatea los saldos actuales en USDT y EUR."""
    saldo_usdt = obtener_saldo_moneda("USDT")
    eur_usdt = obtener_precio_eur()
    saldo_eur = saldo_usdt * eur_usdt if eur_usdt else 0

    return (
        f"💰 <b>Saldos Actuales:</b>\n"
        f" - USDT: {saldo_usdt:.2f}\n"
        f" - EUR: {saldo_eur:.2f}"
    )

# =================== ESTRATEGIA PRINCIPAL ===================

# Diccionario para almacenar el estado de cada posición:
# { 'SYMBOL': { 'precio_compra': float, 'cantidad_base': float, 'max_precio_alcanzado': float } }
posiciones_abiertas = {} 

while True:
    start_time_cycle = time.time()
    try:
        general_message = "" 

        for symbol in SYMBOLS:
            base = symbol.replace("USDT", "") 
            
            # Necesitamos obtener saldo_base aquí, ya que puede cambiar después de una venta.
            saldo_base = obtener_saldo_moneda(base) 
            precio_actual = obtener_precio_actual(symbol)
            
            # Calcular EMA y RSI
            ema_valor, rsi_valor = calcular_ema_rsi(symbol, EMA_PERIODO, RSI_PERIODO)

            if ema_valor is None or rsi_valor is None:
                logging.warning(f"⚠️ No se pudieron calcular EMA o RSI para {symbol}. Saltando este símbolo.")
                continue

            mensaje_simbolo = f"📊 <b>{symbol}</b>\nPrecio actual: {precio_actual:.2f} USDT\nEMA ({EMA_PERIODO}m): {ema_valor:.2f}\nRSI ({RSI_PERIODO}m): {rsi_valor:.2f}"

            # 📈 Condición de COMPRA (Precio > EMA Y RSI no sobrecomprado)
            # Volvemos a obtener saldo_usdt aquí porque puede cambiar entre símbolos si se compra.
            saldo_usdt = obtener_saldo_moneda("USDT")
            if saldo_usdt > 10 and precio_actual > ema_valor and rsi_valor < RSI_UMBRAL_SOBRECOMPRA and symbol not in posiciones_abiertas:
                cantidad = calcular_cantidad_a_comprar(symbol, precio_actual, saldo_usdt)
                if cantidad > 0:
                    orden = comprar(symbol, cantidad)
                    if orden and 'fills' in orden and len(orden['fills']) > 0:
                        precio_compra = float(orden['fills'][0]['price'])
                        # Asegurarse de que la cantidad comprada sea el valor correcto del fill.
                        cantidad_comprada_real = float(orden['fills'][0]['qty'])
                        posiciones_abiertas[symbol] = {
                            'precio_compra': precio_compra,
                            'cantidad_base': cantidad_comprada_real,
                            'max_precio_alcanzado': precio_actual 
                        }
                        mensaje_simbolo += f"\n✅ COMPRA ejecutada a {precio_compra:.2f} USDT"
                        mensaje_simbolo += f"\nCantidad comprada: {cantidad_comprada_real:.6f} {base}"
                    else:
                         mensaje_simbolo += f"\n❌ COMPRA fallida para {symbol}."
                else:
                    mensaje_simbolo += f"\n⚠️ No hay suficiente capital o cantidad mínima para comprar {symbol}."

            # 📉 Condición de VENTA (TP, SL o Trailing Stop Loss)
            elif symbol in posiciones_abiertas:
                posicion = posiciones_abiertas[symbol]
                precio_compra = posicion['precio_compra']
                cantidad_en_posicion = posicion['cantidad_base']
                max_precio_alcanzado = posicion['max_precio_alcanzado']

                # Actualizar el precio máximo alcanzado
                if precio_actual > max_precio_alcanzado:
                    posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                    max_precio_alcanzado = precio_actual # Actualizar variable local también

                # Niveles de venta
                take_profit_nivel = precio_compra * (1 + TAKE_PROFIT_PORCENTAJE)
                stop_loss_fijo_nivel = precio_compra * (1 - STOP_LOSS_PORCENTAJE)
                
                # Calcular Trailing Stop Loss
                trailing_stop_nivel = max_precio_alcanzado * (1 - TRAILING_STOP_PORCENTAJE)

                mensaje_simbolo += (
                    f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                    f"TP: {take_profit_nivel:.2f} | SL Fijo: {stop_loss_fijo_nivel:.2f}\n"
                    f"Max Alcanzado: {max_precio_alcanzado:.2f} | TSL: {trailing_stop_nivel:.2f}"
                )

                vender_ahora = False
                motivo_venta = ""

                # Prioridad de venta: TP, luego SL Fijo, luego TSL
                if precio_actual >= take_profit_nivel:
                    vender_ahora = True
                    motivo_venta = "TAKE PROFIT alcanzado"
                elif precio_actual <= stop_loss_fijo_nivel:
                    vender_ahora = True
                    motivo_venta = "STOP LOSS FIJO alcanzado"
                elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra): 
                    # TSL solo si el precio actual es mayor al precio de compra (estamos en ganancias)
                    vender_ahora = True
                    motivo_venta = "TRAILING STOP LOSS activado"
                
                # Consideración: Si el TSL baja por debajo del precio de compra, y el SL fijo no lo ha cogido,
                # esta lógica actual priorizará el SL fijo si está por encima del TSL en pérdida.
                # Si quieres que el TSL también actúe en pérdida (por debajo del precio de compra),
                # la condición `precio_actual > precio_compra` debería eliminarse o ajustarse.
                # Para un TSL que protege ganancias, esta condición es correcta.

                if vender_ahora:
                    step = get_step_size(symbol)
                    # Asegurarse de que la cantidad a vender es el saldo actual disponible del activo base
                    # Esto es importante porque si una venta anterior falló o hubo un retiro manual,
                    # la cantidad_en_posicion del diccionario podría no reflejar el saldo real.
                    cantidad_a_vender_real = ajustar_cantidad(obtener_saldo_moneda(base), step) 
                    
                    if cantidad_a_vender_real > 0:
                        orden = vender(symbol, cantidad_a_vender_real)
                        if orden and 'fills' in orden and len(orden['fills']) > 0:
                            salida = float(orden['fills'][0]['price'])
                            ganancia = (salida - precio_compra) * cantidad_a_vender_real
                            mensaje_simbolo += (
                                f"\n✅ VENTA ejecutada por {motivo_venta} a {salida:.2f} USDT\n"
                                f"Ganancia/Pérdida: {ganancia:.2f} USDT"
                            )
                            posiciones_abiertas.pop(symbol) # Elimina el símbolo de las posiciones abiertas
                        else:
                            mensaje_simbolo += f"\n❌ VENTA fallida para {symbol}."
                    else:
                        mensaje_simbolo += f"\n⚠️ No hay {base} disponible para vender o cantidad muy pequeña."
            
            # Añadir los saldos actuales al final del mensaje de cada símbolo
            mensaje_simbolo += "\n" + obtener_saldos_formateados() 
            general_message += mensaje_simbolo + "\n\n" 

        send_telegram_message(general_message) # Envía un solo mensaje con toda la información

        elapsed_time = time.time() - start_time_cycle
        sleep_duration = max(0, INTERVALO - elapsed_time)
        print(f"⏳ Esperando {sleep_duration:.0f} segundos (aprox. {sleep_duration // 60} minutos)...\n")
        time.sleep(sleep_duration)

    except Exception as e:
        logging.error(f"Error general: {e}", exc_info=True) 
        send_telegram_message(f"❌ Error general en el bot: {e}\n\n{obtener_saldos_formateados()}") # Enviar saldos también en caso de error general
        print(f"❌ Error general: {e}")
        time.sleep(INTERVALO)




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