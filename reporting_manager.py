import os
import csv
import logging
from datetime import datetime
import telegram_handler
import binance_utils # Necesario para obtener_precio_eur y obtener_saldos_formateados

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def generar_y_enviar_csv_ahora(telegram_token, telegram_chat_id, transacciones_diarias):
    """
    Genera un archivo CSV con las transacciones registradas hasta el momento y lo envía por Telegram.
    Requiere el token y chat_id de Telegram, y la lista de transacciones diarias.
    """
    if not transacciones_diarias:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "🚫 No hay transacciones registradas para generar el CSV.")
        return

    fecha_actual = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    nombre_archivo_csv = f"transacciones_historico_{fecha_actual}.csv"

    try:
        with open(nombre_archivo_csv, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['FechaHora', 'Símbolo', 'Tipo', 'Precio', 'Cantidad', 'GananciaPerdidaUSDT', 'Motivo']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for transaccion in transacciones_diarias:
                writer.writerow(transaccion)

        telegram_handler.send_telegram_document(telegram_token, telegram_chat_id, nombre_archivo_csv, f"📊 Informe de transacciones generado: {fecha_actual}")
        
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el CSV bajo demanda: {e}", exc_info=True)
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al generar o enviar el CSV: {e}")
    finally:
        if os.path.exists(nombre_archivo_csv):
            os.remove(nombre_archivo_csv)

def enviar_informe_diario(telegram_token, telegram_chat_id, transacciones_diarias):
    """
    Genera un archivo CSV con las transacciones registradas para el día y lo envía por Telegram.
    Requiere el token y chat_id de Telegram, y la lista de transacciones diarias.
    """
    if not transacciones_diarias:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, "🚫 No hay transacciones registradas para el día de hoy.")
        return

    fecha_diario = datetime.now().strftime("%Y-%m-%d")
    nombre_archivo_diario_csv = f"transacciones_diarias_{fecha_diario}.csv"
    
    try:
        with open(nombre_archivo_diario_csv, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['FechaHora', 'Símbolo', 'Tipo', 'Precio', 'Cantidad', 'GananciaPerdidaUSDT', 'Motivo']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            writer.writeheader()
            for transaccion in transacciones_diarias:
                writer.writerow(transaccion)
        telegram_handler.send_telegram_document(telegram_token, telegram_chat_id, nombre_archivo_diario_csv, f"📊 Informe diario de transacciones para {fecha_diario}")
    except Exception as e:
        logging.error(f"❌ Error al generar o enviar el informe diario CSV: {e}", exc_info=True)
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error al generar o enviar el informe diario CSV: {e}")
    finally:
        if os.path.exists(nombre_archivo_diario_csv):
            os.remove(nombre_archivo_diario_csv)
    # Importante: No limpiar transacciones_diarias aquí, se debe hacer en el bucle principal
    # para que el informe se envíe y luego se resetee para el nuevo día.

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
