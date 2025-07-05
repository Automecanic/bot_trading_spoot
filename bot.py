import os  # Para variables de entorno
import time  # Para pausas entre ciclos
import logging  # Para guardar logs en archivo
import requests  # Para enviar mensajes a Telegram
from binance.client import Client  # Cliente oficial Binance API
from binance.exceptions import BinanceAPIException  # Para capturar errores de Binance

# =================== CONFIGURACIÓN ===================

API_KEY = os.getenv("BINANCE_API_KEY")  # API key de Binance desde variables de entorno
API_SECRET = os.getenv("BINANCE_API_SECRET")  # Secret key Binance

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")  # Token bot Telegram
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # ID del chat Telegram

INTERVALO = 300  # Tiempo entre ciclos en segundos (5 minutos)
PORCENTAJE_CAPITAL = 0.1  # Porcentaje de saldo USDT a invertir en cada operación
STOP_LOSS_PCT = 0.02  # Stop-loss: pérdida máxima permitida (2%)
TAKE_PROFIT_PCT = 0.04  # Take-profit: ganancia objetivo (4%)

# Lista con símbolos de las criptomonedas que se van a tradear
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "SOLUSDT"]

# =====================================================

# Crear cliente Binance con keys
client = Client(API_KEY, API_SECRET)
# Usar testnet para pruebas (cambiar o quitar si usas real)
client.API_URL = 'https://testnet.binance.vision/api'

# Configurar logging para guardar en archivo con formato fecha-nivel-mensaje
logging.basicConfig(filename='trading_bot.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Diccionario para guardar estado de cada operación por símbolo
# Guardamos el precio de entrada para poder calcular ganancias o activar stop-loss/take-profit
estado_operaciones = {symbol: {"precio_entrada": None} for symbol in SYMBOLS}

# =================== FUNCIONES ===================

# Función para enviar mensajes a Telegram
def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:  # Si no hay token o chat, no enviar
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"  # URL API Telegram
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'HTML'}  # Parámetros mensaje
    try:
        requests.post(url, json=payload).raise_for_status()  # Enviar mensaje y verificar estado
    except requests.exceptions.RequestException as e:  # Capturar errores de red o API
        print(f"❌ Error al enviar mensaje: {e}")

# Obtener precio actual de un símbolo (ej: BTCUSDT)
def obtener_precio_actual(symbol):
    return float(client.get_symbol_ticker(symbol=symbol)["price"])

# Obtener saldos disponibles de todas las monedas
def obtener_saldos():
    cuenta = client.get_account()  # Información completa de la cuenta
    saldos = {asset["asset"]: float(asset["free"]) for asset in cuenta["balances"]}  # Diccionario asset: saldo libre
    return saldos

# Obtener tamaño mínimo para cantidad (stepSize) para evitar errores al operar
def get_step_size(symbol):
    info = client.get_symbol_info(symbol)  # Información del símbolo
    for f in info['filters']:  # Buscar filtro LOT_SIZE
        if f['filterType'] == 'LOT_SIZE':
            return float(f['stepSize'])
    return 0.000001  # Valor muy pequeño si no se encuentra (fallback)

# Ajustar la cantidad para cumplir con el stepSize (evitar decimales inválidos)
def ajustar_cantidad(cantidad, step_size):
    return round(cantidad - (cantidad % step_size), 6)  # Restar el residuo y redondear a 6 decimales

# Calcular la cantidad a comprar en BTC usando porcentaje del saldo USDT y el precio actual
def calcular_cantidad_a_comprar(precio, saldo_usdt, step_size):
    cantidad_usdt = saldo_usdt * PORCENTAJE_CAPITAL  # Porción de USDT a usar
    cantidad = cantidad_usdt / precio  # Convertir a BTC
    return ajustar_cantidad(cantidad, step_size)  # Ajustar cantidad al stepSize

# Realizar orden de compra de mercado (market buy)
def comprar(symbol, cantidad):
    try:
        return client.order_market_buy(symbol=symbol, quantity=cantidad)
    except BinanceAPIException as e:  # Capturar errores Binance y enviar Telegram
        send_telegram_message(f"❌ Error al comprar {symbol}: {e}")
        return None

# Realizar orden de venta de mercado (market sell)
def vender(symbol, cantidad):
    try:
        return client.order_market_sell(symbol=symbol, quantity=cantidad)
    except BinanceAPIException as e:
        send_telegram_message(f"❌ Error al vender {symbol}: {e}")
        return None

# Estimar saldo en EUR usando un tipo de cambio fijo USD->EUR
def estimar_eur(valor_usdt, tasa=1.08):
    return round(valor_usdt / tasa, 2)

# =================== BUCLE PRINCIPAL ===================

while True:
    try:
        saldos = obtener_saldos()  # Obtener todos los saldos
        saldo_usdt = saldos.get("USDT", 0)  # Saldo disponible en USDT

        # Recorrer cada símbolo para evaluar compra o venta
        for symbol in SYMBOLS:
            base = symbol.replace("USDT", "")  # Ejemplo: "BTC" de "BTCUSDT"
            saldo_base = saldos.get(base, 0)  # Saldo disponible de la moneda base
            precio_actual = obtener_precio_actual(symbol)  # Precio actual del símbolo
            step_size = get_step_size(symbol)  # Obtener stepSize para esa moneda
            estado = estado_operaciones[symbol]  # Estado actual de esa moneda
            entrada = estado["precio_entrada"]  # Precio al que se compró (si hay)

            print(f"\n📊 {symbol} - Precio: {precio_actual} | Saldo {base}: {saldo_base} | USDT: {saldo_usdt}")

            # Si tengo moneda base y ya compré antes (precio_entrada no es None)
            if saldo_base > 0 and entrada:
                # Verificar si activo stop-loss o take-profit
                if precio_actual <= entrada * (1 - STOP_LOSS_PCT):
                    razon = "🛑 <b>Stop-Loss activado</b>"
                elif precio_actual >= entrada * (1 + TAKE_PROFIT_PCT):
                    razon = "🎯 <b>Take-Profit alcanzado</b>"
                else:
                    continue  # Si no se cumple stop-loss ni take-profit, no vender

                cantidad_vender = ajustar_cantidad(saldo_base, step_size)  # Ajustar cantidad a vender
                orden = vender(symbol, cantidad_vender)  # Ejecutar venta
                if orden:
                    precio_venta = float(orden['fills'][0]['price'])  # Precio de venta promedio
                    qty = float(orden['executedQty'])  # Cantidad vendida
                    total = float(orden['cummulativeQuoteQty'])  # Total recibido en USDT
                    ganancia = round((precio_venta - entrada) * qty, 2)  # Calcular ganancia

                    # Construir mensaje para Telegram
                    mensaje = (
                        f"{razon} para {symbol}:\n\n"
                        f" - Vendido: {qty:.6f} {base}\n"
                        f" - Precio: {precio_venta:.2f} USDT\n"
                        f" - Total: {total:.2f} USDT\n"
                        f" - Ganancia: <b>{ganancia} USDT</b>\n"
                        f" - Total en EUR (estimado): {estimar_eur(saldo_usdt)} EUR"
                    )
                    send_telegram_message(mensaje)  # Enviar mensaje
                    estado_operaciones[symbol]["precio_entrada"] = None  # Resetear precio entrada

            # Si no tengo la moneda base pero sí saldo USDT suficiente para comprar
            elif saldo_usdt > 10:
                cantidad_comprar = calcular_cantidad_a_comprar(precio_actual, saldo_usdt, step_size)  # Cantidad a comprar
                if cantidad_comprar <= 0:  # Si la cantidad es inválida, saltar
                    continue

                orden = comprar(symbol, cantidad_comprar)  # Ejecutar compra
                if orden:
                    precio_entrada = float(orden['fills'][0]['price'])  # Precio promedio compra
                    qty = float(orden['executedQty'])  # Cantidad comprada
                    total = float(orden['cummulativeQuoteQty'])  # Total invertido USDT

                    # Construir mensaje compra
                    mensaje = (
                        f"✅ <b>COMPRA DE {symbol}</b>:\n\n"
                        f" - Comprado: {qty:.6f} {base}\n"
                        f" - Precio: {precio_entrada:.2f} USDT\n"
                        f" - Total: {total:.2f} USDT\n"
                        f" - Total en EUR (estimado): {estimar_eur(saldo_usdt)} EUR"
                    )
                    send_telegram_message(mensaje)  # Enviar mensaje
                    estado_operaciones[symbol]["precio_entrada"] = precio_entrada  # Guardar precio entrada

        print(f"\n⏳ Esperando {INTERVALO//60} minutos...\n")  # Mostrar espera
        time.sleep(INTERVALO)  # Pausar ejecución

    except Exception as e:
        logging.error(f"Error general: {e}")  # Guardar error en log
        send_telegram_message(f"⚠️ Error general: {e}")  # Notificar por Telegram
        time.sleep(INTERVALO)  # Esperar antes de seguir intentando



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