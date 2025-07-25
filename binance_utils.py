import logging  # Importa el módulo logging para registrar eventos y mensajes.
# Importa la excepción específica de Binance API.
from binance.exceptions import BinanceAPIException
# Importa el módulo math para funciones matemáticas como floor y log10.
import math

# Configura el sistema de registro básico para este módulo.
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def obtener_saldo_moneda(client, asset):
    """
    Obtiene el saldo disponible (free) de un activo específico en la cuenta de Binance.

    Args:
        client: Instancia del cliente de Binance.
        asset (str): El símbolo del activo (ej. "USDT", "BTC").

    Returns:
        float: El saldo disponible del activo. Retorna 0.0 si hay un error o el activo no se encuentra.
    """
    try:
        # Obtiene la información de la cuenta.
        account_info = client.get_account()
        # Itera sobre los balances para encontrar el activo deseado.
        for balance in account_info['balances']:
            if balance['asset'] == asset:
                # Retorna el saldo 'free' (disponible para trading).
                return float(balance['free'])
        # Si el activo no se encuentra, retorna 0.0.
        logging.warning(
            f"⚠️ Activo {asset} no encontrado en los balances de la cuenta.")
        return 0.0
    except BinanceAPIException as e:
        # Captura errores específicos de la API de Binance.
        logging.error(
            f"❌ Error de Binance API al obtener saldo de {asset}: {e}", exc_info=True)
        return 0.0
    except Exception as e:
        # Captura cualquier otro error inesperado.
        logging.error(
            f"❌ Error al obtener saldo de {asset}: {e}", exc_info=True)
        return 0.0


def obtener_precio_actual(client, symbol):
    """
    Obtiene el precio de mercado actual de un par de trading.

    Args:
        client: Instancia del cliente de Binance.
        symbol (str): El par de trading (ej. "BTCUSDT").

    Returns:
        float: El precio actual del símbolo. Retorna 0.0 si hay un error.
    """
    try:
        # Obtiene la información del ticker (precio actual).
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])  # Retorna el precio.
    except BinanceAPIException as e:
        # Captura errores específicos de la API de Binance.
        logging.error(
            f"❌ Error de Binance API al obtener precio de {symbol}: {e}", exc_info=True)
        return 0.0
    except Exception as e:
        # Captura cualquier otro error inesperado.
        logging.error(
            f"❌ Error al obtener precio de {symbol}: {e}", exc_info=True)
        return 0.0


def get_step_size(client, symbol):
    """
    Obtiene el 'stepSize' para un símbolo dado, que define la granularidad de la cantidad
    en las órdenes de Binance.

    Args:
        client: Instancia del cliente de Binance.
        symbol (str): El par de trading (ej. "BTCUSDT").

    Returns:
        float: El stepSize para el símbolo. Retorna 0.0 si no se encuentra o hay un error.
    """
    try:
        # Obtiene la información de intercambio para el símbolo.
        info = client.get_symbol_info(symbol)
        if info:
            # Itera sobre los filtros para encontrar el filtro 'LOT_SIZE'.
            for f in info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    return float(f['stepSize'])  # Retorna el stepSize.
        logging.warning(
            f"⚠️ No se encontró el filtro LOT_SIZE para el símbolo {symbol}.")
        return 0.0
    except BinanceAPIException as e:
        # Captura errores específicos de la API de Binance.
        logging.error(
            f"❌ Error de Binance API al obtener stepSize para {symbol}: {e}", exc_info=True)
        return 0.0
    except Exception as e:
        # Captura cualquier otro error inesperado.
        logging.error(
            f"❌ Error al obtener stepSize para {symbol}: {e}", exc_info=True)
        return 0.0


def ajustar_cantidad(cantidad, step_size):
    """
    Ajusta una cantidad dada al 'stepSize' requerido por Binance.
    Por ejemplo, si stepSize es 0.001, una cantidad de 0.00123 se ajustaría a 0.001.
    Si stepSize es 1.0, una cantidad de 1.23 se ajustaría a 1.0.

    Args:
        cantidad (float): La cantidad deseada de criptomoneda.
        step_size (float): El stepSize obtenido de la información del símbolo de Binance.

    Returns:
        float: La cantidad ajustada. Retorna 0.0 si step_size es 0.
    """
    if step_size <= 0:
        logging.warning(
            "⚠️ step_size es cero o negativo. No se puede ajustar la cantidad.")
        return 0.0

    # Calcula el número de decimales del step_size.
    # Ej: step_size = 0.001 -> decimal_places = 3
    # Ej: step_size = 1.0   -> decimal_places = 0
    # Ej: step_size = 0.000001 -> decimal_places = 6
    decimal_places = int(round(-math.log10(step_size))) if step_size < 1 else 0

    # Divide la cantidad por el step_size, redondea al entero más cercano y multiplica por step_size.
    # Esto asegura que la cantidad sea un múltiplo exacto del step_size.
    # Por ejemplo, si cantidad = 0.00123 y step_size = 0.001:
    # 0.00123 / 0.001 = 1.23
    # round(1.23) = 1
    # 1 * 0.001 = 0.001

    # Si cantidad = 0.0018 y step_size = 0.001:
    # 0.0018 / 0.001 = 1.8
    # round(1.8) = 2
    # 2 * 0.001 = 0.002 (Esto podría ser un problema si queremos truncar en lugar de redondear)

    # Para asegurar que siempre truncamos hacia abajo (no compramos más de lo que podemos o queremos)
    # y para manejar la precisión de flotantes, es mejor usar la siguiente lógica:

    # Calcula el número de "pasos" que caben en la cantidad.
    num_steps = math.floor(cantidad / step_size)

    # La cantidad ajustada es el número de pasos multiplicado por el step_size.
    adjusted_cantidad = num_steps * step_size

    # Redondea la cantidad ajustada a la cantidad correcta de decimales para evitar problemas de flotantes.
    # Esto es crucial para que Binance acepte la orden.
    adjusted_cantidad = round(adjusted_cantidad, decimal_places)

    logging.info(
        f"DEBUG: Ajustando cantidad {cantidad} con step_size {step_size} (decimales: {decimal_places}). Cantidad ajustada: {adjusted_cantidad}")

    return adjusted_cantidad


def obtener_precio_eur(client):
    """
    Obtiene la tasa de conversión actual de USDT a EUR (EURUSDT).

    Args:
        client: Instancia del cliente de Binance.

    Returns:
        float: La tasa de conversión EURUSDT. Retorna 0.0 si hay un error.
    """
    try:
        # Obtiene el precio del par EURUSDT.
        eur_usdt_ticker = client.get_symbol_ticker(symbol="EURUSDT")
        return float(eur_usdt_ticker['price'])
    except BinanceAPIException as e:
        # Captura errores específicos de la API de Binance.
        logging.error(
            f"❌ Error de Binance API al obtener precio EURUSDT: {e}", exc_info=True)
        return 0.0
    except Exception as e:
        # Captura cualquier otro error inesperado.
        logging.error(f"❌ Error al obtener precio EURUSDT: {e}", exc_info=True)
        return 0.0


def obtener_saldos_formateados(client, open_positions):
    """
    Obtiene y formatea los saldos de USDT y de los activos en posiciones abiertas.

    Args:
        client: Instancia del cliente de Binance.
        open_positions (dict): Diccionario de posiciones abiertas del bot.

    Returns:
        str: Una cadena formateada con los saldos.
    """
    # Obtener el saldo de USDT.
    saldo_usdt = obtener_saldo_moneda(client, "USDT")

    # Construir el mensaje de saldos.
    saldos_msg = f"💰 Saldos:\n"
    saldos_msg += f" - USDT: {saldo_usdt:.2f}\n"

    # Obtener saldos de los activos en posiciones abiertas.
    for symbol in open_positions.keys():
        base_asset = symbol.replace("USDT", "")
        saldo_base = obtener_saldo_moneda(client, base_asset)
        # Formatear a 6 decimales para mayor precisión.
        saldos_msg += f" - {base_asset}: {saldo_base:.6f}\n"

    return saldos_msg


def get_total_capital_usdt(client, open_positions):
    """
    Calcula el capital total en USDT, sumando el saldo de USDT disponible
    y el valor actual de todas las posiciones abiertas.

    Args:
        client: Instancia del cliente de Binance.
        open_positions (dict): Diccionario de posiciones abiertas del bot.

    Returns:
        float: El capital total estimado en USDT.
    """
    total_capital = obtener_saldo_moneda(
        client, "USDT")  # Inicia con el saldo de USDT.

    # Suma el valor actual de cada posición abierta.
    for symbol, data in open_positions.items():
        try:
            current_price = obtener_precio_actual(client, symbol)
            if current_price > 0:
                total_capital += data['cantidad_base'] * current_price
        except Exception as e:
            logging.warning(
                f"⚠️ No se pudo calcular el valor de la posición para {symbol}: {e}. Se ignorará en el cálculo del capital total.", exc_info=True)
            continue
    return total_capital
