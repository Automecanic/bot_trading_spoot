# Importamos librerías necesarias
import os                  # Para trabajar con variables de entorno
import time                # Para hacer pausas (sleep)
import json                # Para leer/escribir archivos en formato JSON
from binance.client import Client                   # Cliente principal de la API de Binance
from binance.exceptions import BinanceAPIException  # Para capturar errores específicos de Binance
from dotenv import load_dotenv                      # Para cargar variables desde un archivo .env

# Cargamos las variables de entorno desde .env
load_dotenv()

# Obtenemos la clave y el secreto de API desde el entorno
api_key = os.getenv("BINANCE_API_KEY")
api_secret = os.getenv("BINANCE_API_SECRET")

# Creamos el cliente de Binance
client = Client(api_key, api_secret)
client.API_URL = 'https://testnet.binance.vision/api'  # <- línea clave

# Nombre del archivo donde se guardará la última operación realizada
estado_file = "estado.json"

# Función para cargar la última operación guardada en el archivo JSON
def cargar_ultimo_estado():
    if os.path.exists(estado_file):  # Si el archivo existe
        with open(estado_file, "r") as f:  # Lo abrimos en modo lectura
            return json.load(f).get("ultima_operacion")  # Devolvemos el valor de "ultima_operacion"
    return None  # Si el archivo no existe, devolvemos None

# Función para guardar una operación ("buy" o "sell") en el archivo JSON
def guardar_estado(operacion):
    with open(estado_file, "w") as f:  # Abrimos en modo escritura
        json.dump({"ultima_operacion": operacion}, f)  # Guardamos un diccionario con la operación

# Función para mostrar el saldo disponible en BTC y USDT
def mostrar_saldo():
    info = client.get_account()  # Obtenemos información de la cuenta
    balances = info['balances']  # Accedemos a la lista de balances
    # Buscamos los balances de BTC y USDT
    btc = next((b for b in balances if b['asset'] == 'BTC'), None)
    usdt = next((b for b in balances if b['asset'] == 'USDT'), None)
    # Convertimos los valores a float (si existen)
    btc_free = float(btc['free']) if btc else 0.0
    usdt_free = float(usdt['free']) if usdt else 0.0
    # Mostramos los saldos por consola
    print(f"Saldo BTC: {btc_free}")
    print(f"Saldo USDT: {usdt_free}")
    return btc_free, usdt_free  # Devolvemos los saldos

# Función para obtener el precio actual de un par, por defecto BTCUSDT
def obtener_precio(simbolo="BTCUSDT"):
    ticker = client.get_symbol_ticker(symbol=simbolo)  # Llamamos a la API de Binance
    return float(ticker['price'])  # Devolvemos el precio como número decimal

# Función para realizar una orden de compra de mercado
def comprar(simbolo="BTCUSDT", cantidad=0.0001):
    try:
        orden = client.order_market_buy(symbol=simbolo, quantity=cantidad)
        guardar_estado("buy")
        
        # Extraer datos relevantes
        precio = orden['fills'][0]['price']
        cantidad_comprada = orden['executedQty']
        total_usdt = orden['cummulativeQuoteQty']
        comision = orden['fills'][0]['commission']
        print(f"✅ COMPRA REALIZADA:")
        print(f" - Símbolo: {orden['symbol']}")
        print(f" - Cantidad comprada: {cantidad_comprada} BTC")
        print(f" - Precio promedio: {precio} USDT")
        print(f" - Total pagado: {total_usdt} USDT")
        print(f" - Comisión: {comision} BTC")
        
    except BinanceAPIException as e:
        print("❌ Error en compra:", e)


# Función para realizar una orden de venta de mercado
ddef vender(simbolo="BTCUSDT", cantidad=0.0001):
    try:
        orden = client.order_market_sell(symbol=simbolo, quantity=cantidad)
        guardar_estado("sell")
        
        # Extraer datos relevantes
        precio = orden['fills'][0]['price']
        cantidad_vendida = orden['executedQty']
        total_usdt = orden['cummulativeQuoteQty']
        comision = orden['fills'][0]['commission']
        print(f"✅ VENTA REALIZADA:")
        print(f" - Símbolo: {orden['symbol']}")
        print(f" - Cantidad vendida: {cantidad_vendida} BTC")
        print(f" - Precio promedio: {precio} USDT")
        print(f" - Total recibido: {total_usdt} USDT")
        print(f" - Comisión: {comision} USDT")
        
    except BinanceAPIException as e:
        print("❌ Error en venta:", e)

# Código principal que se ejecuta continuamente
if __name__ == "__main__":
    while True:  # Bucle infinito (se puede detener manualmente o con Ctrl+C)
        try:
            # Obtenemos el precio actual de BTC/USDT
            precio = obtener_precio()
            print(f"Precio actual BTCUSDT: {precio}")

            # Obtenemos los saldos disponibles
            btc_saldo, usdt_saldo = mostrar_saldo()

            # Cargamos la última operación realizada desde archivo
            ultima_operacion = cargar_ultimo_estado()

            # Si hay suficiente USDT y la última operación NO fue una compra, compramos
            if usdt_saldo > 10 and ultima_operacion != "buy":
                print("Intentando comprar 0.0001 BTC...")
                comprar(cantidad=0.0001)

            # Si hay suficiente BTC y la última operación NO fue una venta, vendemos
            elif btc_saldo > 0.0001 and ultima_operacion != "sell":
                print("Intentando vender 0.0001 BTC...")
                vender(cantidad=0.0001)

            else:
                # Si no se cumplen las condiciones, no se hace ninguna operación
                print("No se realiza operación para evitar duplicados.")

        except Exception as e:
            # Captura errores generales
            print("Error en ejecución:", e)

        # Esperamos 5 minutos (300 segundos) antes de repetir el ciclo
        print("Esperando 5 minutos...\n")
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