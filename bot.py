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
import logging
import threading
from datetime import datetime, timedelta
import requests
from binance.client import Client
from binance.enums import *
import numpy as np
import talib

# ------------- IMPORTS DE MÓDULOS PROPIOS -------------
import config_manager
import position_manager
import telegram_handler
import binance_utils
import trading_logic
import firestore_utils
import reporting_manager
import ai_optimizer as inteligens  # Importa el módulo de optimización AI
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
# Carga todos los parámetros del bot desde el archivo de configuración o base de datos
bot_params = config_manager.load_parameters()

# Lista de símbolos que el bot monitorea y opera activamente
# Parámetros clásicos de trading: define los pares de trading a seguir
SYMBOLS = ["BTCUSDT", "BNBUSDT", "XLMUSDT", "TRXUSDT",
           "ADAUSDT", "XRPUSDT", "DOGEUSDT", "SOLUSDT", "ETHUSDT"]
# Intervalo (en segundos) entre cada análisis y posible ejecución de operaciones
INTERVALO = bot_params["INTERVALO"]
# Porcentaje del balance a riesgo en cada operación (ej: 0.02 = 2%)
RIESGO_POR_OPERACION_PORCENTAJE = bot_params["RIESGO_POR_OPERACION_PORCENTAJE"]
# Porcentaje de ganancia objetivo (ej: 0.03 = 3%)
TAKE_PROFIT_PORCENTAJE = bot_params["TAKE_PROFIT_PORCENTAJE"]
# Porcentaje de pérdida máx permitida en cada operación (ej: 0.02 = 2%)
STOP_LOSS_PORCENTAJE = bot_params["STOP_LOSS_PORCENTAJE"]
# Trailing stop: mantiene stop loss actualizándose según el precio sube
# Parámetros de las Medias Móviles Exponenciales (EMA) - indicadores de tendencia
# EMA corta: seguimiento rápido, sensible a cambios recientes
EMA_CORTA_PERIODO = bot_params.get("EMA_CORTA_PERIODO", 20)
# EMA media: balance entre sensibilidad y estabilidad
EMA_MEDIA_PERIODO = bot_params.get("EMA_MEDIA_PERIODO", 50)
# EMA larga: detecta tendencia general, menos ruido
EMA_LARGA_PERIODO = bot_params.get("EMA_LARGA_PERIODO", 200)
# Período del RSI (Relative Strength Index) - indica sobrecompra/sobreventa
RSI_PERIODO = bot_params["RSI_PERIODO"]
# Umbral RSI por encima del cual se considera sobrecompra (ej: 70 = RSI > 70)
RSI_UMBRAL_SOBRECOMPRA = bot_params["RSI_UMBRAL_SOBRECOMPRA"]
# Porcentaje de ganancia mínima para activar breakeven (move stop loss al precio de entrada)

# NUEVOS parámetros para operar en rango (estrategia de rango lateral)
# Activa/desactiva la detección automática de mercados laterales
RANGO_OPERAR = bot_params.get("RANGO_OPERAR", True)
# Número de velas a analizar para detectar rango lateral
RANGO_PERIODO_ANALISIS = bot_params.get("RANGO_PERIODO_ANALISIS", 20)
# Umbral del ATR (Average True Range) para identificar rangos estrechos
RANGO_UMBRAL_ATR = bot_params.get("RANGO_UMBRAL_ATR", 0.015)
# RSI por debajo del cual se compra en rango (ej: 30 = entrada en sobreventa)
RANGO_RSI_SOBREVENTA = bot_params.get("RANGO_RSI_SOBREVENTA", 30)
# RSI por encima del cual se vende en rango (ej: 70 = salida en sobrecompra)
RANGO_RSI_SOBRECOMPRA = bot_params.get("RANGO_RSI_SOBRECOMPRA", 70)
# Parámetros personalizados por símbolo (ej: take_profit específico por par)
PARAMS = bot_params.get("symbols", {})
# Asegurar persistencia: guarda los parámetros cargados en almacenamiento
config_manager.save_parameters(bot_params)

# Intervalo para optimización IA gestionado por hilo dedicado (ver optimizar_ai_loop)
# # --------- CLIENTE BINANCE ---------
# Inicializa el cliente de Binance con credenciales y configuración de testnet
client = Client(API_KEY, API_SECRET, testnet=True,
                requests_params={'timeout': 30})
# Sobrescribe la URL del cliente para usar el testnet de Binance
client.API_URL = 'https://testnet.binance.vision/api'

# --------- VARIABLES DE CONTROL ---------
# Diccionario con todas las posiciones activas del bot
posiciones_abiertas = position_manager.load_open_positions(
    STOP_LOSS_PORCENTAJE)
# ID del último update de Telegram procesado (para no procesar duplicados)
last_update_id = 0
# Intervalo en segundos entre revisiones de comandos de Telegram
TELEGRAM_LISTEN_INTERVAL = 5
# Lista de transacciones registradas durante el día actual
transacciones_diarias = []
# Fecha del último informe CSV enviado (YYYY-MM-DD)
ultima_fecha_informe_enviado = None
# Timestamp del último análisis de trading ejecutado
last_trading_check_time = 0
# Lock (mutex) para evitar condiciones de carrera en acceso a variables compartidas
shared_data_lock = threading.Lock()


def cfg(symbol):
    """
    Retorna la configuración personalizada de un símbolo.
    Si existe configuración específica, la usa; si no, retorna valores por defecto.

    Args:
        symbol (str): Par de trading (ej: 'BTCUSDT')

    Returns:
        dict: Diccionario con parámetros personalizados del símbolo
    """
    return PARAMS.get(symbol, {
        "stop_loss_pct": 0.03,  # Stop loss por defecto: 3%
        "take_profit_pct": 0.05,  # Take profit por defecto: 5%
        "trailing_stop_pct": 0.025,  # Trailing stop por defecto: 2.5%
        "breakeven_pct": 0.01,  # Breakeven por defecto: 1%
        "rsi_buy": 35,  # RSI para entrada en compra
        "rsi_sell": 65,  # RSI para salida/venta
        "volume_factor": 1.5,  # Factor de volumen multiplicador
        "ema_fast": 9,  # Período EMA rápida
        "ema_slow": 21  # Período EMA lenta
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
                elif command == "/optimizar_ai":

                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "optimizando...")
                    if (inteligens.run_optimization()):
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "✅ Optimización IA completada")
                    else:
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Error en Optimización IA")

                elif command == "/beneficio":
                    db = firestore_utils.get_firestore_db()
                    beneficio_total = 0.0
                    if db:
                        try:
                            docs = db.collection(
                                firestore_utils.FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
                            for doc in docs:
                                trans = doc.to_dict()
                                beneficio_total += trans.get(
                                    'ganancia_usdt', 0.0)
                        except Exception as e:
                            logging.error(
                                f"Error calculando beneficio total: {e}")

                        eur_rate = binance_utils.obtener_precio_eur(client)
                        beneficio_eur = beneficio_total / eur_rate if eur_rate else 0.0
                        if beneficio_eur > 0:
                            emoji = "👍"
                        else:
                            emoji = "💩"
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"📈 <b>Beneficio Total Acumulado (TODAS):</b>\n"
                            f"   {emoji} <b>{beneficio_total:.2f} USDT</b>\n"
                            f"   {emoji} <b>{beneficio_eur:.2f} EUR</b>"
                        )

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
                                    beneficio_dia += trans.get(
                                        'ganancia_usdt', 0.0)
                        except Exception as e:
                            logging.error(
                                f"Error calculando beneficio diario: {e}")
                        eur_rate = binance_utils.obtener_precio_eur(client)
                        beneficio_eur = beneficio_dia / eur_rate if eur_rate else 0.0
                        if beneficio_eur > 0:
                            emoji = "👍"
                        else:
                            emoji = "💩"
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            f"📊 <b>Beneficio del día {hoy}</b>:\n"
                            f"  {emoji}  <b>{beneficio_dia:.2f} USDT</b>\n"
                            f"  {emoji}  <b>{beneficio_eur:.2f} EUR</b>"
                        )

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
    Envía un resumen compacto del ciclo de trading al chat de Telegram.
    Incluye estado de cada símbolo, saldo y beneficio acumulado.

    Args:
        resumen_dict (dict): Diccionario con análisis de cada símbolo
        saldo_usdt (float): Balance actual en USDT
        beneficio (float): Beneficio acumulado total
    """
    # Construimos el mensaje con formato HTML para Telegram
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
    """
    Función que se ejecuta en un hilo separado escuchando comandos de Telegram.
    Polling continuo de nuevos mensajes cada TELEGRAM_LISTEN_INTERVAL segundos.

    Args:
        stop_event (threading.Event): Evento para detener el listener
    """
    # Bucle continuo mientras no se establezca el evento de parada
    while not stop_event.is_set():
        try:
            # Procesa todos los comandos de Telegram pendientes
            handle_telegram_commands()
            # Espera antes de hacer polling nuevamente
            time.sleep(TELEGRAM_LISTEN_INTERVAL)
        except Exception as e:
            # Log de errores sin detener el listener
            logging.error(f"Error hilo Telegram: {e}")

# ------------------------------------------------------------------
#  FUNCIÓN INDICADORES (nueva)
# ------------------------------------------------------------------


def indicadores(symbol):
    """
    Calcula los indicadores técnicos principais para un símbolo en velas de 1 hora.

    Args:
        symbol (str): Par de trading (ej: 'BTCUSDT')

    Returns:
        tuple: (price, rsi, ema_fast, ema_slow, vol_ratio)
            - price: Precio de cierre actual
            - rsi: Índice de Fuerza Relativa (0-100)
            - ema_fast: Media móvil exponencial rápida
            - ema_slow: Media móvil exponencial lenta
            - vol_ratio: Ratio de volumen (volumen actual vs media 20 velas)
    """
    # Obtiene las últimas 50 velas de 1 hora para tener suficiente historia
    klines = client.get_klines(
        symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=50)
    # Extrae los precios de cierre (índice 4 en cada vela)
    closes = np.array([float(k[4]) for k in klines])
    # Extrae los volúmenes (índice 5 en cada vela)
    vols = np.array([float(k[5]) for k in klines])
    # Calcula RSI con período 14 (estándar), toma el valor actual (-1)
    rsi = talib.RSI(closes, timeperiod=14)[-1]
    # Calcula EMA rápida usando período personalizado del símbolo
    ema_fast = talib.EMA(closes, timeperiod=cfg(symbol)["ema_fast"])[-1]
    # Calcula EMA lenta usando período personalizado del símbolo
    ema_slow = talib.EMA(closes, timeperiod=cfg(symbol)["ema_slow"])[-1]
    # Calcula ratio: volumen actual vs promedio de últimas 20 velas (detecta explosiones)
    vol_ratio = vols[-1] / (np.mean(vols[-20:]) + 1e-8)
    # Obtiene el precio de cierre más reciente
    price = closes[-1]
    return price, rsi, ema_fast, ema_slow, vol_ratio

    # ---función principal del bot comenzado por el usuario


def optimizar_ai_loop(stop_event):
    """
    Ejecuta la optimización IA cada 12 horas en un hilo separado.
    Permite ajustes automáticos de parámetros basados en histórico de trades.

    Args:
        stop_event (threading.Event): Evento para detener el loop
    """
    while not stop_event.is_set():
        try:
            # Inicia proceso de optimización
            logging.info("🔄 Iniciando optimización IA (periodo 12h)...")
            # Ejecuta optimización (analiza histórico y ajusta parámetros)
            inteligens.run_optimization()
            logging.info("✅ Optimización IA completada correctamente")

            # Espera 12 horas (24 x 1800 segundos / 2 = 12 horas)
            # Utiliza loop para permitir parada rápida sin esperar bloqueada
            for _ in range(24):
                # Verifica si se solicitó detener
                if stop_event.is_set():
                    break
                # Duerme en incrementos de 1 hora
                time.sleep(3600)

        except Exception as e:
            # Log de errores durante optimización
            logging.error(f"❌ Error en optimización IA: {e}")
            # Continúa esperando antes de reintentar
            time.sleep(3600)


def main():  # Define la función principal del bot.
    """
    Función principal que inicia el bot y maneja el ciclo de trading.
    """
    global last_trading_check_time, ultima_fecha_informe_enviado  # Declara que se usarán/actualizarán estas variables globales.

    # 1. Conecta con Binance
    # Escribe en el log que se iniciará el cliente de Binance.
    logging.info("Iniciando cliente Binance...")
    # Envía un ping a Binance para verificar conectividad y credenciales.
    client.ping()

    # 2. Carga las posiciones que estén abiertas
    # Informa en el log que cargará posiciones abiertas.
    logging.info("Cargando posiciones abiertas...")
    # Indica que se modificará la variable global de posiciones abiertas.
    global posiciones_abiertas
    posiciones_abiertas = position_manager.load_open_positions(  # Carga de almacenamiento persistente las posiciones abiertas.
        # Pasa el porcentaje de stop-loss por defecto para validar/normalizar posiciones.
        STOP_LOSS_PORCENTAJE)

# 3. Inicializa los comandos de Telegram
    # Mensaje informativo para el log.
    logging.info("Iniciando manejador de comandos Telegram...")
    # Configura el menú/atajos de comandos del bot en Telegram.
    telegram_handler.set_telegram_commands_menu(TELEGRAM_BOT_TOKEN)
    # Confirma que el bot está listo.
    logging.info("Bot iniciado. Esperando comandos y monitoreando mercado...")

    # 4. Lanza el hilo que escucha comandos de Telegram
    # Crea un evento para poder detener el hilo del listener cuando sea necesario.
    telegram_stop_event = threading.Event()
    telegram_thread = threading.Thread(  # Crea un nuevo hilo que ejecutará la función que escucha Telegram.
        # Pasa el evento de parada como argumento al listener.
        target=telegram_listener, args=(telegram_stop_event,))
    telegram_thread.start()  # Inicia el hilo de escucha de Telegram.
   # 6. CREAR HILO DE OPTIMIZACIÓN CADA 12 HORAS
    optimizar_ai_stop_event = threading.Event()

    # Crear e iniciar el hilo de optimización
    optimizar_ai_thread = threading.Thread(
        target=lambda: optimizar_ai_loop(optimizar_ai_stop_event),
        daemon=True
    )
    optimizar_ai_thread.start()
    logging.info("🔄 Hilo de optimización IA cada 12h iniciado")

    try:
        # Bloque principal protegido - captura excepciones graves e interrupciones (Ctrl+C)
        # Bucle infinito del ciclo de trading (hasta que se interrumpa manual o programáticamente)
        # Cada iteración puede durar varios segundos según el intervalo configurado
        while True:
            # Marca el instante de inicio del ciclo para calcular tiempo de espera
            start_time_cycle = time.time()

# ------------------------------------------------------------------
#   Informe diario CSV (solo cuando cambia el día)
# ------------------------------------------------------------------

# 5. Informe diario CSV (solo cuando cambia el día)
            # Obtiene la fecha actual en formato YYYY-MM-DD como cadena.
            hoy = time.strftime("%Y-%m-%d")
            # Si es el primer ciclo del día o cambió la fecha...
            if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
                # Si ya había una fecha previa, toca cerrar y reportar el día anterior.
                if ultima_fecha_informe_enviado is not None:
                    telegram_handler.send_telegram_message(  # Notifica en Telegram que se preparará el informe del día terminado.
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                        # Mensaje indicando la fecha del informe.
                        f"📊 Preparando informe del día {ultima_fecha_informe_enviado}")
                    reporting_manager.generar_y_enviar_csv_ahora(  # Genera el CSV diario y lo envía por Telegram.
                        # Usa las credenciales/destino configurados.
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                # Actualiza la marca de fecha de último informe enviado al día actual.
                ultima_fecha_informe_enviado = hoy
                # Entra en sección crítica para modificar estructuras compartidas sin condiciones de carrera.
                with shared_data_lock:
                    # Vacía el registro de transacciones del nuevo día.
                    transacciones_diarias.clear()
# ------------------------------------------------------------------
#   limpia posiciones con saldo insuficiente
# ------------------------------------------------------------------

 # 6. Limpia posiciones con saldo insuficiente
            with shared_data_lock:  # Bloquea el acceso concurrente a posiciones_abiertas y saldos.
                # Prepara una lista de símbolos que se eliminarán tras la verificación.
                symbols_to_remove = []
                # Itera sobre una copia de items para poder borrar con seguridad.
                for symbol, data in list(posiciones_abiertas.items()):
                    # Si el símbolo ya no está en la lista de seguimiento activa...
                    if symbol not in SYMBOLS:
                        # Lo marca para eliminar.
                        symbols_to_remove.append(symbol)
                        continue  # Continúa con el siguiente símbolo.
                    # Extrae el activo base (p. ej., BTC de BTCUSDT).
                    base_asset = symbol.replace("USDT", "")
                    actual_balance = binance_utils.obtener_saldo_moneda(  # Obtiene el saldo actual del activo base en la cuenta.
                        # Usa el cliente de Binance para consultar saldos.
                        client, base_asset)
                    # Pide a Binance la información del símbolo (filtros, pasos, etc.).
                    info = client.get_symbol_info(symbol)
                    # Inicializa la cantidad mínima permitida para operar.
                    min_qty = 0.0
                    # Recorre los filtros del mercado del símbolo.
                    for f in info['filters']:
                        # Busca el filtro de tamaño de lote, que define cantidades mínimas y pasos.
                        if f['filterType'] == 'LOT_SIZE':
                            # Toma la cantidad mínima del filtro como flotante.
                            min_qty = float(f['minQty'])
                            # Sale del bucle al encontrar el filtro relevante.
                            break
                    # Define un umbral mínimo para considerar que existe posición/saldo.
                    threshold = max(min_qty, 1e-8)
                    # Si el saldo real es inferior al mínimo operativo...
                    if actual_balance < threshold:
                        # Marca el símbolo para eliminar de posiciones abiertas.
                        symbols_to_remove.append(symbol)
                for symbol in symbols_to_remove:  # Recorre los símbolos que deben ser eliminados.
                    if symbol in posiciones_abiertas:  # Si aún figura como posición abierta...
                        # Elimina la posición de la estructura en memoria.
                        del posiciones_abiertas[symbol]
                        position_manager.save_open_positions_debounced(  # Guarda las posiciones a disco de forma diferida/optimizada.
                            # Pasa el diccionario actualizado.
                            posiciones_abiertas)
                        telegram_handler.send_telegram_message(  # Notifica por Telegram que se ha eliminado la posición por saldo insuficiente.
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                            # Mensaje con el símbolo eliminado.
                            f"🗑️ Posición {symbol} eliminada (saldo insuficiente)")

 # 7. Solo ejecuta el ciclo si ha pasado INTERVALO segundos
            # Comprueba si ya tocaba correr el ciclo principal según el intervalo.
            if (time.time() - last_trading_check_time) >= INTERVALO:
                # Log de inicio de un nuevo ciclo de trading.
                logging.info("Iniciando ciclo de trading principal...")
# ------------------------------------------------------------------
#  datos globales y resumen (siempre disponibles)
# ------------------------------------------------------------------

 # 8. Datos globales (siempre disponibles)
                # Entra en sección crítica para leer saldos y posiciones de forma consistente.
                with shared_data_lock:
                    saldo_usdt_global = binance_utils.obtener_saldo_moneda(  # Obtiene el saldo libre en USDT.
                        client, "USDT")  # Consulta al cliente Binance.
                    total_capital_usdt_global = binance_utils.get_total_capital_usdt(  # Calcula capital total (saldos + valor de posiciones) en USDT.
                        # Usa posiciones abiertas actuales.
                        client, posiciones_abiertas)
                    # Obtiene el tipo de cambio USDT→EUR (precio de referencia).
                    eur_usdt_rate = binance_utils.obtener_precio_eur(client)
                    total_capital_eur_global = (  # Calcula el capital total expresado en EUR.
                        total_capital_usdt_global / eur_usdt_rate
                        # Evita división por cero si no hay tipo de cambio válido.
                        if eur_usdt_rate and eur_usdt_rate > 0 else 0
                    )

                    # Cabecera del informe
                    general_message = (  # Inicializa el mensaje-resumen que se enviará por Telegram.
                        # Hora del ciclo en formato HH:MM:SS.
                        f"📈 Resumen ciclo {datetime.now().strftime('%H:%M:%S')}\n"
                        # Saldo USDT con 2 decimales.
                        f"💰 USDT libre: {saldo_usdt_global:.2f}\n"
                        # Capital total en USDT.
                        f"💲 Total: {total_capital_usdt_global:.2f} USDT\n"
                        # Capital total en EUR.
                        f"💶 Total: {total_capital_eur_global:.2f} EUR\n\n"
                    )
# ------------------------------------------------------------------
#   Recorre todos los símbolos
# ------------------------------------------------------------------

# 9. Recorre todos los símbolos
                # Itera cada par/mercado a monitorear (p. ej., BTCUSDT, ETHUSDT, etc.).
                for symbol in SYMBOLS:
                    # Obtiene el activo base del símbolo para consultas de saldo.
                    base = symbol.replace("USDT", "")
                    precio_actual = binance_utils.obtener_precio_actual(  # Consulta el último precio conocido del símbolo.
                        # Usa el cliente de Binance para obtener datos de mercado.
                        client, symbol)

# 10. Parámetros personalizados por símbolo
                    cf = bot_params.get("symbols", {}).get(symbol, {  # Carga la configuración específica del símbolo o usa valores por defecto.
                        # Porcentaje de stop-loss.
                        "stop_loss_pct": STOP_LOSS_PORCENTAJE,
                        # Porcentaje de take-profit.
                        "take_profit_pct": TAKE_PROFIT_PORCENTAJE,
                        # Porcentaje del trailing stop.
                        "trailing_stop_pct": TRAILING_STOP_PORCENTAJE,
                        # Umbral para mover SL a break-even.
                        "breakeven_pct": BREAKEVEN_PORCENTAJE,
                        # Umbral de RSI para compras (nomenclatura heredada).
                        "rsi_buy": RSI_UMBRAL_SOBRECOMPRA,
                        # Factor de volumen para validar impulso.
                        "volume_factor": 1.5,
                        # Periodo EMA rápida para tendencia.
                        "ema_fast": EMA_CORTA_PERIODO,
                        # Periodo EMA media para tendencia.
                        "ema_slow": EMA_MEDIA_PERIODO
                    })  # Fin de la obtención de configuración.

 # 11. Detecta rango lateral
                    # Lee si la operativa de rango está habilitada.
                    rango_activo = bot_params.get('RANGO_OPERAR', True)
                    if rango_activo:  # Si está activada la lógica de rango...
                        en_rango, soporte, resistencia = detectar_rango_lateral(  # Detecta si el precio está en rango y los niveles estimados.
                            client, symbol,
                            # Número de velas para evaluar rango.
                            periodo=bot_params.get(
                                'RANGO_PERIODO_ANALISIS', 20),
                            # ADX límite para considerar poca tendencia.
                            adx_umbral=bot_params.get('RANGO_ADX_UMBRAL', 25),
                            # Máximo ancho de bandas para rango.
                            band_width_max=bot_params.get(
                                'RANGO_BAND_WIDTH_MAX', 0.05)
                        )  # Fin de la detección de rango.
                        if en_rango:  # Si se considera que hay rango...
                            senal_rango = estrategia_rango(  # Calcula la señal (COMPRA/VENTA/NEUTRO) basada en soporte/resistencia y RSI.
                                client, symbol, soporte, resistencia,
                                rsi=trading_logic.calcular_ema_rsi(  # Reutiliza cálculo EMA/RSI para obtener RSI actual.
                                    client, symbol,
                                    cf["ema_fast"], cf["ema_slow"],
                                    # Índice 3 corresponde al RSI retornado.
                                    EMA_LARGA_PERIODO, RSI_PERIODO)[3],
                                # Umbral RSI sobreventa para compras en rango.
                                rsi_sobreventa=bot_params.get(
                                    'RANGO_RSI_SOBREVENTA', 30),
                                # Umbral RSI sobrecompra para ventas en rango.
                                rsi_sobrecompra=bot_params.get(
                                    'RANGO_RSI_SOBRECOMPRA', 70)
                            )  # Fin de la evaluación de señal en rango.

# ------------------------------------------------------------------
#   Compra en rango o
# ------------------------------------------------------------------

# 11.1 Compra en rango
                            # Condiciones para abrir compra en rango.
                            if senal_rango == 'COMPRA' and symbol not in posiciones_abiertas and saldo_usdt_global > 10:
                                cantidad = trading_logic.calcular_cantidad_a_comprar(  # Calcula tamaño de posición según riesgo, SL y capital.
                                    client, saldo_usdt_global, precio_actual,
                                    cf["stop_loss_pct"], symbol,
                                    RIESGO_POR_OPERACION_PORCENTAJE, total_capital_usdt_global)
                                if cantidad > 0:  # Si la cantidad es operable...
                                    with shared_data_lock:  # Bloquea para operar con seguridad.
                                        orden = trading_logic.comprar(  # Lanza la orden de compra a mercado o límite según implementación.
                                            client, symbol, cantidad, posiciones_abiertas,
                                            cf["stop_loss_pct"], transacciones_diarias,
                                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                            # Archivo donde persistir posiciones.
                                            OPEN_POSITIONS_FILE)
                                    if orden:  # Si la orden se ejecutó correctamente...
                                        # Añade línea al informe general.
                                        general_message += f"🟢 COMPRA RANGO {symbol}"
                                    # Salta a siguiente símbolo (ya se tomó acción en rango).
                                    continue
# ------------------------------------------------------------------
#  Venta en rango
# ------------------------------------------------------------------

 # 11.2 Venta en rango
                            # Condiciones para cerrar en resistencia dentro de rango.
                            elif senal_rango == 'VENTA' and symbol in posiciones_abiertas:
                                cantidad_vender = binance_utils.ajustar_cantidad(  # Ajusta la cantidad a vender al step size permitido.
                                    binance_utils.obtener_saldo_moneda(
                                        client, base),
                                    binance_utils.get_step_size(client, symbol))
                                if cantidad_vender > 0:  # Si hay cantidad disponible para vender...
                                    with shared_data_lock:  # Bloquea durante la operación de venta.
                                        orden = trading_logic.vender(  # Ejecuta la orden de venta y actualiza estructuras y persistencia.
                                            client, symbol, cantidad_vender,
                                            posiciones_abiertas,
                                            # Pasa acumulado para métricas.
                                            bot_params.get(
                                                'TOTAL_BENEFICIO_ACUMULADO', 0.0),
                                            bot_params, transacciones_diarias,
                                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                            OPEN_POSITIONS_FILE, config_manager,
                                            # Etiqueta el motivo de la venta.
                                            motivo_venta="VENTA EN RANGO")
                                        bot_params['TOTAL_BENEFICIO_ACUMULADO'] = bot_params.get(  # Asegura clave presente aunque no cambie.
                                            'TOTAL_BENEFICIO_ACUMULADO', 0.0)
                                        # Persiste la configuración/estadísticas del bot.
                                        config_manager.save_parameters(
                                            bot_params)
                                    # Si la orden se envió/ejecutó...
                                    if orden:
                                        # Añade al informe el resultado de venta.
                                        general_message += f"🔴 VENTA RANGO {symbol}"
                                    # Salta al siguiente símbolo tras actuar en rango.
                                    continue
# ------------------------------------------------------------------
#  operación en tendencia
# ------------------------------------------------------------------

 # 12. Operación en tendencia
                    ema_corta, ema_media, ema_larga, rsi = trading_logic.calcular_ema_rsi(  # Calcula EMAs y RSI para el símbolo actual.
                        client, symbol,
                        cf["ema_fast"], cf["ema_slow"],
                        # Usa periodos configurados.
                        EMA_LARGA_PERIODO, RSI_PERIODO)
                    # Si faltan datos para indicadores...
                    if any(v is None for v in (ema_corta, ema_media, ema_larga, rsi)):
                        continue  # Omite este símbolo en este ciclo.

 # 13. Filtro de volumen
                    klines = client.get_klines(  # Solicita las últimas 20 velas de 1 hora para calcular volumen medio.
                        symbol=symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=20)
                    vol_ratio = float(  # Calcula el ratio de volumen: volumen última vela / volumen medio 20 velas.
                        klines[-1][5]) / (sum(float(k[5]) for k in klines[-20:]) / 20 + 1e-8)

                    # Define condición de tendencia alcista por EMAs encadenadas.
                    tendencia_alcista = (
                        precio_actual > ema_corta > ema_media > ema_larga)
# ------------------------------------------------------------------
#  Lógica  ce compra
# ------------------------------------------------------------------

 # 14. Lógica de compra
                    comprar_cond = (  # Construye condición booleana para comprar en tendencia.
                        # Requiere saldo mínimo en USDT.
                        saldo_usdt_global > 10 and
                        # Debe existir estructura alcista de EMAs.
                        tendencia_alcista and
                        # RSI por debajo del umbral definido para entrada.
                        rsi < cf["rsi_buy"] and
                        # Volumen actual superior al factor de confirmación.
                        vol_ratio > cf["volume_factor"] and
                        # Evita duplicar posiciones en el mismo símbolo.
                        symbol not in posiciones_abiertas
                    )
                    if comprar_cond:  # Si se cumplen todos los criterios de compra...
                        cantidad = trading_logic.calcular_cantidad_a_comprar(  # Calcula tamaño de la orden basado en riesgo y SL.
                            client, saldo_usdt_global, precio_actual,
                            cf["stop_loss_pct"], symbol,
                            RIESGO_POR_OPERACION_PORCENTAJE, total_capital_usdt_global)
                        if cantidad > 0:  # Solo si la cantidad cumple mínimos de exchange.
                            with shared_data_lock:  # Protege actualización de estructuras compartidas.
                                orden = trading_logic.comprar(  # Ejecuta la compra.
                                    client, symbol, cantidad, posiciones_abiertas,
                                    cf["stop_loss_pct"], transacciones_diarias,
                                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                    OPEN_POSITIONS_FILE)
                            if orden:  # Si se envió/ejecutó correctamente...
                                # Lo refleja en el informe.
                                general_message += f"✅ COMPRA TENDENCIA {symbol}"
# ------------------------------------------------------------------
#   Lógica de venta
# ------------------------------------------------------------------

 # 15. Lógica de venta
                    # Si no se compra y existe posición abierta, se evalúa venta/gestión.
                    elif symbol in posiciones_abiertas:
                        # Obtiene la posición almacenada para el símbolo.
                        pos = posiciones_abiertas[symbol]
                        # Precio de entrada registrado.
                        precio_compra = pos['precio_compra']
                        # Máximo precio alcanzado desde que se abrió la posición.
                        max_precio_alcanzado = pos['max_precio_alcanzado']
                        sl_actual = pos.get('stop_loss_fijo_nivel_actual',  # Nivel de SL actual (fijo) o se calcula por defecto sobre el precio de compra.
                                            precio_compra * (1 - cf["stop_loss_pct"]))
                        # Calcula el nivel de take-profit.
                        tp = precio_compra * (1 + cf["take_profit_pct"])
                        # Calcula trailing stop a partir del máximo alcanzado.
                        tsl = max_precio_alcanzado * \
                            (1 - cf["trailing_stop_pct"])

                        # Si el precio hace un nuevo máximo desde la entrada...
                        if precio_actual > max_precio_alcanzado:
                            with shared_data_lock:  # Protege escritura concurrente.
                                # Actualiza el nuevo máximo.
                                posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                                # Persiste cambios de posiciones de forma diferida.
                                position_manager.save_open_positions_debounced(
                                    posiciones_abiertas)

                        # Flag que indica si se debe vender en este instante.
                        vender_ahora = False
                        # Texto que documenta el motivo de la venta.
                        motivo = ""
                        if precio_actual >= tp:  # Si se alcanza el objetivo de beneficio...
                            # Marca venta por TP.
                            vender_ahora, motivo = True, "TAKE PROFIT"
                        # Si el precio cae al nivel de stop-loss fijo...
                        elif precio_actual <= sl_actual:
                            # Marca venta por SL.
                            vender_ahora, motivo = True, "STOP LOSS"
                        # Si cae al trailing stop pero aún por encima de la entrada...
                        elif precio_actual <= tsl and precio_actual > precio_compra:
                            # Marca venta por TSL.
                            vender_ahora, motivo = True, "TRAILING STOP"

                        if vender_ahora:  # Si se determinó vender...
                            cantidad_vender = binance_utils.ajustar_cantidad(  # Ajusta cantidad a vender al paso mínimo permitido.
                                binance_utils.obtener_saldo_moneda(
                                    client, base),
                                binance_utils.get_step_size(client, symbol)
                            )
                            if cantidad_vender > 0:  # Solo procede si hay cantidad disponible según exchange.
                                with shared_data_lock:  # Bloquea operaciones concurrentes.
                                    orden = trading_logic.vender(  # Envía la orden de venta y actualiza el estado de la posición.
                                        client, symbol, cantidad_vender,
                                        posiciones_abiertas,
                                        bot_params.get(
                                            'TOTAL_BENEFICIO_ACUMULADO', 0.0),
                                        bot_params, transacciones_diarias,
                                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                        OPEN_POSITIONS_FILE, config_manager,
                                        # Pasa el motivo calculado (TP/SL/TSL).
                                        motivo
                                    )
                                    bot_params['TOTAL_BENEFICIO_ACUMULADO'] = bot_params.get(  # Asegura que la clave exista (y pueda actualizarse en vender()).
                                        'TOTAL_BENEFICIO_ACUMULADO', 0.0)
                                    # Guarda la configuración/estadísticas tras la operación.
                                    config_manager.save_parameters(bot_params)
                                if orden:  # Si la orden se ejecutó...
                                    # Añade la línea correspondiente al informe general.
                                    general_message += f"🔴 VENTA {motivo} {symbol}"

 # 16. Construye línea del informe por símbolo
                    ema_c, ema_m, ema_l, rsi = trading_logic.calcular_ema_rsi(  # Recalcula EMAs/RSI para mostrar en el informe final por símbolo.
                        client, symbol, EMA_CORTA_PERIODO, EMA_MEDIA_PERIODO,
                        EMA_LARGA_PERIODO, RSI_PERIODO)
                    # Si no hay datos suficientes para indicadores...
                    if any(v is None for v in (ema_c, ema_m, ema_l, rsi)):
                        # Omite la agregación del mensaje para este símbolo.
                        continue
                    # Determina emoji según relación de EMAs.
                    tend_emoji = "📈" if precio_actual > ema_c > ema_m else "📉" if ema_l > ema_m > ema_c else "ǁ"
                    # Texto de tendencia.
                    tend_text = "Alcista" if tend_emoji == "📈" else "Bajista" if tend_emoji == "📉" else "Lateral/Consolidación"

                    msg = (  # Construye el bloque de texto para este símbolo.
                        # Muestra el símbolo en negrita (formato HTML/Telegram).
                        f"📊 <b>{symbol}</b>\n"
                        # Precio actual con 2 decimales.
                        f"Precio: {precio_actual:.2f} USDT\n"
                        # EMAs corta/media/larga.
                        f"EMA: {ema_c:.2f} / {ema_m:.2f} / {ema_l:.2f}\n"
                        f"RSI: {rsi:.2f}"  # RSI con 2 decimales.
                        # Emoji + descripción de tendencia.
                        f"Tend: {tend_emoji} {tend_text}\n"
                    )
                    # Si hay posición abierta, añade información de gestión.
                    if symbol in posiciones_abiertas:
                        # Recupera la posición.
                        pos = posiciones_abiertas[symbol]
                        msg += (  # Agrega métricas de la posición al mensaje.
                            # Precio de entrada.
                            f"Posición: Entrada {pos['precio_compra']:.2f} |   "
                            # Nivel de take-profit actual por porcentaje global.
                            f"TP: {pos['precio_compra']*(1+TAKE_PROFIT_PORCENTAJE):.2f} |   "
                            # Stop-loss fijo actual o calculado.
                            f"SL: {pos.get('stop_loss_fijo_nivel_actual', pos['precio_compra']*(1-STOP_LOSS_PORCENTAJE)):.2f} |   "
                            # Máximo alcanzado desde la entrada.
                            f"Max: {pos['max_precio_alcanzado']:.2f} |   "
                            # Trailing stop estimado a partir del máximo.
                            f"TSL: {pos['max_precio_alcanzado']*(1-TRAILING_STOP_PORCENTAJE):.2f}\n\n"
                        )
                    else:  # Si no hay posición...
                        # Indica explícitamente que no se mantiene posición en este símbolo.
                        msg += "Sin posición\n"
                    # Añade el bloque del símbolo al mensaje general, con una línea en blanco de separación.
                    general_message += msg + "\n"

 # 17. Envía el informe por Telegram
                # Sección crítica antes de enviar (por si otro hilo también publicara).
                with shared_data_lock:
                    try:  # Intenta enviar el resumen del ciclo.
                        telegram_handler.send_telegram_message(  # Envío del mensaje general al chat de Telegram de monitoreo.
                            # Pasa token, chat y contenido.
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, general_message)
                    # Captura errores de red/formato/limites de Telegram.
                    except Exception as e:
                        # Loguea el fallo de envío.
                        logging.error(f"Fallo al enviar informe: {e}")

# 18. Actualiza el tiempo de la última ejecución
                # Registra el instante actual como último chequeo para controlar INTERVALO.
                last_trading_check_time = time.time()

# 19. Espera el tiempo restante para el siguiente ciclo
            sleep_duration = max(  # Calcula cuánto falta para completar el INTERVALO, evitando valores negativos.
                0, INTERVALO - (time.time() - start_time_cycle))
            # Muestra en consola cuánto falta para el siguiente ciclo (redondeado a s).
            print(f"⏳ Próxima revisión en {sleep_duration:.0f}s")
            # Duerme el hilo principal el tiempo calculado.
            time.sleep(sleep_duration)

    # Si el usuario detiene el proceso (Ctrl+C) u otra interrupción de teclado...
    except KeyboardInterrupt:
        # Informa en el log que se está cerrando ordenadamente de forma controlada
        logging.info(
            "KeyboardInterrupt detectado. Terminando bot de forma ordenada...")
        # Señaliza al hilo de Telegram que debe detenerse
        telegram_stop_event.set()
        # Espera a que el hilo de Telegram termine su ejecución de forma limpia
        telegram_thread.join(timeout=5)
        # Señaliza al hilo de optimización IA que debe parar
        optimizar_ai_stop_event.set()
        # Espera a que el hilo de optimización termine
        optimizar_ai_thread.join(timeout=5)
        logging.info("Bot detenido correctamente")

    except Exception as e:
        # Captura cualquier otra excepción no controlada durante el ciclo de trading
        # Log detallado del error con stack trace completo para debugging
        logging.error(f"Error critico en bot.py: {e}", exc_info=True)
        # Protege el envío de mensajes en caso de errores concurrentes
        with shared_data_lock:
            try:
                # Envía un mensaje de error crítico con saldos actuales para diagnóstico remoto
                telegram_handler.send_telegram_message(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                    # Incluye saldos y posiciones formateadas para conocer el estado al fallar
                    f"Error critico detectado: {e}")
            except:
                # Si falla el envío de Telegram, al menos lo registramos en logs
                logging.error(
                    "No se pudo enviar mensaje de error por Telegram")
        # Señaliza al hilo de Telegram que debe detenerse tras el error
        telegram_stop_event.set()
        # Espera su finalización para salir de forma limpia
        telegram_thread.join(timeout=5)
        # Señaliza que debe detenerse
        optimizar_ai_stop_event.set()
        # Espera a que termine
        optimizar_ai_thread.join(timeout=5)


# ========================================================================
# PUNTO DE ENTRADA DEL SCRIPT
# ========================================================================
# Punto de entrada del script cuando se ejecuta directamente (no importado como módulo)
if __name__ == "__main__":
    # Configura el nivel de logging a INFO para ver todos los eventos importantes
    logging.basicConfig(level=logging.INFO,
                        # Define el formato completo de las líneas de log con timestamp
                        format='%(asctime)s - %(levelname)s - %(message)s')
    # Escribe una línea inicial en el log indicando el inicio del bot
    logging.info("Iniciando bot de trading...")
    # Llama a la función principal para iniciar el ciclo de trading
    main()
