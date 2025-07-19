import logging
import time
import json
from binance.enums import *
from datetime import datetime # Importar datetime para los timestamps
import firestore_utils # NUEVO: Importa el módulo para Firestore
import os # NUEVO: Importa el módulo os para os.getenv

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


def calcular_ema_rsi(client, symbol, ema_periodo, rsi_periodo):
    """
    Calcula la Media Móvil Exponencial (EMA) y el Índice de Fuerza Relativa (RSI)
    para un símbolo dado.
    Requiere el cliente de Binance y los períodos para cada indicador.
    """
    try:
        # Obtener datos históricos (velas) para el cálculo de indicadores.
        # Se obtienen 100 velas para asegurar suficientes datos para EMA y RSI.
        klines = client.get_historical_klines(symbol, KLINE_INTERVAL_1MINUTE, "100 minutes ago UTC")
        
        # Extraer los precios de cierre de las velas.
        close_prices = [float(k[4]) for k in klines]

        if len(close_prices) < max(ema_periodo, rsi_periodo):
            logging.warning(f"⚠️ No hay suficientes datos para calcular EMA/RSI para {symbol}. Se necesitan al menos {max(ema_periodo, rsi_periodo)} velas.")
            return None, None

        # Calcular EMA
        # La EMA se calcula aplicando una fórmula recursiva.
        ema_values = []
        if ema_periodo > 0:
            smoothing_factor = 2 / (ema_periodo + 1)
            ema = close_prices[0] # Inicializar EMA con el primer precio de cierre
            for i in range(1, len(close_prices)):
                ema = (close_prices[i] * smoothing_factor) + (ema * (1 - smoothing_factor))
                ema_values.append(ema)
            ema_valor = ema_values[-1] if ema_values else None
        else:
            ema_valor = None
        
        # Calcular RSI
        # El RSI se calcula a partir de las ganancias y pérdidas promedio.
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
            return ema_valor, None

        avg_gain = sum(gains[:rsi_periodo]) / rsi_periodo
        avg_loss = sum(losses[:rsi_periodo]) / rsi_periodo

        for i in range(rsi_periodo, len(gains)):
            avg_gain = ((avg_gain * (rsi_periodo - 1)) + gains[i]) / rsi_periodo
            avg_loss = ((avg_loss * (rsi_periodo - 1)) + losses[i]) / rsi_periodo

        rs = avg_gain / avg_loss if avg_loss != 0 else (2 if avg_gain > 0 else 1) # Evitar división por cero
        rsi_valor = 100 - (100 / (1 + rs)) if avg_loss != 0 or avg_gain != 0 else 50 # Si ambos son cero, RSI es 50

        return ema_valor, rsi_valor

    except Exception as e:
        logging.error(f"❌ Error al calcular EMA/RSI para {symbol}: {e}", exc_info=True)
        return None, None

def calcular_cantidad_a_comprar(client, saldo_usdt, precio_actual, stop_loss_porcentaje, symbol, riesgo_por_operacion_porcentaje):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el saldo USDT disponible,
    el precio actual, el stop loss y el porcentaje de riesgo por operación.
    """
    if precio_actual <= 0:
        logging.warning("❌ Precio actual es cero o negativo. No se puede calcular la cantidad a comprar.")
        return 0.0

    # Calcular el capital a arriesgar en USDT
    capital_a_riesgar_usdt = saldo_usdt * riesgo_por_operacion_porcentaje

    # Calcular la pérdida máxima por unidad (si se alcanza el stop loss)
    perdida_por_unidad = precio_actual * stop_loss_porcentaje

    if perdida_por_unidad <= 0:
        logging.warning("❌ Pérdida por unidad es cero o negativa. Revisa el stop_loss_porcentaje.")
        return 0.0

    # Calcular la cantidad teórica basada en el riesgo
    cantidad_teorica = capital_a_riesgar_usdt / perdida_por_unidad
    
    # Obtener el stepSize para el símbolo para ajustar la cantidad
    step_size = binance_utils.get_step_size(client, symbol)
    cantidad_ajustada = binance_utils.ajustar_cantidad(cantidad_teorica, step_size)

    # Asegurarse de que la cantidad ajustada no exceda el saldo disponible
    max_cantidad_posible = saldo_usdt / precio_actual
    cantidad_final = min(cantidad_ajustada, max_cantidad_posible)
    
    # Asegurar que la cantidad final sea un múltiplo del step_size
    cantidad_final = binance_utils.ajustar_cantidad(cantidad_final, step_size)

    # Binance tiene un valor mínimo para las órdenes, por ejemplo, 10 USDT
    # Aunque la API no siempre lo expone directamente como un filtro fácil de obtener,
    # podemos usar un umbral general o intentar obtener el MIN_NOTIONAL filter.
    # Para simplificar, asumiremos un valor mínimo en USDT.
    min_notional = 10.0 # Valor mínimo de la orden en USDT (ej. 10 USDT)
    
    if (cantidad_final * precio_actual) < min_notional:
        logging.warning(f"⚠️ La cantidad calculada para {symbol} ({cantidad_final:.6f} {symbol.replace('USDT', '')}) resulta en un valor inferior al mínimo nocional ({min_notional} USDT).")
        return 0.0

    return cantidad_final

def comprar(client, symbol, cantidad, posiciones_abiertas, stop_loss_porcentaje, transacciones_diarias, telegram_bot_token, telegram_chat_id, open_positions_file):
    """
    Ejecuta una orden de compra a precio de mercado en Binance.
    Registra la posición, la transacción y envía una notificación a Telegram.
    """
    try:
        # Ejecutar orden de compra a mercado
        order = client.order_market_buy(symbol=symbol, quantity=cantidad)
        
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
            
            # NUEVO: Guardar la transacción en Firestore
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
                                                   f"⚠️ No hay <b>{base_asset}</b> disponible para vender o la cantidad ({cantidad_a_vender_ajustada:.8f}) es demasiado pequeña (mínimo: {min_qty:.8f}).")
            logging.warning(f"⚠️ No hay {base_asset} disponible para vender o la cantidad ({cantidad_a_vender_ajustada:.8f}) es demasiado pequeña (mínimo: {min_qty:.8f}).")
            
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

            # NUEVO: Guardar la transacción en Firestore
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
        telegram_handler.send_telegram_message(telegram_bot_token, telegram_chat_id, f"❌ No hay saldo de <b>{base_asset}</b> en tu cuenta de Binance para vender.")
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
                                               f"⚠️ La cantidad de <b>{base_asset}</b> disponible ({cantidad_a_vender_ajustada:.8f}) o su valor ({valor_nocional:.2f} USDT) es demasiado pequeña para una orden de venta. Mínimo nocional: {min_notional:.2f} USDT, Mínimo cantidad: {min_qty:.8f}.")
        logging.warning(f"⚠️ La cantidad de {base_asset} disponible ({cantidad_a_vender_ajustada:.8f}) o su valor ({valor_nocional:.2f} USDT) es demasiado pequeña para una orden de venta.")
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
