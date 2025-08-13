# -*- coding: utf-8 -*-
"""
bot.py  – 2025-06-05
VERSIÓN COMPLETA:
- Opera en tendencia (EMA/RSI) como siempre.
- Detecta mercado lateral y opera en rango (cuando está activo).
- Sin eliminar ninguna funcionalidad anterior.
- Comandos Telegram:
    /toggle_rango           – Activa/Desactiva detección de rango
    /set_rango_params       – Ajusta período y umbral
    /set_rango_rsi          – Ajusta RSI para rango
"""

# ------------------- IMPORTS -------------------
import os
import time
import json
import csv
import logging
import threading
from datetime import datetime, timedelta
import requests
from binance.client import Client
from binance.enums import *

# ------------- IMPORTS DE MÓDULOS PROPIOS -------------
import config_manager
import position_manager
import telegram_handler
import binance_utils
import trading_logic
import reporting_manager
# NUEVO módulo para detectar mercado lateral y operar en rango
from range_trading import detectar_rango_lateral, estrategia_rango

# ----------------- CONFIGURACIÓN LOGGING -----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ----------------- VARIABLES GLOBALES -----------------
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_API_SECRET")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
OPEN_POSITIONS_FILE = "open_positions.json"

# --------- CARGA DE PARÁMETROS (incluidos rango) ----------
bot_params = config_manager.load_parameters()

# Parámetros clásicos
SYMBOLS = ["BTCUSDT", "BNBUSDT", "XLMUSDT", "TRXUSDT",
           "ADAUSDT", "XRPUSDT", "DOGEUSDT", "SOLUSDT", "ETHUSDT"]
INTERVALO = bot_params["INTERVALO"]
RIESGO_POR_OPERACION_PORCENTAJE = bot_params["RIESGO_POR_OPERACION_PORCENTAJE"]
TAKE_PROFIT_PORCENTAJE = bot_params["TAKE_PROFIT_PORCENTAJE"]
STOP_LOSS_PORCENTAJE = bot_params["STOP_LOSS_PORCENTAJE"]
TRAILING_STOP_PORCENTAJE = bot_params["TRAILING_STOP_PORCENTAJE"]
EMA_CORTA_PERIODO = bot_params.get("EMA_CORTA_PERIODO", 20)
EMA_MEDIA_PERIODO = bot_params.get("EMA_MEDIA_PERIODO", 50)
EMA_LARGA_PERIODO = bot_params.get("EMA_LARGA_PERIODO", 200)
RSI_PERIODO = bot_params["RSI_PERIODO"]
RSI_UMBRAL_SOBRECOMPRA = bot_params["RSI_UMBRAL_SOBRECOMPRA"]
BREAKEVEN_PORCENTAJE = bot_params["BREAKEVEN_PORCENTAJE"]

# NUEVOS parámetros para operar en rango
RANGO_OPERAR = bot_params.get("RANGO_OPERAR", True)
RANGO_PERIODO_ANALISIS = bot_params.get("RANGO_PERIODO_ANALISIS", 20)
RANGO_UMBRAL_ATR = bot_params.get("RANGO_UMBRAL_ATR", 0.015)
RANGO_RSI_SOBREVENTA = bot_params.get("RANGO_RSI_SOBREVENTA", 30)
RANGO_RSI_SOBRECOMPRA = bot_params.get("RANGO_RSI_SOBRECOMPRA", 70)
PARAMS = bot_params.get("symbols", {})
# Asegurar persistencia
config_manager.save_parameters(bot_params)


# ----------------- CLIENTE BINANCE -----------------
client = Client(API_KEY, API_SECRET, testnet=True,
                requests_params={'timeout': 30})
client.API_URL = 'https://testnet.binance.vision/api'

# ----------------- VARIABLES DE CONTROL -----------------
posiciones_abiertas = position_manager.load_open_positions(
    STOP_LOSS_PORCENTAJE)
last_update_id = 0
TELEGRAM_LISTEN_INTERVAL = 5
transacciones_diarias = []
ultima_fecha_informe_enviado = None
last_trading_check_time = 0
shared_data_lock = threading.Lock()


def cfg(symbol):
    return PARAMS.get(symbol, {
        "stop_loss_pct": 0.03,
        "take_profit_pct": 0.05,
        "trailing_stop_pct": 0.025,
        "breakeven_pct": 0.01,
        "rsi_buy": 35,
        "rsi_sell": 65,
        "volume_factor": 1.5,
        "ema_fast": 9,
        "ema_slow": 21
    })


# ------------------------------------------------------------------
#  MANEJADOR DE COMANDOS TELEGRAM (completo) – incluye nuevos comandos
# ------------------------------------------------------------------

def handle_telegram_commands():
    """
    Función maestra que procesa TODOS los comandos de Telegram.
    Cada comando actualiza inmediatamente la variable global y persiste en Firestore/JSON.
    Los cambios se reflejan sin reiniciar el bot.
    """
    # Variables que podremos modificar desde Telegram
    global last_update_id, bot_params, posiciones_abiertas, transacciones_diarias, \
        INTERVALO, RIESGO_POR_OPERACION_PORCENTAJE, TAKE_PROFIT_PORCENTAJE, \
        STOP_LOSS_PORCENTAJE, TRAILING_STOP_PORCENTAJE, EMA_CORTA_PERIODO, \
        EMA_MEDIA_PERIODO, EMA_LARGA_PERIODO, RSI_PERIODO, RSI_UMBRAL_SOBRECOMPRA, \
        BREAKEVEN_PORCENTAJE

    # Obtenemos las actualizaciones de Telegram
    updates = telegram_handler.get_telegram_updates(
        last_update_id + 1, TELEGRAM_BOT_TOKEN)

    if updates and updates['ok']:
        for update in updates['result']:
            last_update_id = update['update_id']

            # Solo procesamos mensajes de texto
            if 'message' not in update or 'text' not in update['message']:
                continue

            chat_id = str(update['message']['chat']['id'])
            text = update['message']['text'].strip()

            # Seguridad: ignorar mensajes desde chats no autorizados
            if chat_id != TELEGRAM_CHAT_ID:
                telegram_handler.send_telegram_message(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    f"⚠️ Comando recibido de chat no autorizado: {chat_id}")
                logging.warning(f"Comando de chat no autorizado: {chat_id}")
                continue

            # Partimos el texto para extraer comando y argumentos
            parts = text.split()
            command = parts[0].lower()

            try:
                # ---------- 1. PARÁMETROS DE ESTRATEGIA ----------
                if command == "/set_intervalo":
                    if len(parts) == 2:
                        nuevo = int(parts[1])
                        with shared_data_lock:
                            bot_params['INTERVALO'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ INTERVALO actualizado a {nuevo} segundos")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_intervalo <segundos_entero>")

                elif command == "/set_riesgo":
                    if len(parts) == 2:
                        nuevo = float(parts[1])
                        with shared_data_lock:
                            bot_params['RIESGO_POR_OPERACION_PORCENTAJE'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ RIESGO por operación a {nuevo:.4f}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_riesgo <decimal_ej_0.01>")

                elif command == "/set_tp":
                    if len(parts) == 2:
                        nuevo = float(parts[1])
                        with shared_data_lock:
                            bot_params['TAKE_PROFIT_PORCENTAJE'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ TAKE PROFIT a {nuevo:.4f}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_tp <decimal_ej_0.03>")

                elif command == "/set_sl_fijo":
                    if len(parts) == 2:
                        nuevo = float(parts[1])
                        with shared_data_lock:
                            bot_params['STOP_LOSS_PORCENTAJE'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ STOP LOSS FIJO a {nuevo:.4f}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_sl_fijo <decimal_ej_0.02>")

                elif command == "/set_tsl":
                    if len(parts) == 2:
                        nuevo = float(parts[1])
                        with shared_data_lock:
                            bot_params['TRAILING_STOP_PORCENTAJE'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ TRAILING STOP a {nuevo:.4f}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_tsl <decimal_ej_0.015>")

                elif command == "/set_breakeven_porcentaje":
                    if len(parts) == 2:
                        nuevo = float(parts[1])
                        with shared_data_lock:
                            bot_params['BREAKEVEN_PORCENTAJE'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ BREAKEVEN a {nuevo:.4f}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_breakeven_porcentaje <decimal_ej_0.005>")

                # ---------- 2. PARÁMETROS DE INDICADORES ----------
                elif command == "/set_ema_corta_periodo":
                    if len(parts) == 2:
                        nuevo = int(parts[1])
                        with shared_data_lock:
                            bot_params['EMA_CORTA_PERIODO'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ EMA CORTA período a {nuevo}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_ema_corta_periodo <entero>")

                elif command == "/set_ema_media_periodo":
                    if len(parts) == 2:
                        nuevo = int(parts[1])
                        with shared_data_lock:
                            bot_params['EMA_MEDIA_PERIODO'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ EMA MEDIA período a {nuevo}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_ema_media_periodo <entero>")

                elif command == "/set_ema_larga_periodo":
                    if len(parts) == 2:
                        nuevo = int(parts[1])
                        with shared_data_lock:
                            bot_params['EMA_LARGA_PERIODO'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ EMA LARGA período a {nuevo}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_ema_larga_periodo <entero>")

                elif command == "/set_rsi_periodo":
                    if len(parts) == 2:
                        nuevo = int(parts[1])
                        with shared_data_lock:
                            bot_params['RSI_PERIODO'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ RSI período a {nuevo}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_rsi_periodo <entero>")

                elif command == "/set_rsi_umbral":
                    if len(parts) == 2:
                        nuevo = int(parts[1])
                        with shared_data_lock:
                            bot_params['RSI_UMBRAL_SOBRECOMPRA'] = nuevo
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"✅ RSI umbral sobrecompra a {nuevo}")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_rsi_umbral <entero>")

                # ---------- 3. PARÁMETROS DE RANGO ----------
                elif command == "/set_rango_params":
                    if len(parts) == 3:
                        try:
                            periodo = int(parts[1])
                            umbral = float(parts[2])
                            with shared_data_lock:
                                bot_params['RANGO_PERIODO_ANALISIS'] = periodo
                                bot_params['RANGO_UMBRAL_ATR'] = umbral
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                f"✅ RANGO período={periodo}, umbral={umbral}")
                        except ValueError:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                "❌ Uso: /set_rango_params <periodo> <umbral>")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_rango_params <periodo> <umbral>")

                elif command == "/set_rango_rsi":
                    if len(parts) == 3:
                        try:
                            sv = int(parts[1])
                            sc = int(parts[2])
                            with shared_data_lock:
                                bot_params['RANGO_RSI_SOBREVENTA'] = sv
                                bot_params['RANGO_RSI_SOBRECOMPRA'] = sc
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                f"✅ RSI rango → sobreventa={sv}, sobrecompra={sc}")
                        except ValueError:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                "❌ Uso: /set_rango_rsi <sobreventa> <sobrecompra>")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /set_rango_rsi <sobreventa> <sobrecompra>")

                elif command == "/toggle_rango":
                    with shared_data_lock:
                        bot_params['RANGO_OPERAR'] = not bot_params.get(
                            'RANGO_OPERAR', True)
                        config_manager.save_parameters(bot_params)
                    estado = "ACTIVADO" if bot_params['RANGO_OPERAR'] else "DESACTIVADO"
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        f"✅ Operar en rango lateral {estado}")

                # ---------- 4. COMANDOS CLÁSICOS (sin cambios) ----------
                elif command == "/start" or command == "/menu":
                    telegram_handler.send_keyboard_menu(
                        TELEGRAM_BOT_TOKEN, chat_id, "¡Hola! Selecciona una opción o usa /help")

                elif command == "/hide_menu":
                    telegram_handler.remove_keyboard_menu(
                        TELEGRAM_BOT_TOKEN, chat_id)

                elif command == "/get_params":
                    with shared_data_lock:
                        msg = "<b>Parámetros actuales:</b>\n"
                        for k, v in bot_params.items():
                            if isinstance(v, float) and 'PORCENTAJE' in k.upper():
                                msg += f"- {k}: {v:.4f}\n"
                            else:
                                msg += f"- {k}: {v}\n"
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)

                elif command == "/csv":
                    with shared_data_lock:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "Generando CSV...")
                        reporting_manager.generar_y_enviar_csv_ahora(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

                elif command == "/beneficio":
                    with shared_data_lock:
                        reporting_manager.send_beneficio_message(
                            client, bot_params.get(
                                'TOTAL_BENEFICIO_ACUMULADO', 0.0),
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

                elif command == "/help":
                    telegram_handler.send_help_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

                elif command == "/vender":
                    if len(parts) == 2:
                        symbol_to_sell = parts[1].upper()
                        if symbol_to_sell in SYMBOLS:
                            with shared_data_lock:
                                trading_logic.vender_por_comando(
                                    client, symbol_to_sell, posiciones_abiertas,
                                    transacciones_diarias, TELEGRAM_BOT_TOKEN,
                                    TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE,
                                    bot_params.get(
                                        'TOTAL_BENEFICIO_ACUMULADO', 0.0),
                                    bot_params, config_manager)
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                f"❌ Símbolo {symbol_to_sell} no reconocido")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            "❌ Uso: /vender <SIMBOLO_USDT>")

                elif command == "/reset_beneficio":
                    with shared_data_lock:
                        bot_params['TOTAL_BENEFICIO_ACUMULADO'] = 0.0
                        config_manager.save_parameters(bot_params)
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        "✅ Beneficio acumulado reseteado a 0")

                elif command == "/posiciones_actuales":
                    with shared_data_lock:
                        telegram_handler.send_current_positions_summary(
                            client, posiciones_abiertas,
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

                elif command == "/analisis":
                    telegram_handler.send_inline_url_button(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        "Ir al análisis",
                        "https://automecanicbibotuno.netlify.app")

                else:
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        "Comando desconocido. Usa /help para ver los disponibles.")

            except ValueError:
                telegram_handler.send_telegram_message(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    "❌ Valor inválido. Asegúrate de usar números correctos.")
            except Exception as ex:
                logging.error(
                    f"Error procesando comando '{text}': {ex}", exc_info=True)
                telegram_handler.send_telegram_message(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    f"❌ Error interno al procesar comando: {ex}")


def enviar_resumen_telegram(resumen_dict, saldo_usdt, beneficio):
    """
    Envía un resumen compacto al chat de Telegram.
    """
    # Construimos el mensaje
    msg = "📊 <b>Resumen del ciclo:</b>\n"
    for symbol, data in resumen_dict.items():
        estado = "📈 TENDENCIA" if not data['en_rango'] else "🔀 RANGO"
        msg += f"• {symbol}: {estado} | ADX: {data['adx']:.1f} | Ancho: {data['band_width']:.3f}\n"

        msg += f"\n💰 <b>Saldo USDT:</b> {saldo_usdt:.2f}\n"
        msg += f"📈 <b>Beneficio acumulado:</b> {beneficio:.2f} USDT\n"
        msg += f"⏳ <b>Próxima revisión:</b> {bot_params['INTERVALO']}s"

    telegram_handler.send_telegram_message(
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, msg)


def telegram_listener(stop_event):
    while not stop_event.is_set():
        try:
            handle_telegram_commands()
            time.sleep(TELEGRAM_LISTEN_INTERVAL)
        except Exception as e:
            logging.error(f"Error hilo Telegram: {e}")

# ------------------------------------------------------------------
#  FUNCIÓN INDICADORES (nueva)
# ------------------------------------------------------------------


def indicadores(symbol):
    """Retorna precio, rsi, ema9, ema21, vol_ratio"""
    klines = client.get_klines(
        symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
    closes = np.array([float(k[4]) for k in klines])
    vols = np.array([float(k[5]) for k in klines])
    rsi = talib.RSI(closes, timeperiod=14)[-1]
    ema_fast = talib.EMA(closes, timeperiod=cfg(symbol)["ema_fast"])[-1]
    ema_slow = talib.EMA(closes, timeperiod=cfg(symbol)["ema_slow"])[-1]
    vol_ratio = vols[-1] / (np.mean(vols[-20:]) + 1e-8)
    price = closes[-1]
    return price, rsi, ema_fast, ema_slow, vol_ratio


def main():
    """
    Función principal que inicia el bot y maneja el ciclo de trading.
    """
    global last_trading_check_time, ultima_fecha_informe_enviado

    # Iniciar el cliente de Binance
    logging.info("Iniciando cliente Binance...")
    client.ping()  # Verifica la conexión

    # Cargar posiciones abiertas desde archivo
    logging.info("Cargando posiciones abiertas...")
    global posiciones_abiertas
    posiciones_abiertas = position_manager.load_open_positions(
        STOP_LOSS_PORCENTAJE)

    # Iniciar el manejador de comandos Telegram
    logging.info("Iniciando manejador de comandos Telegram...")
    telegram_handler.set_telegram_commands_menu(TELEGRAM_BOT_TOKEN)
    logging.info("Bot iniciado. Esperando comandos y monitoreando mercado...")

    telegram_stop_event = threading.Event()
    telegram_thread = threading.Thread(
        target=telegram_listener, args=(telegram_stop_event,))
    telegram_thread.start()

    try:
        while True:
            start_time_cycle = time.time()

            # --------- INFORME DIARIO ----------
            hoy = time.strftime("%Y-%m-%d")
            if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
                if ultima_fecha_informe_enviado is not None:
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        f"📊 Preparando informe del día {ultima_fecha_informe_enviado}")
                    reporting_manager.generar_y_enviar_csv_ahora(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                ultima_fecha_informe_enviado = hoy
                with shared_data_lock:
                    transacciones_diarias.clear()

            # --------- LIMPIEZA PROACTIVA ----------
            with shared_data_lock:
                symbols_to_remove = []
                for symbol, data in list(posiciones_abiertas.items()):
                    if symbol not in SYMBOLS:
                        symbols_to_remove.append(symbol)
                        continue
                    base_asset = symbol.replace("USDT", "")
                    actual_balance = binance_utils.obtener_saldo_moneda(
                        client, base_asset)
                    info = client.get_symbol_info(symbol)
                    min_qty = 0.0
                    for f in info['filters']:
                        if f['filterType'] == 'LOT_SIZE':
                            min_qty = float(f['minQty'])
                            break
                    threshold = max(min_qty, 1e-8)
                    if actual_balance < threshold:
                        symbols_to_remove.append(symbol)
                for symbol in symbols_to_remove:
                    if symbol in posiciones_abiertas:
                        del posiciones_abiertas[symbol]
                        position_manager.save_open_positions_debounced(
                            posiciones_abiertas)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"🗑️ Posición {symbol} eliminada (saldo insuficiente)")

            # --------- CICLO DE TRADING ----------
            if (time.time() - last_trading_check_time) >= INTERVALO:
                logging.info("Iniciando ciclo de trading principal...")
                general_message = ""

                with shared_data_lock:
                    saldo_usdt_global = binance_utils.obtener_saldo_moneda(
                        client, "USDT")
                    total_capital_usdt_global = binance_utils.get_total_capital_usdt(
                        client, posiciones_abiertas)
                    eur_usdt_rate = binance_utils.obtener_precio_eur(client)
                    total_capital_eur_global = (
                        total_capital_usdt_global / eur_usdt_rate
                        if eur_usdt_rate and eur_usdt_rate > 0 else 0
                    )

                for symbol in SYMBOLS:
                    base = symbol.replace("USDT", "")
                    saldo_base = binance_utils.obtener_saldo_moneda(
                        client, base)
                    precio_actual = binance_utils.obtener_precio_actual(
                        client, symbol)

                    # ---------- PARÁMETROS POR SÍMBOLO ----------
                    cf = bot_params.get("symbols", {}).get(symbol, {
                        "stop_loss_pct": STOP_LOSS_PORCENTAJE,
                        "take_profit_pct": TAKE_PROFIT_PORCENTAJE,
                        "trailing_stop_pct": TRAILING_STOP_PORCENTAJE,
                        "breakeven_pct": BREAKEVEN_PORCENTAJE,
                        "rsi_buy": RSI_UMBRAL_SOBRECOMPRA,
                        "volume_factor": 1.5,
                        "ema_fast": EMA_CORTA_PERIODO,
                        "ema_slow": EMA_MEDIA_PERIODO
                    })

                    # ----------------------------------
                    # DETECCIÓN Y OPERACIÓN EN RANGO
                    # ----------------------------------
                    rango_activo = bot_params.get('RANGO_OPERAR', True)
                    if rango_activo:
                        en_rango, soporte, resistencia = detectar_rango_lateral(
                            client,
                            symbol,
                            periodo=bot_params.get(
                                'RANGO_PERIODO_ANALISIS', 20),
                            adx_umbral=bot_params.get('RANGO_ADX_UMBRAL', 25),
                            band_width_max=bot_params.get(
                                'RANGO_BAND_WIDTH_MAX', 0.05)
                        )
                        if en_rango:
                            senal_rango = estrategia_rango(
                                client,
                                symbol,
                                soporte,
                                resistencia,
                                rsi=trading_logic.calcular_ema_rsi(
                                    client, symbol,
                                    EMA_CORTA_PERIODO,
                                    EMA_MEDIA_PERIODO,
                                    EMA_LARGA_PERIODO,
                                    RSI_PERIODO
                                )[3],
                                rsi_sobreventa=bot_params.get(
                                    'RANGO_RSI_SOBREVENTA', 30),
                                rsi_sobrecompra=bot_params.get(
                                    'RANGO_RSI_SOBRECOMPRA', 70)
                            )
                            if senal_rango == 'COMPRA' and symbol not in posiciones_abiertas and saldo_usdt_global > 10:
                                cantidad = trading_logic.calcular_cantidad_a_comprar(
                                    client, saldo_usdt_global, precio_actual,
                                    cf["stop_loss_pct"], symbol,
                                    RIESGO_POR_OPERACION_PORCENTAJE, total_capital_usdt_global
                                )
                                if cantidad > 0:
                                    with shared_data_lock:
                                        orden = trading_logic.comprar(
                                            client, symbol, cantidad, posiciones_abiertas,
                                            cf["stop_loss_pct"], transacciones_diarias,
                                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                            OPEN_POSITIONS_FILE
                                        )
                                    if orden:
                                        general_message += f"🟢 COMPRA RANGO {symbol}\n"
                                    continue

                            elif senal_rango == 'VENTA' and symbol in posiciones_abiertas:
                                cantidad_vender = binance_utils.ajustar_cantidad(
                                    binance_utils.obtener_saldo_moneda(
                                        client, base),
                                    binance_utils.get_step_size(client, symbol)
                                )
                                if cantidad_vender > 0:
                                    with shared_data_lock:
                                        orden = trading_logic.vender(
                                            client, symbol, cantidad_vender,
                                            posiciones_abiertas,
                                            bot_params.get(
                                                'TOTAL_BENEFICIO_ACUMULADO', 0.0),
                                            bot_params, transacciones_diarias,
                                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                            OPEN_POSITIONS_FILE, config_manager,
                                            motivo_venta="VENTA EN RANGO"
                                        )
                                        bot_params['TOTAL_BENEFICIO_ACUMULADO'] = bot_params.get(
                                            'TOTAL_BENEFICIO_ACUMULADO', 0.0)
                                        config_manager.save_parameters(
                                            bot_params)
                                    if orden:
                                        general_message += f"🔴 VENTA RANGO {symbol}\n"
                                    continue

                    # ----------------------------------
                    # OPERACIÓN EN TENDENCIA
                    # ----------------------------------
                    ema_corta, ema_media, ema_larga, rsi = trading_logic.calcular_ema_rsi(
                        client, symbol,
                        cf["ema_fast"],
                        cf["ema_slow"],
                        EMA_LARGA_PERIODO,
                        RSI_PERIODO
                    )
                    if any(v is None for v in (ema_corta, ema_media, ema_larga, rsi)):
                        continue

                    # Filtro de volumen
                    klines = client.get_klines(
                        symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=20)
                    vol_ratio = float(
                        klines[-1][5]) / (sum(float(k[5]) for k in klines[-20:]) / 20 + 1e-8)

                    tendencia_alcista = (
                        precio_actual > ema_corta > ema_media > ema_larga)

                    comprar_cond = (
                        saldo_usdt_global > 10 and
                        tendencia_alcista and
                        rsi < cf["rsi_buy"] and
                        vol_ratio > cf["volume_factor"] and
                        symbol not in posiciones_abiertas
                    )
                    if comprar_cond:
                        cantidad = trading_logic.calcular_cantidad_a_comprar(
                            client, saldo_usdt_global, precio_actual,
                            cf["stop_loss_pct"], symbol,
                            RIESGO_POR_OPERACION_PORCENTAJE, total_capital_usdt_global
                        )
                        if cantidad > 0:
                            with shared_data_lock:
                                orden = trading_logic.comprar(
                                    client, symbol, cantidad, posiciones_abiertas,
                                    cf["stop_loss_pct"], transacciones_diarias,
                                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                    OPEN_POSITIONS_FILE
                                )
                            if orden:
                                general_message += f"✅ COMPRA TENDENCIA {symbol}\n"

                    elif symbol in posiciones_abiertas:
                        pos = posiciones_abiertas[symbol]
                        precio_compra = pos['precio_compra']
                        max_precio_alcanzado = pos['max_precio_alcanzado']
                        sl_actual = pos.get('stop_loss_fijo_nivel_actual',
                                            precio_compra * (1 - cf["stop_loss_pct"]))
                        tp = precio_compra * (1 + cf["take_profit_pct"])
                        tsl = max_precio_alcanzado * \
                            (1 - cf["trailing_stop_pct"])

                        if precio_actual > max_precio_alcanzado:
                            with shared_data_lock:
                                posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                                position_manager.save_open_positions_debounced(
                                    posiciones_abiertas)

                        vender_ahora = False
                        motivo = ""
                        if precio_actual >= tp:
                            vender_ahora, motivo = True, "TAKE PROFIT"
                        elif precio_actual <= sl_actual:
                            vender_ahora, motivo = True, "STOP LOSS"
                        elif precio_actual <= tsl and precio_actual > precio_compra:
                            vender_ahora, motivo = True, "TRAILING STOP"

                        if vender_ahora:
                            cantidad_vender = binance_utils.ajustar_cantidad(
                                binance_utils.obtener_saldo_moneda(
                                    client, base),
                                binance_utils.get_step_size(client, symbol)
                            )
                            if cantidad_vender > 0:
                                with shared_data_lock:
                                    orden = trading_logic.vender(
                                        client, symbol, cantidad_vender,
                                        posiciones_abiertas,
                                        bot_params.get(
                                            'TOTAL_BENEFICIO_ACUMULADO', 0.0),
                                        bot_params, transacciones_diarias,
                                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                        OPEN_POSITIONS_FILE, config_manager,
                                        motivo
                                    )
                                    bot_params['TOTAL_BENEFICIO_ACUMULADO'] = bot_params.get(
                                        'TOTAL_BENEFICIO_ACUMULADO', 0.0)
                                    config_manager.save_parameters(bot_params)
                                if orden:
                                    general_message += f"🔴 VENTA {motivo} {symbol}\n"

                # Resumen enviado por Telegram
                # Construimos el resumen compacto
                # ---------- CONSTRUIR resumen_dict SIEMPRE COMPLETO ----------
                # ---------- ENVÍO DEL INFORME DETALLADO POR SÍMBOLO ----------
                general_message = ""
                with shared_data_lock:
                    saldo_usdt_global = binance_utils.obtener_saldo_moneda(
                        client, "USDT")
                    total_capital_usdt_global = binance_utils.get_total_capital_usdt(
                        client, posiciones_abiertas)
                    eur_usdt_rate = binance_utils.obtener_precio_eur(client)
                    total_capital_eur_global = (
                        total_capital_usdt_global / eur_usdt_rate
                        if eur_usdt_rate and eur_usdt_rate > 0 else 0
                    )

                    for symbol in SYMBOLS:
                        base = symbol.replace("USDT", "")
                        precio_actual = binance_utils.obtener_precio_actual(
                            client, symbol)

                        # Indicadores
                        ema_c, ema_m, ema_l, rsi = trading_logic.calcular_ema_rsi(
                            client, symbol, EMA_CORTA_PERIODO, EMA_MEDIA_PERIODO,
                            EMA_LARGA_PERIODO, RSI_PERIODO)

                        # Tendencia
                        if ema_c is None or ema_m is None or ema_l is None or rsi is None:
                            continue
                        tend_emoji = "📈"
                        tend_text = "Alcista"
                        if ema_l > ema_m > ema_c:
                            tend_emoji = "📉"
                            tend_text = "Bajista"
                        elif abs(ema_l - ema_c) < 0.01 * ema_c:
                            tend_emoji = "ǁ"
                            tend_text = "Lateral/Consolidación"

                        # Mensaje por símbolo
                        msg = (
                            f"📊 <b>{symbol}</b>\n"
                            f"Precio actual: {precio_actual:.2f} USDT\n"
                            f"EMA Corta ({EMA_CORTA_PERIODO}m): {ema_c:.2f}\n"
                            f"EMA Media ({EMA_MEDIA_PERIODO}m): {ema_m:.2f}\n"
                            f"EMA Larga ({EMA_LARGA_PERIODO}m): {ema_l:.2f}\n"
                            f"RSI ({RSI_PERIODO}m): {rsi:.2f}\n"
                            f"Tend: {tend_emoji} <b>{tend_text}</b>"
                        )

                        # Datos de posición
                        if symbol in posiciones_abiertas:
                            pos = posiciones_abiertas[symbol]
                            precio_entrada = pos['precio_compra']
                            tp = precio_entrada * (1 + TAKE_PROFIT_PORCENTAJE)
                            sl = pos.get('stop_loss_fijo_nivel_actual',
                                         precio_entrada * (1 - STOP_LOSS_PORCENTAJE))
                            max_alc = pos['max_precio_alcanzado']
                            tsl = max_alc * (1 - TRAILING_STOP_PORCENTAJE)
                            invertido = pos['cantidad_base'] * precio_entrada

                        msg += (
                            f"\nPosición:\n"
                            f" Entrada: {precio_entrada:.2f} | Actual: {precio_actual:.2f}\n"
                            f"TP: {tp:.2f} | SL Fijo: {sl:.2f}\n"
                            f"Max Alcanzado: {max_alc:.2f} | TSL: {tsl:.2f}\n"
                            f"Saldo USDT Invertido (Entrada): {invertido:.2f}\n"
                        )
                        eur_invertido = invertido / (eur_usdt_rate or 1)
                        msg += f"SEI: {eur_invertido:.2f}"

                        msg += (
                            f"\n💰 Saldo USDT: {saldo_usdt_global:.2f}\n"
                            f"💲 Capital Total (USDT): {total_capital_usdt_global:.2f}\n"
                            f"💶 Capital Total (EUR): {total_capital_eur_global:.2f}\n"
                        )
                        general_message += msg + "\n\n"

                    try:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, general_message)
                    except Exception as e:
                        logging.error(f"Fallo al enviar informe: {e}")
                # Esperar hasta siguiente ciclo
                sleep_duration = max(
                    0, INTERVALO - (time.time() - start_time_cycle))
                print(f"⏳ Próxima revisión en {sleep_duration:.0f}s")
                time.sleep(sleep_duration)

    except KeyboardInterrupt:
        logging.info("KeyboardInterrupt detectado. Terminando bot...")
        telegram_stop_event.set()
        telegram_thread.join()
    except Exception as e:
        logging.error(f"Error crítico en bot.py: {e}", exc_info=True)
        with shared_data_lock:
            telegram_handler.send_telegram_message(
                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                f"❌ Error crítico: {e}\n{binance_utils.obtener_saldos_formateados(client, posiciones_abiertas)}")
        telegram_stop_event.set()
        telegram_thread.join()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    logging.info("Iniciando bot de trading...")
    main()
