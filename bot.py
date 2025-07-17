import os # Importa el módulo os para interactuar con el sistema operativo, como acceder a variables de entorno.
import time # Importa el módulo time para funciones relacionadas con el tiempo, como pausas (sleep).
import logging # Importa el módulo logging para registrar eventos y mensajes del bot.
import json # Importa el módulo json para trabajar con datos en formato JSON (guardar/cargar configuraciones).
import csv # Importa el módulo csv para trabajar con archivos CSV (generar informes de transacciones).
from binance.client import Client # Importa la clase Client del SDK de Binance para interactuar con la API.
from binance.enums import * # Importa todas las enumeraciones de Binance (ej. KLINE_INTERVAL_1MINUTE) para mayor comodidad.
from datetime import datetime, timedelta # Importa datetime para trabajar con fechas y horas, y timedelta para cálculos de tiempo.
import threading # Importa el módulo threading para trabajar con hilos.

# Importa los módulos refactorizados que contienen la lógica modularizada del bot.
import config_manager # Módulo para gestionar la configuración del bot (cargar/guardar parámetros).
import position_manager # Módulo para gestionar las posiciones abiertas del bot (cargar/guardar, debounce).
import telegram_handler # Módulo para todas las interacciones con la API de Telegram (enviar mensajes, gestionar comandos).
import binance_utils # Módulo con funciones auxiliares para interactuar con la API de Binance (saldos, precios, stepSize).
import trading_logic # Módulo que contiene la lógica principal de trading (cálculo de indicadores, compra/venta).
import reporting_manager # Módulo para la generación y envío de informes (CSV, mensajes de beneficio).

# --- Configuración de Logging ---
# Configura el sistema de registro básico para el bot. Los mensajes se mostrarán en la consola.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =================== CONFIGURACIÓN (Asegúrate de que estas variables de entorno estén configuradas) ===================

# Claves de API de Binance. ¡NO COMPARTAS ESTAS CLAVES!
# Se obtienen de las variables de entorno para mayor seguridad.
API_KEY = os.getenv("BINANCE_API_KEY") # Clave API para autenticación en Binance.
API_SECRET = os.getenv("BINANCE_API_SECRET") # Clave secreta para autenticación en Binance.

# NUEVO: Log para depurar la carga de la API Key
if API_KEY:
    logging.info(f"API_KEY cargada (primeros 5 caracteres): {API_KEY[:5]}*****")
else:
    logging.warning("API_KEY no cargada desde las variables de entorno.")
if API_SECRET:
    logging.info(f"API_SECRET cargada (primeros 5 caracteres): {API_SECRET[:5]}*****")
else:
    logging.warning("API_SECRET no cargada desde las variables de entorno.")


# Token de tu bot de Telegram y Chat ID para enviar mensajes.
# Se obtienen de las variables de entorno.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN") # Token único de tu bot de Telegram.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID") # ID del chat donde el bot enviará mensajes.

# Archivos para guardar y cargar las posiciones del bot.
OPEN_POSITIONS_FILE = "open_positions.json" # Nombre del archivo JSON para guardar las posiciones abiertas.

# =================== CARGA DE PARÁMETROS DESDE config_manager ===================

# Cargar parámetros al inicio del bot utilizando el nuevo módulo config_manager.
bot_params = config_manager.load_parameters() # Carga la configuración del bot desde 'config.json'.

# Asignar los valores del diccionario cargado a las variables globales del bot.
# Estos parámetros controlan la estrategia de trading y el comportamiento del bot.
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT","XRPUSDT", "DOGEUSDT", "MATICUSDT"] # Lista de pares de trading a monitorear.
INTERVALO = bot_params["INTERVALO"] # Intervalo de tiempo en segundos entre cada ciclo de trading principal.
RIESGO_POR_OPERACION_PORCENTAJE = bot_params["RIESGO_POR_OPERACION_PORCENTAJE"] # Porcentaje del capital total a arriesgar por operación.
TAKE_PROFIT_PORCENTAJE = bot_params["TAKE_PROFIT_PORCENTAJE"] # Porcentaje de ganancia para cerrar una posición (Take Profit).
STOP_LOSS_PORCENTAJE = bot_params["STOP_LOSS_PORCENTAJE"] # Porcentaje de pérdida para cerrar una posición (Stop Loss fijo).
TRAILING_STOP_PORCENTAJE = bot_params["TRAILING_STOP_PORCENTAJE"] # Porcentaje para activar el Trailing Stop Loss.
EMA_PERIODO = bot_params["EMA_PERIODO"] # Período para el cálculo de la Media Móvil Exponencial (EMA).
RSI_PERIODO = bot_params["RSI_PERIODO"] # Período para el cálculo del Índice de Fuerza Relativa (RSI).
RSI_UMBRAL_SOBRECOMPRA = bot_params["RSI_UMBRAL_SOBRECOMPRA"] # Umbral superior del RSI para identificar condiciones de sobrecompra.
TOTAL_BENEFICIO_ACUMULADO = bot_params["TOTAL_BENEFICIO_ACUMULADO"] # Beneficio total acumulado por el bot desde su inicio.
BREAKEVEN_PORCENTAJE = bot_params["BREAKEVEN_PORCENTAJE"] # Porcentaje de ganancia para mover el Stop Loss a Breakeven.

# =================== INICIALIZACIÓN DE CLIENTES BINANCE Y TELEGRAM ===================

# Inicializa el cliente de la API de Binance.
client = Client(API_KEY, API_SECRET, testnet=True) # Crea una instancia del cliente de Binance con las claves API.
client.API_URL = 'https://testnet.binance.vision/api' # Configura la URL de la API para usar la red de prueba (Testnet) de Binance.

# Diccionario para almacenar las posiciones que el bot tiene abiertas y está gestionando.
# Se carga desde el archivo de persistencia al inicio.
posiciones_abiertas = position_manager.load_open_positions(STOP_LOSS_PORCENTAJE) # Carga las posiciones guardadas, aplicando el SL inicial.

# Variables para la gestión de la comunicación con Telegram
last_update_id = 0 # ID del último mensaje procesado de Telegram para evitar duplicados.
TELEGRAM_LISTEN_INTERVAL = 5 # Intervalo de tiempo en segundos para verificar nuevos comandos de Telegram.

# Variables para la gestión de informes diarios
transacciones_diarias = [] # Lista para almacenar las transacciones realizadas en el día actual.
ultima_fecha_informe_enviado = None # Almacena la fecha del último informe diario enviado.
last_trading_check_time = 0 # Marca de tiempo de la última vez que se ejecutó la lógica de trading principal.

# Objeto Lock para proteger el acceso a variables compartidas entre hilos
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
           STOP_LOSS_PORCENTAJE, TRAILING_STOP_PORCENTAJE, EMA_PERIODO, RSI_PERIODO, \
           RSI_UMBRAL_SOBRECOMPRA, INTERVALO, bot_params, TOTAL_BENEFICIO_ACUMULADO

    updates = telegram_handler.get_telegram_updates(TELEGRAM_BOT_TOKEN, last_update_id + 1)

    if updates and updates['ok']:
        for update in updates['result']: # Itera sobre cada actualización recibida.
            last_update_id = update['update_id'] # Actualiza el ID del último mensaje procesado.

            if 'message' in update and 'text' in update['message']: # Si la actualización es un mensaje de texto.
                chat_id = str(update['message']['chat']['id']) # Obtiene el ID del chat.
                text = update['message']['text'].strip() # Obtiene el texto del mensaje y elimina espacios en blanco.
                
                # Verifica si el chat ID del mensaje es el autorizado.
                if chat_id != TELEGRAM_CHAT_ID:
                    telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"⚠️ Comando recibido de chat no autorizado: <code>{chat_id}</code>")
                    logging.warning(f"Comando de chat no autorizado: {chat_id}")
                    continue # Ignora el mensaje si no es del chat autorizado.

                parts = text.split() # Divide el texto del mensaje en partes para extraer el comando.
                command = parts[0].lower() # El primer elemento es el comando, convertido a minúsculas.
                
                logging.info(f"Comando Telegram recibido: {text}") # Registra el comando recibido.

                try:
                    # --- Comandos para mostrar/ocultar el teclado personalizado de Telegram ---
                    if command == "/start" or command == "/menu":
                        telegram_handler.send_keyboard_menu(TELEGRAM_BOT_TOKEN, chat_id, "¡Hola! Soy tu bot de trading. Selecciona una opción del teclado o usa /help.")
                    elif command == "/hide_menu":
                        telegram_handler.remove_keyboard_menu(TELEGRAM_BOT_TOKEN, chat_id)
                    
                    # --- Comandos para establecer parámetros de estrategia (modifican config.json) ---
                    # Ahora, todas las modificaciones de bot_params están protegidas por el lock.
                    elif command == "/set_tp":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                TAKE_PROFIT_PORCENTAJE = new_value
                                bot_params['TAKE_PROFIT_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params) # Guarda los parámetros actualizados.
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ TP establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_tp &lt;porcentaje_decimal_ej_0.03&gt;</code>")
                    elif command == "/set_sl_fijo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                STOP_LOSS_PORCENTAJE = new_value
                                bot_params['STOP_LOSS_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ SL Fijo establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_sl_fijo &lt;porcentaje_decimal_ej_0.02&gt;</code>")
                    elif command == "/set_tsl":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                TRAILING_STOP_PORCENTAJE = new_value
                                bot_params['TRAILING_STOP_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ TSL establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_tsl &lt;porcentaje_decimal_ej_0.015&gt;</code>")
                    elif command == "/set_riesgo":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                RIESGO_POR_OPERACION_PORCENTAJE = new_value
                                bot_params['RIESGO_POR_OPERACION_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Riesgo por operación establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_riesgo &lt;porcentaje_decimal_ej_0.01&gt;</code>")
                    elif command == "/set_ema_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                EMA_PERIODO = new_value
                                bot_params['EMA_PERIODO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Período EMA establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_ema_periodo &lt;numero_entero_ej_10&gt;</code>")
                    elif command == "/set_rsi_periodo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                RSI_PERIODO = new_value
                                bot_params['RSI_PERIODO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Período RSI establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_rsi_periodo &lt;numero_entero_ej_14&gt;</code>")
                    elif command == "/set_rsi_umbral":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                RSI_UMBRAL_SOBRECOMPRA = new_value
                                bot_params['RSI_UMBRAL_SOBRECOMPRA'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Umbral RSI sobrecompra establecido en: <b>{new_value}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_rsi_umbral &lt;numero_entero_ej_70&gt;</code>")
                    elif command == "/set_intervalo":
                        if len(parts) == 2:
                            new_value = int(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                INTERVALO = new_value
                                bot_params['INTERVALO'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Intervalo del ciclo establecido en: <b>{new_value}</b> segundos")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_intervalo &lt;segundos_ej_300&gt;</code>")
                    elif command == "/set_breakeven_porcentaje":
                        if len(parts) == 2:
                            new_value = float(parts[1])
                            with shared_data_lock: # Protege el acceso a bot_params
                                BREAKEVEN_PORCENTAJE = new_value
                                bot_params['BREAKEVEN_PORCENTAJE'] = new_value
                                config_manager.save_parameters(bot_params)
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ Porcentaje de Breakeven establecido en: <b>{new_value:.4f}</b>")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/set_breakeven_porcentaje &lt;porcentaje_decimal_ej_0.005&gt;</code>")
                    
                    # --- Comandos de información y utilidades ---
                    elif command == "/get_params": # Muestra todos los parámetros actuales del bot.
                        with shared_data_lock: # Lee los parámetros con el bloqueo
                            current_params_msg = "<b>Parámetros Actuales:</b>\n"
                            for key, value in bot_params.items():
                                if isinstance(value, float) and 'PORCENTAJE' in key.upper():
                                    current_params_msg += f"- {key}: {value:.4f}\n"
                                else:
                                    current_params_msg += f"- {key}: {value}\n"
                        telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, current_params_msg)
                    elif command == "/csv": # Genera y envía un informe CSV de transacciones.
                        telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "Generando informe CSV. Esto puede tardar un momento...")
                        with shared_data_lock: # Accede a transacciones_diarias con el bloqueo
                            reporting_manager.generar_y_enviar_csv_ahora(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, transacciones_diarias)
                    elif command == "/help": # Muestra el mensaje de ayuda con todos los comandos.
                        telegram_handler.send_help_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                        telegram_handler.send_keyboard_menu(TELEGRAM_BOT_TOKEN, chat_id, "Aquí tienes los comandos disponibles. También puedes usar el teclado de abajo:")
                    elif command == "/vender": # Permite vender una posición manualmente.
                        if len(parts) == 2:
                            symbol_to_sell = parts[1].upper() # Obtiene el símbolo a vender.
                            if symbol_to_sell in SYMBOLS: # Verifica que el símbolo esté en la lista de monitoreo.
                                with shared_data_lock: # Protege el acceso a posiciones_abiertas y variables de beneficio
                                    trading_logic.vender_por_comando(
                                        client, symbol_to_sell, posiciones_abiertas, transacciones_diarias,
                                        TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE,
                                        TOTAL_BENEFICIO_ACUMULADO, bot_params, config_manager
                                    )
                                    # Actualizar TOTAL_BENEFICIO_ACUMULADO después de la venta dentro del bloqueo
                                    # Esto es importante porque vender_por_comando actualiza bot_params['TOTAL_BENEFICIO_ACUMULADO']
                                    TOTAL_BENEFICIO_ACUMULADO = bot_params['TOTAL_BENEFICIO_ACUMULADO']
                            else:
                                telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ Símbolo <b>{symbol_to_sell}</b> no reconocido o no monitoreado por el bot.")
                        else:
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Uso: <code>/vender &lt;SIMBOLO_USDT&gt;</code> (ej. /vender BTCUSDT)")
                    elif command == "/beneficio": # Muestra el beneficio total acumulado.
                        with shared_data_lock: # Accede a TOTAL_BENEFICIO_ACUMULADO con el bloqueo
                            reporting_manager.send_beneficio_message(client, TOTAL_BENEFICIO_ACUMULADO, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
                    elif command == "/get_positions_file": # Muestra el contenido del archivo de posiciones abiertas (para depuración).
                        with shared_data_lock: # Accede a OPEN_POSITIONS_FILE con el bloqueo
                             telegram_handler.send_positions_file_content(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE)
                    elif command == "/convert_dust": # Comando para convertir saldos pequeños a BNB
                        telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "⚙️ Intentando convertir saldos pequeños (dust) a BNB...")
                        with shared_data_lock: # Protege el acceso al cliente de Binance si es necesario
                            conversion_result = binance_utils.convert_dust_to_bnb(client)
                        
                        if conversion_result and conversion_result['status'] == 'success':
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"✅ {conversion_result['message']}")
                        else:
                            error_msg = conversion_result.get('message', 'Error desconocido al convertir dust.')
                            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ {error_msg}")
                            logging.error(f"Fallo en la conversión de dust: {error_msg}")
                    else: # Comando no reconocido.
                        telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "Comando desconocido. Usa <code>/help</code> para ver los comandos disponibles.")

                except ValueError: # Maneja errores cuando los valores introducidos no son válidos (ej. texto en lugar de número).
                    telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, "❌ Valor inválido. Asegúrate de introducir un número o porcentaje correcto.")
                except Exception as ex: # Captura cualquier otra excepción durante el procesamiento de comandos.
                    logging.error(f"Error procesando comando '{text}': {ex}", exc_info=True) # Registra el error completo.
                    telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ Error interno al procesar comando: {ex}") # Envía un mensaje de error a Telegram.

# Función que se ejecutará en el hilo separado para escuchar Telegram
def telegram_listener(stop_event):
    """
    Función que se ejecuta en un hilo separado para escuchar y procesar comandos de Telegram.
    Utiliza un stop_event para saber cuándo debe detenerse.
    """
    global last_update_id # Necesario para mantener el offset de los mensajes de Telegram
    while not stop_event.is_set(): # El bucle se ejecuta hasta que el evento de parada se activa.
        try:
            # handle_telegram_commands ya contiene la lógica para obtener y procesar actualizaciones.
            # Todas las modificaciones a variables globales dentro de handle_telegram_commands
            # ya están protegidas por 'shared_data_lock'.
            handle_telegram_commands()
            time.sleep(TELEGRAM_LISTEN_INTERVAL) # Espera un corto intervalo antes de la siguiente consulta a Telegram.
        except Exception as e:
            logging.error(f"Error en el hilo de Telegram: {e}", exc_info=True)
            time.sleep(TELEGRAM_LISTEN_INTERVAL * 2) # Espera un poco más en caso de error para evitar bucles rápidos.

# =================== BUCLE PRINCIPAL DEL BOT ===================

# Configurar el menú de comandos de Telegram al inicio del bot.
telegram_handler.set_telegram_commands_menu(TELEGRAM_BOT_TOKEN)

logging.info("Bot iniciado. Esperando comandos y monitoreando el mercado...") # Mensaje de inicio del bot.

# Crear y arrancar el hilo de Telegram
telegram_stop_event = threading.Event() # Crea un evento para señalar al hilo de Telegram que debe detenerse.
telegram_thread = threading.Thread(target=telegram_listener, args=(telegram_stop_event,)) # Crea el hilo, pasando la función y el evento.
telegram_thread.start() # Inicia el hilo en segundo plano.

try:
    while True: # Bucle infinito que mantiene el bot en funcionamiento.
        start_time_cycle = time.time() # Registra el tiempo de inicio de cada ciclo principal.
        
        # --- Lógica del Informe Diario ---
        hoy = time.strftime("%Y-%m-%d")

        # Comprueba si es un nuevo día o si es la primera ejecución para enviar el informe diario.
        if ultima_fecha_informe_enviado is None or hoy != ultima_fecha_informe_enviado:
            if ultima_fecha_informe_enviado is not None: # Si ya se había enviado un informe antes (no es la primera ejecución).
                telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"Preparando informe del día {ultima_fecha_informe_enviado}...")
                with shared_data_lock: # Protege el acceso a transacciones_diarias
                    reporting_manager.enviar_informe_diario(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, transacciones_diarias)
            
            ultima_fecha_informe_enviado = hoy # Actualiza la fecha del último informe enviado a la fecha actual.
            with shared_data_lock: # Protege la limpieza de transacciones_diarias
                transacciones_diarias.clear() # Limpia la lista de transacciones diarias para el nuevo día.

        # --- LÓGICA PRINCIPAL DE TRADING ---
        # Ejecuta la lógica de trading solo si ha pasado el INTERVALO de tiempo configurado.
        if (time.time() - last_trading_check_time) >= INTERVALO:
            logging.info(f"Iniciando ciclo de trading principal (cada {INTERVALO}s)...")
            general_message = "" # Variable para acumular mensajes de resumen del ciclo.

            for symbol in SYMBOLS: # Itera sobre cada símbolo de trading configurado.
                base = symbol.replace("USDT", "") # Extrae la criptomoneda base (ej. BTC de BTCUSDT).
                
                saldo_base = binance_utils.obtener_saldo_moneda(client, base) 
                precio_actual = binance_utils.obtener_precio_actual(client, symbol)
                
                ema_valor, rsi_valor = trading_logic.calcular_ema_rsi(client, symbol, EMA_PERIODO, RSI_PERIODO)

                if ema_valor is None or rsi_valor is None: # Si no se pudieron calcular los indicadores, salta este símbolo.
                    logging.warning(f"⚠️ No se pudieron calcular EMA o RSI para {symbol}. Saltando este símbolo en este ciclo.")
                    continue

                # Construye un mensaje de estado para el símbolo actual.
                mensaje_simbolo = (
                    f"📊 <b>{symbol}</b>\n"
                    f"Precio actual: {precio_actual:.2f} USDT\n"
                    f"EMA ({EMA_PERIODO}m): {ema_valor:.2f}\n"
                    f"RSI ({RSI_PERIODO}m): {rsi_valor:.2f}"
                )

                # --- LÓGICA DE COMPRA ---
                saldo_usdt = binance_utils.obtener_saldo_moneda(client, "USDT") # Obtiene el saldo disponible de USDT.
                # Condiciones para entrar en una posición (compra):
                # 1. Saldo USDT suficiente (>10).
                # 2. Precio actual por encima de la EMA (tendencia alcista).
                # 3. RSI por debajo del umbral de sobrecompra (no sobrecomprado).
                # 4. No hay una posición abierta para este símbolo.
                if (saldo_usdt > 10 and 
                    precio_actual > ema_valor and 
                    rsi_valor < RSI_UMBRAL_SOBRECOMPRA and 
                    symbol not in posiciones_abiertas):
                    
                    # Calcula la cantidad a comprar utilizando trading_logic.
                    cantidad = trading_logic.calcular_cantidad_a_comprar(
                        client, saldo_usdt, precio_actual, STOP_LOSS_PORCENTAJE, symbol, RIESGO_POR_OPERACION_PORCENTAJE
                    )
                    
                    if cantidad > 0: # Si la cantidad a comprar es válida.
                        with shared_data_lock: # Protege el acceso a posiciones_abiertas y transacciones_diarias
                            orden = trading_logic.comprar(
                                client, symbol, cantidad, posiciones_abiertas, STOP_LOSS_PORCENTAJE,
                                transacciones_diarias, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE
                            )
                        if orden: # Si la orden de compra fue exitosa.
                            precio_ejecucion = float(orden['fills'][0]['price'])
                            cantidad_comprada_real = float(orden['fills'][0]['qty'])
                            
                            mensaje_simbolo += f"\n✅ COMPRA ejecutada a {precio_ejecucion:.2f} USDT"
                            
                            capital_invertido_usd = precio_ejecucion * cantidad_comprada_real
                            riesgo_max_trade_usd = saldo_usdt * RIESGO_POR_OPERACION_PORCENTAJE
                            mensaje_simbolo += (
                                f"\nCantidad comprada: {cantidad_comprada_real:.6f} {base}"
                                f"\nInversión en este trade: {capital_invertido_usd:.2f} USDT"
                                f"\nRiesgo Máx. Permitido por Trade: {riesgo_max_trade_usd:.2f} USDT"
                            )
                        else: # Si la orden de compra falló.
                            mensaje_simbolo += f"\n❌ COMPRA fallida para {symbol}."
                    else: # Si no hay suficiente capital o la cantidad es muy pequeña.
                        mensaje_simbolo += f"\n⚠️ No hay suficiente capital o cantidad mínima para comprar {symbol} con el riesgo definido."

                # --- LÓGICA DE VENTA (Take Profit, Stop Loss Fijo, Trailing Stop Loss, Breakeven) ---
                elif symbol in posiciones_abiertas: # Si ya hay una posición abierta para este símbolo.
                    # Se hace una copia de la posición para leerla, las modificaciones se harán bajo el lock.
                    posicion = posiciones_abiertas[symbol].copy() 
                    precio_compra = posicion['precio_compra'] # Precio al que se compró.
                    cantidad_en_posicion = posicion['cantidad_base'] # Cantidad de la criptomoneda en la posición.
                    max_precio_alcanzado = posicion['max_precio_alcanzado'] # Precio máximo que ha alcanzado la criptomoneda desde la compra.

                    stop_loss_fijo_nivel = precio_compra * (1 - STOP_LOSS_PORCENTAJE) # Calcula el nivel del Stop Loss fijo.

                    # Actualiza el precio máximo alcanzado si el precio actual es mayor.
                    if precio_actual > max_precio_alcanzado:
                        with shared_data_lock: # Protege la modificación de posiciones_abiertas
                            posiciones_abiertas[symbol]['max_precio_alcanzado'] = precio_actual
                            max_precio_alcanzado = precio_actual # Actualiza la variable local para el resto del ciclo
                            position_manager.save_open_positions_debounced(posiciones_abiertas) # Guarda la actualización de la posición.

                    # --- Lógica de Stop Loss a Breakeven ---
                    breakeven_nivel_real = precio_compra * (1 + BREAKEVEN_PORCENTAJE) # Calcula el nivel para mover a Breakeven.

                    # Si el precio actual alcanza el nivel de Breakeven y aún no se ha movido el SL.
                    if (precio_actual >= breakeven_nivel_real and
                        not posicion['sl_moved_to_breakeven']):
                        
                        with shared_data_lock: # Protege la modificación de posiciones_abiertas
                            # Mueve el Stop Loss al nivel de Breakeven (o lo mantiene si el fijo es más alto).
                            posiciones_abiertas[symbol]['stop_loss_fijo_nivel_actual'] = max(stop_loss_fijo_nivel, breakeven_nivel_real)
                            posiciones_abiertas[symbol]['sl_moved_to_breakeven'] = True # Marca que el SL ya se movió a Breakeven.
                        telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"🔔 SL de <b>{symbol}</b> movido a Breakeven: <b>{breakeven_nivel_real:.2f}</b>")
                        logging.info(f"SL de {symbol} movido a Breakeven: {breakeven_nivel_real:.2f}")
                        with shared_data_lock: # Protege la modificación de posiciones_abiertas
                            position_manager.save_open_positions_debounced(posiciones_abiertas) # Guarda la actualización de la posición.

                    # --- Niveles de Salida ---
                    # Obtiene el nivel de Stop Loss actual (fijo o breakeven).
                    # Se lee dentro del lock para asegurar que se obtiene el valor más reciente.
                    with shared_data_lock:
                        current_stop_loss_level = posiciones_abiertas[symbol].get('stop_loss_fijo_nivel_actual', stop_loss_fijo_nivel)

                    take_profit_nivel = precio_compra * (1 + TAKE_PROFIT_PORCENTAJE) # Calcula el nivel de Take Profit.
                    trailing_stop_nivel = max_precio_alcanzado * (1 - TRAILING_STOP_PORCENTAJE) # Calcula el nivel de Trailing Stop.

                    eur_usdt_conversion_rate = binance_utils.obtener_precio_eur(client) # Obtiene la tasa de conversión USDT a EUR.
                    saldo_invertido_usdt = precio_compra * cantidad_en_posicion # Calcula el saldo invertido en USDT.
                    saldo_invertido_eur = saldo_invertido_usdt * eur_usdt_conversion_rate if eur_usdt_conversion_rate else 0 # Calcula el saldo invertido en EUR.

                    # Añade información de la posición al mensaje del símbolo.
                    mensaje_simbolo += (
                        f"\nPosición:\n Entrada: {precio_compra:.2f} | Actual: {precio_actual:.2f}\n"
                        f"TP: {take_profit_nivel:.2f} | SL Fijo: {current_stop_loss_level:.2f}\n"
                        f"Max Alcanzado: {max_precio_alcanzado:.2f} | TSL: {trailing_stop_nivel:.2f}\n"
                        f"Saldo USDT Invertido (Entrada): {saldo_invertido_usdt:.2f}\n"
                        f"SEI: {saldo_invertido_eur:.2f}"
                    )

                    vender_ahora = False # Bandera para indicar si se debe vender.
                    motivo_venta = "" # Motivo de la venta.

                    # --- Condiciones para vender ---
                    if precio_actual >= take_profit_nivel: # Si el precio alcanza el Take Profit.
                        vender_ahora = True
                        motivo_venta = "TAKE PROFIT alcanzado"
                    elif precio_actual <= current_stop_loss_level: # Si el precio cae al Stop Loss (fijo o breakeven).
                        vender_ahora = True
                        motivo_venta = "STOP LOSS FIJO alcanzado (o Breakeven)"
                    elif (precio_actual <= trailing_stop_nivel and precio_actual > precio_compra): # Si el precio cae y activa el Trailing Stop.
                        vender_ahora = True
                        motivo_venta = "TRAILING STOP LOSS activado"
                    
                    if vender_ahora: # Si alguna condición de venta se cumple.
                        # Ajusta la cantidad a vender basándose en el saldo real y el step_size de Binance.
                        cantidad_a_vender_real = binance_utils.ajustar_cantidad(binance_utils.obtener_saldo_moneda(client, base), binance_utils.get_step_size(client, symbol)) 
                        
                        if cantidad_a_vender_real > 0: # Si la cantidad a vender es válida.
                            with shared_data_lock: # Protege el acceso a posiciones_abiertas, TOTAL_BENEFICIO_ACUMULADO, bot_params y transacciones_diarias
                                orden = trading_logic.vender(
                                    client, symbol, cantidad_a_vender_real, posiciones_abiertas,
                                    TOTAL_BENEFICIO_ACUMULADO, bot_params, transacciones_diarias,
                                    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, OPEN_POSITIONS_FILE, config_manager,
                                    motivo_venta # Pasa el motivo_venta a la función vender
                                )
                                # Actualizar TOTAL_BENEFICIO_ACUMULADO después de la venta, ya que trading_logic lo modifica en bot_params.
                                TOTAL_BENEFICIO_ACUMULADO = bot_params['TOTAL_BENEFICIO_ACUMULADO']

                            if orden: # Si la orden de venta fue exitosa.
                                salida = float(orden['fills'][0]['price'])
                                ganancia = (salida - precio_compra) * cantidad_a_vender_real
                                mensaje_simbolo += (
                                    f"\n✅ VENTA ejecutada por {motivo_venta} a {salida:.2f} USDT\n"
                                    f"Ganancia/Pérdida: {ganancia:.2f} USDT"
                                )
                            else: # Si la orden de venta falló.
                                mensaje_simbolo += f"\n❌ VENTA fallida para {symbol}."
                        else: # Si no hay saldo de la criptomoneda para vender.
                            mensaje_simbolo += f"\n⚠️ No hay {base} disponible para vender o cantidad muy pequeña."
                    
                # Añade el resumen de saldos al mensaje del símbolo.
                with shared_data_lock: # Protege el acceso a posiciones_abiertas
                    mensaje_simbolo += "\n" + binance_utils.obtener_saldos_formateados(client, posiciones_abiertas)
                general_message += mensaje_simbolo + "\n\n" # Acumula el mensaje del símbolo al mensaje general.

            telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, general_message)
            last_trading_check_time = time.time() # Actualiza la marca de tiempo del último chequeo de trading.

        # --- GESTIÓN DEL TIEMPO ENTRE CICLOS ---
        time_elapsed_overall = time.time() - start_time_cycle # Calcula el tiempo transcurrido en el ciclo actual.
        # El hilo principal ahora solo se detiene por el INTERVALO de trading, el hilo de Telegram es independiente.
        sleep_duration = max(0, INTERVALO - time_elapsed_overall) 
        print(f"⏳ Próxima revisión en {sleep_duration:.0f} segundos (Ciclo de trading)...\n")
        time.sleep(sleep_duration) # Pausa el bot por el tiempo restante para mantener el intervalo.

except KeyboardInterrupt:
    logging.info("Detectado KeyboardInterrupt. Señalando al hilo de Telegram para detenerse...")
    telegram_stop_event.set() # Señala al hilo de Telegram que debe detenerse.
    telegram_thread.join() # Espera a que el hilo de Telegram termine su ejecución.
    logging.info("Bot detenido.")
except Exception as e: # Captura cualquier excepción general en el bucle principal.
    logging.error(f"Error general en el bot: {e}", exc_info=True) 
    with shared_data_lock: # Protege el acceso a posiciones_abiertas
        telegram_handler.send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, f"❌ Error general en el bot: {e}\n\n{binance_utils.obtener_saldos_formateados(client, posiciones_abiertas)}") 
    print(f"❌ Error general en el bot: {e}") # Imprime el error en la consola.
    # En caso de un error inesperado, también se intenta detener el hilo de Telegram.
    telegram_stop_event.set()
    telegram_thread.join()