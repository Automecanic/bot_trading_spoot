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
import numpy as np
import pandas as pd  # Reemplazamos talib por pandas

# ------------- IMPORTS DE MÓDULOS PROPIOS -------------
import config_manager
import position_manager
import telegram_handler
import binance_utils
import trading_logic
import firestore_utils
import reporting_manager
import ai_optimizer
from range_trading import detectar_rango_lateral, estrategia_rango

# Importaciones para Telegram y Scheduler
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update
from apscheduler.schedulers.background import BackgroundScheduler
from pytz import timezone
import pytz

# ----------------- CONFIGURACIÓN LOGGING -----------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# ----------------- FUNCIONES TÉCNICAS ALTERNATIVAS (sin talib) -----------------


def calculate_ema(prices, period):
    """Calcula EMA usando pandas"""
    return pd.Series(prices).ewm(span=period, adjust=False).mean().iloc[-1]


def calculate_rsi(prices, period=14):
    """Calcula RSI usando pandas"""
    delta = pd.Series(prices).diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs.iloc[-1]))


# ----------------- VARIABLES GLOBALES -----------------
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET")
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

# Cargar parámetros IA si existen
try:
    with open('ai_params.json', 'r') as f:
        ia_params = json.load(f)
        bot_params.update(ia_params)
        logging.info("✅ Parámetros IA cargados al inicio.")
except FileNotFoundError:
    logging.info("ℹ️ No hay parámetros IA previos, se usarán los por defecto.")

# Asegurar persistencia
config_manager.save_parameters(bot_params)

# ----------------- CLIENTE BINANCE -----------------
client = Client(API_KEY, API_SECRET, testnet=True,
                requests_params={'timeout': 30})
client.API_URL = 'https://testnet.binance.vision/api'

# ----------------- VARIABLES DE CONTROL -----------------
posiciones_abiertas = position_manager.load_open_positions(
    STOP_LOSS_PORCENTAJE)
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


async def handle_telegram_commands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Versión PTB v20 que maneja todos los comandos de Telegram
    """
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    # Seguridad: solo chat autorizado
    if chat_id != TELEGRAM_CHAT_ID:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⚠️ Comando recibido de chat no autorizado: {chat_id}")
        return

    # Parseo de comandos
    parts = text.split()
    command = parts[0].lower()

    # Variables globales
    global bot_params, posiciones_abiertas, transacciones_diarias, \
        INTERVALO, RIESGO_POR_OPERACION_PORCENTAJE, TAKE_PROFIT_PORCENTAJE, \
        STOP_LOSS_PORCENTAJE, TRAILING_STOP_PORCENTAJE, EMA_CORTA_PERIODO, \
        EMA_MEDIA_PERIODO, EMA_LARGA_PERIODO, RSI_PERIODO, RSI_UMBRAL_SOBRECOMPRA, \
        BREAKEVEN_PORCENTAJE

    try:
        # ---------- 1. PARÁMETROS DE ESTRATEGIA ----------
        if command == "/set_intervalo":
            if len(parts) == 2:
                nuevo = int(parts[1])
                with shared_data_lock:
                    bot_params['INTERVALO'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ INTERVALO actualizado a {nuevo} segundos")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_intervalo <segundos_entero>")

        elif command == "/set_riesgo":
            if len(parts) == 2:
                nuevo = float(parts[1])
                with shared_data_lock:
                    bot_params['RIESGO_POR_OPERACION_PORCENTAJE'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ RIESGO por operación a {nuevo:.4f}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_riesgo <decimal_ej_0.01>")

        elif command == "/set_tp":
            if len(parts) == 2:
                nuevo = float(parts[1])
                with shared_data_lock:
                    bot_params['TAKE_PROFIT_PORCENTAJE'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ TAKE PROFIT a {nuevo:.4f}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_tp <decimal_ej_0.03>")

        elif command == "/set_sl_fijo":
            if len(parts) == 2:
                nuevo = float(parts[1])
                with shared_data_lock:
                    bot_params['STOP_LOSS_PORCENTAJE'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ STOP LOSS FIJO a {nuevo:.4f}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_sl_fijo <decimal_ej_0.02>")

        elif command == "/set_tsl":
            if len(parts) == 2:
                nuevo = float(parts[1])
                with shared_data_lock:
                    bot_params['TRAILING_STOP_PORCENTAJE'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ TRAILING STOP a {nuevo:.4f}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_tsl <decimal_ej_0.015>")

        elif command == "/optimizar_ahora":
            ejecutar_optimizacion_ia()
            await context.bot.send_message(
                chat_id=chat_id,
                text="✅ Optimización IA iniciada")

        elif command == "/set_breakeven_porcentaje":
            if len(parts) == 2:
                nuevo = float(parts[1])
                with shared_data_lock:
                    bot_params['BREAKEVEN_PORCENTAJE'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ BREAKEVEN a {nuevo:.4f}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_breakeven_porcentaje <decimal_ej_0.005>")

        # ---------- 2. PARÁMETROS DE INDICADORES ----------
        elif command == "/set_ema_corta_periodo":
            if len(parts) == 2:
                nuevo = int(parts[1])
                with shared_data_lock:
                    bot_params['EMA_CORTA_PERIODO'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ EMA CORTA período a {nuevo}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_ema_corta_periodo <entero>")

        elif command == "/set_ema_media_periodo":
            if len(parts) == 2:
                nuevo = int(parts[1])
                with shared_data_lock:
                    bot_params['EMA_MEDIA_PERIODO'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ EMA MEDIA período a {nuevo}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_ema_media_periodo <entero>")

        elif command == "/set_ema_larga_periodo":
            if len(parts) == 2:
                nuevo = int(parts[1])
                with shared_data_lock:
                    bot_params['EMA_LARGA_PERIODO'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ EMA LARGA período a {nuevo}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_ema_larga_periodo <entero>")

        elif command == "/set_rsi_periodo":
            if len(parts) == 2:
                nuevo = int(parts[1])
                with shared_data_lock:
                    bot_params['RSI_PERIODO'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ RSI período a {nuevo}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_rsi_periodo <entero>")

        elif command == "/set_rsi_umbral":
            if len(parts) == 2:
                nuevo = int(parts[1])
                with shared_data_lock:
                    bot_params['RSI_UMBRAL_SOBRECOMPRA'] = nuevo
                    config_manager.save_parameters(bot_params)
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ RSI umbral sobrecompra a {nuevo}")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_rsi_umbral <entero>")

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
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ RANGO período={periodo}, umbral={umbral}")
                except ValueError:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Uso: /set_rango_params <periodo> <umbral>")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_rango_params <periodo> <umbral>")

        elif command == "/set_rango_rsi":
            if len(parts) == 3:
                try:
                    sv = int(parts[1])
                    sc = int(parts[2])
                    with shared_data_lock:
                        bot_params['RANGO_RSI_SOBREVENTA'] = sv
                        bot_params['RANGO_RSI_SOBRECOMPRA'] = sc
                        config_manager.save_parameters(bot_params)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ RSI rango → sobreventa={sv}, sobrecompra={sc}")
                except ValueError:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text="❌ Uso: /set_rango_rsi <sobreventa> <sobrecompra>")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /set_rango_rsi <sobreventa> <sobrecompra>")

        elif command == "/toggle_rango":
            with shared_data_lock:
                bot_params['RANGO_OPERAR'] = not bot_params.get(
                    'RANGO_OPERAR', True)
                config_manager.save_parameters(bot_params)
            estado = "ACTIVADO" if bot_params['RANGO_OPERAR'] else "DESACTIVADO"
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ Operar en rango lateral {estado}")

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
            await context.bot.send_message(
                chat_id=chat_id,
                text=msg,
                parse_mode='HTML')

        elif command == "/csv":
            with shared_data_lock:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="Generando CSV...")
                reporting_manager.generar_y_enviar_csv_ahora(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

        elif command == "/beneficio":
            db = firestore_utils.get_firestore_db()
            beneficio_total = 0.0
            if db:
                try:
                    docs = db.collection(
                        firestore_utils.FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
                    for doc in docs:
                        trans = doc.to_dict()
                        beneficio_total += trans.get('ganancia_usdt', 0.0)
                except Exception as e:
                    logging.error(f"Error calculando beneficio total: {e}")

                eur_rate = binance_utils.obtener_precio_eur(client)
                beneficio_eur = beneficio_total / eur_rate if eur_rate else 0.0
                emoji = "👍" if beneficio_eur > 0 else "💩"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📈 <b>Beneficio Total Acumulado (TODAS):</b>\n"
                    f"   {emoji} <b>{beneficio_total:.2f} USDT</b>\n"
                    f"   {emoji} <b>{beneficio_eur:.2f} EUR</b>",
                    parse_mode='HTML')

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
                            bot_params.get('TOTAL_BENEFICIO_ACUMULADO', 0.0),
                            bot_params, config_manager)
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"✅ Orden de venta enviada para {symbol_to_sell}")
                else:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"❌ Símbolo {symbol_to_sell} no reconocido")
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="❌ Uso: /vender <SIMBOLO_USDT>")

        elif command == "/beneficio_diario":
            hoy = datetime.now().strftime("%Y-%m-%d")
            beneficio_dia = 0.0
            db = firestore_utils.get_firestore_db()
            if db:
                try:
                    docs = db.collection(
                        firestore_utils.FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
                    for doc in docs:
                        trans = doc.to_dict()
                        if trans.get('timestamp', '').startswith(hoy):
                            beneficio_dia += trans.get('ganancia_usdt', 0.0)
                except Exception as e:
                    logging.error(f"Error calculando beneficio diario: {e}")

                eur_rate = binance_utils.obtener_precio_eur(client)
                beneficio_eur = beneficio_dia / eur_rate if eur_rate else 0.0
                emoji = "👍" if beneficio_eur > 0 else "💩"
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"📊 <b>Beneficio del día {hoy}</b>:\n"
                    f"  {emoji}  <b>{beneficio_dia:.2f} USDT</b>\n"
                    f"  {emoji}  <b>{beneficio_eur:.2f} EUR</b>",
                    parse_mode='HTML')

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
            await context.bot.send_message(
                chat_id=chat_id,
                text="Comando desconocido. Usa /help para ver los disponibles.")

    except ValueError:
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Valor inválido. Asegúrate de usar números correctos.")
    except Exception as ex:
        logging.error(
            f"Error procesando comando '{text}': {ex}", exc_info=True)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ Error interno al procesar comando: {ex}")

# ------------------------------------------------------------------
#  FUNCIÓN INDICADORES (ahora sin talib)
# ------------------------------------------------------------------


def indicadores(symbol):
    """Retorna precio, rsi, ema9, ema21, vol_ratio"""
    klines = client.get_klines(
        symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
    closes = np.array([float(k[4]) for k in klines])
    vols = np.array([float(k[5]) for k in klines])

    # Calcular indicadores usando pandas en lugar de talib
    rsi = calculate_rsi(closes, 14)
    ema_fast = calculate_ema(closes, cfg(symbol)["ema_fast"])
    ema_slow = calculate_ema(closes, cfg(symbol)["ema_slow"])
    vol_ratio = vols[-1] / (np.mean(vols[-20:]) + 1e-8)
    price = closes[-1]

    return price, rsi, ema_fast, ema_slow, vol_ratio

# ------------------------------------------------------------------
#  FUNCIONES DE OPTIMIZACIÓN Y REPORTING
# ------------------------------------------------------------------


def ejecutar_optimizacion_ia():
    """Genera CSV, ejecuta optimización IA y envía informe."""
    db = firestore_utils.get_firestore_db()
    if not db:
        telegram_handler.send_telegram_message(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
            "❌ No se pudo conectar a Firestore para optimizar.")
        return

    FIRESTORE_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/transactions_history"
    docs = db.collection(FIRESTORE_PATH).stream()
    data = [
        {
            'TAKE_PROFIT_PORCENTAJE': d.get('TAKE_PROFIT_PORCENTAJE', 0.03),
            'TRAILING_STOP_PORCENTAJE': d.get('TRAILING_STOP_PORCENTAJE', 0.015),
            'RIESGO_POR_OPERACION_PORCENTAJE': d.get('RIESGO_POR_OPERACION_PORCENTAJE', 0.01),
            'ganancia_usdt': d.get('ganancia_usdt', 0)
        }
        for doc in docs
        if (d := doc.to_dict())
    ]
    if not data:
        telegram_handler.send_telegram_message(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
            "⚠️ No hay transacciones para optimizar.")
        return
    pd.DataFrame(data).to_csv('transacciones_historico.csv', index=False)
    ai_optimizer.run()
    telegram_handler.send_telegram_message(
        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
        "✅ Optimización IA ejecutada.")


def generar_csv_desde_firestore():
    """Genera transacciones_historico.csv desde Firestore."""
    db = firestore_utils.get_firestore_db()
    if not db:
        logging.error("❌ No se pudo conectar a Firestore para generar CSV")
        return

    FIRESTORE_TRANSACTIONS_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/transactions_history"
    docs = db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()

    data = []
    for doc in docs:
        d = doc.to_dict()
        data.append({
            'TAKE_PROFIT_PORCENTAJE': d.get('TAKE_PROFIT_PORCENTAJE', 0.03),
            'TRAILING_STOP_PORCENTAJE': d.get('TRAILING_STOP_PORCENTAJE', 0.015),
            'RIESGO_POR_OPERACION_PORCENTAJE': d.get('RIESGO_POR_OPERACION_PORCENTAJE', 0.01),
            'ganancia_usdt': d.get('ganancia_usdt', 0)
        })

    if not data:
        logging.warning("⚠️ No hay transacciones para generar CSV")
        return

    pd.DataFrame(data).to_csv('transacciones_historico.csv', index=False)
    logging.info(f"✅ CSV generado con {len(data)} transacciones")

# ------------------------------------------------------------------
#  FUNCIÓN PRINCIPAL DEL BOT
# ------------------------------------------------------------------


def main():
    # 1. Logs iniciales
    logging.info("🚀 Iniciando bot...")

    # 2. Verificar credenciales
    if not all([API_KEY, API_SECRET, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.error("❌ Faltan variables de entorno necesarias")
        return

    # 3. Scheduler IA (una sola vez)
    scheduler = BackgroundScheduler(timezone=pytz.UTC)
    scheduler.add_job(
        ejecutar_optimizacion_ia,  # ✅ Corregido: referencia directa a la función
        trigger='cron',
        hour=2,
        minute=0,
        timezone=pytz.UTC
    )
    scheduler.start()
    logging.info("📅 Scheduler IA activado a las 02:00 UTC")

    # 4. Arrancar el trading en otro hilo
    trading_thread = threading.Thread(target=trading_loop, daemon=True)
    trading_thread.start()
    logging.info("🔄 Trading loop iniciado en hilo separado")

    # 5. Inicializar bot de Telegram
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Añadir manejador para todos los comandos
    application.add_handler(MessageHandler(
        filters.COMMAND, handle_telegram_commands))

    # Añadir manejador para mensajes de texto (no comandos)
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_telegram_commands))

    logging.info("🤖 Bot de Telegram inicializado")

    # 6. Iniciar el bot (esto bloqueará el hilo principal)
    try:
        application.run_polling()
    except Exception as e:
        logging.error(f"❌ Error en el bot de Telegram: {e}", exc_info=True)
    finally:
        scheduler.shutdown()
        logging.info("🛑 Bot detenido")


def trading_loop():
    """Bucle principal de trading"""
    global last_trading_check_time, ultima_fecha_informe_enviado

    logging.info("Iniciando cliente Binance...")
    try:
        client.ping()
        logging.info("✅ Conexión con Binance establecida")
    except Exception as e:
        logging.error(f"❌ Error conectando con Binance: {e}")
        return

    logging.info("Cargando posiciones abiertas...")
    global posiciones_abiertas
    posiciones_abiertas = position_manager.load_open_positions(
        STOP_LOSS_PORCENTAJE)

    try:
        while True:
            start_time_cycle = time.time()

            # 1. Informe diario CSV (solo cuando cambia el día)
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

            # 2. Limpia posiciones con saldo insuficiente
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

            # 3. Ejecutar ciclo de trading si ha pasado el intervalo
            if (time.time() - last_trading_check_time) >= INTERVALO:
                logging.info("Iniciando ciclo de trading principal...")
                last_trading_check_time = time.time()

                # 4. Datos globales (siempre disponibles)
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

                    general_message = (
                        f"📈 Resumen ciclo {datetime.now().strftime('%H:%M:%S')}\n"
                        f"💰 USDT libre: {saldo_usdt_global:.2f}\n"
                        f"💲 Total: {total_capital_usdt_global:.2f} USDT\n"
                        f"💶 Total: {total_capital_eur_global:.2f} EUR\n\n"
                    )

                # 5. Recorre todos los símbolos
                for symbol in SYMBOLS:
                    base = symbol.replace("USDT", "")
                    precio_actual = binance_utils.obtener_precio_actual(
                        client, symbol)

                    # 6. Parámetros personalizados por símbolo
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

                    # 7. Detecta rango lateral
                    rango_activo = bot_params.get('RANGO_OPERAR', True)
                    if rango_activo:
                        en_rango, soporte, resistencia = detectar_rango_lateral(
                            client, symbol,
                            periodo=bot_params.get(
                                'RANGO_PERIODO_ANALISIS', 20),
                            adx_umbral=bot_params.get('RANGO_ADX_UMBRAL', 25),
                            band_width_max=bot_params.get(
                                'RANGO_BAND_WIDTH_MAX', 0.05)
                        )

                        if en_rango:
                            senal_rango = estrategia_rango(
                                client, symbol, soporte, resistencia,
                                rsi=trading_logic.calcular_ema_rsi(
                                    client, symbol,
                                    cf["ema_fast"], cf["ema_slow"],
                                    EMA_LARGA_PERIODO, RSI_PERIODO)[3],
                                rsi_sobreventa=bot_params.get(
                                    'RANGO_RSI_SOBREVENTA', 30),
                                rsi_sobrecompra=bot_params.get(
                                    'RANGO_RSI_SOBRECOMPRA', 70)
                            )

                            # 7.1 Compra en rango
                            if senal_rango == 'COMPRA' and symbol not in posiciones_abiertas and saldo_usdt_global > 10:
                                cantidad = trading_logic.calcular_cantidad_a_comprar(
                                    client, saldo_usdt_global, precio_actual,
                                    cf["stop_loss_pct"], symbol,
                                    RIESGO_POR_OPERACION_PORCENTAJE, total_capital_usdt_global)
                                if cantidad > 0:
                                    with shared_data_lock:
                                        orden = trading_logic.comprar(
                                            client, symbol, cantidad, posiciones_abiertas,
                                            cf["stop_loss_pct"], transacciones_diarias,
                                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                            OPEN_POSITIONS_FILE)
                                    if orden:
                                        general_message += f"🟢 COMPRA RANGO {symbol}\n"
                                    continue

                            # 7.2 Venta en rango
                            elif senal_rango == 'VENTA' and symbol in posiciones_abiertas:
                                cantidad_vender = binance_utils.ajustar_cantidad(
                                    binance_utils.obtener_saldo_moneda(
                                        client, base),
                                    binance_utils.get_step_size(client, symbol))
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
                                            motivo_venta="VENTA EN RANGO")
                                        bot_params['TOTAL_BENEFICIO_ACUMULADO'] = bot_params.get(
                                            'TOTAL_BENEFICIO_ACUMULADO', 0.0)
                                        config_manager.save_parameters(
                                            bot_params)
                                    if orden:
                                        general_message += f"🔴 VENTA RANGO {symbol}\n"
                                    continue

                    # 8. Operación en tendencia
                    ema_corta, ema_media, ema_larga, rsi = trading_logic.calcular_ema_rsi(
                        client, symbol,
                        cf["ema_fast"], cf["ema_slow"],
                        EMA_LARGA_PERIODO, RSI_PERIODO)

                    if any(v is None for v in (ema_corta, ema_media, ema_larga, rsi)):
                        continue

                    # 9. Filtro de volumen
                    klines = client.get_klines(
                        symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=20)
                    vol_ratio = float(
                        klines[-1][5]) / (sum(float(k[5]) for k in klines[-20:]) / 20 + 1e-8)

                    tendencia_alcista = (
                        precio_actual > ema_corta > ema_media > ema_larga)

                    # 10. Lógica de compra
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
                            RIESGO_POR_OPERACION_PORCENTAJE, total_capital_usdt_global)
                        if cantidad > 0:
                            with shared_data_lock:
                                orden = trading_logic.comprar(
                                    client, symbol, cantidad, posiciones_abiertas,
                                    cf["stop_loss_pct"], transacciones_diarias,
                                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                    OPEN_POSITIONS_FILE)
                            if orden:
                                general_message += f"✅ COMPRA TENDENCIA {symbol}\n"

                    # 11. Lógica de venta
                    elif symbol in posiciones_abiertas:
                        # Implementar lógica de venta en tendencia
                        pass

                # Enviar resumen del ciclo
                if general_message:
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        general_message)

            # Calcular tiempo de espera hasta próximo ciclo
            elapsed = time.time() - start_time_cycle
            sleep_time = max(0, INTERVALO - elapsed)
            time.sleep(sleep_time)

    except Exception as e:
        logging.error(f"❌ Error en trading_loop: {e}", exc_info=True)
        time.sleep(60)  # Esperar antes de reintentar


if __name__ == "__main__":
    main()
