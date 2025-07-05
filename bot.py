import os
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
    """Envía mensaje a Telegram con API requests"""
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
    """Obtiene datos OHLCV de Binance para cálculo indicadores"""
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
    """Calcula EMA20 y RSI sobre dataframe"""
    df['EMA20'] = ta.trend.ema_indicator(df['close'], window=20)
    df['RSI'] = ta.momentum.rsi(df['close'], window=14)
    return df

def obtener_saldos():
    """Obtiene saldo libre de BTC y USDT"""
    cuenta = client.get_account()
    saldo_btc = float(next(asset['free'] for asset in cuenta['balances'] if asset['asset'] == 'BTC'))
    saldo_usdt = float(next(asset['free'] for asset in cuenta['balances'] if asset['asset'] == 'USDT'))
    return saldo_btc, saldo_usdt

def get_step_size(symbol):
    """Obtiene step size para ajustar cantidad de orden"""
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001

def ajustar_cantidad(cantidad, step_size):
    """Ajusta cantidad a múltiplo de step_size (evita errores lot size)"""
    return round(cantidad - (cantidad % step_size), 6)

def comprar_btc(cantidad):
    """Orden de compra mercado"""
    try:
        orden = client.order_market_buy(symbol=SYMBOL, quantity=cantidad)
        return orden
    except BinanceAPIException as e:
        logging.error(f"Error en compra: {e}")
        send_telegram_message(f"❌ Error en compra: {e}")
        return None

def vender_btc(cantidad):
    """Orden de venta mercado"""
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

if __name__ == "__main__":
    main()


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