import requests
import json
import logging
import os # Necesario para os.path.exists, os.path.basename, os.remove
import csv # Necesario para trabajar con archivos CSV

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_telegram_message(token, chat_id, message):
    """
    Envía un mensaje de texto al chat de Telegram configurado.
    Permite formato HTML básico (ej. <b> para negrita, <code> para código) para mejorar la legibilidad.
    """
    if not token or not chat_id:
        logging.warning("⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al enviar mensaje a Telegram: {e}")
        return False

def send_telegram_document(token, chat_id, file_path, caption=""):
    """
    Envía un documento (ej. un archivo CSV de transacciones) a un chat de Telegram específico.
    """
    if not token:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se pueden enviar documentos.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        with open(file_path, 'rb') as doc:
            files = {'document': doc}
            payload = {'chat_id': chat_id, 'caption': caption}
            response = requests.post(url, data=payload, files=files)
            response.raise_for_status()
            logging.info(f"✅ Documento {file_path} enviado con éxito a Telegram.")
            return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error enviando documento Telegram '{file_path}': {e}")
        send_telegram_message(token, chat_id, f"❌ Error enviando documento: {e}")
        return False
    except Exception as e:
        logging.error(f"❌ Error inesperado en send_telegram_document: {e}")
        send_telegram_message(token, chat_id, f"❌ Error inesperado enviando documento: {e}")
        return False

def get_telegram_updates(token, offset=None):
    """
    Obtiene actualizaciones (mensajes) del bot de Telegram usando el método long polling.
    El parámetro 'offset' es crucial para que el bot solo procese mensajes nuevos
    y evite procesar mensajes que ya fueron manejados en iteraciones anteriores.
    """
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    params = {'timeout': 30} # Tiempo máximo de espera para nuevas actualizaciones.
    if offset:
        params['offset'] = offset # Si se proporciona un offset, solo se obtienen mensajes posteriores a ese ID.
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al obtener actualizaciones de Telegram: {e}")
        return None

def send_keyboard_menu(token, chat_id, message_text="Selecciona una opción:"):
    """
    Envía un mensaje a Telegram que incluye un teclado personalizado con botones.
    Este teclado aparece en lugar del teclado normal del dispositivo del dispositivo del usuario.
    """
    if not token:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede enviar el teclado personalizado.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    keyboard = {
        'keyboard': [
            [{'text': '/beneficio'}, {'text': '/get_params'}],
            [{'text': '/csv'}, {'text': '/get_positions_file'}],
            [{'text': '/vender BTCUSDT'}, {'text': '/vender ETHUSDT'}], # Añadido ETHUSDT para ejemplo
            [{'text': '/reset_beneficio'}], # CAMBIO: Botón para resetear beneficio
            [{'text': '/help'}, {'text': '/hide_menu'}] # Añadido help y hide_menu
        ],
        'resize_keyboard': True,
        'one_time_keyboard': False
    }

    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'reply_markup': json.dumps(keyboard)
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info("✅ Teclado personalizado enviado con éxito.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al enviar teclado personalizado a Telegram: {e}")
        return False

def remove_keyboard_menu(token, chat_id, message_text="Teclado oculto."):
    """
    Oculta el teclado personalizado de Telegram, volviendo al teclado normal del dispositivo.
    """
    if not token:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede ocultar el teclado.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    remove_keyboard = {
        'remove_keyboard': True
    }

    payload = {
        'chat_id': chat_id,
        'text': message_text,
        'reply_markup': json.dumps(remove_keyboard)
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info("✅ Teclado personalizado ocultado con éxito.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error al ocultar teclado personalizado: {e}")
        return False

def set_telegram_commands_menu(token):
    """
    Configura el menú de comandos que aparece cuando el usuario escribe '/' en el campo de texto de Telegram.
    Esta función debe ser llamada una vez al inicio del bot para registrar los comandos con la API de Telegram.
    """
    if not token:
        logging.warning("⚠️ TOKEN de Telegram no configurado. No se puede configurar el menú de comandos.")
        return False

    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    
    commands = [
        {"command": "start", "description": "Iniciar el bot y mostrar menú"},
        {"command": "menu", "description": "Mostrar el menú de comandos"},
        {"command": "hide_menu", "description": "Ocultar el menú de comandos"},
        {"command": "get_params", "description": "Mostrar parámetros actuales del bot"},
        {"command": "set_tp", "description": "Establece el Take Profit (ej. /set_tp 0.03)"},
        {"command": "set_sl_fijo", "description": "Establece el Stop Loss Fijo (ej. /set_sl_fijo 0.02)"},
        {"command": "set_tsl", "description": "Establece el Trailing Stop Loss (ej. /set_tsl 0.015)"},
        {"command": "set_riesgo", "description": "Establece el riesgo por operación (ej. /set_riesgo 0.01)"},
        {"command": "set_ema_periodo", "description": "Establece el período de la EMA (ej. /set_ema_periodo 10)"},
        {"command": "set_rsi_periodo", "description": "Establece el período del RSI (ej. /set_rsi_periodo 14)"},
        {"command": "set_rsi_umbral", "description": "Establece el umbral de sobrecompra del RSI (ej. 70)"},
        {"command": "set_intervalo", "description": "Establece el intervalo del ciclo (ej. /set_intervalo 300)"},
        {"command": "set_breakeven_porcentaje", "description": "Mueve SL a breakeven (ej. /set_breakeven_porcentaje 0.005)"},
        {"command": "csv", "description": "Generar y enviar informe CSV de transacciones"},
        {"command": "beneficio", "description": "Mostrar beneficio total acumulado"},
        {"command": "vender", "description": "Vender una posición (ej. /vender BTCUSDT)"},
        {"command": "reset_beneficio", "description": "Resetear beneficio acumulado a cero"}, # CAMBIO: Comando reset_beneficio
        {"command": "get_positions_file", "description": "Obtener archivo de posiciones abiertas"},
        {"command": "help", "description": "Mostrar ayuda y comandos disponibles"}
    ]

    payload = {'commands': json.dumps(commands)}
    headers = {'Content-Type': 'application/json'}

    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        if result['ok']:
            logging.info("✅ Menú de comandos de Telegram configurado con éxito.")
            return True
        else:
            logging.error(f"❌ Fallo al configurar el menú de comandos: {result.get('description', 'Error desconocido')}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ Error de red al configurar el menú de comandos: {e}")
        return False

def send_positions_file_content(token, chat_id, file_path):
    """
    Lee el contenido del archivo OPEN_POSITIONS_FILE (JSON), lo convierte a CSV
    y lo envía como un documento adjunto al chat de Telegram.
    """
    if not os.path.exists(file_path):
        send_telegram_message(token, chat_id, f"❌ Archivo de posiciones abiertas (<code>{file_path}</code>) no encontrado.")
        logging.warning(f"Intento de leer {file_path}, pero no existe.")
        return

    csv_file_name = file_path.replace(".json", ".csv")
    try:
        with open(file_path, 'r') as f:
            positions_data = json.load(f)

        if not positions_data:
            send_telegram_message(token, chat_id, "🚫 No hay posiciones abiertas registradas para generar el CSV.")
            return

        # Preparar los datos para el CSV
        # Cada clave del diccionario principal (ej. "BTCUSDT") se convierte en una fila.
        # Las claves internas de cada posición se convierten en columnas.
        
        # Definir los nombres de los campos (columnas) para el CSV
        # Aseguramos que 'Symbol' sea la primera columna
        all_keys = set()
        for data in positions_data.values():
            all_keys.update(data.keys())
        
        fieldnames = ['Symbol'] + sorted(list(all_keys)) # Ordenamos para consistencia

        # Crear una lista de diccionarios, donde cada diccionario es una fila del CSV
        csv_rows = []
        for symbol, data in positions_data.items():
            row = {'Symbol': symbol}
            row.update(data) # Añade todos los campos de la posición a la fila
            csv_rows.append(row)

        with open(csv_file_name, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(csv_rows)

        caption = f"📄 Posiciones abiertas en formato CSV: <code>{os.path.basename(csv_file_name)}</code>"
        send_telegram_document(token, chat_id, csv_file_name, caption)
        logging.info(f"Archivo {csv_file_name} enviado como documento a Telegram.")

    except json.JSONDecodeError as e:
        send_telegram_message(token, chat_id, f"❌ Error al leer el archivo JSON de posiciones (formato inválido): {e}")
        logging.error(f"❌ Error al decodificar JSON de {file_path}: {e}", exc_info=True)
    except Exception as e:
        send_telegram_message(token, chat_id, f"❌ Error al convertir o enviar el archivo de posiciones como CSV: {e}")
        logging.error(f"❌ Error al procesar {file_path} y enviar como CSV: {e}", exc_info=True)
    finally:
        # Limpiar el archivo CSV temporal después de enviarlo
        if os.path.exists(csv_file_name):
            os.remove(csv_file_name)
            logging.info(f"Archivo CSV temporal {csv_file_name} eliminado.")

def send_help_message(token, chat_id):
    """Envía un mensaje de ayuda detallado con la lista de todos los comandos disponibles."""
    help_message = (
        "🤖 <b>Comandos disponibles:</b>\n\n"
        "<b>Parámetros de Estrategia:</b>\n"
        " - <code>/get_params</code>: Muestra los parámetros actuales del bot.\n"
        " - <code>/set_tp &lt;valor&gt;</code>: Establece el porcentaje de Take Profit (ej. 0.03).\n"
        " - <code>/set_sl_fijo &lt;valor&gt;</code>: Establece el porcentaje de Stop Loss Fijo (ej. 0.02).\n"
        " - <code>/set_tsl &lt;valor&gt;</code>: Establece el porcentaje de Trailing Stop Loss (ej. 0.015).\n"
        " - <code>/set_riesgo &lt;valor&gt;</code>: Establece el porcentaje de riesgo por operación (ej. 0.01).\n"
        " - <code>/set_ema_periodo &lt;valor&gt;</code>: Establece el período de la EMA (ej. 10).\n"
        " - <code>/set_rsi_periodo &lt;valor&gt;</code>: Establece el período del RSI (ej. 14).\n"
        " - <code>/set_rsi_umbral &lt;valor&gt;</code>: Establece el umbral de sobrecompra del RSI (ej. 70).\n"
        " - <code>/set_intervalo &lt;segundos&gt;</code>: Establece el intervalo del ciclo principal del bot en segundos (ej. 300).\n"
        " - <code>/set_breakeven_porcentaje &lt;valor&gt;</code>: Establece el porcentaje de ganancia para mover SL a breakeven (ej. 0.005).\n\n"
        "<b>Informes:</b>\n"
        " - <code>/csv</code>: Genera y envía un archivo CSV con las transacciones del día hasta el momento.\n"
        " - <code>/beneficio</code>: Muestra el beneficio total acumulado por el bot.\n\n"
        "<b>Utilidades:</b>\n"
        " - <code>/vender &lt;SIMBOLO_USDT&gt;</code>: Vende una posición abierta de forma manual (ej. /vender BTCUSDT).\n"
        " - <code>/reset_beneficio</code>: Resetear beneficio acumulado a cero.\n" # CAMBIO: Descripción del comando reset_beneficio
        " - <code>/get_positions_file</code>: Obtener archivo de posiciones abiertas.\n"
        " - <code>/menu</code>: Muestra el teclado de comandos principal.\n"
        " - <code>/hide_menu</code>: Oculta el teclado de comandos.\n\n"
        "<b>Ayuda:</b>\n"
        " - <code>/help</code>: Muestra este mensaje de ayuda.\n\n"
        "<i>Recuerda usar valores decimales para porcentajes y enteros para períodos/umbrales.</i>"
    )
    send_telegram_message(token, chat_id, help_message)
