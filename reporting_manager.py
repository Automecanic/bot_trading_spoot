import os
import csv
import logging
from datetime import datetime
import telegram_handler
import binance_utils # Necesario para obtener_precio_eur y obtener_saldos_formateados
import firestore_utils # NUEVO: Importa el módulo para Firestore

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Nombre de la colección en Firestore para el historial de transacciones
# Debe coincidir con la definida en trading_logic.py
FIRESTORE_TRANSACTIONS_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/transactions_history"


def generar_y_enviar_csv_ahora(telegram_token, telegram_chat_id):
    """
    Genera un archivo CSV con TODAS las transacciones registradas en Firestore y lo envía por Telegram.
    Requiere el token y chat_id de Telegram.
    """
    db = firestore_utils.get_firestore_db()
    if not db:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "❌ Error: No se pudo conectar a Firestore para obtener transacciones.")
        logging.error("❌ No se pudo conectar a Firestore para generar CSV bajo demanda.")
        return

    transacciones_firestore = []
    try:
        # Obtener todas las transacciones de Firestore
        docs = db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
        for doc in docs:
            transacciones_firestore.append(doc.to_dict())
        logging.info(f"✅ {len(transacciones_firestore)} transacciones cargadas desde Firestore para CSV bajo demanda.")
    except Exception as e:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al cargar transacciones desde Firestore: {e}")
        logging.error(f"❌ Error al cargar transacciones desde Firestore para CSV bajo demanda: {e}", exc_info=True)
        return

    if not transacciones_firestore:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "🚫 No hay transacciones registradas en Firestore para generar el CSV.")
        return

    fecha_actual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nombre_archivo_csv = f"transacciones_historico_{fecha_actual}.csv"

    try:
        # Obtener todos los nombres de campo de todas las transacciones para el header del CSV
        all_fieldnames = set()
        for transaccion in transacciones_firestore:
            all_fieldnames.update(transaccion.keys())
        
        # Ordenar los nombres de campo para consistencia, y priorizar 'timestamp' si existe
        fieldnames = sorted(list(all_fieldnames))
        if 'timestamp' in fieldnames:
            fieldnames.remove('timestamp')
            fieldnames.insert(0, 'timestamp') # Asegura que timestamp sea la primera columna

        with open(nombre_archivo_csv, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            writer.writerows(transacciones_firestore)

        telegram_handler.send_telegram_document(telegram_token, telegram_chat_id, nombre_archivo_csv, f"📊 Informe de transacciones generado: {fecha_actual}")
        
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el CSV bajo demanda: {e}", exc_info=True)
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al generar o enviar el CSV: {e}")
    finally:
        if os.path.exists(nombre_archivo_csv):
            os.remove(nombre_archivo_csv)

def enviar_informe_diario(telegram_token, telegram_chat_id):
    """
    Genera un archivo CSV con las transacciones registradas para el día actual desde Firestore y lo envía por Telegram.
    Requiere el token y chat_id de Telegram.
    """
    db = firestore_utils.get_firestore_db()
    if not db:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "❌ Error: No se pudo conectar a Firestore para generar informe diario.")
        logging.error("❌ No se pudo conectar a Firestore para generar informe diario.")
        return

    fecha_diario = datetime.now().strftime("%Y-%m-%d")
    nombre_archivo_diario_csv = f"transacciones_diarias_{fecha_diario}.csv"
    
    transacciones_del_dia = []
    try:
        # Filtrar transacciones por el día actual
        # Firestore no soporta directamente filtros de fecha/hora complejos sin índices.
        # Una forma simple es obtener todas y filtrar en Python, o usar un campo de fecha específico.
        # Asumimos que 'timestamp' está en formato ISO (YYYY-MM-DDTHH:MM:SS.ffffff)
        docs = db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).stream()
        for doc in docs:
            transaccion = doc.to_dict()
            if transaccion.get('timestamp', '').startswith(fecha_diario):
                transacciones_del_dia.append(transaccion)
        logging.info(f"✅ {len(transacciones_del_dia)} transacciones cargadas desde Firestore para el informe diario de {fecha_diario}.")

    except Exception as e:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al cargar transacciones diarias desde Firestore: {e}")
        logging.error(f"❌ Error al cargar transacciones diarias desde Firestore: {e}", exc_info=True)
        return

    if not transacciones_del_dia:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "🚫 No hay transacciones registradas en Firestore para el día de hoy.")
        return

    try:
        # Obtener todos los nombres de campo de todas las transacciones del día para el header del CSV
        all_fieldnames = set()
        for transaccion in transacciones_del_dia:
            all_fieldnames.update(transaccion.keys())
        
        fieldnames = sorted(list(all_fieldnames))
        if 'timestamp' in fieldnames:
            fieldnames.remove('timestamp')
            fieldnames.insert(0, 'timestamp')

        with open(nombre_archivo_diario_csv, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            writer.writerows(transacciones_del_dia)
        telegram_handler.send_telegram_document(telegram_token, telegram_chat_id, nombre_archivo_diario_csv, f"📊 Informe diario de transacciones para {fecha_diario}")
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el informe diario CSV: {e}", exc_info=True)
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al generar o enviar el informe diario CSV: {e}")
    finally:
        if os.path.exists(nombre_archivo_diario_csv):
            os.remove(nombre_archivo_diario_csv)

def send_beneficio_message(client, total_beneficio_acumulado, telegram_token, telegram_chat_id):
    """
    Envía el beneficio total acumulado por el bot a Telegram.
    Requiere el objeto 'client' de Binance, el beneficio acumulado, y el token/chat_id de Telegram.
    """
    eur_usdt_rate = binance_utils.obtener_precio_eur(client)
    beneficio_eur = total_beneficio_acumulado * eur_usdt_rate if eur_usdt_rate else 0.0

    message = (
        f"📈 <b>Beneficio Total Acumulado:</b>\n"
        f"   - <b>{total_beneficio_acumulado:.2f} USDT</b>\n"
        f"   - <b>{beneficio_eur:.2f} EUR</b>"
    )
    telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, message)

