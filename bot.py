import os
import time
import logging
from binance.client import Client
from binance.enums import *
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
import telegram
import asyncio

# Cargar variables de entorno desde .env
load_dotenv()

# Inicialización de claves API y bot de Telegram
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")
telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

# Cliente de Binance apuntando a Testnet
client = Client(api_key, api_secret)
client.API_URL = 'https://testnet.binance.vision/api'

# Inicialización del bot de Telegram
bot = telegram.Bot(token=telegram_token)

# Configuración de logging para guardar en archivo .log
logging.basicConfig(
    filename="trading_bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Función para enviar mensajes por Telegram (usando asyncio)
async def enviar_telegram(mensaje):
    await bot.send_message(chat_id=telegram_chat_id, text=mensaje)

# Función para mostrar saldos de BTC y USDT
def mostrar_saldo():
    info = client.get_account()
    balances = info['balances']
    btc = next((b for b in balances if b['asset'] == 'BTC'), None)
    usdt = next((b for b in balances if b['asset'] == 'USDT'), None)
    btc_free = float(btc['free']) if btc else 0.0
    usdt_free = float(usdt['free']) if usdt else 0.0
    return btc_free, usdt_free

# Obtener el precio actual de BTC
def obtener_precio(simbolo="BTCUSDT"):
    ticker = client.get_symbol_ticker(symbol=simbolo)
    return float(ticker['price'])

# Obtener reglas de trading del símbolo (como tamaño mínimo de lote)
def obtener_lote_minimo(simbolo="BTCUSDT"):
    exchange_info = client.get_symbol_info(simbolo)
    lot_size_filter = next(f for f in exchange_info['filters'] if f['filterType'] == 'LOT_SIZE')
    min_qty = float(lot_size_filter['minQty'])
    step_size = float(lot_size_filter['stepSize'])
    return min_qty, step_size

# Redondear cantidad según step size
def redondear_cantidad(cantidad, step_size):
    precision = int(round(-1 * (math.log10(step_size))))
    return round(cantidad, precision)

# Compra usando un porcentaje fijo del capital en USDT
def comprar(simbolo="BTCUSDT", porcentaje=0.01):
    try:
        precio = obtener_precio(simbolo)
        _, step_size = obtener_lote_minimo(simbolo)
        _, usdt_saldo = mostrar_saldo()
        monto_usdt = usdt_saldo * porcentaje

        cantidad = monto_usdt / precio
        cantidad = redondear_cantidad(cantidad, step_size)

        orden = client.order_market_buy(symbol=simbolo, quantity=cantidad)

        total = float(orden['cummulativeQuoteQty'])
        avg_price = float(orden['fills'][0]['price'])
        comision = orden['fills'][0]['commission']
        comision_asset = orden['fills'][0]['commissionAsset']

        mensaje = (
            "✅ *COMPRA REALIZADA:*\n\n"
            f" - Símbolo: {simbolo}\n"
            f" - Cantidad comprada: {cantidad:.8f} BTC\n"
            f" - Precio promedio: {avg_price:.8f} USDT\n"
            f" - Total pagado: {total:.2f} USDT\n"
            f" - Comisión: {comision} {comision_asset}"
        )

        logging.info(mensaje)
        asyncio.run(enviar_telegram(mensaje))
        return total

    except BinanceAPIException as e:
        logging.error(f"Error en compra: {e}")
        asyncio.run(enviar_telegram(f"❌ Error en compra: {e}"))

# Venta usando una cantidad fija o lo comprado anteriormente
def vender(simbolo="BTCUSDT", cantidad=0.0001, total_compra=0.0):
    try:
        precio = obtener_precio(simbolo)
        _, step_size = obtener_lote_minimo(simbolo)

        cantidad = redondear_cantidad(cantidad, step_size)

        orden = client.order_market_sell(symbol=simbolo, quantity=cantidad)

        total = float(orden['cummulativeQuoteQty'])
        avg_price = float(orden['fills'][0]['price'])
        comision = orden['fills'][0]['commission']
        comision_asset = orden['fills'][0]['commissionAsset']

        ganancia = total - total_compra
        mensaje = (
            "✅ *VENTA REALIZADA:*\n\n"
            f" - Símbolo: {simbolo}\n"
            f" - Cantidad vendida: {cantidad:.8f} BTC\n"
            f" - Precio promedio: {avg_price:.8f} USDT\n"
            f" - Total recibido: {total:.2f} USDT\n"
            f" - Comisión: {comision} {comision_asset}\n"
            f" - Ganancia estimada: {ganancia:.2f} USDT"
        )

        logging.info(mensaje)
        asyncio.run(enviar_telegram(mensaje))
        return ganancia

    except BinanceAPIException as e:
        logging.error(f"Error en venta: {e}")
        asyncio.run(enviar_telegram(f"❌ Error en venta: {e}"))

# ========================
# Bucle principal del bot
# ========================
if __name__ == "__main__":
    print("🚀 Iniciando bot de trading...\n")
    while True:
        try:
            precio = obtener_precio()
            mensaje_precio = f"\n📊 Precio actual BTCUSDT: {precio:.2f}"
            print(mensaje_precio)
            asyncio.run(enviar_telegram(mensaje_precio))

            btc_saldo, usdt_saldo = mostrar_saldo()
            print(f"Saldo BTC: {btc_saldo}")
            print(f"Saldo USDT: {usdt_saldo}\n")

            # Ejecutar compra si hay USDT suficiente
            if usdt_saldo > 10:
                print("Intentando comprar BTC...\n")
                total_compra = comprar(porcentaje=0.01)
            else:
                total_compra = 0

            # Ejecutar venta si hay BTC suficiente
            if btc_saldo > 0.0001:
                print("Intentando vender BTC...\n")
                vender(cantidad=0.0001, total_compra=total_compra)

        except Exception as e:
            logging.error(f"Error en ejecución: {e}")
            asyncio.run(enviar_telegram(f"❌ Error general: {e}"))

        print("⏳ Esperando 5 minutos...\n")
        time.sleep(300)


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