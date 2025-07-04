import os
import time
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv
import requests

# Cargar variables de entorno desde el archivo .env
load_dotenv()

# Credenciales de Binance (Testnet)
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

# Credenciales de Telegram
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

# Crear cliente de Binance apuntando al entorno de testnet
client = Client(api_key, api_secret)
client.API_URL = 'https://testnet.binance.vision/api'

# Configurar logging
logging.basicConfig(
    filename='trading.log',
    level=logging.INFO,
    format='%(asctime)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Variables para seguimiento de ganancias
ganancia_total = 0.0

# Función para enviar mensaje a Telegram
def enviar_telegram(mensaje):
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {"chat_id": telegram_chat_id, "text": mensaje}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print("Error al enviar mensaje a Telegram:", e)

# Obtener saldos de BTC y USDT
def mostrar_saldo():
    info = client.get_account()
    balances = info['balances']
    btc = next((b for b in balances if b['asset'] == 'BTC'), None)
    usdt = next((b for b in balances if b['asset'] == 'USDT'), None)
    btc_free = float(btc['free']) if btc else 0.0
    usdt_free = float(usdt['free']) if usdt else 0.0
    print(f"Saldo BTC: {btc_free}")
    print(f"Saldo USDT: {usdt_free}")
    return btc_free, usdt_free

# Obtener precio actual del par
def obtener_precio(simbolo="BTCUSDT"):
    ticker = client.get_symbol_ticker(symbol=simbolo)
    return float(ticker['price'])

# Ejecutar orden de compra
def comprar(simbolo="BTCUSDT", cantidad=0.0001):
    try:
        orden = client.order_market_buy(symbol=simbolo, quantity=cantidad)
        fill = orden['fills'][0]
        precio = float(fill['price'])
        total = float(fill['qty']) * precio
        mensaje = (
            f"✅ COMPRA REALIZADA:\n"
            f"\n - Símbolo: {orden['symbol']}"
            f"\n - Cantidad comprada: {fill['qty']} BTC"
            f"\n - Precio promedio: {fill['price']} USDT"
            f"\n - Total pagado: {total:.2f} USDT"
            f"\n - Comisión: {fill['commission']} {fill['commissionAsset']}"
        )
        print(mensaje)
        logging.info(mensaje)
        enviar_telegram(mensaje)
        return total
    except BinanceAPIException as e:
        print("Error en compra:", e)
        logging.error(f"Error en compra: {e}")
        enviar_telegram(f"❌ Error en compra: {e}")
        return 0.0

# Ejecutar orden de venta
def vender(simbolo="BTCUSDT", cantidad=0.0001, precio_compra=0.0):
    global ganancia_total
    try:
        orden = client.order_market_sell(symbol=simbolo, quantity=cantidad)
        fill = orden['fills'][0]
        precio_venta = float(fill['price'])
        total_venta = float(fill['qty']) * precio_venta
        ganancia = total_venta - precio_compra
        ganancia_total += ganancia

        mensaje = (
            f"✅ VENTA REALIZADA:\n"
            f"\n - Símbolo: {orden['symbol']}"
            f"\n - Cantidad vendida: {fill['qty']} BTC"
            f"\n - Precio promedio: {fill['price']} USDT"
            f"\n - Total recibido: {total_venta:.2f} USDT"
            f"\n - Comisión: {fill['commission']} {fill['commissionAsset']}"
            f"\n - Ganancia: {ganancia:.2f} USDT"
            f"\n - Ganancia acumulada: {ganancia_total:.2f} USDT"
        )
        print(mensaje)
        logging.info(mensaje)
        enviar_telegram(mensaje)
    except BinanceAPIException as e:
        print("Error en venta:", e)
        logging.error(f"Error en venta: {e}")
        enviar_telegram(f"❌ Error en venta: {e}")

# Bucle principal
if __name__ == "__main__":
    while True:
        try:
            # Obtener precio actual
            precio = obtener_precio()
            print(f"\nPrecio actual BTCUSDT: {precio}")

            # Mostrar saldos
            btc_saldo, usdt_saldo = mostrar_saldo()

            # Comprar si hay suficiente USDT
            if usdt_saldo > 10:
                print("\nIntentando comprar 0.0001 BTC...")
                total_pagado = comprar(cantidad=0.0001)
            else:
                total_pagado = 0.0

            # Vender si hay suficiente BTC
            if btc_saldo > 0.0001:
                print("\nIntentando vender 0.0001 BTC...")
                vender(cantidad=0.0001, precio_compra=total_pagado)

        except Exception as e:
            print("Error en ejecución:", e)
            logging.error(f"Error general: {e}")
            enviar_telegram(f"⚠️ Error en ejecución: {e}")

        # Esperar 5 minutos
        print("\nEsperando 5 minutos...\n")
        time.sleep(300)




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