import os
import time
import logging
import requests
from binance.client import Client
from binance.exceptions import BinanceAPIException

# =================== CONFIGURACIÓN ===================

API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT"]
INTERVALO = 300  # en segundos
PORCENTAJE_CAPITAL = 0.1
STOP_LOSS_PCT = 0.02
TAKE_PROFIT_PCT = 0.03

# =====================================================

client = Client(API_KEY, API_SECRET)
client.API_URL = 'https://testnet.binance.vision/api'

logging.basicConfig(
    filename='trading_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ============ FUNCIONES ==============

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ No se puede enviar mensaje de Telegram.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"✅ Mensaje enviado: {message}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al enviar mensaje: {e}")

def obtener_precio_actual(symbol):
    return float(client.get_symbol_ticker(symbol=symbol)["price"])

def obtener_saldos():
    cuenta = client.get_account()
    saldos = {b['asset']: float(b['free']) for b in cuenta['balances']}
    return saldos

def get_step_size(symbol):
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001

def ajustar_cantidad(cantidad, step_size):
    return round(cantidad - (cantidad % step_size), 6)

def calcular_cantidad_a_comprar(symbol, saldo_usdt):
    precio = obtener_precio_actual(symbol)
    step_size = get_step_size(symbol)
    cantidad_usdt = saldo_usdt * PORCENTAJE_CAPITAL
    cantidad = cantidad_usdt / precio
    return ajustar_cantidad(cantidad, step_size)

def comprar(symbol, cantidad):
    try:
        return client.order_market_buy(symbol=symbol, quantity=cantidad)
    except BinanceAPIException as e:
        logging.error(f"Compra {symbol} - {e}")
        send_telegram_message(f"❌ Error al comprar {symbol}: {e}")
        return None

def vender(symbol, cantidad):
    try:
        return client.order_market_sell(symbol=symbol, quantity=cantidad)
    except BinanceAPIException as e:
        logging.error(f"Venta {symbol} - {e}")
        send_telegram_message(f"❌ Error al vender {symbol}: {e}")
        return None

def obtener_precio_usdt_eur():
    try:
        ticker = client.get_symbol_ticker(symbol="EURUSDT")
        return 1 / float(ticker["price"])
    except:
        return 0.92  # Valor estimado en caso de error

# ============ BUCLE PRINCIPAL ==============

precios_entrada = {}

while True:
    try:
        saldos = obtener_saldos()
        saldo_usdt = saldos.get("USDT", 0)
        saldo_total_usdt = saldo_usdt
        eur_rate = obtener_precio_usdt_eur()

        for symbol in SYMBOLS:
            base_asset = symbol.replace("USDT", "")
            saldo_base = saldos.get(base_asset, 0)
            precio_actual = obtener_precio_actual(symbol)
            step_size = get_step_size(symbol)

            if saldo_base > 0:
                precio_entrada = precios_entrada.get(symbol)
                ganancia_pct = (precio_actual - precio_entrada) / precio_entrada if precio_entrada else 0

                if ganancia_pct >= TAKE_PROFIT_PCT or ganancia_pct <= -STOP_LOSS_PCT:
                    cantidad_vender = ajustar_cantidad(saldo_base, step_size)
                    orden = vender(symbol, cantidad_vender)
                    if orden:
                        precio_salida = float(orden['fills'][0]['price'])
                        cantidad = float(orden['executedQty'])
                        recibido = float(orden['cummulativeQuoteQty'])
                        ganancia = round((precio_salida - precio_entrada) * cantidad, 2)

                        mensaje = (
                            f"✅ <b>VENTA DE {symbol}</b>\n"
                            f" - Cantidad: {cantidad:.6f} {base_asset}\n"
                            f" - Precio: {precio_salida:.2f} USDT\n"
                            f" - Total: {recibido:.2f} USDT\n"
                            f" - Ganancia: <b>{ganancia} USDT</b>"
                        )
                        send_telegram_message(mensaje)
                        precios_entrada[symbol] = None
                        saldo_total_usdt += recibido

            elif saldo_usdt > 10:
                cantidad = calcular_cantidad_a_comprar(symbol, saldo_usdt)
                orden = comprar(symbol, cantidad)
                if orden:
                    precio = float(orden['fills'][0]['price'])
                    cantidad_comprada = float(orden['executedQty'])
                    total_invertido = float(orden['cummulativeQuoteQty'])

                    precios_entrada[symbol] = precio
                    saldo_total_usdt -= total_invertido

                    mensaje = (
                        f"✅ <b>COMPRA DE {symbol}</b>\n"
                        f" - Cantidad: {cantidad_comprada:.6f} {base_asset}\n"
                        f" - Precio: {precio:.2f} USDT\n"
                        f" - Total: {total_invertido:.2f} USDT"
                    )
                    send_telegram_message(mensaje)

        saldo_eur = saldo_total_usdt * eur_rate
        resumen = (
            f"💼 <b>RESUMEN DE CUENTA</b>\n"
            f" - Total estimado: {saldo_total_usdt:.2f} USDT / {saldo_eur:.2f} EUR"
        )
        send_telegram_message(resumen)

        print("⏳ Esperando próximo ciclo...\n")
        time.sleep(INTERVALO)

    except Exception as e:
        logging.error(f"Error general: {e}")
        send_telegram_message(f"❌ Error general: {e}")
        time.sleep(INTERVALO)




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