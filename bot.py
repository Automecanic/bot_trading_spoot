# Importa el módulo os para interactuar con el sistema operativo, como acceder a variables de entorno.
import os
# Importa el módulo time para funciones relacionadas con el tiempo, como pausas (sleep).
import time
# Importa el módulo logging para registrar eventos y mensajes del bot.
import logging
# Importa el módulo json para trabajar con datos en formato JSON (guardar/cargar configuraciones).
import json
# Importa el módulo csv para trabajar con archivos CSV (generar informes de transacciones).
import csv
# Importa la clase Client del SDK de Binance para interactuar con la API.
from binance.client import Client
# Importa todas las enumeraciones de Binance (ej. KLINE_INTERVAL_1MINUTE) para mayor comodidad.
from binance.enums import *
# Importa datetime para trabajar con fechas y horas, y timedelta para cálculos de tiempo.
from datetime import datetime, timedelta
import threading  # Importa el módulo threading para trabajar con hilos.
# Importa requests para manejar excepciones de red, como ReadTimeoutError.
import requests

# Importa los módulos refactorizados que contienen la lógica modularizada del bot.
# Módulo para gestionar la configuración del bot (cargar/guardar parámetros).
import config_manager
# Módulo para gestionar las posiciones abiertas del bot (cargar/guardar, debounce).
import position_manager
# Módulo para todas las interacciones con la API de Telegram (enviar mensajes, gestionar comandos).
import telegram_handler
# Módulo con funciones auxiliares para interactuar con la API de Binance (saldos, precios, stepSize).
import binance_utils
# Módulo que contiene la lógica principal de trading (cálculo de indicadores, compra/venta).
import trading_logic
# Módulo para la generación y envío de informes (CSV, mensajes de beneficio).
import reporting_manager

# --- Configuración de Logging ---
# Configura el sistema de registro básico para el bot. Los mensajes se mostrarán en la consola.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# =================== CONFIGURACIÓN (Asegúrate de que estas variables de entorno estén configuradas) ===================

# Claves de API de Binance. ¡NO COMPARTAS ESTAS CLAVES!
# Se obtienen de las variables de entorno para mayor seguridad.
# Clave API para autenticación en Binance.
API_KEY = os.getenv("BINANCE_API_KEY")
# Clave secreta para autenticación en Binance.
API_SECRET = os.getenv("BINANCE_API_SECRET")

# Log para depurar la carga de la API Key.
if API_KEY:
    logging.info(
        f"API_KEY cargada (primeros 5 caracteres): {API_KEY[:5]}*****")
else:
    logging.warning("API_KEY no cargada desde las variables de entorno.")
if API_SECRET:
    logging.info(
        f"API_SECRET cargada (primeros 5 caracteres): {API_SECRET[:5]}*****")
else:
    logging.warning("API_SECRET no cargada desde las variables de entorno.")


# Token de tu bot de Telegram y Chat ID para enviar mensajes.
# Se obtienen de las variables de entorno.
# Token único de tu bot de Telegram.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
# ID del chat donde el bot enviará mensajes.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Archivos para guardar y cargar las posiciones del bot.
# Nombre del archivo JSON para guardar las posiciones abiertas.
OPEN_POSITIONS_FILE = "open_positions.json"

# =================== CARGA DE PARÁMETROS DESDE config_manager ===================

# Cargar parámetros al inicio del bot utilizando el nuevo módulo config_manager.
# Carga la configuración del bot desde 'config.json' o Firestore.
bot_params = config_manager.load_parameters()

# Asignar los valores del diccionario cargado a las variables globales del bot.
# Estos parámetros controlan la estrategia de trading y el comportamiento del bot.
# Lista de pares de trading a monitorear.
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT",
           "SOLUSDT", "ADAUSDT", "XRPUSDT", "DOGEUSDT"]
# Intervalo de tiempo en segundos entre cada ciclo de trading principal.
INTERVALO = bot_params["INTERVALO"]
# Porcentaje del capital total a arriesgar por operación.
RIESGO_POR_OPERACION_PORCENTAJE = bot_params["RIESGO_POR_OPERACION_PORCENTAJE"]
# Porcentaje de ganancia para cerrar una posición (Take Profit).
TAKE_PROFIT_PORCENTAJE = bot_params["TAKE_PROFIT_PORCENTAJE"]
# Porcentaje de pérdida para cerrar una posición (Stop Loss fijo).
STOP_LOSS_PORCENTAJE = bot_params["STOP_LOSS_PORCENTAJE"]
# Porcentaje para activar el Trailing Stop Loss.
TRAILING_STOP_PORCENTAJE = bot_params["TRAILING_STOP_PORCENTAJE"]
# Período para la EMA corta (default 20)
EMA_CORTA_PERIODO = bot_params.get("EMA_CORTA_PERIODO", 20)
# Período para la EMA media (default 50)
EMA_MEDIA_PERIODO = bot_params.get("EMA_MEDIA_PERIODO", 50)
# Período para la EMA larga (default 200)
EMA_LARGA_PERIODO = bot_params.get("EMA_LARGA_PERIODO", 200)
# Período para el cálculo del Índice de Fuerza Relativa (RSI).
RSI_PERIODO = bot_params["RSI_PERIODO"]
# Umbral superior del RSI para identificar condiciones de sobrecompra.
RSI_UMBRAL_SOBRECOMPRA = bot_params["RSI_UMBRAL_SOBRECOMPRA"]
# Beneficio total acumulado por el bot desde su inicio.
TOTAL_BENEFICIO_ACUMULADO = bot_params["TOTAL_BENEFICIO_ACUMULADO"]
# Porcentaje de ganancia para mover el Stop Loss a Breakeven.
BREAKEVEN_PORCENTAJE = bot_params["BREAKEVEN_PORCENTAJE"]

# Asegurarse de que los nuevos parámetros estén en bot_params si no estaban.
# Esto es importante para que config_manager.save_parameters los persista correctamente.
bot_params['EMA_CORTA_PERIODO'] = EMA_CORTA_PERIODO
bot_params['EMA_MEDIA_PERIODO'] = EMA_MEDIA_PERIODO
bot_params['EMA_LARGA_PERIODO'] = EMA_LARGA_PERIODO
# Guardar los parámetros actualizados para asegurar persistencia.
config_manager.save_parameters(bot_params)

# =================== INICIALIZACIÓN DE CLIENTES BINANCE Y TELEGRAM ===================

# Inicializa el cliente de la API de Binance.
# Se pasa un diccionario 'requests_params' con el 'timeout' deseado en segundos para evitar errores de tiempo de espera.
# Aumentado a 30 segundos.
client = Client(API_KEY, API_SECRET, testnet=True,
                requests_params={'timeout': 30})
# Configura la URL de la API para usar la red de prueba (Testnet) de Binance.
client.API_URL = 'https://testnet.binance.vision/api'

# Filtrar la lista de SYMBOLS para incluir solo los válidos en Binance.
logging.info("Verificando símbolos de trading válidos en Binance Testnet...")
try:
    # Obtiene información de todos los símbolos disponibles en el exchange.
    exchange_info = client.get_exchange_info()
    # Crea un set de símbolos válidos para búsqueda rápida.
    valid_binance_symbols = {s['symbol'] for s in exchange_info['symbols']}

    filtered_symbols = []  # Lista para almacenar los símbolos que son válidos.
    for symbol in SYMBOLS:
        if symbol in valid_binance_symbols:
            # Si el símbolo es válido, se añade a la lista filtrada.
            filtered_symbols.append(symbol)
        else:
            logging.warning(
                f"⚠️ El símbolo {symbol} no es válido en Binance Testnet y será ignorado.")
    # Actualiza la lista de símbolos a monitorear con los válidos.
    SYMBOLS = filtered_symbols
    logging.info(f"Símbolos de trading activos: {SYMBOLS}")
    if not SYMBOLS:
        logging.error(
            "❌ No hay símbolos de trading válidos configurados. El bot no operará.")
except requests.exceptions.ReadTimeout as e:
    # Maneja específicamente los errores de tiempo de espera durante la obtención de información del exchange.
    logging.error(
        f"❌ Error de tiempo de espera al obtener información de intercambio de Binance: {e}. Esto puede deberse a problemas de red o sobrecarga de la API. El bot continuará con la lista de símbolos predefinida, lo que podría causar errores si los símbolos no son válidos.", exc_info=True)
except Exception as e:
    # Captura cualquier otra excepción durante la obtención de información del exchange.
    logging.error(
        f"❌ Error al obtener información de intercambio de Binance para filtrar símbolos: {e}", exc_info=True)
    logging.error(
        "Continuando con la lista de símbolos original, lo que puede causar errores.")


# Diccionario para almacenar las posiciones que el bot tiene abiertas y está gestionando.
# Se carga desde el archivo de persistencia al inicio.
# Carga las posiciones guardadas, aplicando el SL inicial.
posiciones_abiertas = position_manager.load_open_positions(
    STOP_LOSS_PORCENTAJE)

# Variables para la gestión de la comunicación con Telegram.
# ID del último mensaje procesado de Telegram para evitar duplicados.
last_update_id = 0
# Intervalo de tiempo en segundos para verificar nuevos comandos de Telegram.
TELEGRAM_LISTEN_INTERVAL = 5

# Variables para la gestión de informes diarios.
# Lista para almacenar las transacciones realizadas en el día actual (para el informe diario).
transacciones_diarias = []
# Almacena la fecha del último informe diario enviado.
ultima_fecha_informe_enviado = None
# Marca de tiempo de la última vez que se ejecutó la lógica de trading principal.
last_trading_check_time = 0

# Objeto Lock para proteger el acceso a variables compartidas entre hilos.
# Este bloqueo se usará para asegurar que solo un hilo acceda o modifique
# variables como bot_params, posiciones_abiertas, TOTAL_BENEFICIO_ACUMULADO, transacciones_diarias.
shared_data_lock = threading.Lock()

# =================== MANEJADOR DE COMANDOS DE TELEGRAM ===================


def handle_telegram_commands():
    """
    Procesa los comandos recibidos por Telegram en cada ciclo de escucha.
    Analiza el texto del mensaje, identifica el comando y ejecuta la función correspondiente.
    También actualiza las variables globales de los parámetros del bot y los guarda si son modificados.
    """
    # Declara las variables globales que esta función puede modificar.
    global last_update_id, RIESGO_POR_OPERACION_PORCENTAJE, TAKE_PROFIT_PORCENTAJE, \
        STOP_LOSS_PORCENTAJE, TRAILING_STOP_PORCENTAJE, EMA_CORTA_PERIODO, EMA_MEDIA_PERIODO, EMA_LARGA_PERIODO, RSI_PERIODO, \
        RSI_UMBRAL_SOBRECOMPRA, INTERVALO, bot_params, TOTAL_BENEFICIO_ACUMULADO, \
        posiciones_abiertas, transacciones_diarias

    # Obtiene las actualizaciones de Telegram, comenzando desde el último ID procesado.
    updates = telegram_handler.get_telegram_updates(
        last_update_id + 1, TELEGRAM_BOT_TOKEN)

    # Si hay actualizaciones y la respuesta es exitosa.
    if updates and updates['ok']:
        # Itera sobre cada actualización recibida.
        for update in updates['result']:
            # Actualiza el ID del último mensaje procesado.
            last_update_id = update['update_id']

            # Si la actualización es un mensaje de texto.
            if 'message' in update and 'text' in update['message']:
                # Obtiene el ID del chat.
                chat_id = str(update['message']['chat']['id'])
                # Obtiene el texto del mensaje y elimina espacios en blanco.
                text = update['message']['text'].strip()

                # Verifica si el chat ID del mensaje es el autorizado.
                if chat_id != TELEGRAM_CHAT_ID:
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"⚠️ Comando recibido de chat no autorizado: <code>{chat_id}</code>")
                    logging.warning(
                        f"Comando de chat no autorizado: {chat_id}")
                    continue  # Ignora el mensaje si no es del chat autorizado.

                # Divide el texto del mensaje en partes para extraer el comando.
                parts = text.split()
                # El primer elemento es el comando, convertido a minúsculas.
                command = parts[0].lower()

                # Registra el comando recibido.
                logging.info(f"Comando Telegram recibido: {text}")

                try:
                    # --- Comandos para mostrar/ocultar el teclado personalizado de Telegram ---
                    if command == "/start" or command == "/menu":
                        telegram_handler.send_keyboard_menu(
                            TELEGRAM_BOT_TOKEN, chat_id, "¡Hola! Soy tu bot de trading. Selecciona una opción del teclado o usa /help.")
                    elif command == "/hide_menu":
                        telegram_handler.remove_keyboard_menu(
                            TELEGRAM_BOT_TOKEN, chat_id)

                    # --- Comandos para establecer parámetros de estrategia (modifican config.json/Firestore) ---
                    # Todas las modificaciones de bot_params están protegidas por el lock para evitar condiciones de carrera.
                    elif command == "/set_tp":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                TAKE_PROFIT_PORCENTAJE = new_value
                                bot_params['TAKE_PROFIT_PORCENTAJE'] = new_value
                                # Guarda los parámetros actualizados.
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ TP establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_tp &lt;porcentaje_decimal_ej_0.03&gt;</code>")
                    elif command == "/set_sl_fijo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                STOP_LOSS_PORCENTAJE = new_value
                                bot_params['STOP_LOSS_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ SL Fijo establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_sl_fijo &lt;porcentaje_decimal_ej_0.02&gt;</code>")
                    elif command == "/set_tsl":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                TRAILING_STOP_PORCENTAJE = new_value
                                bot_params['TRAILING_STOP_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ TSL establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_tsl &lt;porcentaje_decimal_ej_0.015&gt;</code>")
                    elif command == "/set_riesgo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                RIESGO_POR_OPERACION_PORCENTAJE = new_value
                                bot_params['RIESGO_POR_OPERACION_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Riesgo por operación establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_riesgo &lt;porcentaje_decimal_ej_0.01&gt;</code>")
                    elif command == "/set_ema_corta_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                EMA_CORTA_PERIODO = new_value
                                bot_params['EMA_CORTA_PERIODO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Período EMA Corta establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_ema_corta_periodo &lt;numero_entero_ej_20&gt;</code>")
                    # Comando para EMA Media.
                    elif command == "/set_ema_media_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                EMA_MEDIA_PERIODO = new_value
                                bot_params['EMA_MEDIA_PERIODO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Período EMA Media establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_ema_media_periodo &lt;numero_entero_ej_50&gt;</code>")
                    elif command == "/set_ema_larga_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                EMA_LARGA_PERIODO = new_value
                                bot_params['EMA_LARGA_PERIODO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Período EMA Larga establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_ema_larga_periodo &lt;numero_entero_ej_200&gt;</code>")
                    elif command == "/set_rsi_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                RSI_PERIODO = new_value
                                bot_params['RSI_PERIODO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Período RSI establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_rsi_periodo &lt;numero_entero_ej_14&gt;</code>")
                    elif command == "/set_rsi_umbral":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                RSI_UMBRAL_SOBRECOMPRA = new_value
                                bot_params['RSI_UMBRAL_SOBRECOMPRA'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Umbral RSI sobrecompra establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_rsi_umbral &lt;numero_entero_ej_70&gt;</code>")
                    elif command == "/set_intervalo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                INTERVALO = new_value
                                bot_params['INTERVALO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Intervalo del ciclo establecido en: <b>{new_value}</b> segundos")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_intervalo &lt;segundos_ej_300&gt;</code>")
                    elif command == "/set_breakeven_porcentaje":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock:  # Protege el acceso a bot_params.
                                BREAKEVEN_PORCENTAJE = new_value
                                bot_params['BREAKEVEN_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Porcentaje de Breakeven establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_breakeven_porcentaje &lt;porcentaje_decimal_ej_0.005&gt;</code>")

                    # --- Comandos de información y utilidades ---
                    # Muestra todos los parámetros actuales del bot.
                    elif command == "/get_params":
                        with shared_data_lock:  # Lee los parámetros con el bloqueo.
                            current_params_msg = "<b>Parámetros Actuales:</b>\n"
                            for key, value in bot_params.items():
                                if isinstance(value, float) and 'PORCENTAJE' in key.upper():
                                    current_params_msg += f"- {key}: {value:.4f}\n"
                                else:
                                    current_params_msg += f"- {key}: {value}\n"
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, current_params_msg)
                    # Genera y envía un informe CSV de transacciones.
                    elif command == "/csv":
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "Generando informe CSV. Esto puede tardar un momento...")
                        # Accede a transacciones_diarias con el bloqueo (aunque ahora lee de Firestore).
                        with shared_data_lock:
                            # La función generar_y_enviar_csv_ahora leerá directamente de Firestore.
                            reporting_manager.generar_y_enviar_csv_ahora(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                    # Muestra el mensaje de ayuda con todos los comandos.
                    elif command == "/help":
                        telegram_handler.send_help_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                        telegram_handler.send_keyboard_menu(
                            TELEGRAM_BOT_TOKEN, chat_id, "Aquí tienes los comandos disponibles. También puedes usar el teclado de abajo:")
                    # Permite vender una posición manualmente.
                    elif command == "/vender":
                        if len(parts) == 2:
                            # Obtiene el símbolo a vender.
                            symbol_to_sell = parts[1].upper()
                            # Asegurarse de que el símbolo esté en la lista de monitoreo FILTRADA.
                            if symbol_to_sell in SYMBOLS:
                                # Protege el acceso a posiciones_abiertas y variables de beneficio.
                                with shared_data_lock:
                                    trading_logic.vender_por_comando(
                                        # transacciones_diarias ya no es tan relevante aquí.
                                        client, symbol_to_sell, posiciones_abiertas, transacciones_diarias,
                                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE,
                                        TOTAL_BENEFICIO_ACUMULADO, bot_params, config_manager
                                    )
                                    # Actualizar TOTAL_BENEFICIO_ACUMULADO después de la venta, ya que trading_logic lo modifica en bot_params.
                                    TOTAL_BENEFICIO_ACUMULADO = bot_params['TOTAL_BENEFICIO_ACUMULADO']
                            else:
                                telegram_handler.send_telegram_message(
                                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ Símbolo <b>{symbol_to_sell}</b> no reconocido o no monitoreado por el bot.")
                        else:
                            telegram_handler.send_telegram_message(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/vender &lt;SIMBOLO_USDT&gt;</code> (ej. /vender BTCUSDT)")
                    # Muestra el beneficio total acumulado.
                    elif command == "/beneficio":
                        with shared_data_lock:  # Accede a TOTAL_BENEFICIO_ACUMULADO con el bloqueo.
                            reporting_manager.send_beneficio_message(
                                client, TOTAL_BENEFICIO_ACUMULADO, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                    # Muestra el contenido del archivo de posiciones abiertas (para depuración).
                    elif command == "/get_positions_file":
                        with shared_data_lock:  # Accede a OPEN_POSITIONS_FILE con el bloqueo.
                            telegram_handler.send_positions_file_content(
                                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE)
                    # Comando para mostrar resumen de posiciones.
                    elif command == "/posiciones_actuales":
                        with shared_data_lock:  # Protege el acceso a posiciones_abiertas.
                            telegram_handler.send_current_positions_summary(
                                client, posiciones_abiertas, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                    # Comando para resetear el beneficio acumulado.
                    elif command == "/reset_beneficio":
                        with shared_data_lock:
                            TOTAL_BENEFICIO_ACUMULADO = 0.0
                            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = 0.0
                            # Guardar en Firestore/local.
                            config_manager.save_parameters(bot_params)
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "✅ Beneficio acumulado reseteado a cero.")
                        logging.info(
                            "Beneficio acumulado reseteado a cero por comando de Telegram.")
                    else:  # Comando no reconocido.
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "Comando desconocido. Usa <code>/help</code> para ver los comandos disponibles.")

                # Maneja errores cuando los valores introducidos no son válidos (ej. texto en lugar de número).
                except ValueError:
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Valor inválido. Asegúrate de introducir un número o porcentaje correcto.")
                # Captura cualquier otra excepción durante el procesamiento de comandos.
                except Exception as ex:
                    # Registra el error completo.
                    logging.error(
                        f"Error procesando comando '{text}': {ex}", exc_info=True)
                    # Envía un mensaje de error a Telegram.
                    telegram_handler.send_telegram_message(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ Error interno al procesar comando: {ex}")

# Función que se ejecutará en el hilo separado para escuchar Telegram.


def telegram_listener(stop_event):
    """
    Función que se ejecuta en un hilo separado para escuchar y procesar comandos de Telegram.
    Utiliza un stop_event para saber cuándo debe detenerse.
    """
    global last_update_id  # Necesario para mantener el offset de los mensajes de Telegram.
    # El bucle se ejecuta hasta que el evento de parada se activa.
    while not stop_event.is_set():
        try:
            # handle_telegram_commands ya contiene la lógica para obtener y procesar actualizaciones.
            # Todas las modificaciones a variables globales dentro de handle_telegram_commands
            # ya están protegidas por 'shared_data_lock'.
            handle_telegram_commands()
            # Espera un corto intervalo antes de la siguiente consulta a Telegram.
            time.sleep(TELEGRAM_LISTEN_INTERVAL)
        except Exception as e:
            logging.error(f"Error en el hilo de Telegram: {e}", exc_info=True)
            # Espera un poco más en caso de error para evitar bucles rápidos.
            time.sleep(TELEGRAM_LISTEN_INTERVAL * 2)

# =================== BUCLE PRINCIPAL DEL BOT ===================


# Configurar el menú de comandos de Telegram al inicio del bot.
telegram_handler.set_telegram_commands_menu(TELEGRAM_BOT_TOKEN)

# Mensaje de inicio del bot.
logging.info("Bot iniciado. Esperando comandos y monitoreando el mercado...")

# Crear y arrancar el hilo de Telegram.
# Crea un evento para señalar al hilo de Telegram que debe detenerse.
telegram_stop_event = threading.Event()
# Crea el hilo, pasando la función y el evento.
telegram_thread = threading.Thread(
    target=telegram_listener, args=(telegram_stop_event,))
telegram_thread.start()  # Inicia el hilo en segundo plano.

try:
    while True:  # Bucle infinito que mantiene el bot en funcionamiento.
        # Registra el tiempo de inicio de cada ciclo principal.
        start_time_cycle = time.time()

        # --- Lógica del Informe Diario ---
        hoy = time.strftime("%Y-%m-%d")

        # Comprueba si es un nuevo día o si es la primera ejecución para enviar el informe diario.
        if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
            # Si ya se había enviado un informe antes (no es la primera ejecución).
            if ultima_fecha_informe_enviado is not None:
                telegram_handler.send_telegram_message(
                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"Preparando informe del día {ultima_fecha_informe_enviado}...")
                with shared_data_lock:  # Protege el acceso a transacciones_diarias.
                    # Ahora, enviar_informe_diario leerá de Firestore.
                    # No necesita transacciones_diarias.
                    reporting_manager.enviar_informe_diario(
                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

            # Actualiza la fecha del último informe enviado a la fecha actual.
            ultima_fecha_informe_enviado = hoy
            with shared_data_lock:  # Protege la limpieza de transacciones_diarias.
                # Limpia la lista de transacciones diarias para el nuevo día.
                transacciones_diarias.clear()

        # --- PROACTIVE POSITION CLEANUP BASED ON ACTUAL BINANCE BALANCES ---
        # Esto asegura que el estado interno del bot refleje la realidad antes de procesar.
        symbols_to_remove = []
        with shared_data_lock:
            # Itera sobre una copia para permitir la modificación.
            for symbol, data in list(posiciones_abiertas.items()):
                base_asset = symbol.replace("USDT", "")
                actual_balance = binance_utils.obtener_saldo_moneda(
                    client, base_asset)

                # Obtiene información del símbolo para verificar min_qty para el par.
                info = client.get_symbol_info(symbol)
                min_qty = 0.0
                for f in info['filters']:
                    if f['filterType'] == 'LOT_SIZE':
                        min_qty = float(f['minQty'])
                        # Se encontró el filtro LOT_SIZE, no es necesario seguir buscando.
                        break

                # Define un pequeño umbral para considerar un saldo "demasiado pequeño".
                # Usar min_qty para el activo específico es más preciso.
                # Usa el min_qty de Binance o un número muy pequeño.
                threshold = max(min_qty, 0.00000001)

                if actual_balance < threshold:
                    logging.warning(
                        f"⚠️ Saldo real de {base_asset} ({actual_balance:.8f}) para {symbol} es demasiado bajo (umbral: {threshold:.8f}). Marcando posición para eliminación.")
                    symbols_to_remove.append(symbol)

            for symbol in symbols_to_remove:
                # Elimina la posición del diccionario interno del bot.
                del posiciones_abiertas[symbol]
                # Guarda los cambios en las posiciones.
                position_manager.save_open_positions_debounced(
                    posiciones_abiertas)
                telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
                                                       f"🗑️ Posición de <b>{symbol}</b> eliminada del registro del bot debido a saldo insuficiente en Binance.")
                logging.info(
                    f"Posición de {symbol} eliminada del registro interno debido a saldo real insuficiente.")
        # --- FIN DE LA LIMPIEZA PROACTIVA ---

        # --- LÓGICA PRINCIPAL DE TRADING ---
        # Ejecuta la lógica de trading solo si ha pasado el INTERVALO de tiempo configurado.
        if (time.time() - last_trading_check_time) >= INTERVALO:
            logging.info(
                f"Iniciando ciclo de trading principal (cada {INTERVALO}s)...")
            # Variable para acumular mensajes de resumen del ciclo.
            general_message = ""

            # Obtener el capital total una vez por ciclo para usarlo en el cálculo de la cantidad a comprar.
            with shared_data_lock:  # Protege el acceso a posiciones_abiertas.
                total_capital = binance_utils.get_total_capital_usdt(
                    client, posiciones_abiertas)

            for symbol in SYMBOLS:  # Itera sobre cada símbolo de trading configurado.
                # Extrae la criptomoneda base (ej. BTC de BTCUSDT).
                base = symbol.replace("USDT", "")

                # Obtener el saldo USDT más reciente para cada símbolo.
                saldo_usdt = binance_utils.obtener_saldo_moneda(client, "USDT")

                # Las siguientes llamadas a binance_utils y trading_logic.calcular_ema_rsi
                # no modifican directamente las variables globales compartidas, solo las leen
                # o interactúan con el cliente de Binance, que es thread-safe en sus llamadas API.
                saldo_base = binance_utils.obtener_saldo_moneda(client, base)
                precio_actual = binance_utils.obtener_precio_actual(
                    client, symbol)

                # Llamada a calcular_ema_rsi con tres períodos de EMA.
                ema_corta_valor, ema_media_valor, ema_larga_valor, rsi_valor = trading_logic.calcular_ema_rsi(
                    client, symbol, EMA_CORTA_PERIODO, EMA_MEDIA_PERIODO, EMA_LARGA_PERIODO, RSI_PERIODO
                )

                if ema_corta_valor is None or ema_media_valor is None or ema_larga_valor is None or rsi_valor is None:
                    logging.warning(
                        f"⚠️ No se pudieron calcular EMA(s) o RSI para {symbol}. Saltando este símbolo en este ciclo.")
                    continue

                # =================== Lógica de Detección de Tendencia ===================
                trend_emoji = "ǁ"  # Emoji por defecto para lateral.
                trend_text = "Lateral/Consolidación"

                if ema_corta_valor > ema_media_valor and ema_media_valor > ema_larga_valor:
                    trend_emoji = "📈"
                    trend_text = "Alcista"
                elif ema_corta_valor < ema_media_valor and ema_media_valor < ema_larga_valor:
                    trend_emoji = "📉"
                    trend_text = "Bajista"
                # =========================================================================

                # Construye un mensaje de estado para el símbolo actual.
                mensaje_simbolo = (
                    f"📊 <b>{symbol}</b>\n"
                    f"Precio actual: {precio_actual:.2f} USDT\n"
                    f"EMA Corta ({EMA_CORTA_PERIODO}m): {ema_corta_valor:.2f}\n"
                    f"EMA Media ({EMA_MEDIA_PERIODO}m): {ema_media_valor:.2f}\n"
                    f"EMA Larga ({EMA_LARGA_PERIODO}m): {ema_larga_valor:.2f}\n"
                    f"RSI ({RSI_PERIODO}m): {rsi_valor:.2f}\n"
                    # Muestra tendencia con emoji y texto.
                    f"Tend: {trend_emoji} <b>{trend_text}</b>"
                )

                # --- LÓGICA DE COMPRA ---
                # Condiciones para entrar en una posición (compra):
                # 1. Saldo USDT suficiente (>10).
                # 2. Precio actual por encima de la EMA corta (tendencia alcista a corto plazo).
                # 3. EMA corta por encima de la EMA media (confirmación de impulso).
                # 4. EMA media por encima de la EMA larga (tendencia alcista general - FILTRO CLAVE).
                # 5. RSI por debajo del umbral de sobrecompra (no sobrecomprado).
                # 6. No hay una posición abierta para este símbolo.
                # 7. La tendencia detectada es "Alcista".
                if (saldo_usdt > 10 and  # Mantener un umbral mínimo para evitar micro-compras.
                    precio_actual > ema_corta_valor and
                    # Filtro de cruce de EMA corta sobre media.
                    ema_corta_valor > ema_media_valor and
                    # Filtro de tendencia alcista general (EMA media sobre EMA larga).
                    ema_media_valor > ema_larga_valor and
                    rsi_valor < RSI_UMBRAL_SOBRECOMPRA and
                    symbol not in posiciones_abiertas and
                        trend_text == "Alcista"):  # Solo comprar si la tendencia general es alcista.

                    # Calcula la cantidad a comprar utilizando trading_logic.
                    cantidad = trading_logic.calcular_cantidad_a_comprar(
                        client, saldo_usdt, precio_actual, STOP_LOSS_PORCENTAJE, symbol, RIESGO_POR_OPERACION_PORCENTAJE, total_capital
                    )

                    if cantidad > 0:  # Si la cantidad a comprar es válida.
                        with shared_data_lock:  # Protege el acceso a posiciones_abiertas y transacciones_diarias.
                            orden = trading_logic.comprar(
                                client, symbol, cantidad, posiciones_abiertas, STOP_LOSS_PORCENTAJE,
                                transacciones_diarias, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE
                            )
                        if orden:  # Si la orden de compra fue exitosa.
                            precio_ejecucion = float(
                                orden['fills'][0]['price'])
                            cantidad_comprada_real = float(
                                orden['fills'][0]['qty'])

                            mensaje_simbolo += f"\n✅ COMPRA ejecutada a {precio_ejecucion:.2f} USDT"

                            capital_invertido_usd = precio_ejecucion * cantidad_comprada_real
                            # Usa total_capital.
                            riesgo_max_trade_usd = total_capital * RIESGO_POR_OPERACION_PORCENTAJE
                            mensaje_simbolo += (
                                f"\nCantidad comprada: {cantidad_comprada_real:.6f} {base}"
                                f"\nInversión en este trade: {capital_invertido_usd:.2f} USDT"
                                f"\nRiesgo Máx. Permitido por Trade: {riesgo_max_trade_usd:.2f} USDT"
                            )
                        else:  # Si la orden de compra falló.
                            mensaje_simbolo += f"\n❌ COMPRA fallida para {symbol}."
                    else:  # Si no hay suficiente capital o la cantidad es muy pequeña.
                        mensaje_simbolo += f"\n⚠️ No hay suficiente capital o cantidad mínima para comprar {symbol} con el riesgo definido."

                # --- LÓGICA DE VENTA (Take Profit, Stop Loss Fijo, Trailing Stop Loss, Breakeven) ---
                # Si ya hay una posición abierta para este símbolo.
                elif symbol in posiciones_abiertas:
                    # Se hace una copia de la posición para leerla, las modificaciones se harán bajo el lock.
                    posicion = posiciones_abiertas[symbol].copy()
                    # Precio al que se compró.
                    precio_compra = posicion['precio_compra']
                    # Cantidad de la criptomoneda en la posición.
                    cantidad_en_posicion = posicion['cantidad_base']
                    # Precio máximo que ha alcanzado la criptomoneda desde la compra.
                    max_precio_alcanzado = posicion['max_precio_alcanzado']

                    # Calcula el nivel del Stop Loss fijo.
                    stop_loss_fijo_nivel = precio_compra * \
                        (1 - STOP_LOSS_PORCENTAJE)

                    # Actualiza el precio máximo alcanzado si el precio actual es mayor.
                    if precio_actual > max_precio_alcanzado:
                        with shared_data_lock:  # Protege la modificación de posiciones_abiertas.
                            posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                            # Actualiza la variable local para el resto del ciclo.
                            max_precio_alcanzado = precio_actual
                            # Guarda la actualización de la posición.
                            position_manager.save_open_positions_debounced(
                                posiciones_abiertas)

                    # --- Lógica de Stop Loss a Breakeven ---
                    # Calcula el nivel para mover a Breakeven.
                    breakeven_nivel_real = precio_compra * \
                        (1 + BREAKEVEN_PORCENTAJE)

                    # Si el precio actual alcanza el nivel de Breakeven y aún no se ha movido el SL.
                    if (precio_actual >= breakeven_nivel_real and
                            not posicion['sl_moved_to_breakeven']):

                        with shared_data_lock:  # Protege la modificación de posiciones_abiertas.
                            # Mueve el Stop Loss al nivel de Breakeven (o lo mantiene si el fijo es más alto).
                            posiciones_abiertas[symbol]['stop_loss_fijo_nivel_actual'] = max(
                                stop_loss_fijo_nivel, breakeven_nivel_real)
                            # Marca que el SL ya se movió a Breakeven.
                            posiciones_abiertas[symbol]['sl_moved_to_breakeven'] = True
                        telegram_handler.send_telegram_message(
                            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"🔔 SL de <b>{symbol}</b> movido a Breakeven: <b>{breakeven_nivel_real:.2f}</b>")
                        logging.info(
                            f"SL de {symbol} movido a Breakeven: {breakeven_nivel_real:.2f}")
                        with shared_data_lock:  # Protege la modificación de posiciones_abiertas.
                            # Guarda la actualización de la posición.
                            position_manager.save_open_positions_debounced(
                                posiciones_abiertas)

                    # --- Niveles de Salida ---
                    # Obtiene el nivel de Stop Loss actual (fijo o breakeven).
                    # Se lee dentro del lock para asegurar que se obtiene el valor más reciente.
                    with shared_data_lock:
                        current_stop_loss_level = posiciones_abiertas[symbol].get(
                            'stop_loss_fijo_nivel_actual', stop_loss_fijo_nivel)

                    # Calcula el nivel de Take Profit.
                    take_profit_nivel = precio_compra * \
                        (1 + TAKE_PROFIT_PORCENTAJE)
                    # Calcula el nivel de Trailing Stop.
                    trailing_stop_nivel = max_precio_alcanzado * \
                        (1 - TRAILING_STOP_PORCENTAJE)

                    # Obtiene la tasa de conversión USDT a EUR.
                    eur_usdt_conversion_rate = binance_utils.obtener_precio_eur(
                        client)
                    # Calcula el saldo invertido en USDT.
                    saldo_invertido_usdt = precio_compra * cantidad_en_posicion
                    # Calcula el saldo invertido en EUR.
                    saldo_invertido_eur = saldo_invertido_usdt * \
                        eur_usdt_conversion_rate if eur_usdt_conversion_rate else 0

                    # Añade información de la posición al mensaje del símbolo.
                    mensaje_simbolo += (
                        f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                        f"TP: {take_profit_nivel:.2f} | SL Fijo: {current_stop_loss_level:.2f}\n"
                        f"Max Alcanzado: {max_precio_alcanzado:.2f} | TSL: {trailing_stop_nivel:.2f}\n"
                        f"Saldo USDT Invertido (Entrada): {saldo_invertido_usdt:.2f}\n"
                        f"SEI: {saldo_invertido_eur:.2f}"
                    )

                    # Bandera para indicar si se debe vender.
                    vender_ahora = False
                    motivo_venta = ""  # Motivo de la venta.

                    # --- Condiciones para vender ---
                    if precio_actual >= take_profit_nivel:  # Si el precio alcanza el Take Profit.
                        vender_ahora = True
                        motivo_venta = "TAKE PROFIT alcanzado"
                    # Si el precio cae al Stop Loss (fijo o breakeven).
                    elif precio_actual <= current_stop_loss_level:
                        vender_ahora = True
                        motivo_venta = "STOP LOSS FIJO alcanzado (o Breakeven)"
                    # Si el precio cae y activa el Trailing Stop.
                    elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra):
                        vender_ahora = True
                        motivo_venta = "TRAILING STOP LOSS activado"

                    if vender_ahora:  # Si alguna condición de venta se cumple.
                        # Ajusta la cantidad a vender basándose en el saldo real y el step_size de Binance.
                        cantidad_a_vender_real = binance_utils.ajustar_cantidad(binance_utils.obtener_saldo_moneda(
                            client, base), binance_utils.get_step_size(client, symbol))

                        if cantidad_a_vender_real > 0:  # Si la cantidad a vender es válida.
                            # Protege el acceso a posiciones_abiertas, TOTAL_BENEFICIO_ACUMULADO, bot_params y transacciones_diarias.
                            with shared_data_lock:
                                orden = trading_logic.vender(
                                    client, symbol, cantidad_a_vender_real, posiciones_abiertas,
                                    TOTAL_BENEFICIO_ACUMULADO, bot_params, transacciones_diarias,
                                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE, config_manager,
                                    # Pasa el motivo_venta a la función vender.
                                    motivo_venta
                                )
                                # Actualizar TOTAL_BENEFICIO_ACUMULADO después de la venta, ya que trading_logic lo modifica en bot_params.
                                TOTAL_BENEFICIO_ACUMULADO = bot_params['TOTAL_BENEFICIO_ACUMULADO']

                            if orden:  # Si la orden de venta fue exitosa.
                                salida = float(orden['fills'][0]['price'])
                                ganancia = (salida - precio_compra) * \
                                    cantidad_a_vender_real
                                mensaje_simbolo += (
                                    f"\n✅ VENTA ejecutada por {motivo_venta} a {salida:.2f} USDT\n"
                                    f"Ganancia/Pérdida: {ganancia:.2f} USDT"
                                )
                            else:  # Si la orden de venta falló.
                                mensaje_simbolo += f"\n❌ VENTA fallida para {symbol}."
                        else:  # Si no hay saldo de la criptomoneda para vender.
                            mensaje_simbolo += f"\n⚠️ No hay {base} disponible para vender o cantidad muy pequeña."

                # Añade el resumen de saldos al mensaje del símbolo.
                with shared_data_lock:  # Protege el acceso a posiciones_abiertas.
                    mensaje_simbolo += "\n" + \
                        binance_utils.obtener_saldos_formateados(
                            client, posiciones_abiertas)
                # Acumula el mensaje del símbolo al mensaje general.
                general_message += mensaje_simbolo + "\n\n"

            telegram_handler.send_telegram_message(
                TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, general_message)
            # Actualiza la marca de tiempo del último chequeo de trading.
            last_trading_check_time = time.time()

        # --- GESTIÓN DEL TIEMPO ENTRE CICLOS ---
        # Calcula el tiempo transcurrido en el ciclo actual.
        time_elapsed_overall = time.time() - start_time_cycle
        # El hilo principal ahora solo se detiene por el INTERVALO de trading, el hilo de Telegram es independiente.
        sleep_duration = max(0, INTERVALO - time_elapsed_overall)
        print(
            f"⏳ Próxima revisión en {sleep_duration:.0f} segundos (Ciclo de trading)...\n")
        # Pausa el bot por el tiempo restante para mantener el intervalo.
        time.sleep(sleep_duration)

except KeyboardInterrupt:
    logging.info(
        "Detectado KeyboardInterrupt. Señalando al hilo de Telegram para detenerse...")
    telegram_stop_event.set()  # Señala al hilo de Telegram que debe detenerse.
    # Espera a que el hilo de Telegram termine su ejecución.
    telegram_thread.join()
    logging.info("Bot detenido.")
except Exception as e:  # Captura cualquier excepción general en el bucle principal.
    logging.error(f"Error general en el bot: {e}", exc_info=True)
    with shared_data_lock:  # Protege el acceso a posiciones_abiertas.
        telegram_handler.send_telegram_message(
            TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ Error general en el bot: {e}\n\n{binance_utils.obtener_saldos_formateados(client, posiciones_abiertas)}")
    print(f"❌ Error general en el bot: {e}")  # Imprime el error en la consola.
    # En caso de un error inesperado, también se intenta detener el hilo de Telegram.
    telegram_stop_event.set()
    telegram_thread.join()
