# Importa la librería requests para hacer peticiones HTTP (necesaria para interactuar con la API de Telegram).
import requests
# Importa el módulo json para trabajar con datos en formato JSON (serialización/deserialización).
import json
# Importa el módulo logging para registrar eventos y mensajes del bot.
import logging
# Importa el módulo os para interactuar con el sistema operativo, como la gestión de archivos (os.path.exists, os.remove).
import os
# Importa el módulo csv para trabajar con archivos CSV (generación de informes).
import csv
import html  # Importa el módulo html para escapar caracteres HTML.
import math  # Importa el módulo math para funciones como isnan e isinf.
# Mover la importación aquí para que sea accesible globalmente en el módulo.
import binance_utils

# Configura el sistema de registro básico para este módulo.
# Esto asegura que los mensajes informativos, advertencias y errores se muestren en la consola del bot.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def _escape_html_entities(text):
    """
    Escapa caracteres especiales HTML en una cadena de texto.
    Esto es crucial para asegurar que el texto dinámico no rompa el formato HTML
    cuando se usa parse_mode='HTML' en Telegram.
    Por ejemplo, '<' se convierte en '&lt;', '>' en '&gt;', '&' en '&amp;', etc.
    También maneja valores None o flotantes no finitos (NaN, Inf) para evitar errores HTML.

    Args:
        text (str): La cadena de texto a escapar.

    Returns:
        str: La cadena de texto con los caracteres HTML escapados.
    """
    if text is None:
        return "N/A"
    # Convertir a float para comprobar NaN/Inf, pero solo si es numérico.
    if isinstance(text, (int, float)):
        if math.isnan(text) or math.isinf(text):
            return "N/A"
    # Asegura que el input sea string antes de escapar.
    return html.escape(str(text))


def send_telegram_message(token, chat_id, message):
    """
    Envía un mensaje de texto al chat de Telegram configurado.
    Permite formato HTML básico (ej. <b> para negrita, <code> para código) para mejorar la legibilidad.

    Args:
        token (str): El token de la API de tu bot de Telegram.
        chat_id (str): El ID del chat de Telegram al que se enviará el mensaje.
        message (str): El texto del mensaje a enviar.

    Returns:
        bool: True si el mensaje se envió con éxito, False en caso contrario.
    """
    # Verifica si el token o el chat_id no están configurados.
    # --- AÑADE ESTO AL PRINCIPIO DE send_telegram_message ---
    if not message or not message.strip():
        logging.warning("⚠️ Mensaje vacío o solo espacios. No se envía.")
        return False

# Resto del código ya existente...

    if not token or not chat_id:
        logging.warning(
            "⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes.")
        return False

    # Inicializa response a None para asegurar que siempre esté definida.
    response = None
    # Construye la URL para la API de Telegram.
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    # Define la carga útil (payload) de la solicitud HTTP, incluyendo el chat_id, el texto y el modo de parseo HTML.
    payload = {
        'chat_id': chat_id,
        # El mensaje ya debe contener las partes dinámicas escapadas si es necesario.
        'text': message,
        # Permite usar etiquetas HTML en el mensaje para formato.
        'parse_mode': 'HTML'
    }
    try:
        # Envía la solicitud POST a la API de Telegram.
        response = requests.post(url, json=payload)
        # Lanza una excepción HTTPError si la respuesta no fue exitosa (código de estado 4xx o 5xx).
        response.raise_for_status()
        return True  # Retorna True si la solicitud fue exitosa.
    except requests.exceptions.RequestException as e:
        # Captura cualquier excepción relacionada con la solicitud (ej. problemas de red, errores HTTP).
        logging.error(f"❌ Error al enviar mensaje a Telegram: {e}")
        # *** NUEVO LOGGING PARA DEPURACIÓN ***
        # Ahora response siempre estará definida.
        if response is not None and response.status_code == 400:
            logging.error(
                f"❌ Detalles del error 400 (Bad Request): Mensaje enviado: '{message}'")
        # ***********************************
        return False  # Retorna False en caso de error.


def send_telegram_document(token, chat_id, file_path, caption=""):
    """
    Envía un documento (ej. un archivo CSV de transacciones) a un chat de Telegram específico.

    Args:
        token (str): El token de la API de tu bot de Telegram.
        chat_id (str): El ID del chat de Telegram al que se enviará el documento.
        file_path (str): La ruta al archivo local que se enviará.
        caption (str, optional): Un texto opcional que acompaña al documento. Por defecto es una cadena vacía.

    Returns:
        bool: True si el documento se envió con éxito, False en caso contrario.
    """
    # Verifica si el token no está configurado.
    if not token:
        logging.warning(
            "⚠️ TOKEN de Telegram no configurado. No se pueden enviar documentos.")
        return False

    # Inicializa response a None para asegurar que siempre esté definida.
    response = None
    # Construye la URL para la API de Telegram.
    url = f"https://api.telegram.org/bot{token}/sendDocument"
    try:
        # Abre el archivo en modo binario de lectura ('rb').
        with open(file_path, 'rb') as doc:
            # Prepara los archivos para la solicitud multipart/form-data.
            files = {'document': doc}
            # Define la carga útil (payload) con el chat_id y la leyenda (caption).
            payload = {'chat_id': chat_id, 'caption': caption}
            # Envía la solicitud POST a la API de Telegram con los datos y el archivo.
            response = requests.post(url, data=payload, files=files)
            # Lanza una excepción HTTPError si la respuesta no fue exitosa.
            response.raise_for_status()
            logging.info(
                f"✅ Documento {file_path} enviado con éxito a Telegram.")
            return True  # Retorna True si la solicitud fue exitosa.
    except requests.exceptions.RequestException as e:
        # Captura errores de solicitud y envía un mensaje de error a Telegram.
        logging.error(
            f"❌ Error enviando documento Telegram '{file_path}': {e}")
        send_telegram_message(
            # Escapar el error
            token, chat_id, f"❌ Error enviando documento: {_escape_html_entities(e)}")
        return False  # Retorna False en caso de error.
    except Exception as e:
        # Captura cualquier otro error inesperado.
        logging.error(f"❌ Error inesperado en send_telegram_document: {e}")
        send_telegram_message(
            # Escapar el error
            token, chat_id, f"❌ Error inesperado enviando documento: {_escape_html_entities(e)}")
        return False  # Retorna False en caso de error.


def get_telegram_updates(offset=None, token=None):
    """
    Obtiene actualizaciones (mensajes) del bot de Telegram usando el método long polling.
    El parámetro 'offset' es crucial para que el bot solo procese mensajes nuevos
    y evite procesar mensajes que ya fueron manejados en iteraciones anteriores.

    Args:
        offset (int, optional): El ID de la última actualización procesada + 1.
                                Esto asegura que solo se reciban mensajes nuevos.
                                Por defecto es None.
        token (str): El token de la API de tu bot de Telegram.

    Returns:
        dict or None: Un diccionario con las actualizaciones de Telegram si la solicitud es exitosa,
                      None en caso de error.
    """
    # Verifica si el token no está configurado.
    if not token:
        logging.warning(
            "⚠️ TOKEN de Telegram no configurado. No se pueden obtener actualizaciones.")
        return None

    # Inicializa response a None para asegurar que siempre esté definida.
    response = None
    # Construye la URL para la API de Telegram.
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    # Define los parámetros de la solicitud, incluyendo un timeout para long polling.
    # Tiempo máximo de espera para nuevas actualizaciones (30 segundos).
    params = {'timeout': 30}
    if offset:
        # Si se proporciona un offset, solo se obtienen mensajes posteriores a ese ID.
        params['offset'] = offset
    try:
        # Envía la solicitud GET a la API de Telegram.
        response = requests.get(url, params=params)
        # Lanza una excepción HTTPError si la respuesta no fue exitosa.
        response.raise_for_status()
        return response.json()  # Retorna la respuesta JSON de la API.
    except requests.exceptions.RequestException as e:
        # Captura errores de solicitud.
        logging.error(f"❌ Error al obtener actualizaciones de Telegram: {e}")
        # *** NUEVO LOGGING PARA DEPURACIÓN ***
        # Ahora response siempre estará definida.
        if response is not None and response.status_code == 409:
            logging.error(
                f"❌ POSIBLE CONFLICTO (Error 409): Otra instancia de tu bot podría estar ejecutándose. Asegúrate de que solo haya una instancia activa. Detalles: {e}")
        # ***********************************
        return None  # Retorna None en caso de error.


def send_keyboard_menu(token, chat_id, message_text="Selecciona una opción:"):
    """
    Envía un mensaje a Telegram que incluye un teclado personalizado con botones.
    Este teclado aparece en lugar del teclado normal del dispositivo del usuario.

    Args:
        token (str): El token de la API de tu bot de Telegram.
        chat_id (str): El ID del chat de Telegram al que se enviará el menú.
        message_text (str, optional): El texto del mensaje que acompaña al teclado.
                                      Por defecto es "Selecciona una opción:".

    Returns:
        bool: True si el teclado se envió con éxito, False en caso contrario.
    """
    # Verifica si el token no está configurado.
    if not token:
        logging.warning(
            "⚠️ TOKEN de Telegram no configurado. No se puede enviar el teclado personalizado.")
        return False

    # Construye la URL para la API de Telegram.
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Define la estructura del teclado personalizado.
    # Cada lista interna representa una fila de botones.
    keyboard = {
        'keyboard': [
            # Fila 1: Beneficio y Parámetros
            [{'text': '/beneficio'}, {'text': '/get_params'}],
            # Fila 2: CSV y Análisis (anteriormente /get_positions_file)
            [{'text': '/csv'}, {'text': '/analisis'}],
            # Fila 3: Botón para posiciones actuales
            [{'text': '/posiciones_actuales'}],
            [{'text': '/reset_beneficio'}],  # Fila 4: Resetear Beneficio
            # Fila 5: Ayuda y Ocultar Menú
            [{'text': '/help'}, {'text': '/hide_menu'}]
        ],
        # Ajusta el tamaño del teclado para que se adapte a la pantalla.
        'resize_keyboard': True,
        # El teclado permanece visible después de un uso.
        'one_time_keyboard': False
    }

    # Define la carga útil (payload) de la solicitud HTTP.
    payload = {
        'chat_id': chat_id,
        'text': message_text,
        # Convierte el diccionario del teclado a una cadena JSON.
        'reply_markup': json.dumps(keyboard)
    }

    try:
        # Envía la solicitud POST a la API de Telegram.
        response = requests.post(url, json=payload)
        # Lanza una excepción HTTPError si la respuesta no fue exitosa.
        response.raise_for_status()
        logging.info("✅ Teclado personalizado enviado con éxito.")
        return True  # Retorna True si la solicitud fue exitosa.
    except requests.exceptions.RequestException as e:
        # Captura errores de solicitud.
        logging.error(
            f"❌ Error al enviar teclado personalizado a Telegram: {e}")
        return False  # Retorna False en caso de error.


def remove_keyboard_menu(token, chat_id, message_text="Teclado oculto."):
    """
    Oculta el teclado personalizado de Telegram, volviendo al teclado normal del dispositivo.

    Args:
        token (str): El token de la API de tu bot de Telegram.
        chat_id (str): El ID del chat de Telegram donde se ocultará el teclado.
        message_text (str, optional): El texto del mensaje que acompaña la acción de ocultar.
                                      Por defecto es "Teclado oculto.".

    Returns:
        bool: True si el teclado se ocultó con éxito, False en caso contrario.
    """
    # Verifica si el token no está configurado.
    if not token:
        logging.warning(
            "⚠️ TOKEN de Telegram no configurado. No se puede ocultar el teclado.")
        return False

    # Construye la URL para la API de Telegram.
    url = f"https://api.telegram.org/bot{token}/sendMessage"

    # Define la estructura para ocultar el teclado.
    remove_keyboard = {
        # Indica a Telegram que oculte el teclado personalizado.
        'remove_keyboard': True
    }

    # Define la carga útil (payload) de la solicitud HTTP.
    payload = {
        'chat_id': chat_id,
        'text': message_text,
        # Convierte el diccionario a una cadena JSON.
        'reply_markup': json.dumps(remove_keyboard)
    }

    try:
        # Envía la solicitud POST a la API de Telegram.
        response = requests.post(url, json=payload)
        # Lanza una excepción HTTPError si la respuesta no fue exitosa.
        response.raise_for_status()
        logging.info("✅ Teclado personalizado ocultado con éxito.")
        return True  # Retorna True si la solicitud fue exitosa.
    except requests.exceptions.RequestException as e:
        # Captura errores de solicitud.
        logging.error(f"❌ Error al ocultar teclado personalizado: {e}")
        return False  # Retorna False en caso de error.


def set_telegram_commands_menu(token):
    """
    Configura el menú de comandos que aparece cuando el usuario escribe '/' en el campo de texto de Telegram.
    Esta función debe ser llamada una vez al inicio del bot para registrar los comandos con la API de Telegram.

    Args:
        token (str): El token de la API de tu bot de Telegram.

    Returns:
        bool: True si el menú de comandos se configuró con éxito, False en caso contrario.
    """
    # Verifica si el token no está configurado.
    if not token:
        logging.warning(
            "⚠️ TOKEN de Telegram no configurado. No se puede configurar el menú de comandos.")
        return False

    # Construye la URL para la API de Telegram.
    url = f"https://api.telegram.org/bot{token}/setMyCommands"

    # Define la lista de comandos y sus descripciones.
    commands = [
        # Comandos existentes...
        {"command": "start", "description": "Iniciar bot y mostrar menú"},
        {"command": "menu", "description": "Mostrar menú"},
        {"command": "hide_menu", "description": "Ocultar menú"},
        {"command": "get_params", "description": "Mostrar parámetros actuales"},
        {"command": "set_tp",
            "description": "Establece Take Profit (ej. 0.03)"},
        {"command": "set_sl_fijo",
            "description": "Establece Stop Loss fijo (ej. 0.02)"},
        {"command": "set_tsl",
            "description": "Establece Trailing Stop (ej. 0.015)"},
        {"command": "set_riesgo",
            "description": "Establece riesgo por operación (ej. 0.01)"},
        {"command": "set_ema_corta_periodo",
            "description": "Período EMA corta (ej. 20)"},
        {"command": "set_ema_media_periodo",
            "description": "Período EMA media (ej. 50)"},
        {"command": "set_ema_larga_periodo",
            "description": "Período EMA larga (ej. 200)"},
        {"command": "set_rsi_periodo", "description": "Período RSI (ej. 14)"},
        {"command": "set_rsi_umbral",
            "description": "Umbral RSI sobrecompra (ej. 70)"},
        {"command": "set_intervalo",
            "description": "Intervalo ciclo en segundos (ej. 900)"},
        {"command": "set_breakeven_porcentaje",
            "description": "Breakeven % (ej. 0.005)"},
        # NUEVOS comandos para rango
        {"command": "set_periodo_analisis",
            "description": "Período análisis rango (ej. 20)"},
        {"command": "set_rango_umbral_atr",
            "description": "Umbral ATR rango (ej. 0.015)"},
        {"command": "set_rango_rsi",
            "description": "RSI rango: sobreventa sobrecompra (ej. 30 70)"},
        {"command": "toggle_rango", "description": "Activa/Desactiva trading en rango"},
        # Comandos clásicos
        {"command": "csv", "description": "Generar informe CSV"},
        {"command": "beneficio", "description": "Mostrar beneficio acumulado"},
        {"command": "vender",
            "description": "Vender posición (ej. /vender BTCUSDT)"},
        {"command": "reset_beneficio", "description": "Resetear beneficio acumulado"},
        {"command": "posiciones_actuales",
            "description": "Resumen de posiciones abiertas"},
        {"command": "help", "description": "Mostrar ayuda"}
    ]

    # Define la carga útil (payload) con la lista de comandos.
    payload = {'commands': json.dumps(commands)}
    # Define las cabeceras de la solicitud.
    headers = {'Content-Type': 'application/json'}

    try:
        # Envía la solicitud POST a la API de Telegram.
        response = requests.post(url, data=payload, headers=headers)
        # Lanza una excepción HTTPError si la respuesta no fue exitosa.
        response.raise_for_status()
        result = response.json()  # Obtiene la respuesta JSON.
        if result['ok']:
            logging.info(
                "✅ Menú de comandos de Telegram configurado con éxito.")
            return True  # Retorna True si la configuración fue exitosa.
        else:
            logging.error(
                f"❌ Fallo al configurar el menú de comandos: {result.get('description', 'Error desconocido')}")
            return False  # Retorna False si hubo un fallo.
    except requests.exceptions.RequestException as e:
        # Captura errores de red.
        logging.error(f"❌ Error de red al configurar el menú de comandos: {e}")
        return False  # Retorna False en caso de error.


def send_positions_file_content(token, chat_id, file_path):
    """
    Lee el contenido del archivo OPEN_POSITIONS_FILE (JSON), lo convierte a CSV
    y lo envía como un documento adjunto al chat de Telegram.

    Args:
        token (str): El token de la API de tu bot de Telegram.
        chat_id (str): El ID del chat de Telegram al que se enviará el documento.
        file_path (str): La ruta al archivo JSON de posiciones abiertas.
    """
    # Verifica si el archivo de posiciones existe.
    if not os.path.exists(file_path):
        send_telegram_message(
            token, chat_id, f"❌ Archivo de posiciones abiertas (<code>{_escape_html_entities(file_path)}</code>) no encontrado.")
        logging.warning(f"Intento de leer {file_path}, pero no existe.")
        return

    # Genera un nombre para el archivo CSV temporal.
    csv_file_name = file_path.replace(".json", ".csv")
    try:
        # Abre el archivo JSON de posiciones en modo lectura.
        with open(file_path, 'r') as f:
            positions_data = json.load(f)  # Carga los datos JSON.

        # Si no hay posiciones, envía un mensaje y sale.
        if not positions_data:
            send_telegram_message(
                token, chat_id, "🚫 No hay posiciones abiertas registradas para generar el CSV.")
            return

        # Preparar los datos para el CSV
        # Recopila todas las claves (nombres de columna) de todas las posiciones.
        all_keys = set()
        for data in positions_data.values():
            all_keys.update(data.keys())

        # Define los nombres de los campos (columnas) para el CSV, asegurando que 'Symbol' sea la primera.
        # Ordena el resto de las columnas para consistencia.
        fieldnames = ['Symbol'] + sorted(list(all_keys))

        # Crea una lista de diccionarios, donde cada diccionario es una fila del CSV.
        csv_rows = []
        for symbol, data in positions_data.items():
            row = {'Symbol': symbol}  # La primera columna es el símbolo.
            # Añade todos los campos de la posición a la fila.
            row.update(data)
            csv_rows.append(row)

        # Abre el archivo CSV en modo escritura, con newline='' para evitar filas en blanco y encoding='utf-8'.
        with open(csv_file_name, 'w', newline='', encoding='utf-8') as csvfile:
            # Crea un escritor de diccionarios CSV.
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()  # Escribe la fila de encabezados.
            writer.writerows(csv_rows)  # Escribe todas las filas de datos.

            # NUEVO: Añadir una fila de resumen con el beneficio total acumulado.
            # Crea un diccionario para la fila de resumen, inicializando todos los campos con cadenas vacías.
            summary_row = {field: '' for field in fieldnames}
            # Etiqueta para identificar esta fila como el resumen total.
            summary_row['timestamp'] = 'RESUMEN_TOTAL'
            # Calcula el beneficio total.
            summary_row['ganancia_usdt'] = sum(
                r.get('ganancia_usdt', 0.0) for r in csv_rows if 'ganancia_usdt' in r)
            # Descripción del contenido de la fila.
            summary_row['motivo_venta'] = 'Beneficio Total Acumulado'
            # Escribe la fila de resumen en el CSV.
            writer.writerow(summary_row)

        # Envía el archivo CSV generado a Telegram como un documento.
        caption = f"📄 Posiciones abiertas en formato CSV: <code>{_escape_html_entities(os.path.basename(csv_file_name))}</code>"
        send_telegram_document(token, chat_id, csv_file_name, caption)
        logging.info(
            f"Archivo {csv_file_name} enviado como documento a Telegram.")

    except json.JSONDecodeError as e:
        # Captura errores si el archivo JSON no es válido.
        send_telegram_message(
            token, chat_id, f"❌ Error al leer el archivo JSON de posiciones (formato inválido): {_escape_html_entities(e)}")
        logging.error(
            f"❌ Error al decodificar JSON de {file_path}: {e}", exc_info=True)
    except Exception as e:
        # Captura cualquier otro error durante la conversión o envío.
        send_telegram_message(
            token, chat_id, f"❌ Error al convertir o enviar el archivo de posiciones como CSV: {_escape_html_entities(e)}")
        logging.error(
            f"❌ Error al procesar {file_path} y enviar como CSV: {e}", exc_info=True)
    finally:
        # Este bloque se ejecuta siempre, asegurando que el archivo CSV temporal se elimine.
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
        " - <code>/set_ema_corta_periodo &lt;valor&gt;</code>: Establece el período de la EMA corta (ej. 20).\n"
        " - <code>/set_ema_media_periodo &lt;valor&gt;</code>: Establece el período de la EMA media (ej. 50).\n"
        " - <code>/set_ema_larga_periodo &lt;valor&gt;</code>: Establece el período de la EMA larga (ej. 200).\n"
        " - <code>/set_rsi_periodo &lt;valor&gt;</code>: Establece el período del RSI (ej. 14).\n"
        " - <code>/set_rsi_umbral &lt;valor&gt;</code>: Establece el umbral de sobrecompra del RSI (ej. 70).\n"
        " - <code>/set_intervalo &lt;segundos&gt;</code>: Establece el intervalo del ciclo principal del bot en segundos (ej. 300).\n"
        " - <code>/set_breakeven_porcentaje &lt;valor&gt;</code>: Mueve SL a breakeven (ej. /set_breakeven_porcentaje 0.005).\n\n"
        "<b>Informes:</b>\n"
        " - <code>/csv</code>: Genera y envía un archivo CSV con las transacciones del día hasta el momento.\n"
        " - <code>/beneficio</code>: Muestra el beneficio total acumulado por el bot.\n\n"
        "<b>Utilidades:</b>\n"
        " - <code>/vender &lt;SIMBOLO_USDT&gt;</code>: Vende una posición abierta de forma manual (ej. /vender BTCUSDT).\n"
        " - <code>/reset_beneficio</code>: Resetear beneficio acumulado a cero.\n"
        # Cambiado el comando y descripción
        " - <code>/analisis</code>: Abrir página de análisis web.\n"
        " - <code>/posiciones_actuales</code>: Mostrar resumen de posiciones abiertas.\n"
        " - <code>/help</code>: Mostrar ayuda y comandos disponibles\n"
        # ---------- AÑADE ESTO AL FINAL DE "Parámetros de Estrategia" ----------
        " - <code>/set_periodo_analisis &lt;entero&gt;</code>: Ajusta período para detectar rango lateral (ej. 20)\n"
        " - <code>/set_rango_umbral_atr &lt;decimal&gt;</code>: Ajusta umbral ATR para rango (ej. 0.015)\n"
        " - <code>/set_rango_rsi &lt;sobreventa&gt; &lt;sobrecompra&gt;</code>: Ajusta RSI para operar en rango (ej. 30 70)\n"
        " - <code>/toggle_rango</code>: Activa o desactiva el trading en mercado lateral\n"
    )
    send_telegram_message(token, chat_id, help_message)


def send_current_positions_summary(client, open_positions, token, chat_id):
    """
    Muestra las posiciones abiertas con SL / TP / TSL.
    """
    if not open_positions:
        send_telegram_message(
            token, chat_id, "🚫 No tienes posiciones abiertas.")
        return

    msg = ""
    for symbol, data in open_positions.items():
        precio_entrada = data.get('precio_compra', 0.0)
        cantidad = data.get('cantidad_base', 0.0)
        precio_actual = binance_utils.obtener_precio_actual(client, symbol)

        # Cálculos
        tp = precio_entrada * \
            (1 + config_manager.load_parameters().get('TAKE_PROFIT_PORCENTAJE', 0.03))
        sl = data.get('stop_loss_fijo_nivel_actual',
                      precio_entrada * (1 - config_manager.load_parameters().get('STOP_LOSS_PORCENTAJE', 0.02)))
        max_alc = data.get('max_precio_alcanzado', precio_entrada)
        tsl = max_alc * \
            (1 - config_manager.load_parameters().get('TRAILING_STOP_PORCENTAJE', 0.015))

        msg += (
            f"📊 <b>{symbol}</b>\n"
            f"Posición:\n"
            f"  Entrada: {precio_entrada:.4f} | Cantidad: {cantidad:.6f} | PA: {precio_actual:.4f}\n"
            f"SL: {sl:.4f} | TP: {tp:.4f} | TSL: {tsl:.4f}\n\n"
        )

    send_telegram_message(token, chat_id, msg.strip())


def send_inline_url_button(token, chat_id, text, url):
    """
    Envía un mensaje con un botón en línea que abre una URL.
    """
    inline_keyboard = {
        'inline_keyboard': [
            [{'text': text, 'url': url}]
        ]
    }
    payload = {
        'chat_id': chat_id,
        'text': "Haz clic para ver el análisis:",
        'reply_markup': json.dumps(inline_keyboard)
    }
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        logging.info(f"✅ Botón de URL en línea enviado con éxito a {chat_id}.")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(
            f"❌ Error al enviar botón de URL en línea: {e}", exc_info=True)
        return False
