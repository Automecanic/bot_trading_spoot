import logging
from binance.client import Client
from binance.enums import *
from datetime import datetime
import binance_utils
import telegram_handler
import config_manager
import position_manager

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def calcular_ema(precios_cierre, periodo):
    """
    Calcula la Media Móvil Exponencial (EMA) para una lista de precios de cierre.
    periodo: Número de períodos para el cálculo de la EMA (ej. 10 para EMA de 10 períodos).
    """
    if len(precios_cierre) < periodo:
        return None
    
    ema = sum(precios_cierre[:periodo]) / periodo
    multiplier = 2 / (periodo + 1)
    
    for i in range(periodo, len(precios_cierre)):
        ema = ((precios_cierre[i] - ema) * multiplier) + ema
    return ema

def calcular_rsi(precios_cierre, periodo):
    """
    Calcula el Índice de Fuerza Relativa (RSI) para una lista de precios de cierre.
    El RSI es un oscilador de momentum que mide la velocidad y el cambio de los movimientos de los precios.
    periodo: Número de períodos para el cálculo del RSI (ej. 14 para RSI de 14 períodos).
    """
    if len(precios_cierre) < periodo + 1:
        return None

    precios_diff = [precios_cierre[i] - precios_cierre[i-1] for i in range(1, len(precios_cierre))]
    
    ganancias = [d if d > 0 else 0 for d in precios_diff]
    perdidas = [-d if d < 0 else 0 for d in precios_diff]

    avg_ganancia = sum(ganancias[:periodo]) / periodo
    avg_perdida = sum(perdidas[:periodo]) / periodo

    if avg_perdida == 0:
        return 100
    
    rs = avg_ganancia / avg_perdida
    rsi = 100 - (100 / (1 + rs))

    for i in range(periodo, len(ganancias)):
        avg_ganancia = ((avg_ganancia * (periodo - 1)) + ganancias[i]) / periodo
        avg_perdida = ((avg_perdida * (periodo - 1)) + perdidas[i]) / periodo
        
        if avg_perdida == 0:
            rsi = 100
        else:
            rs = avg_ganancia / avg_perdida
            rsi = 100 - (100 / (1 + rs))
    return rsi

def calcular_ema_rsi(client, symbol, ema_periodo, rsi_periodo):
    """
    Obtiene los datos de las velas (klines) de Binance para un símbolo dado
    y luego calcula la EMA y el RSI utilizando esos datos.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    try:
        limit = max(ema_periodo, rsi_periodo) + 10
        klines = client.get_klines(symbol=symbol, interval=Client.KLINE_INTERVAL_1MINUTE, limit=limit)
        
        precios_cierre = [float(kline[4]) for kline in klines]
        
        ema = calcular_ema(precios_cierre, ema_periodo)
        rsi = calcular_rsi(precios_cierre, rsi_periodo)
        
        return ema, rsi
    except Exception as e:
        logging.error(f"❌ Error al obtener klines o calcular indicadores para {symbol}: {e}")
        return None, None

def calcular_cantidad_a_comprar(client, saldo_usdt, precio_actual, stop_loss_porcentaje, symbol, riesgo_por_operacion_porcentaje):
    """
    Calcula la cantidad de criptomoneda a comprar basándose en el riesgo por operación
    definido y el porcentaje de stop loss. También considera el mínimo nocional de Binance
    y el saldo USDT disponible.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    if precio_actual <= 0:
        logging.warning("El precio actual es cero o negativo, no se puede calcular la cantidad a comprar.")
        return 0.0

    capital_total = saldo_usdt
    riesgo_max_por_operacion_usdt = capital_total * riesgo_por_operacion_porcentaje
    
    diferencia_precio_sl = precio_actual * stop_loss_porcentaje
    
    if diferencia_precio_sl <= 0:
        logging.warning("La diferencia de precio con el SL es cero o negativa, no se puede calcular la cantidad a comprar.")
        return 0.0

    cantidad_a_comprar = riesgo_max_por_operacion_usdt / diferencia_precio_sl

    step = binance_utils.get_step_size(client, symbol)
    min_notional = 10.0

    cantidad_ajustada = binance_utils.ajustar_cantidad(cantidad_a_comprar, step)
    
    if (cantidad_ajustada * precio_actual) < min_notional:
        logging.warning(f"La cantidad calculada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) es demasiado pequeña para el mínimo nocional de {min_notional} USDT.")
        min_cantidad_ajustada = binance_utils.ajustar_cantidad(min_notional / precio_actual, step)
        if (min_cantidad_ajustada * precio_actual) <= saldo_usdt:
            cantidad_ajustada = min_cantidad_ajustada
            logging.info(f"Ajustando a la cantidad mínima nocional permitida: {cantidad_ajustada:.6f} {symbol.replace('USDT', '')}")
        else:
            logging.warning(f"No hay suficiente saldo USDT para comprar la cantidad mínima nocional de {symbol}.")
            return 0.0

    if (cantidad_ajustada * precio_actual) > saldo_usdt:
        logging.warning(f"La cantidad ajustada ({cantidad_ajustada:.6f} {symbol.replace('USDT', '')}) excede el saldo disponible en USDT. Reduciendo a lo máximo posible.")
        cantidad_max_posible = binance_utils.ajustar_cantidad(saldo_usdt / precio_actual, step)
        if (cantidad_max_posible * precio_actual) >= min_notional:
            cantidad_ajustada = cantidad_max_posible
        else:
            logging.warning(f"El saldo restante no permite comprar ni la cantidad mínima nocional de {symbol}.")
            return 0.0

    return cantidad_ajustada

def comprar(client, symbol, cantidad, posiciones_abiertas, stop_loss_porcentaje, transacciones_diarias, telegram_token, telegram_chat_id, open_positions_file):
    """
    Ejecuta una orden de compra de mercado en Binance para un símbolo y cantidad dados.
    Registra la operación en los logs y en la lista de transacciones diarias.
    Además, guarda la nueva posición en el archivo de persistencia.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de compra de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        order = client.order_market_buy(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE COMPRA EXITOSA para {symbol}: {order}")
        
        if order and 'fills' in order and len(order['fills']) > 0:
            precio_ejecucion = float(order['fills'][0]['price'])
            qty_ejecutada = float(order['fills'][0]['qty'])
            
            posiciones_abiertas[symbol] = {
                'precio_compra': precio_ejecucion,
                'cantidad_base': qty_ejecutada,
                'max_precio_alcanzado': precio_ejecucion,
                'sl_moved_to_breakeven': False,
                'stop_loss_fijo_nivel_actual': precio_ejecucion * (1 - stop_loss_porcentaje)
            }
            try:
                position_manager.save_open_positions_debounced(posiciones_abiertas)
                logging.info(f"✅ Posiciones abiertas guardadas en {open_positions_file} (después de compra).")
            except IOError as e:
                logging.error(f"❌ Error al escribir en el archivo {open_positions_file} después de compra: {e}")
            
            transacciones_diarias.append({
                'FechaHora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'Símbolo': symbol,
                'Tipo': 'COMPRA',
                'Precio': precio_ejecucion,
                'Cantidad': qty_ejecutada,
                'GananciaPerdidaUSDT': 0.0,
                'Motivo': 'Condiciones de entrada'
            })
        return order
    except Exception as e:
        logging.error(f"❌ FALLO DE ORDEN DE COMPRA para {symbol} (Cantidad: {cantidad}): {e}")
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error en compra de {symbol}: {e}")
        return None

def vender(client, symbol, cantidad, posiciones_abiertas, total_beneficio_acumulado, bot_params, transacciones_diarias, telegram_token, telegram_chat_id, open_positions_file, config_manager_ref):
    """
    Ejecuta una orden de venta de mercado en Binance para un símbolo y cantidad dados.
    Calcula la ganancia/pérdida de la operación, actualiza el beneficio total acumulado,
    elimina la posición del registro en memoria y guarda el estado en el archivo de persistencia.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    if cantidad <= 0:
        logging.warning(f"⚠️ Intento de venta de {symbol} con cantidad no positiva: {cantidad}")
        return None
    try:
        order = client.order_market_sell(
            symbol=symbol,
            quantity=cantidad
        )
        logging.info(f"✅ ORDEN DE VENTA EXITOSA para {symbol}: {order}")
        
        ganancia_perdida_usdt = 0.0
        precio_venta_ejecutada = float(order['fills'][0]['price']) if order and 'fills' in order and len(order['fills']) > 0 else 0.0

        if symbol in posiciones_abiertas:
            precio_compra = posiciones_abiertas[symbol]['precio_compra']
            ganancia_perdida_usdt = (precio_venta_ejecutada - precio_compra) * cantidad
            
            # Actualiza el beneficio total acumulado y lo guarda a través del config_manager.
            total_beneficio_acumulado += ganancia_perdida_usdt
            bot_params['TOTAL_BENEFICIO_ACUMULADO'] = total_beneficio_acumulado
            config_manager_ref.save_parameters(bot_params)

            posiciones_abiertas.pop(symbol)
            try:
                position_manager.save_open_positions_debounced(posiciones_abiertas)
                logging.info(f"✅ Posiciones abiertas guardadas en {open_positions_file} (después de venta).")
            except IOError as e:
                logging.error(f"❌ Error al escribir en el archivo {open_positions_file} después de venta: {e}")

        transacciones_diarias.append({
            'FechaHora': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'Símbolo': symbol,
            'Tipo': 'VENTA',
            'Precio': precio_venta_ejecutada,
            'Cantidad': float(order['fills'][0]['qty']) if order and 'fills' in order and len(order['fills']) > 0 else 0.0,
            'GananciaPerdidaUSDT': ganancia_perdida_usdt,
            'Motivo': motivo_venta
        })
        return order
    except Exception as e:
        logging.error(f"❌ FALLO DE ORDEN DE VENTA para {symbol} (Cantidad: {cantidad}): {e}")
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Error en venta de {symbol}: {e}")
        return None

def vender_por_comando(client, symbol, posiciones_abiertas, transacciones_diarias, telegram_token, telegram_chat_id, open_positions_file, total_beneficio_acumulado, bot_params, config_manager_ref):
    """
    Intenta vender una posición abierta para un símbolo específico,
    activada por un comando de Telegram (ej. /vender BTCUSDT).
    Verifica si el bot tiene una posición registrada y si hay saldo real en Binance para vender.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    if symbol not in posiciones_abiertas:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ No hay una posición abierta para <b>{symbol}</b> que gestionar por comando.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero no hay posición abierta.")
        return

    base_asset = symbol.replace("USDT", "")
    cantidad_en_posicion = binance_utils.obtener_saldo_moneda(client, base_asset)

    if cantidad_en_posicion <= 0:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ No hay saldo disponible de <b>{base_asset}</b> para vender.")
        logging.warning(f"Intento de venta por comando para {symbol}, pero el saldo es 0.")
        return

    step = binance_utils.get_step_size(client, symbol)
    cantidad_a_vender_ajustada = binance_utils.ajustar_cantidad(cantidad_en_posicion, step)

    if cantidad_a_vender_ajustada <= 0:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ La cantidad de <b>{base_asset}</b> a vender es demasiado pequeña o inválida.")
        logging.warning(f"Cantidad a vender ajustada para {symbol} es <= 0: {cantidad_a_vender_ajustada}")
        return

    telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"⚙️ Intentando vender <b>{cantidad_a_vender_ajustada:.6f} {base_asset}</b> de <b>{symbol}</b> por comando...")
    logging.info(f"Comando de venta manual recibido para {symbol}. Cantidad a vender: {cantidad_a_vender_ajustada}")

    orden = vender(client, symbol, cantidad_a_vender_ajustada, posiciones_abiertas, total_beneficio_acumulado, bot_params, transacciones_diarias, telegram_token, telegram_chat_id, open_positions_file, config_manager_ref)

    if orden:
        logging.info(f"Venta de {symbol} ejecutada con éxito por comando.")
    else:
        telegram_handler.send_telegram_message(telegram_token, telegram_chat_id, f"❌ Fallo al ejecutar la venta de <b>{symbol}</b> por comando. Revisa los logs.")
        logging.error(f"Fallo al ejecutar la venta de {symbol} por comando.")

