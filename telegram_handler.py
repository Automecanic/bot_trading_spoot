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

    Args:
        text (str): La cadena de texto a escapar.

    Returns:
        str: La cadena de texto con los caracteres HTML escapados.
    """
    return html.escape(str(text))  # Asegura que el input sea string antes de escapar.


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
    if not token or not chat_id:
        logging.warning(
            "⚠️ TOKEN o CHAT_ID de Telegram no configurados. No se pueden enviar mensajes.")
        return False

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
            # Fila 2: CSV y Archivo de Posiciones
            [{'text': '/csv'}, {'text': '/get_positions_file'}],
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
        {"command": "start", "description": "Iniciar el bot y mostrar menú"},
        {"command": "menu", "description": "Mostrar el menú de comandos"},
        {"command": "hide_menu", "description": "Ocultar el menú de comandos"},
        {"command": "get_params", "description": "Mostrar parámetros actuales del bot"},
        {"command": "set_tp",
            "description": "Establece el Take Profit (ej. /set_tp 0.03)"},
        {"command": "set_sl_fijo",
            "description": "Establece el Stop Loss Fijo (ej. /set_sl_fijo 0.02)"},
        {"command": "set_tsl",
            "description": "Establece el Trailing Stop Loss (ej. /set_tsl 0.015)"},
        {"command": "set_riesgo",
            "description": "Establece el porcentaje de riesgo por operación (ej. 0.01)"},
        {"command": "set_ema_corta_periodo",
            "description": "Establece el período de la EMA corta (ej. 20)"},
        {"command": "set_ema_media_periodo",
            "description": "Establece el período de la EMA media (ej. 50)"},
        {"command": "set_ema_larga_periodo",
            "description": "Establece el período de la EMA larga (ej. 200)"},
        {"command": "set_rsi_periodo",
            "description": "Establece el período del RSI (ej. 14)"},
        {"command": "set_rsi_umbral",
            "description": "Establece el umbral de sobrecompra del RSI (ej. 70)"},
        {"command": "set_intervalo",
            "description": "Establece el intervalo del ciclo principal del bot en segundos (ej. 300)"},
        {"command": "set_breakeven_porcentaje",
            "description": "Mueve SL a breakeven (ej. /set_breakeven_porcentaje 0.005)"},
        {"command": "csv", "description": "Generar y enviar informe CSV de transacciones"},
        {"command": "beneficio", "description": "Mostrar beneficio total acumulado"},
        {"command": "vender",
            "description": "Vender una posición (ej. /vender BTCUSDT)"},
        {"command": "reset_beneficio",
            "description": "Resetear beneficio acumulado a cero"},
        {"command": "get_positions_file",
            "description": "Obtener archivo de posiciones abiertas"},
        # Descripción del nuevo comando
        {"command": "posiciones_actuales",
            "description": "Mostrar resumen de posiciones abiertas"},
        {"command": "help", "description": "Mostrar ayuda y comandos disponibles"}
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
        " - <code>/get_positions_file</code>: Obtener archivo de posiciones abiertas.\n"
        # Descripción del comando de posiciones actuales.
        " - <code>/posiciones_actuales</code>: Mostrar resumen de posiciones abiertas.\n"
        " - <code>/menu</code>: Muestra el teclado de comandos principal.\n"
        " - <code>/hide_menu</code>: Oculta el teclado de comandos.\n\n"
        "<b>Ayuda:</b>\n"
        " - <code>/help</code>: Muestra este mensaje de ayuda.\n\n"
        "<i>Recuerda usar valores decimales para porcentajes y enteros para períodos/umbrales.</i>"
    )
    # Envía el mensaje de ayuda.
    send_telegram_message(token, chat_id, help_message)


def send_current_positions_summary(client, open_positions, telegram_token, telegram_chat_id):
    """
    Envía un resumen de las posiciones abiertas actuales a Telegram.
    Muestra la cantidad, el símbolo y el valor actual en USDT.

    Args:
        client: Instancia del cliente de Binance.
        open_positions (dict): Diccionario que contiene las posiciones abiertas del bot.
        telegram_token (str): El token de la API de tu bot de Telegram.
        telegram_chat_id (str): El ID del chat de Telegram al que se enviará el resumen.
    """
    # Si no hay posiciones abiertas, envía un mensaje informativo y sale.
    if not open_positions:
        send_telegram_message(telegram_token, telegram_chat_id,
                              "🚫 No tienes posiciones abiertas en este momento.")
        return

    # Encabezado del mensaje.
    summary_message = "📊 <b>Tus posiciones abiertas:</b>\n\n"
    total_value_usdt = 0.0

    # Itera sobre cada posición abierta.
    for symbol, data in open_positions.items():
        try:
            # Obtiene el precio actual del símbolo desde Binance.
            current_price = client.get_symbol_ticker(symbol=symbol)['price']
            current_price = float(current_price)

            cantidad = data.get('cantidad_base', 0.0)
            valor_actual = cantidad * current_price
            total_value_usdt += valor_actual

            # Escapar todas las partes dinámicas, incluyendo los números formateados
            escaped_cantidad = _escape_html_entities(f"{cantidad:.6f}")
            escaped_base_symbol = _escape_html_entities(
                symbol.replace('USDT', ''))
            escaped_precio_compra = _escape_html_entities(
                f"{data['precio_compra']:.4f}")
            escaped_valor_actual = _escape_html_entities(f"{valor_actual:.2f}")

            # Añade los detalles de la posición al mensaje de resumen.
            summary_message += (
                # Cantidad y símbolo base escapado.
                f" - <b>{escaped_cantidad} {escaped_base_symbol}</b> "
                # Precio de compra y valor actual.
                f"a {escaped_precio_compra} USDT (valor actual: <b>{escaped_valor_actual} USDT</b>)\n"
            )
        except Exception as e:
            # Captura errores al obtener datos de un símbolo y lo registra.
            logging.error(
                f"❌ Error al obtener datos para {symbol} en el resumen de posiciones: {e}", exc_info=True)
            # Añade un mensaje de error para ese símbolo, escapando el error.
            summary_message += f" - <b>{_escape_html_entities(symbol)}</b>: Error al obtener datos: {_escape_html_entities(e)}.\n"

    escaped_total_value_usdt = _escape_html_entities(f"{total_value_usdt:.2f}")
    # Añade el valor total al final.
    summary_message += f"\n<b>Valor total de posiciones: {escaped_total_value_usdt} USDT</b>"

    # Envía el resumen a Telegram.
    send_telegram_message(telegram_token, telegram_chat_id, summary_message)
