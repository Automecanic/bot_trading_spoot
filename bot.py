
import os
from binance.client import Client

# Cargar las claves API desde variables de entorno
API_KEY = os.getenv('API_KEY')
API_SECRET = os.getenv('API_SECRET')

# Crear cliente Binance apuntando a testnet
client = Client(API_KEY, API_SECRET, testnet=True)

# Definir el símbolo y los activos base y cotizados
symbol = 'BTCUSDT'
base_asset = 'BTC'   # activo que queremos comprar/vender
quote_asset = 'USDT' # activo con el que pagamos

# Función para mostrar el saldo disponible de BTC y USDT
def mostrar_saldo():
    balances = client.get_account()['balances']  # Obtener balances de la cuenta
    btc_balance = next((b for b in balances if b['asset'] == base_asset), None)
    usdt_balance = next((b for b in balances if b['asset'] == quote_asset), None)
    print(f"Saldo BTC: {btc_balance['free'] if btc_balance else '0'}")
    print(f"Saldo USDT: {usdt_balance['free'] if usdt_balance else '0'}")

# Función para crear una orden limitada de compra
def comprar_limitada(quantity, limit_price):
    try:
        order = client.create_order(
            symbol=symbol,
            side='BUY',                # tipo compra
            type='LIMIT',              # orden limitada
            timeInForce='GTC',         # válida hasta cancelar o ejecutar
            quantity=quantity,         # cantidad a comprar
            price=str(limit_price)     # precio límite
        )
        print("Orden limitada de compra creada:", order)
    except Exception as e:
        print("Error comprando:", e)

# Función para vender al precio de mercado toda una cantidad dada
def vender_market(quantity):
    try:
        order = client.create_order(
            symbol=symbol,
            side='SELL',               # tipo venta
            type='MARKET',             # orden de mercado (ejecuta al mejor precio)
            quantity=quantity          # cantidad a vender
        )
        print("Orden de venta a mercado creada:", order)
    except Exception as e:
        print("Error vendiendo:", e)

# Función para colocar una orden stop loss limitada para proteger la posición
def colocar_stop_loss(quantity, stop_price, stop_limit_price):
    try:
        order = client.create_order(
            symbol=symbol,
            side='SELL',               # venta para proteger
            type='STOP_LOSS_LIMIT',    # orden stop loss limitada
            quantity=quantity,         # cantidad a vender si se activa
            price=str(stop_limit_price), # precio límite para la orden stop
            stopPrice=str(stop_price),   # precio trigger que activa la orden stop
            timeInForce='GTC'          # válida hasta cancelar o ejecutar
        )
        print("Orden stop loss creada:", order)
    except Exception as e:
        print("Error creando stop loss:", e)

if __name__ == "__main__":
    # Mostrar saldo inicial antes de operaciones
    print("Saldo inicial:")
    mostrar_saldo()

    # Parámetros para la compra limitada
    cantidad_compra = 0.001
    precio_limite = 20000

    # Crear orden limitada de compra
    comprar_limitada(cantidad_compra, precio_limite)

    # Parámetros para el stop loss (venta si baja de cierto precio)
    stop_price = 19000
    stop_limit_price = 18950

    # Colocar orden stop loss para proteger la compra
    colocar_stop_loss(cantidad_compra, stop_price, stop_limit_price)

    # Mostrar saldo después de colocar órdenes
    print("\nSaldo después de la compra:")
    mostrar_saldo()

    # Consultar saldo actual para vender todo lo que tengamos en BTC
    balances = client.get_account()['balances']
    btc_balance = next((b for b in balances if b['asset'] == base_asset), None)
    cantidad_venta = float(btc_balance['free']) if btc_balance else 0

    # Si hay BTC, vender todo a mercado
    if cantidad_venta > 0:
        vender_market(cantidad_venta)
    else:
        print("No tienes BTC para vender.")

    # Mostrar saldo final después de la venta
    print("\nSaldo final:")
    mostrar_saldo()



"""from binance.client import Client

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