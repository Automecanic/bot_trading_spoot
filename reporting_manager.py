import csv
import os
import logging
from datetime import datetime
import telegram_handler
import binance_utils # Necesario para obtener_precio_eur y obtener_saldos_formateados
import firestore_utils # Importa el nuevo módulo para Firestore, que permite la interacción con la base de datos Firestore.

# Configura el sistema de registro para este módulo.
# Esto asegura que los mensajes informativos, advertencias y errores se muestren en la consola del bot.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre de la colección en Firestore para el historial de transacciones.
# Esta ruta sigue las reglas de seguridad de Firestore para datos públicos de la aplicación.
# '__app_id' es una variable de entorno proporcionada por el entorno de Canvas/Railway.
FIRESTORE_TRANSACTIONS_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/transactions_history"


def generar_y_enviar_csv_ahora(telegram_token, telegram_chat_id):
    """
    Genera un archivo CSV con TODAS las transacciones registradas en Firestore y lo envía por Telegram.
    Este comando es útil para obtener un historial completo de operaciones bajo demanda.
    Requiere el token y chat_id de Telegram para enviar el documento.
    Incluye el beneficio total acumulado de todas las transacciones como una fila de resumen al final del CSV.
    """
    # Intenta obtener una instancia de la base de datos Firestore.
    db = firestore_utils.get_firestore_db()
    if not db:
        # Si la conexión a Firestore falla, envía un mensaje de error a Telegram y registra el error.
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "❌ Error: No se pudo conectar a Firestore para obtener transacciones.")
        logging.error("❌ No se pudo conectar a Firestore para generar CSV bajo demanda.")
        return

    transacciones_firestore = []
    # Inicializa la variable para acumular el beneficio total de todas las transacciones para este CSV.
    total_beneficio_acumulado_csv = 0.0

    try:
        # Obtener todas las transacciones de la colección especificada en Firestore.
        # El método .stream() recupera todos los documentos de la colección.
        docs = db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
        for doc in docs:
            transaccion = doc.to_dict() # Convierte el documento de Firestore a un diccionario Python.
            transacciones_firestore.append(transaccion) # Añade la transacción a la lista.
            # Suma la ganancia/pérdida de cada transacción al beneficio total acumulado.
            # Usa .get() con un valor por defecto (0.0) para evitar errores si 'ganancia_usdt' no existe.
            total_beneficio_acumulado_csv += transaccion.get('ganancia_usdt', 0.0)
        logging.info(f"✅ {len(transacciones_firestore)} transacciones cargadas desde Firestore para CSV bajo demanda. Beneficio total: {total_beneficio_acumulado_csv:.2f} USDT.")
    except Exception as e:
        # Si hay un error al cargar las transacciones de Firestore, notifica a Telegram y registra el error.
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al cargar transacciones desde Firestore: {e}")
        logging.error(f"❌ Error al cargar transacciones desde Firestore para CSV bajo demanda: {e}", exc_info=True)
        return

    if not transacciones_firestore:
        # Si no se encontraron transacciones en Firestore, informa al usuario.
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "🚫 No hay transacciones registradas en Firestore para generar el CSV.")
        return

    # Genera un nombre de archivo único para el CSV usando la fecha y hora actuales.
    fecha_actual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nombre_archivo_csv = f"transacciones_historico_{fecha_actual}.csv"

    try:
        # Obtener todos los nombres de campo (encabezados de columna) de todas las transacciones.
        # Esto asegura que el CSV contenga todas las columnas posibles, incluso si algunas transacciones
        # no tienen todos los campos.
        all_fieldnames = set()
        for transaccion in transacciones_firestore:
            all_fieldnames.update(transaccion.keys())
        
        # Ordenar los nombres de campo para consistencia en el CSV.
        # Prioriza 'timestamp' para que sea la primera columna si existe.
        fieldnames = sorted(list(all_fieldnames))
        if 'timestamp' in fieldnames:
            fieldnames.remove('timestamp')
            fieldnames.insert(0, 'timestamp') # Asegura que timestamp sea la primera columna

        # Abre el archivo CSV en modo escritura ('w') con codificación UTF-8.
        with open(nombre_archivo_csv, 'w', newline='', encoding='utf-8') as csvfile:
            # Crea un objeto DictWriter, que escribe filas de diccionarios en el CSV.
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader() # Escribe la fila de encabezados (nombres de columna).
            writer.writerows(transacciones_firestore) # Escribe todas las filas de transacciones.

            # NUEVO: Añadir una fila de resumen con el beneficio total acumulado.
            # Crea un diccionario para la fila de resumen, inicializando todos los campos con cadenas vacías.
            summary_row = {field: '' for field in fieldnames}
            summary_row['timestamp'] = 'RESUMEN_TOTAL' # Etiqueta para identificar esta fila como el resumen total.
            summary_row['ganancia_usdt'] = total_beneficio_acumulado_csv # El beneficio total acumulado.
            summary_row['motivo_venta'] = 'Beneficio Total Acumulado' # Descripción del contenido de la fila.
            writer.writerow(summary_row) # Escribe la fila de resumen en el CSV.

        # Envía el archivo CSV generado a Telegram como un documento.
        telegram_handler.send_telegram_document(telegram_token, telegram_chat_id, nombre_archivo_csv, f"📊 Informe de transacciones generado: {fecha_actual}")
        
    except Exception as e:
        # Captura cualquier error durante la generación o envío del CSV.
        logging.error(f"❌ Error al generar o enviar el CSV bajo demanda: {e}", exc_info=True)
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al generar o enviar el CSV: {e}")
    finally:
        # Este bloque se ejecuta siempre, asegurando que el archivo CSV temporal se elimine.
        if os.path.exists(nombre_archivo_csv):
            os.remove(nombre_archivo_csv)
            logging.info(f"Archivo CSV temporal {nombre_archivo_csv} eliminado.")

def enviar_informe_diario(telegram_token, telegram_chat_id):
    """
    Genera un archivo CSV con las transacciones registradas para el día actual desde Firestore y lo envía por Telegram.
    Este informe se genera automáticamente al inicio de un nuevo día de operación del bot.
    Requiere el token y chat_id de Telegram.
    Incluye el beneficio total diario como una fila de resumen al final del CSV.
    """
    # Intenta obtener una instancia de la base de datos Firestore.
    db = firestore_utils.get_firestore_db()
    if not db:
        # Si la conexión a Firestore falla, envía un mensaje de error a Telegram y registra el error.
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "❌ Error: No se pudo conectar a Firestore para generar informe diario.")
        logging.error("❌ No se pudo conectar a Firestore para generar informe diario.")
        return

    # Obtiene la fecha actual en formato YYYY-MM-DD para filtrar las transacciones del día.
    fecha_diario = datetime.now().strftime("%Y-%m-%d")
    # Genera un nombre de archivo único para el CSV diario.
    nombre_archivo_diario_csv = f"transacciones_diarias_{fecha_diario}.csv"
    
    transacciones_del_dia = []
    # Inicializa la variable para acumular el beneficio total del día.
    total_beneficio_diario = 0.0

    try:
        # Obtener todas las transacciones de la colección de Firestore.
        docs = db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
        for doc in docs:
            transaccion = doc.to_dict() # Convierte el documento de Firestore a un diccionario Python.
            # Filtra las transacciones para incluir solo las que ocurrieron en el día actual.
            if transaccion.get('timestamp', '').startswith(fecha_diario):
                transacciones_del_dia.append(transaccion) # Añade la transacción a la lista.
                # Suma la ganancia/pérdida de la transacción al beneficio diario.
                total_beneficio_diario += transaccion.get('ganancia_usdt', 0.0)
        logging.info(f"✅ {len(transacciones_del_dia)} transacciones cargadas desde Firestore para el informe diario de {fecha_diario}. Beneficio diario: {total_beneficio_diario:.2f} USDT.")

    except Exception as e:
        # Si hay un error al cargar las transacciones diarias de Firestore, notifica a Telegram y registra el error.
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al cargar transacciones diarias desde Firestore: {e}")
        logging.error(f"❌ Error al cargar transacciones diarias desde Firestore: {e}", exc_info=True)
        return

    if not transacciones_del_dia:
        # Si no se encontraron transacciones para el día actual, informa al usuario.
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "🚫 No hay transacciones registradas en Firestore para el día de hoy.")
        return

    try:
        # Obtener todos los nombres de campo de todas las transacciones del día para el encabezado del CSV.
        all_fieldnames = set()
        for transaccion in transacciones_del_dia:
            all_fieldnames.update(transaccion.keys())
        
        # Ordenar los nombres de campo para consistencia, y priorizar 'timestamp' si existe.
        fieldnames = sorted(list(all_fieldnames))
        if 'timestamp' in fieldnames:
            fieldnames.remove('timestamp')
            fieldnames.insert(0, 'timestamp')

        # Abre el archivo CSV en modo escritura ('w') con codificación UTF-8.
        with open(nombre_archivo_diario_csv, 'w', newline='', encoding='utf-8') as csvfile:
            # Crea un objeto DictWriter, que escribe filas de diccionarios en el CSV.
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader() # Escribe la fila de encabezados (nombres de columna).
            writer.writerows(transacciones_del_dia) # Escribe todas las filas de transacciones del día.
            
            # NUEVO: Añadir una fila de resumen con el beneficio total diario.
            # Crea un diccionario para la fila de resumen, inicializando todos los campos con cadenas vacías.
            summary_row = {field: '' for field in fieldnames}
            summary_row['timestamp'] = 'RESUMEN_DIARIO' # Etiqueta para identificar esta fila como el resumen diario.
            summary_row['ganancia_usdt'] = total_beneficio_diario # El beneficio total del día.
            summary_row['motivo_venta'] = 'Beneficio Total Diario' # Descripción del contenido de la fila.
            writer.writerow(summary_row) # Escribe la fila de resumen en el CSV.

        # Envía el archivo CSV diario generado a Telegram como un documento.
        telegram_handler.send_telegram_document(telegram_token, telegram_chat_id, nombre_archivo_diario_csv, f"📊 Informe diario de transacciones para {fecha_diario}")
    except Exception as e:
        # Captura cualquier error durante la generación o envío del CSV diario.
        logging.error(f"❌ Error al generar o enviar el informe diario CSV: {e}", exc_info=True)
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al generar o enviar el informe diario CSV: {e}")
    finally:
        # Este bloque se ejecuta siempre, asegurando que el archivo CSV temporal se elimine.
        if os.path.exists(nombre_archivo_diario_csv):
            os.remove(nombre_archivo_diario_csv)

def send_beneficio_message(client, total_beneficio_acumulado, telegram_token, telegram_chat_id):
    """
    Envía el beneficio total acumulado por el bot a Telegram como un mensaje de texto.
    Requiere el objeto 'client' de Binance para obtener la tasa de conversión a EUR,
    el beneficio acumulado en USDT, y el token/chat_id de Telegram.
    """
    # Obtiene la tasa de conversión de USDT a EUR para mostrar el beneficio en ambas monedas.
    eur_usdt_rate = binance_utils.obtener_precio_eur(client)
    # Calcula el beneficio en EUR. Si la tasa no se puede obtener, usa 0.0.
    beneficio_eur = total_beneficio_acumulado * eur_usdt_rate if eur_usdt_rate else 0.0

    # Construye el mensaje con el beneficio formateado.
    if total_beneficio_acumulado > 0:
        message = (
        f"📈 <b>Beneficio Total Acumulado:</b>\n"
        f"   👍 <b>{total_beneficio_acumulado:.2f} USDT</b>\n"
        f"   👍 <b>{beneficio_eur:.2f} EUR</b>"
        )
    else:
        message = (
        f"📈 <b>Beneficio Total Acumulado:</b>\n"
        f"   💩 <b>{total_beneficio_acumulado:.2f} USDT</b>\n"
        f"   💩 <b>{beneficio_eur:.2f} EUR</b>"
        )

    # Envía el mensaje a Telegram.
    telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, message)
