import os
import time
import logging
import telegram
from binance.client import Client
from binance.exceptions import BinanceAPIException

# Configuración de logging para guardar en un archivo
logging.basicConfig(
    filename='trading.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Parámetros de entorno
api_key = os.getenv('BINANCE_API_KEY')
api_secret = os.getenv('BINANCE_API_SECRET')
telegram_token = os.getenv('TELEGRAM_TOKEN')
chat_id = os.getenv('TELEGRAM_CHAT_ID')  # ID de tu chat o grupo

# Inicializar cliente de Binance
client = Client(api_key, api_secret)
client.API_URL = 'https://testnet.binance.vision/api'


# Inicializar bot de Telegram (versión sin async)
bot = telegram.Bot(token=telegram_token)

# Configuraciones generales
SIMBOLO = "BTCUSDT"
PORCENTAJE_CAPITAL = 0.1  # Invertir el 10% del capital USDT disponible

# Función para obtener el precio actual de un símbolo
def obtener_precio_actual():
    ticker = client.get_symbol_ticker(symbol=SIMBOLO)
    return float(ticker['price'])

# Función para obtener los balances de BTC y USDT
def obtener_saldos():
    balance_btc = float(client.get_asset_balance(asset="BTC")['free'])
    balance_usdt = float(client.get_asset_balance(asset="USDT")['free'])
    return balance_btc, balance_usdt

# Función para enviar mensajes a Telegram
def enviar_mensaje_telegram(mensaje):
    bot.send_message(chat_id=chat_id, text=mensaje)

# Función para comprar BTC
def comprar():
    _, usdt = obtener_saldos()
    precio_actual = obtener_precio_actual()
    monto_usar = usdt * PORCENTAJE_CAPITAL
    cantidad = round(monto_usar / precio_actual, 6)  # ajusta según el LOT_SIZE de Binance

    try:
        orden = client.order_market_buy(symbol=SIMBOLO, quantity=cantidad)
        precio = float(orden['fills'][0]['price'])
        total = round(precio * cantidad, 2)
        mensaje = (
            f"✅ COMPRA REALIZADA:\n\n"
            f" - Cantidad: {cantidad:.6f} BTC\n"
            f" - Precio promedio: {precio:.2f} USDT\n"
            f" - Total pagado: {total:.2f} USDT"
        )
        logging.info(mensaje)
        enviar_mensaje_telegram(mensaje)
        return precio, cantidad
    except BinanceAPIException as e:
        logging.error(f"Error en compra: {e}")
        enviar_mensaje_telegram(f"❌ Error en compra: {e}")
        return None, 0

# Función para vender BTC
def vender():
    btc, _ = obtener_saldos()
    cantidad = round(btc * PORCENTAJE_CAPITAL, 6)

    try:
        orden = client.order_market_sell(symbol=SIMBOLO, quantity=cantidad)
        precio = float(orden['fills'][0]['price'])
        total = round(precio * cantidad, 2)
        mensaje = (
            f"✅ VENTA REALIZADA:\n\n"
            f" - Cantidad: {cantidad:.6f} BTC\n"
            f" - Precio promedio: {precio:.2f} USDT\n"
            f" - Total recibido: {total:.2f} USDT"
        )
        logging.info(mensaje)
        enviar_mensaje_telegram(mensaje)
        return precio, cantidad
    except BinanceAPIException as e:
        logging.error(f"Error en venta: {e}")
        enviar_mensaje_telegram(f"❌ Error en venta: {e}")
        return None, 0

# Función principal de ejecución del bot
def run_bot():
    precio_compra = None
    while True:
        precio_actual = obtener_precio_actual()
        btc, usdt = obtener_saldos()

        mensaje = (
            f"📊 Precio actual {SIMBOLO}: {precio_actual:.2f} USDT\n"
            f"Saldo BTC: {btc:.6f}\n"
            f"Saldo USDT: {usdt:.2f}"
        )
        print(mensaje)
        enviar_mensaje_telegram(mensaje)

        # Alternar compra/venta si tenemos capital suficiente
        if usdt > 10:
            print("\nIntentando comprar BTC...")
            precio_compra, cantidad = comprar()
        elif btc > 0.0002:
            print("\nIntentando vender BTC...")
            precio_venta, cantidad = vender()
            if precio_compra:
                ganancia = (precio_venta - precio_compra) * cantidad
                ganancia_mensaje = f"💰 Ganancia estimada: {ganancia:.2f} USDT"
                logging.info(ganancia_mensaje)
                enviar_mensaje_telegram(ganancia_mensaje)

        print("\n⏳ Esperando 5 minutos...\n")
        time.sleep(300)

# Ejecutar el bot
if __name__ == "__main__":
    run_bot()


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