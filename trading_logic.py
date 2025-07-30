import config_manager  # Para guardar bot_params actualizado.
import telegram_handler  # Importar telegram_handler para usar _escape_html_entities
import position_manager
import binance_utils
# Importa el módulo logging para registrar eventos y mensajes informativos, de advertencia o error.
import logging
# Importa el módulo time para funciones relacionadas con el tiempo.
import time
import json  # Importa el módulo json para trabajar con datos en formato JSON.
# Importa todas las enumeraciones de Binance (ej. KLINE_INTERVAL_1MINUTE) para mayor comodidad.
from binance.enums import *
# Importa datetime y timedelta para trabajar con fechas y horas.
from datetime import datetime, timedelta
# Importa el módulo para Firestore, que permite la interacción con la base de datos Firestore.
import firestore_utils
# Importa el módulo os para interactuar con el sistema operativo, como acceder a variables de entorno.
import os
# Importa la excepción específica de Binance API.
from binance.exceptions import BinanceAPIException

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Importa módulos auxiliares que trading_logic necesita.
# Asumimos que estos módulos existen y están correctamente configurados en el mismo entorno.

# Nombre de la colección en Firestore para el historial de transacciones.
# La ruta sigue las reglas de seguridad de Firestore para datos públicos de la aplicación.
# '__app_id' es una variable de entorno proporcionada por el entorno de Canvas/Railway.
FIRESTORE_TRANSACTIONS_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/transactions_history"


def calcular_ema_rsi(client, symbol, ema_periodo_corta, ema_periodo_media, ema_periodo_larga, rsi_periodo):
    """
    Calcula la Media Móvil Exponencial (EMA) corta, EMA media, EMA larga y el Índice de Fuerza Relativa (RSI)
    para un símbolo dado.
    Requiere el cliente de Binance y los períodos para cada indicador.

    Args:
        client: Instancia del cliente de Binance.
        symbol (str): El par de trading (ej. "BTCUSDT").
        ema_periodo_corta (int): Período para la EMA corta.
        ema_periodo_media (int): Período para la EMA media.
        ema_periodo_larga (int): Período para la EMA larga.
        rsi_periodo (int): Período para el cálculo del RSI.

    Returns:
        tuple: Una tupla que contiene (ema_corta_valor, ema_media_valor, ema_larga_valor, rsi_valor).
               Retorna (None, None, None, None) si no se pueden calcular los indicadores.
    """
    try:
        # Obtener datos históricos (velas) para el cálculo de indicadores.
        # Se obtienen suficientes velas para la EMA más larga y el RSI, más un buffer.
        max_periodo = max(ema_periodo_corta, ema_periodo_media,
                          ema_periodo_larga, rsi_periodo)

        # Calcular el tiempo de inicio en milisegundos
        # Se necesitan suficientes minutos para cubrir el período más largo + un buffer.
        # Por ejemplo, si el período más largo es 200, y queremos 50 velas de buffer,
        # necesitamos datos de 250 minutos atrás.
        start_time = datetime.now() - timedelta(minutes=max_periodo + 50)
        # Convertir el objeto datetime a milisegundos para la API de Binance.
        start_str_ms = int(start_time.timestamp() * 1000)

        # Usar el timestamp en milisegundos para get_historical_klines
        klines = client.get_historical_klines(
            symbol, KLINE_INTERVAL_1MINUTE, start_str_ms)

        # Extraer los precios de cierre de las velas.
        close_prices = [float(k[4]) for k in klines]

        if len(close_prices) < max_periodo:
            logging.warning(
                f"⚠️ No hay suficientes datos para calcular indicadores para {symbol}. Se necesitan al menos {max_periodo} velas, pero se obtuvieron {len(close_prices)}.")
            return None, None, None, None

        # Función auxiliar interna para calcular una EMA.
        def calculate_single_ema(prices, period):
            if period <= 0 or len(prices) < period:
                return None
            smoothing_factor = 2 / (period + 1)
            # Inicializar EMA con el promedio de los primeros 'period' precios
            # Esto es una forma más robusta de inicializar la EMA para evitar sesgos iniciales.
            ema = sum(prices[:period]) / period
            for i in range(period, len(prices)):
                ema = (prices[i] * smoothing_factor) + \
                    (ema * (1 - smoothing_factor))
            return ema

        # Calcular los valores de las tres EMAs.
        ema_corta_valor = calculate_single_ema(close_prices, ema_periodo_corta)
        ema_media_valor = calculate_single_ema(close_prices, ema_periodo_media)
        ema_larga_valor = calculate_single_ema(close_prices, ema_periodo_larga)

        # Calcular RSI.
        gains = []
        losses = []
        for i in range(1, len(close_prices)):
            difference = close_prices[i] - close_prices[i-1]
            if difference > 0:
                gains.append(difference)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(difference))

        if len(gains) < rsi_periodo:
            logging.warning(
                f"⚠️ No hay suficientes datos para calcular RSI para {symbol}. Se necesitan al menos {rsi_periodo} cambios de precio, pero se obtuvieron {len(gains)}.")
            return ema_corta_valor, ema_media_valor, ema_larga_valor, None

        # Calcular la ganancia y pérdida promedio inicial.
        avg_gain = sum(gains[:rsi_periodo]) / rsi_periodo
        avg_loss = sum(losses[:rsi_periodo]) / rsi_periodo

        # Calcular la ganancia y pérdida promedio suavizada para el resto de los datos.
        for i in range(rsi_periodo, len(gains)):
            avg_gain = ((avg_gain * (rsi_periodo - 1)) +
                        gains[i]) / rsi_periodo
            avg_loss = ((avg_loss * (rsi_periodo - 1)) +
                        losses[i]) / rsi_periodo

        # Calcular Relative Strength (RS) y Relative Strength Index (RSI).
        # Evitar división por cero, asignar inf si solo hay ganancias.
        rs = avg_gain / \
            avg_loss if avg_loss != 0 else (
                float('inf') if avg_gain > 0 else 0)
        rsi_valor = 100 - (100 / (1 + rs)) if (avg_loss != 0 or avg_gain != 0) and rs != float(
            # Si ambos son cero, RSI es 50 (neutral).
            'inf') else (100 if rs == float('inf') else 50)

        return ema_corta_valor, ema_media_valor, ema_larga_valor, rsi_valor

    except Exception as e:
        logging.error(
            f"❌ Error al calcular EMA/RSI para {symbol}: {e}", exc_info=True)
        return None, None, None, None


def calcular_cantidad_a_comprar(client, saldo_usdt, precio_actual, stop_loss_porcentaje, symbol, riesgo_por_operacion_porcentaje, capital_total):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el saldo USDT disponible,
    el precio actual, el stop loss y el porcentaje de riesgo por operación,
    asegurando que el riesgo se calcule sobre el capital total y la cantidad no exceda el saldo disponible.

    Args:
        client: Instancia del cliente de Binance.
        saldo_usdt (float): Saldo actual de USDT disponible en la cuenta.
        precio_actual (float): Precio actual del par de trading.
        stop_loss_porcentaje (float): Porcentaje de stop loss para calcular el riesgo.
        symbol (str): El par de trading (ej. "BTCUSDT").
        riesgo_por_operacion_porcentaje (float): Porcentaje del capital total a arriesgar por operación.
        capital_total (float): El capital total disponible en USDT.

    Returns:
        float: La cantidad de criptomoneda a comprar, ajustada a las reglas de Binance. Retorna 0.0 si no es posible comprar.
    """
    if precio_actual <= 0:
        logging.warning(
            "❌ Precio actual es cero o negativo. No se puede calcular la cantidad a comprar.")
        return 0.0

    # 1. Calcular el monto máximo en USDT que estamos dispuestos a arriesgar en esta operación.
    max_usdt_a_riesgar = capital_total * riesgo_por_operacion_porcentaje
    logging.info(
        f"DEBUG: Capital Total: {capital_total:.2f} USDT, Riesgo por Operación: {riesgo_por_operacion_porcentaje*100:.2f}%, Máximo USDT a Arriesgar: {max_usdt_a_riesgar:.2f} USDT")

    # 2. Calcular el saldo USDT disponible con un buffer para comisiones.
    BUFFER_PORCENTAJE = 0.0015  # 0.15% de buffer para comisiones y precisión.
    saldo_usdt_con_buffer = saldo_usdt * (1 - BUFFER_PORCENTAJE)
    logging.info(
        f"DEBUG: Saldo USDT disponible: {saldo_usdt:.2f} USDT, Saldo con buffer ({BUFFER_PORCENTAJE*100:.2f}%): {saldo_usdt_con_buffer:.2f} USDT")

    # 3. Determinar el presupuesto efectivo para la compra.
    # Es el mínimo entre el riesgo permitido y el saldo disponible con buffer.
    effective_budget_usdt = min(max_usdt_a_riesgar, saldo_usdt_con_buffer)
    logging.info(
        f"DEBUG: Presupuesto efectivo para la compra: {effective_budget_usdt:.2f} USDT")

    if effective_budget_usdt <= 0:
        logging.warning(
            "⚠️ Presupuesto efectivo para la compra es cero o negativo. No se puede comprar.")
        return 0.0

    # 4. Calcular la cantidad raw basada en el presupuesto efectivo.
    cantidad_raw = effective_budget_usdt / precio_actual
    logging.info(
        f"DEBUG: Cantidad raw basada en presupuesto efectivo: {cantidad_raw:.8f}")

    # 5. Obtener los filtros de Binance.
    step_size = binance_utils.get_step_size(client, symbol)
    info = client.get_symbol_info(symbol)
    min_notional = 0.0
    min_qty = 0.0
    for f in info['filters']:
        if f['filterType'] == 'MIN_NOTIONAL':
            min_notional = float(f['minNotional'])
        elif f['filterType'] == 'LOT_SIZE':
            min_qty = float(f['minQty'])

    # *** NUEVO LOGGING PARA DEPURACIÓN ***
    logging.info(
        f"DEBUG: Filters for {symbol}: Step Size={step_size}, Min Qty={min_qty}, Min Notional={min_notional}")
    # ***********************************

    # 6. Ajustar la cantidad raw al step_size.
    cantidad_final_ajustada = binance_utils.ajustar_cantidad(
        cantidad_raw, step_size)
    logging.info(
        f"DEBUG: Cantidad ajustada por step_size (primera pasada): {cantidad_final_ajustada:.8f}")

    # 7. Bucle para asegurar que el valor de la orden no exceda el saldo disponible.
    # Reducimos la cantidad en un step_size si el valor total de la orden excede el saldo con buffer.
    # También nos aseguramos de que la cantidad no caiga por debajo de min_qty o min_notional.
    while (cantidad_final_ajustada * precio_actual) > saldo_usdt_con_buffer and cantidad_final_ajustada > min_qty:
        logging.warning(
            f"⚠️ Valor de orden ({cantidad_final_ajustada * precio_actual:.2f} USDT) excede saldo con buffer ({saldo_usdt_con_buffer:.2f} USDT). Reduciendo cantidad en un step_size.")
        cantidad_final_ajustada = binance_utils.ajustar_cantidad(
            cantidad_final_ajustada - step_size, step_size)
        if cantidad_final_ajustada < min_qty or (cantidad_final_ajustada * precio_actual) < min_notional:
            logging.warning(
                f"⚠️ Reducción de cantidad para {symbol} resultó en un valor por debajo de min_qty o min_notional. Abortando compra.")
            return 0.0

    # Verificación final después de los ajustes.
    if cantidad_final_ajustada <= 0 or cantidad_final_ajustada < min_qty or (cantidad_final_ajustada * precio_actual) < min_notional:
        logging.warning(
            f"⚠️ La cantidad final ajustada para {symbol} ({cantidad_final_ajustada:.6f} {symbol.replace('USDT', '')}) es insignificante o resulta en un valor inferior al mínimo nocional ({min_notional} USDT) o min_qty ({min_qty}). Retornando 0.")
        return 0.0

    logging.info(
        f"✅ Cantidad final a comprar para {symbol}: {cantidad_final_ajustada:.8f} (Valor: {cantidad_final_ajustada * precio_actual:.2f} USDT)")
    return cantidad_final_ajustada


def comprar(client, symbol, cantidad, posiciones_abiertas, stop_loss_porcentaje, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file):
    """
    Ejecuta una orden de compra a precio de mercado en Binance.
    Registra la posición, la transacción y envía una notificación a Telegram.

    Args:
        client: Instancia del cliente de Binance.
        symbol (str): El par de trading (ej. "BTCUSDT").
        cantidad (float): La cantidad de la criptomoneda a comprar.
        posiciones_abiertas (dict): Diccionario de posiciones abiertas del bot.
        stop_loss_porcentaje (float): Porcentaje de stop loss para la nueva posición.
        transacciones_diarias (list): Lista de transacciones del día para el informe.
        telegram_bot_token (str): Token del bot de Telegram.
        telegram_chat_id (str): ID del chat de Telegram.
        open_positions_file (str): Ruta al archivo de posiciones abiertas.

    Returns:
        dict or None: La respuesta de la orden de Binance si fue exitosa, None en caso contrario.
    """
    try:
        # --- Pre-check robusto antes de colocar la orden ---
        # Volver a obtener el saldo USDT más reciente justo antes de colocar la orden.
        latest_saldo_usdt = binance_utils.obtener_saldo_moneda(client, "USDT")
        latest_precio_actual = binance_utils.obtener_precio_actual(
            client, symbol)

        if latest_precio_actual <= 0:
            logging.error(
                f"❌ No se pudo obtener el precio actual para {symbol} justo antes de la compra. Abortando.")
            telegram_handler.send_telegram_message(
                telegram_bot_token, telegram_chat_id, f"❌ Error: No se pudo obtener precio para <b>{telegram_handler._escape_html_entities(symbol)}</b> antes de comprar.")
            return None

        # Definir un buffer para comisiones y asegurar que la orden pase.
        BUFFER_PORCENTAJE = 0.0015  # 0.15% de buffer.

        # Calcular la cantidad máxima posible basada en el saldo USDT más reciente y el buffer.
        max_cantidad_posible_por_saldo_latest = (
            latest_saldo_usdt * (1 - BUFFER_PORCENTAJE)) / latest_precio_actual

        # Obtener los filtros de cantidad mínima y valor nocional de Binance.
        step_size = binance_utils.get_step_size(client, symbol)
        info = client.get_symbol_info(symbol)
        min_notional = 0.0
        min_qty = 0.0
        for f in info['filters']:
            if f['filterType'] == 'MIN_NOTIONAL':
                min_notional = float(f['minNotional'])
            elif f['filterType'] == 'LOT_SIZE':
                min_qty = float(f['minQty'])

        # Tomar el mínimo entre la cantidad calculada por la estrategia y la cantidad máxima posible por saldo.
        final_cantidad_to_buy = min(
            cantidad, max_cantidad_posible_por_saldo_latest)
        # Ajustar la cantidad final al step_size de Binance.
        final_cantidad_to_buy = binance_utils.ajustar_cantidad(
            final_cantidad_to_buy, step_size)

        # Verificación final contra min_notional y min_qty.
        if final_cantidad_to_buy <= 0 or final_cantidad_to_buy < min_qty or (final_cantidad_to_buy * latest_precio_actual) < min_notional:
            logging.warning(f"⚠️ Compra de {symbol} abortada: Cantidad final ({final_cantidad_to_buy:.8f}) o valor nocional ({final_cantidad_to_buy * latest_precio_actual:.2f} USDT) es insuficiente para la orden. Saldo USDT: {latest_saldo_usdt:.2f}. Min. Nocional: {min_notional:.2f}, Min. Qty: {min_qty:.8f}")
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                   f"⚠️ Compra de <b>{telegram_handler._escape_html_entities(symbol)}</b> abortada: Saldo insuficiente o cantidad/valor mínimo no alcanzado. Saldo USDT: {latest_saldo_usdt:.2f}.")
            return None

        logging.info(
            f"Intentando COMPRA de {symbol} con cantidad: {final_cantidad_to_buy:.8f} (Saldo USDT justo antes: {latest_saldo_usdt:.2f})")

        # Ejecutar orden de compra a mercado.
        order = client.order_market_buy(
            symbol=symbol, quantity=final_cantidad_to_buy)

        # Procesar la respuesta de la orden.
        if order and order['status'] == 'FILLED':
            # Precio al que se ejecutó la orden.
            precio_ejecucion = float(order['fills'][0]['price'])
            # Cantidad real comprada.
            cantidad_comprada_real = float(order['fills'][0]['qty'])

            # Registrar la nueva posición en el diccionario de posiciones abiertas del bot.
            posiciones_abiertas[symbol] = {
                'precio_compra': precio_ejecucion,
                'cantidad_base': cantidad_comprada_real,
                # El precio máximo alcanzado se inicializa con el precio de compra.
                'max_precio_alcanzado': precio_ejecucion,
                # Calcula el SL inicial.
                'stop_loss_fijo_nivel_actual': precio_ejecucion * (1 - stop_loss_porcentaje),
                # Bandera para el breakeven, inicialmente False.
                'sl_moved_to_breakeven': False,
                # Timestamp de apertura de la posición.
                'timestamp_apertura': datetime.now().isoformat()
            }
            # Guarda las posiciones (con debounce).
            position_manager.save_open_positions_debounced(posiciones_abiertas)

            # Registrar la transacción para el informe diario y Firestore.
            transaccion = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'tipo': 'COMPRA',
                'precio': precio_ejecucion,
                'cantidad': cantidad_comprada_real,
                'valor_usdt': precio_ejecucion * cantidad_comprada_real
            }
            # Añade a la lista de transacciones diarias.
            transacciones_diarias.append(transaccion)

            # Guardar la transacción en Firestore.
            db = firestore_utils.get_firestore_db()
            if db:
                try:
                    db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).add(
                        transaccion)
                    logging.info(
                        f"✅ Transacción de COMPRA guardada en Firestore para {symbol}.")
                except Exception as e:
                    logging.error(
                        f"❌ Error al guardar transacción de COMPRA en Firestore para {symbol}: {e}", exc_info=True)
                    telegram_handler.send_telegram_message(
                        telegram_bot_token, telegram_chat_id, f"❌ Error al guardar transacción de COMPRA en Firestore para {telegram_handler._escape_html_entities(symbol)}: {telegram_handler._escape_html_entities(e)}")

            # Envía notificación de compra exitosa a Telegram.
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                   f"🟢 COMPRA de <b>{telegram_handler._escape_html_entities(symbol)}</b> ejecutada a <b>{precio_ejecucion:.4f}</b> USDT. Cantidad: {cantidad_comprada_real:.6f}")
            logging.info(
                f"✅ COMPRA exitosa de {cantidad_comprada_real} {symbol} a {precio_ejecucion}")
            return order  # Retorna la respuesta de la orden de Binance.
        else:
            # Si la orden no se llenó, envía un mensaje de fallo a Telegram y registra el error.
            error_msg_content = f"Estado: {telegram_handler._escape_html_entities(order.get('status', 'N/A'))}"
            if 'msg' in order:  # Algunos errores de Binance tienen un campo 'msg'
                error_msg_content += f", Mensaje: {telegram_handler._escape_html_entities(order['msg'])}"
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                   f"❌ Fallo al ejecutar COMPRA de <b>{telegram_handler._escape_html_entities(symbol)}</b>. {error_msg_content}")
            logging.error(
                f"❌ Fallo al ejecutar COMPRA de {symbol}. Respuesta: {order}")
            return None  # Retorna None si la compra falló.
    except BinanceAPIException as e:
        # Captura errores específicos de la API de Binance.
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                               f"❌ Error de Binance API al intentar COMPRA de <b>{telegram_handler._escape_html_entities(symbol)}</b>: Código: {telegram_handler._escape_html_entities(str(e.code))}, Mensaje: {telegram_handler._escape_html_entities(e.message)}")
        logging.error(
            f"❌ Error en la función comprar para {symbol}: {e}", exc_info=True)
        return None  # Retorna None en caso de error.
    except Exception as e:
        # Captura cualquier otro error general durante el intento de compra.
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                               f"❌ Error general al intentar COMPRA de <b>{telegram_handler._escape_html_entities(symbol)}</b>: {telegram_handler._escape_html_entities(str(e))}")
        logging.error(
            f"❌ Error en la función comprar para {symbol}: {e}", exc_info=True)
        return None  # Retorna None en caso de error.


def vender(client, symbol, cantidad_a_vender, posiciones_abiertas, total_beneficio_acumulado, bot_params, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file, config_manager, motivo_venta=""):
    """
    Ejecuta una orden de venta a precio de mercado en Binance.
    Actualiza el beneficio total, elimina la posición y envía una notificación a Telegram.
    Maneja órdenes parcialmente llenadas o expiradas, calculando el beneficio sobre la cantidad realmente vendida.

    Args:
        client: Instancia del cliente de Binance.
        symbol (str): El par de trading (ej. "BTCUSDT").
        cantidad_a_vender (float): La cantidad de la criptomoneda a vender.
        posiciones_abiertas (dict): Diccionario de posiciones abiertas del bot.
        total_beneficio_acumulado (float): El beneficio total acumulado del bot.
        bot_params (dict): Diccionario de parámetros del bot (para actualizar el beneficio).
        transacciones_diarias (list): Lista de transacciones del día para el informe.
        telegram_bot_token (str): Token del bot de Telegram.
        telegram_chat_id (str): ID del chat de Telegram.
        open_positions_file (str): Ruta al archivo de posiciones abiertas.
        config_manager: Módulo para guardar los parámetros del bot.
        motivo_venta (str, optional): El motivo por el cual se realiza la venta (ej. "TAKE PROFIT").

    Returns:
        dict or None: La respuesta de la orden de Binance si fue exitosa (total o parcial), None en caso contrario.
    """
    base_asset = symbol.replace(
        "USDT", "")  # Extrae el activo base (ej. BTC de BTCUSDT).

    try:
        # Obtener información del símbolo para verificar la cantidad mínima de la orden (minQty y minNotional).
        info = client.get_symbol_info(symbol)
        min_notional = 0.0  # Valor mínimo de la orden en USDT.
        min_qty = 0.0  # Cantidad mínima de la moneda base.

        for f in info['filters']:
            if f['filterType'] == 'MIN_NOTIONAL':
                min_notional = float(f['minNotional'])
            elif f['filterType'] == 'LOT_SIZE':
                min_qty = float(f['minQty'])

        # Obtener el saldo real actual para este activo en la cuenta de Binance.
        saldo_real_activo = binance_utils.obtener_saldo_moneda(
            client, base_asset)

        # Ajustar la cantidad a vender al step_size de Binance para asegurar que la orden sea válida.
        cantidad_a_vender_ajustada = binance_utils.ajustar_cantidad(
            saldo_real_activo, binance_utils.get_step_size(client, symbol))

        # Verificar si la cantidad ajustada es suficiente para una orden.
        if cantidad_a_vender_ajustada <= 0 or cantidad_a_vender_ajustada < min_qty:
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                   f"⚠️ No hay <b>{telegram_handler._escape_html_entities(symbol)}</b> disponible para vender o la cantidad ({cantidad_a_vender_ajustada:.8f}) es demasiado pequeña (mínimo: {min_qty:.8f}).")
            logging.warning(
                f"⚠️ No hay {symbol} disponible para vender o la cantidad ({cantidad_a_vender_ajustada:.8f}) es demasiado pequeña (mínimo: {min_qty:.8f}).")

            # Si la posición está en el registro del bot pero no hay saldo real, eliminarla para sincronizar.
            if symbol in posiciones_abiertas:
                del posiciones_abiertas[symbol]
            # Guarda los cambios.
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(
                f"Posición de {symbol} eliminada del registro interno debido a saldo insuficiente.")
            return None

        # Verificar si el valor nocional (cantidad * precio) es suficiente.
        precio_actual = binance_utils.obtener_precio_actual(client, symbol)
        valor_nocional = cantidad_a_vender_ajustada * precio_actual

        if valor_nocional < min_notional:
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                   f"⚠️ El valor de venta de <b>{telegram_handler._escape_html_entities(symbol)}</b> ({valor_nocional:.2f} USDT) es inferior al mínimo nocional requerido ({min_notional:.2f} USDT). No se puede vender.")
            logging.warning(
                f"⚠️ El valor de venta de {symbol} ({valor_nocional:.2f} USDT) es inferior al mínimo nocional requerido ({min_notional:.2f} USDT).")

            # Si la posición está en el registro del bot pero su valor es muy bajo, eliminarla.
            if symbol in posiciones_abiertas:
                del posiciones_abiertas[symbol]
            # Guarda los cambios.
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(
                f"Posición de {symbol} eliminada del registro interno debido a valor nocional insuficiente.")
            return None

        # Ejecutar orden de venta a mercado.
        order = client.order_market_sell(
            symbol=symbol, quantity=cantidad_a_vender_ajustada)

        # Procesar la respuesta de la orden.
        # Se considera exitosa si el estado es 'FILLED' (completada) o 'EXPIRED' con una cantidad ejecutada > 0 (parcialmente llenada).
        if order and (order['status'] == 'FILLED' or (order['status'] == 'EXPIRED' and float(order.get('executedQty', 0)) > 0)):
            # Precio de la primera ejecución (se usa como precio promedio si hay múltiples fills).
            precio_ejecucion = float(order['fills'][0]['price'])
            # Cantidad total ejecutada (realmente vendida).
            cantidad_vendida_real = float(order['executedQty'])

            # Calcular beneficio/pérdida solo para la cantidad que realmente se vendió.
            # Se intenta obtener el precio de compra de la posición abierta.
            if symbol in posiciones_abiertas:
                # Eliminar la posición del diccionario de posiciones abiertas.
                posicion = posiciones_abiertas.pop(symbol)
                precio_compra = posicion['precio_compra']
            else:
                # Si la posición no está en el registro (ej. fue eliminada previamente por limpieza),
                # se usa el precio de ejecución como referencia para el cálculo de ganancia,
                # aunque esto podría no ser 100% preciso si la posición no se gestionó internamente.
                precio_compra = precio_ejecucion
                logging.warning(
                    f"⚠️ Posición de {symbol} no encontrada en el registro al vender. Usando precio de ejecución {precio_ejecucion} para cálculo de ganancia.")

            # Calcula la ganancia/pérdida.
            ganancia_usdt = (precio_ejecucion - precio_compra) * \
                cantidad_vendida_real
            # Sumar al beneficio total acumulado del bot.
            total_beneficio_acumulado += ganancia_usdt

            # Actualizar bot_params con el nuevo beneficio total.
            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = total_beneficio_acumulado
            logging.info(
                f"DEBUG: TOTAL_BENEFICIO_ACUMULADO antes de guardar en config_manager: {bot_params['TOTAL_BENEFICIO_ACUMULADO']:.2f} USDT")
            # Guardar los parámetros actualizados (persistencia).
            config_manager.save_parameters(bot_params)

            # Guarda las posiciones actualizadas (con debounce).
            position_manager.save_open_positions_debounced(posiciones_abiertas)

            # Registrar la transacción.
            transaccion = {
                # Timestamp de la transacción.
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'tipo': 'VENTA',
                'precio': precio_ejecucion,
                'cantidad': cantidad_vendida_real,
                'valor_usdt': precio_ejecucion * cantidad_vendida_real,
                'ganancia_usdt': ganancia_usdt,
                'motivo_venta': motivo_venta,
                # Registrar el estado real de la orden de Binance.
                'estado_orden_binance': order['status']
            }
            # Añade a la lista de transacciones diarias.
            transacciones_diarias.append(transaccion)

            # Guardar la transacción en Firestore.
            db = firestore_utils.get_firestore_db()
            if db:
                try:
                    db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).add(
                        transaccion)
                    logging.info(
                        f"✅ Transacción de VENTA guardada en Firestore para {symbol}.")
                except Exception as e:
                    logging.error(
                        f"❌ Error al guardar transacción de VENTA en Firestore para {symbol}: {e}", exc_info=True)
                    telegram_handler.send_telegram_message(
                        telegram_bot_token, telegram_chat_id, f"❌ Error al guardar transacción de VENTA en Firestore para {telegram_handler._escape_html_entities(symbol)}: {telegram_handler._escape_html_entities(e)}")

            # Envía mensaje de Telegram más específico según el estado de la orden.
            if order['status'] == 'EXPIRED':
                telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                       f"🟠 VENTA de <b>{telegram_handler._escape_html_entities(symbol)}</b> (PARCIAL/EXPIRADA) ejecutada por <b>{telegram_handler._escape_html_entities(motivo_venta)}</b> a <b>{precio_ejecucion:.4f}</b> USDT. Cantidad vendida: {cantidad_vendida_real:.6f}. Ganancia: <b>{ganancia_usdt:.2f}</b> USDT.")
                logging.info(
                    f"✅ VENTA PARCIAL/EXPIRADA exitosa de {cantidad_vendida_real} {symbol} a {precio_ejecucion} por {motivo_venta}. Ganancia: {ganancia_usdt:.2f} USDT")
            else:  # Estado 'FILLED'.
                telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                       f"🔴 VENTA de <b>{telegram_handler._escape_html_entities(symbol)}</b> ejecutada por <b>{telegram_handler._escape_html_entities(motivo_venta)}</b> a <b>{precio_ejecucion:.4f}</b> USDT. Cantidad: {cantidad_vendida_real:.6f}. Ganancia: <b>{ganancia_usdt:.2f}</b> USDT.")
                logging.info(
                    f"✅ VENTA exitosa de {cantidad_vendida_real} {symbol} a {precio_ejecucion} por {motivo_venta}. Ganancia: {ganancia_usdt:.2f} USDT")
            return order  # Retorna la respuesta de la orden de Binance.
        else:
            # Si la orden no se llenó, envía un mensaje de fallo a Telegram y registra el error.
            error_msg_content = f"Estado: {telegram_handler._escape_html_entities(order.get('status', 'N/A'))}"
            if 'msg' in order:  # Algunos errores de Binance tienen un campo 'msg'
                error_msg_content += f", Mensaje: {telegram_handler._escape_html_entities(order['msg'])}"
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                                   f"❌ Fallo al ejecutar VENTA de <b>{telegram_handler._escape_html_entities(symbol)}</b>. {error_msg_content}")
            logging.error(
                f"❌ Fallo al ejecutar VENTA de {symbol}. Respuesta: {order}")
            return None  # Retorna None si la venta falló.
    except BinanceAPIException as e:
        # Captura errores específicos de la API de Binance.
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                               f"❌ Error de Binance API al intentar VENTA de <b>{telegram_handler._escape_html_entities(symbol)}</b>: Código: {telegram_handler._escape_html_entities(str(e.code))}, Mensaje: {telegram_handler._escape_html_entities(e.message)}")
        logging.error(
            f"❌ Error en la función vender para {symbol}: {e}", exc_info=True)
        return None  # Retorna None en caso de error.
    except Exception as e:
        # Captura cualquier otro error general durante el intento de venta.
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                               f"❌ Error general al intentar VENTA de <b>{telegram_handler._escape_html_entities(symbol)}</b>: {telegram_handler._escape_html_entities(str(e))}")
        logging.error(
            f"❌ Error en la función vender para {symbol}: {e}", exc_info=True)
        return None  # Retorna None en caso de error.


def vender_por_comando(client, symbol, posiciones_abiertas, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file, total_beneficio_acumulado, bot_params, config_manager):
    """
    Permite vender una posición manualmente a través de un comando de Telegram.
    Realiza verificaciones de saldo real antes de intentar vender.

    Args:
        client: Instancia del cliente de Binance.
        symbol (str): El par de trading a vender (ej. "BTCUSDT").
        posiciones_abiertas (dict): Diccionario de posiciones abiertas del bot.
        transacciones_diarias (list): Lista de transacciones del día (para el informe).
        telegram_bot_token (str): Token del bot de Telegram.
        telegram_chat_id (str): ID del chat de Telegram.
        open_positions_file (str): Ruta al archivo de posiciones abiertas.
        total_beneficio_acumulado (float): El beneficio total acumulado del bot.
        bot_params (dict): Diccionario de parámetros del bot.
        config_manager: Módulo para guardar los parámetros del bot.

    Returns:
        dict or None: La respuesta de la orden de Binance si fue exitosa (total o parcial), None en caso contrario.
    """
    if symbol not in posiciones_abiertas:
        telegram_handler.send_telegram_message(
            telegram_bot_token, telegram_chat_id, f"❌ No hay una posición abierta para <b>{telegram_handler._escape_html_entities(symbol)}</b> en el registro del bot.")
        return None  # Retorna None si no hay posición en el registro.

    base_asset = symbol.replace("USDT", "")  # Extrae el activo base.
    # Obtiene el saldo real del activo.
    saldo_real_activo = binance_utils.obtener_saldo_moneda(client, base_asset)

    if saldo_real_activo <= 0:
        telegram_handler.send_telegram_message(
            telegram_bot_token, telegram_chat_id, f"❌ No hay saldo de <b>{telegram_handler._escape_html_entities(symbol)}</b> en tu cuenta de Binance para vender.")
        # Eliminar la posición del registro del bot si el saldo real es cero.
        if symbol in posiciones_abiertas:
            del posiciones_abiertas[symbol]
            # Guarda los cambios.
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(
                f"Posición de {symbol} eliminada del registro interno debido a saldo real cero.")
        return None  # Retorna None si no hay saldo para vender.

    # Ajustar la cantidad a vender al step_size de Binance.
    cantidad_a_vender_ajustada = binance_utils.ajustar_cantidad(
        saldo_real_activo, binance_utils.get_step_size(client, symbol))

    # Verificar si la cantidad ajustada es suficiente para una orden (minQty y minNotional).
    info = client.get_symbol_info(symbol)
    min_notional = 0.0
    min_qty = 0.0
    for f in info['filters']:
        if f['filterType'] == 'MIN_NOTIONAL':
            min_notional = float(f['minNotional'])
        elif f['filterType'] == 'LOT_SIZE':
            min_qty = float(f['minQty'])

    precio_actual = binance_utils.obtener_precio_actual(client, symbol)
    valor_nocional = cantidad_a_vender_ajustada * precio_actual

    if cantidad_a_vender_ajustada <= 0 or cantidad_a_vender_ajustada < min_qty or valor_nocional < min_notional:
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id,
                                               f"⚠️ La cantidad de <b>{telegram_handler._escape_html_entities(symbol)}</b> disponible ({cantidad_a_vender_ajustada:.8f}) o su valor ({valor_nocional:.2f} USDT) es demasiado pequeña para una orden de venta. Mínimo nocional: {min_notional:.2f} USDT, Mínimo cantidad: {min_qty:.8f}.")
        logging.warning(
            f"⚠️ La cantidad de {symbol} disponible ({cantidad_a_vender_ajustada:.8f}) o su valor ({valor_nocional:.2f} USDT) es demasiado pequeña para una orden de venta.")
        # Eliminar la posición del registro del bot si la cantidad es muy pequeña para vender.
        if symbol in posiciones_abiertas:
            del posiciones_abiertas[symbol]
            # Guarda los cambios.
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(
                f"Posición de {symbol} eliminada del registro interno debido a cantidad/valor nocional insuficiente.")
        return None  # Retorna None si la cantidad es insuficiente.

    telegram_handler.send_telegram_message(
        telegram_bot_token, telegram_chat_id, f"⚙️ Intentando vender <b>{telegram_handler._escape_html_entities(symbol)}</b> por comando...")

    # Reutilizar la función vender principal para ejecutar la venta.
    orden = vender(
        client, symbol, cantidad_a_vender_ajustada, posiciones_abiertas,
        total_beneficio_acumulado, bot_params, transacciones_diarias,
        telegram_bot_token, telegram_chat_id, open_positions_file, config_manager,
        # Motivo específico para ventas manuales.
        motivo_venta="Comando Manual"
    )
    return orden  # Retorna la respuesta de la orden.
