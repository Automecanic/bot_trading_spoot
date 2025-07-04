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

SYMBOL = "BTCUSDT"
INTERVALO = 300  # en segundos
PORCENTAJE_CAPITAL = 0.1  # 10% del capital por operación
TAKE_PROFIT_PORCENTAJE = 0.02  # +2%
STOP_LOSS_PORCENTAJE = 0.01    # -1%

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
        print("⚠️ No se puede enviar mensaje de Telegram: TOKEN o CHAT_ID no configurados.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print(f"✅ Mensaje de Telegram enviado: {message}")
    except requests.exceptions.RequestException as e:
        print(f"❌ Error al enviar mensaje de Telegram: {e}")

def obtener_precio_actual():
    ticker = client.get_symbol_ticker(symbol=SYMBOL)
    return float(ticker["price"])

def obtener_saldos():
    cuenta = client.get_account()
    saldo_btc = float(next(asset["free"] for asset in cuenta["balances"] if asset["asset"] == "BTC"))
    saldo_usdt = float(next(asset["free"] for asset in cuenta["balances"] if asset["asset"] == "USDT"))
    return saldo_btc, saldo_usdt

def get_step_size(symbol):
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001

def ajustar_cantidad(cantidad, step_size):
    return round(cantidad - (cantidad % step_size), 6)

def calcular_cantidad_a_comprar(precio, saldo_usdt, step_size):
    cantidad_usdt = saldo_usdt * PORCENTAJE_CAPITAL
    cantidad_btc = cantidad_usdt / precio
    return ajustar_cantidad(cantidad_btc, step_size)

def comprar_btc(cantidad):
    try:
        orden = client.order_market_buy(symbol=SYMBOL, quantity=cantidad)
        return orden
    except BinanceAPIException as e:
        logging.error(f"Error en compra: {e}")
        send_telegram_message(f"❌ Error en compra: {e}")
        return None

def vender_btc(cantidad):
    try:
        orden = client.order_market_sell(symbol=SYMBOL, quantity=cantidad)
        return orden
    except BinanceAPIException as e:
        logging.error(f"Error en venta: {e}")
        send_telegram_message(f"❌ Error en venta: {e}")
        return None

# ============ BUCLE PRINCIPAL ==============

precio_entrada = None
step_size = get_step_size(SYMBOL)

while True:
    try:
        precio_actual = obtener_precio_actual()
        saldo_btc, saldo_usdt = obtener_saldos()

        print(f"\n📊 Precio actual {SYMBOL}: {precio_actual}")
        print(f"Saldo BTC: {saldo_btc}")
        print(f"Saldo USDT: {saldo_usdt}")

        if saldo_btc > 0 and precio_entrada:
            variacion = (precio_actual - precio_entrada) / precio_entrada

            if variacion >= TAKE_PROFIT_PORCENTAJE:
                print("🎯 Condición de TAKE PROFIT alcanzada. Vendiendo...")
            elif variacion <= -STOP_LOSS_PORCENTAJE:
                print("🔻 Condición de STOP LOSS alcanzada. Vendiendo...")
            else:
                print("📉 Esperando condiciones de venta...")
                time.sleep(INTERVALO)
                continue

            cantidad_vender = ajustar_cantidad(saldo_btc * PORCENTAJE_CAPITAL, step_size)
            if cantidad_vender < step_size:
                print("⚠️ Cantidad a vender demasiado pequeña.")
                continue

            orden_venta = vender_btc(cantidad_vender)
            if orden_venta:
                precio_salida = float(orden_venta['fills'][0]['price'])
                cantidad_vendida = float(orden_venta['executedQty'])
                total_recibido = float(orden_venta['cummulativeQuoteQty'])
                ganancia = (precio_salida - precio_entrada) * cantidad_vendida
                ganancia = round(ganancia, 2)

                mensaje = (
                    f"✅ <b>VENTA REALIZADA</b>:\n\n"
                    f" - Símbolo: {SYMBOL}\n"
                    f" - Precio entrada: {precio_entrada:.2f} USDT\n"
                    f" - Precio venta: {precio_salida:.2f} USDT\n"
                    f" - Cantidad vendida: {cantidad_vendida:.8f} BTC\n"
                    f" - Total recibido: {total_recibido:.2f} USDT\n"
                    f" - Resultado: <b>{ganancia} USDT</b>"
                )
                send_telegram_message(mensaje)
                precio_entrada = None

        elif saldo_usdt > 10:
            print("🛒 Intentando comprar BTC...")
            cantidad_btc = calcular_cantidad_a_comprar(precio_actual, saldo_usdt, step_size)

            if cantidad_btc < step_size:
                print("⚠️ Cantidad a comprar demasiado pequeña.")
                continue

            orden_compra = comprar_btc(cantidad_btc)
            if orden_compra:
                precio_entrada = float(orden_compra['fills'][0]['price'])
                cantidad_comprada = float(orden_compra['executedQty'])
                total_usado = float(orden_compra['cummulativeQuoteQty'])

                mensaje = (
                    f"✅ <b>COMPRA REALIZADA</b>:\n\n"
                    f" - Símbolo: {SYMBOL}\n"
                    f" - Precio compra: {precio_entrada:.2f} USDT\n"
                    f" - Cantidad comprada: {cantidad_comprada:.8f} BTC\n"
                    f" - Total invertido: {total_usado:.2f} USDT"
                )
                send_telegram_message(mensaje)

        else:
            print("❗ No hay fondos suficientes para operar.")

        print(f"\n⏳ Esperando {INTERVALO // 60} minutos...\n")
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