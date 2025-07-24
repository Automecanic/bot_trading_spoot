import logging
import time
import json
from binance.enums import *
from datetime import datetime # Importar datetime para los timestamps
import firestore_utils # Importa el módulo para Firestore
import os # Importa el módulo os para os.getenv

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Importa módulos auxiliares que trading_logic necesita.
# Asumimos que estos módulos existen y están correctamente configurados.
import binance_utils
import position_manager
import telegram_handler
import config_manager # Para guardar bot_params actualizado

# Nombre de la colección en Firestore para el historial de transacciones
# Siguiendo las reglas de seguridad: /artifacts/{appId}/public/data/transactions_history
FIRESTORE_TRANSACTIONS_COLLECTION_PATH = f"artifacts/{os.getenv('__app_id', 'default-app-id')}/public/data/transactions_history"


# Modificación: Ahora calcula y devuelve dos EMAs (corta y larga)
def calcular_ema_rsi(client, symbol, ema_periodo_corta, ema_periodo_larga, rsi_periodo):
    """
    Calcula la Media Móvil Exponencial (EMA) corta, EMA larga y el Índice de Fuerza Relativa (RSI)
    para un símbolo dado.
    Requiere el cliente de Binance y los períodos para cada indicador.
    """
    try:
        # Obtener datos históricos (velas) para el cálculo de indicadores.
        # Se obtienen suficientes velas para la EMA más larga y el RSI.
        max_periodo = max(ema_periodo_corta, ema_periodo_larga, rsi_periodo)
        klines = client.get_historical_klines(symbol, KLINE_INTERVAL_1MINUTE, f"{max_periodo + 50} minutes ago UTC") # +50 para asegurar datos
        
        # Extraer los precios de cierre de las velas.
        close_prices = [float(k[4]) for k in klines]

        if len(close_prices) < max_periodo:
            logging.warning(f"⚠️ No hay suficientes datos para calcular indicadores para {symbol}. Se necesitan al menos {max_periodo} velas.")
            return None, None, None

        # Función auxiliar para calcular una EMA
        def calculate_single_ema(prices, period):
            if period <= 0 or len(prices) < period:
                return None
            smoothing_factor = 2 / (period + 1)
            ema = prices[0] # Inicializar EMA con el primer precio de cierre
            for i in range(1, len(prices)):
                ema = (prices[i] * smoothing_factor) + (ema * (1 - smoothing_factor))
            return ema

        # Calcular EMA Corta
        ema_corta_valor = calculate_single_ema(close_prices, ema_periodo_corta)
        
        # Calcular EMA Larga
        ema_larga_valor = calculate_single_ema(close_prices, ema_periodo_larga)

        # Calcular RSI
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
            logging.warning(f"⚠️ No hay suficientes datos para calcular RSI para {symbol}. Se necesitan al menos {rsi_periodo} cambios de precio.")
            return ema_corta_valor, ema_larga_valor, None

        avg_gain = sum(gains[:rsi_periodo]) / rsi_periodo
        avg_loss = sum(losses[:rsi_periodo]) / rsi_periodo

        for i in range(rsi_periodo, len(gains)):
            avg_gain = ((avg_gain * (rsi_periodo - 1)) + gains[i]) / rsi_periodo
            avg_loss = ((avg_loss * (rsi_periodo - 1)) + losses[i]) / rsi_periodo

        rs = avg_gain / avg_loss if avg_loss != 0 else (2 if avg_gain > 0 else 1) # Evitar división por cero
        rsi_valor = 100 - (100 / (1 + rs)) if avg_loss != 0 or avg_gain != 0 else 50 # Si ambos son cero, RSI es 50

        return ema_corta_valor, ema_larga_valor, rsi_valor

    except Exception as e:
        logging.error(f"❌ Error al calcular EMA/RSI para {symbol}: {e}", exc_info=True)
        return None, None, None

def calcular_cantidad_a_comprar(client, saldo_usdt, precio_actual, stop_loss_porcentaje, symbol, riesgo_por_operacion_porcentaje, capital_total):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el saldo USDT disponible,
    el precio actual, el stop loss y el porcentaje de riesgo por operación,
    asegurando que el riesgo se calcule sobre el capital total y la cantidad no exceda el saldo disponible.
    """
    if precio_actual <= 0:
        logging.warning("❌ Precio actual es cero o negativo. No se puede calcular la cantidad a comprar.")
        return 0.0

    # 1. Calcular el monto máximo en USDT que estamos dispuestos a arriesgar en esta operación.
    # Este es el monto que se perdería si el stop loss se activa.
    max_usdt_a_riesgar = capital_total * riesgo_por_operacion_porcentaje
    logging.info(f"DEBUG: Capital Total: {capital_total:.2f} USDT, Riesgo por Operación: {riesgo_por_operacion_porcentaje*100:.2f}%, Máximo USDT a Arriesgar: {max_usdt_a_riesgar:.2f} USDT")

    # 2. Calcular la cantidad de la moneda base que, si cae el % del stop loss,
    # resultaría en la pérdida de 'max_usdt_a_riesgar'.
    # Formula: Cantidad = (Máximo USDT a Arriesgar) / (Precio actual * Stop Loss Porcentaje)
    # Esta es la cantidad "ideal" basada en el riesgo.
    if stop_loss_porcentaje <= 0:
        logging.warning("❌ STOP_LOSS_PORCENTAJE es cero o negativo. No se puede calcular la cantidad a comprar.")
        return 0.0
    
    cantidad_ideal_por_riesgo = max_usdt_a_riesgar / (precio_actual * stop_loss_porcentaje)

    # 3. Determinar el monto en USDT a invertir para comprar esa cantidad ideal.
    # Monto a invertir = Cantidad ideal * Precio actual
    usdt_para_cantidad_ideal = cantidad_ideal_por_riesgo * precio_actual
    logging.info(f"DEBUG: USDT necesario para cantidad ideal por riesgo ({cantidad_ideal_por_riesgo:.8f}): {usdt_para_cantidad_ideal:.2f} USDT")

    # 4. Asegurarse de que el monto a invertir no exceda el saldo USDT disponible.
    # El monto real a invertir será el mínimo entre el saldo disponible y el monto calculado.
    # CAMBIO CRÍTICO: Aplicar un pequeño buffer al saldo USDT disponible
    BUFFER_PORCENTAJE = 0.0015 # 0.15% de buffer para comisiones y precisión
    saldo_usdt_con_buffer = saldo_usdt * (1 - BUFFER_PORCENTAJE)
    
    usdt_a_invertir_real = min(usdt_para_cantidad_ideal, saldo_usdt_con_buffer)
    logging.info(f"DEBUG: Saldo USDT disponible: {saldo_usdt:.2f} USDT, Saldo con buffer ({BUFFER_PORCENTAJE*100:.2f}%): {saldo_usdt_con_buffer:.2f} USDT, USDT a invertir real: {usdt_a_invertir_real:.2f} USDT")

    # 5. Calcular la cantidad final de la criptomoneda a comprar basada en el monto real a invertir.
    if precio_actual <= 0: # Doble chequeo, aunque ya se hizo al inicio
        logging.warning("❌ Precio actual es cero o negativo al recalcular cantidad final. Abortando.")
        return 0.0
    
    cantidad_final_calculada = usdt_a_invertir_real / precio_actual

    # 6. Ajustar la cantidad final al step_size y verificar el min_notional.
    step_size = binance_utils.get_step_size(client, symbol)
    cantidad_ajustada_por_step = binance_utils.ajustar_cantidad(cantidad_final_calculada, step_size)

    # Obtener el filtro MIN_NOTIONAL de Binance para el símbolo
    min_notional = 0.0
    info = client.get_symbol_info(symbol)
    for f in info['filters']:
        if f['filterType'] == 'MIN_NOTIONAL':
            min_notional = float(f['minNotional'])
            break

    # Verificación final de la cantidad y el valor nocional
    if (cantidad_ajustada_por_step * precio_actual) < min_notional:
        logging.warning(f"⚠️ La cantidad ajustada para {symbol} ({cantidad_ajustada_por_step:.6f} {symbol.replace('USDT', '')}) resulta en un valor inferior al mínimo nocional ({min_notional} USDT). Retornando 0.")
        return 0.0
    
    if cantidad_ajustada_por_step <= 0.00000001: # Umbral muy pequeño para evitar cantidades insignificantes
        logging.warning(f"⚠️ La cantidad final calculada para {symbol} ({cantidad_ajustada_por_step:.8f}) es insignificante. Retornando 0.")
        return 0.0

    logging.info(f"✅ Cantidad final a comprar para {symbol}: {cantidad_ajustada_por_step:.8f} (Valor: {cantidad_ajustada_por_step * precio_actual:.2f} USDT)")
    return cantidad_ajustada_por_step

def comprar(client, symbol, cantidad, posiciones_abiertas, stop_loss_porcentaje, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file):
    """
    Ejecuta una orden de compra a precio de mercado en Binance.
    Registra la posición, la transacción y envía una notificación a Telegram.
    """
    try:
        # --- Pre-check antes de colocar la orden ---
        # Volver a obtener el saldo USDT más reciente justo antes de colocar la orden
        latest_saldo_usdt = binance_utils.obtener_saldo_moneda(client, "USDT")
        latest_precio_actual = binance_utils.obtener_precio_actual(client, symbol)

        if latest_precio_actual <= 0:
            logging.error(f"❌ No se pudo obtener el precio actual para {symbol} justo antes de la compra. Abortando.")
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, f"❌ Error: No se pudo obtener precio para <b>{symbol}</b> antes de comprar.")
            return None

        # Recalcular la cantidad máxima posible basada en el saldo más reciente
        # CAMBIO CRÍTICO: Aplicar el mismo buffer aquí para consistencia
        BUFFER_PORCENTAJE = 0.0015 # 0.15% de buffer
        max_cantidad_posible_por_saldo_latest = (latest_saldo_usdt * (1 - BUFFER_PORCENTAJE)) / latest_precio_actual
        
        # Asegurarse de que la cantidad a comprar no exceda el último saldo disponible
        # y también respete el min_notional y step_size de Binance
        step_size = binance_utils.get_step_size(client, symbol)
        info = client.get_symbol_info(symbol)
        min_notional = 0.0
        min_qty = 0.0
        for f in info['filters']:
            if f['filterType'] == 'MIN_NOTIONAL':
                min_notional = float(f['minNotional'])
            elif f['filterType'] == 'LOT_SIZE':
                min_qty = float(f['minQty'])

        # Tomar el mínimo de la cantidad originalmente calculada y la última cantidad posible
        final_cantidad_to_buy = min(cantidad, max_cantidad_posible_por_saldo_latest)
        final_cantidad_to_buy = binance_utils.ajustar_cantidad(final_cantidad_to_buy, step_size)

        # Verificación final contra min_notional y min_qty
        if final_cantidad_to_buy <= 0 or final_cantidad_to_buy < min_qty or (final_cantidad_to_buy * latest_precio_actual) < min_notional:
            logging.warning(f"⚠️ Cantidad final para {symbol} ({final_cantidad_to_buy:.8f}) o valor nocional ({final_cantidad_to_buy * latest_precio_actual:.2f} USDT) es insuficiente para la compra. Saldo USDT: {latest_saldo_usdt:.2f}. Abortando.")
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"⚠️ Compra de <b>{symbol}</b> abortada: Saldo insuficiente o cantidad/valor mínimo no alcanzado. Saldo USDT: {latest_saldo_usdt:.2f}.")
            return None

        logging.info(f"Intentando COMPRA de {symbol} con cantidad: {final_cantidad_to_buy:.8f} (Saldo USDT justo antes: {latest_saldo_usdt:.2f})")

        # Ejecutar orden de compra a mercado
        order = client.order_market_buy(symbol=symbol, quantity=final_cantidad_to_buy)
        
        # Procesar la respuesta de la orden
        if order and order['status'] == 'FILLED':
            precio_ejecucion = float(order['fills'][0]['price'])
            cantidad_comprada_real = float(order['fills'][0]['qty'])
            
            # Registrar la nueva posición
            posiciones_abiertas[symbol] = {
                'precio_compra': precio_ejecucion,
                'cantidad_base': cantidad_comprada_real,
                'max_precio_alcanzado': precio_ejecucion,
                'stop_loss_fijo_nivel_actual': precio_ejecucion * (1 - stop_loss_porcentaje),
                'sl_moved_to_breakeven': False,
                'timestamp_apertura': datetime.now().isoformat()
            }
            position_manager.save_open_positions_debounced(posiciones_abiertas) # Guardar posiciones

            # Registrar la transacción
            transaccion = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'tipo': 'COMPRA',
                'precio': precio_ejecucion,
                'cantidad': cantidad_comprada_real,
                'valor_usdt': precio_ejecucion * cantidad_comprada_real
            }
            transacciones_diarias.append(transaccion) # Todavía se añade para el informe diario
            
            # Guardar la transacción en Firestore
            db = firestore_utils.get_firestore_db()
            if db:
                try:
                    # Firestore generará un ID de documento automático para cada transacción
                    db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).add(transaccion)
                    logging.info(f"✅ Transacción de COMPRA guardada en Firestore para {symbol}.")
                except Exception as e:
                    logging.error(f"❌ Error al guardar transacción de COMPRA en Firestore para {symbol}: {e}", exc_info=True)


            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"🟢 COMPRA de <b>{symbol}</b> ejecutada a <b>{precio_ejecucion:.4f}</b> USDT. Cantidad: {cantidad_comprada_real:.6f}")
            logging.info(f"✅ COMPRA exitosa de {cantidad_comprada_real} {symbol} a {precio_ejecucion}")
            return order
        else:
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"❌ Fallo al ejecutar COMPRA de <b>{symbol}</b>. Estado: {order.get('status', 'N/A')}")
            logging.error(f"❌ Fallo al ejecutar COMPRA de {symbol}. Respuesta: {order}")
            return None
    except Exception as e:
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                               f"❌ Error al intentar COMPRA de <b>{symbol}</b>: {e}")
        logging.error(f"❌ Error en la función comprar para {symbol}: {e}", exc_info=True)
        return None

def vender(client, symbol, cantidad_a_vender, posiciones_abiertas, total_beneficio_acumulado, bot_params, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file, config_manager, motivo_venta=""):
    """
    Ejecuta una orden de venta a precio de mercado en Binance.
    Actualiza el beneficio total, elimina la posición y envía una notificación a Telegram.
    """
    base_asset = symbol.replace("USDT", "")
    
    try:
        # Obtener información del símbolo para verificar la cantidad mínima de la orden
        info = client.get_symbol_info(symbol)
        min_notional = 0.0 # Valor mínimo de la orden en USDT
        min_qty = 0.0 # Cantidad mínima de la moneda base
        
        for f in info['filters']:
            if f['filterType'] == 'MIN_NOTIONAL':
                min_notional = float(f['minNotional'])
            elif f['filterType'] == 'LOT_SIZE':
                min_qty = float(f['minQty'])
        
        # Obtener el saldo real actual para este activo
        saldo_real_activo = binance_utils.obtener_saldo_moneda(client, base_asset)
        
        # Ajustar la cantidad a vender al step_size
        cantidad_a_vender_ajustada = binance_utils.ajustar_cantidad(saldo_real_activo, binance_utils.get_step_size(client, symbol))

        # Verificar si la cantidad ajustada es suficiente para una orden
        if cantidad_a_vender_ajustada <= 0 or cantidad_a_vender_ajustada < min_qty:
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"⚠️ No hay <b>{symbol}</b> disponible para vender o la cantidad ({cantidad_a_vender_ajustada:.8f}) es demasiado pequeña (mínimo: {min_qty:.8f}).")
            logging.warning(f"⚠️ No hay {symbol} disponible para vender o la cantidad ({cantidad_a_vender_ajustada:.8f}) es demasiado pequeña (mínimo: {min_qty:.8f}).")
            
            # Si la posición está en el registro del bot pero no hay saldo real, eliminarla
            if symbol in posiciones_abiertas:
                del posiciones_abiertas[symbol]
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(f"Posición de {symbol} eliminada del registro interno debido a saldo insuficiente.")
            return None
        
        # Verificar si el valor nocional es suficiente
        precio_actual = binance_utils.obtener_precio_actual(client, symbol)
        valor_nocional = cantidad_a_vender_ajustada * precio_actual

        if valor_nocional < min_notional:
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"⚠️ El valor de venta de <b>{symbol}</b> ({valor_nocional:.2f} USDT) es inferior al mínimo nocional requerido ({min_notional:.2f} USDT). No se puede vender.")
            logging.warning(f"⚠️ El valor de venta de {symbol} ({valor_nocional:.2f} USDT) es inferior al mínimo nocional requerido ({min_notional:.2f} USDT).")
            
            # Si la posición está en el registro del bot pero su valor es muy bajo, eliminarla
            if symbol in posiciones_abiertas:
                del posiciones_abiertas[symbol]
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(f"Posición de {symbol} eliminada del registro interno debido a valor nocional insuficiente.")
            return None
            
        # Ejecutar orden de venta a mercado
        order = client.order_market_sell(symbol=symbol, quantity=cantidad_a_vender_ajustada)
        
        # Procesar la respuesta de la orden
        if order and order['status'] == 'FILLED':
            precio_ejecucion = float(order['fills'][0]['price'])
            cantidad_vendida_real = float(order['fills'][0]['qty'])
            
            # Calcular beneficio/pérdida
            posicion = posiciones_abiertas.pop(symbol) # Eliminar la posición del diccionario
            precio_compra = posicion['precio_compra']
            
            ganancia_usdt = (precio_ejecucion - precio_compra) * cantidad_vendida_real
            total_beneficio_acumulado += ganancia_usdt # Sumar al beneficio total

            # Actualizar bot_params con el nuevo beneficio total
            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = total_beneficio_acumulado
            logging.info(f"DEBUG: TOTAL_BENEFICIO_ACUMULADO antes de guardar en config_manager: {bot_params['TOTAL_BENEFICIO_ACUMULADO']:.2f} USDT") # NUEVO LOG
            config_manager.save_parameters(bot_params) # Guardar los parámetros actualizados

            position_manager.save_open_positions_debounced(posiciones_abiertas) # Guardar posiciones actualizadas

            # Registrar la transacción
            transaccion = {
                'timestamp': datetime.now().isoformat(),
                'symbol': symbol,
                'tipo': 'VENTA',
                'precio': precio_ejecucion,
                'cantidad': cantidad_vendida_real,
                'valor_usdt': precio_ejecucion * cantidad_vendida_real,
                'ganancia_usdt': ganancia_usdt,
                'motivo_venta': motivo_venta
            }
            transacciones_diarias.append(transaccion) # Todavía se añade para el informe diario

            # Guardar la transacción en Firestore
            db = firestore_utils.get_firestore_db()
            if db:
                try:
                    # Firestore generará un ID de documento automático para cada transacción
                    db.collection(FIRESTORE_TRANSACTIONS_COLLECTION_PATH).add(transaccion)
                    logging.info(f"✅ Transacción de VENTA guardada en Firestore para {symbol}.")
                except Exception as e:
                    logging.error(f"❌ Error al guardar transacción de VENTA en Firestore para {symbol}: {e}", exc_info=True)


            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"🔴 VENTA de <b>{symbol}</b> ejecutada por <b>{motivo_venta}</b> a <b>{precio_ejecucion:.4f}</b> USDT. Ganancia: <b>{ganancia_usdt:.2f}</b> USDT.")
            logging.info(f"✅ VENTA exitosa de {cantidad_vendida_real} {symbol} a {precio_ejecucion} por {motivo_venta}. Ganancia: {ganancia_usdt:.2f} USDT")
            return order
        else:
            telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                                   f"❌ Fallo al ejecutar VENTA de <b>{symbol}</b>. Estado: {order.get('status', 'N/A')}")
            logging.error(f"❌ Fallo al ejecutar VENTA de {symbol}. Respuesta: {order}")
            return None
    except Exception as e:
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, 
                                               f"❌ Error al intentar VENTA de <b>{symbol}</b>: {e}")
        logging.error(f"❌ Error en la función vender para {symbol}: {e}", exc_info=True)
        return None

def vender_por_comando(client, symbol, posiciones_abiertas, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file, total_beneficio_acumulado, bot_params, config_manager):
    """
    Permite vender una posición manualmente a través de un comando de Telegram.
    """
    if symbol not in posiciones_abiertas:
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, f"❌ No hay una posición abierta para <b>{symbol}</b> en el registro del bot.")
        return

    base_asset = symbol.replace("USDT", "")
    saldo_real_activo = binance_utils.obtener_saldo_moneda(client, base_asset)
    
    if saldo_real_activo <= 0:
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, f"❌ No hay saldo de <b>{symbol}</b> en tu cuenta de Binance para vender.")
        # Eliminar la posición del registro del bot si el saldo real es cero
        if symbol in posiciones_abiertas:
            del posiciones_abiertas[symbol]
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(f"Posición de {symbol} eliminada del registro interno debido a saldo real cero.")
        return

    # Ajustar la cantidad a vender al step_size
    cantidad_a_vender_ajustada = binance_utils.ajustar_cantidad(saldo_real_activo, binance_utils.get_step_size(client, symbol))

    # Verificar si la cantidad ajustada es suficiente para una orden
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
                                               f"⚠️ La cantidad de <b>{symbol}</b> disponible ({cantidad_a_vender_ajustada:.8f}) o su valor ({valor_nocional:.2f} USDT) es demasiado pequeña para una orden de venta. Mínimo nocional: {min_notional:.2f} USDT, Mínimo cantidad: {min_qty:.8f}.")
        logging.warning(f"⚠️ La cantidad de {symbol} disponible ({cantidad_a_vender_ajustada:.8f}) o su valor ({valor_nocional:.2f} USDT) es demasiado pequeña para una orden de venta.")
        # Eliminar la posición del registro del bot si la cantidad es muy pequeña para vender
        if symbol in posiciones_abiertas:
            del posiciones_abiertas[symbol]
            position_manager.save_open_positions_debounced(posiciones_abiertas)
            logging.info(f"Posición de {symbol} eliminada del registro interno debido a cantidad/valor nocional insuficiente.")
        return

    telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, f"⚙️ Intentando vender <b>{symbol}</b> por comando...")
    
    # Reutilizar la función vender principal
    orden = vender(
        client, symbol, cantidad_a_vender_ajustada, posiciones_abiertas,
        total_beneficio_acumulado, bot_params, transacciones_diarias,
        telegram_bot_token, telegram_chat_id, open_positions_file, config_manager,
        motivo_venta="Comando Manual"
    )
    return orden