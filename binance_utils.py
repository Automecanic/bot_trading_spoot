import logging
from binance.client import Client

# Configura el sistema de registro para este módulo.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def obtener_saldo_moneda(client, asset):
    """
    Obtiene el saldo disponible (free balance) de una moneda específica de tu cuenta de Binance.
    'free' balance es la cantidad que no está bloqueada en órdenes abiertas.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    try:
        balance = client.get_asset_balance(asset=asset)
        return float(balance['free'])
    except Exception as e:
        logging.error(f"❌ Error al obtener saldo de {asset}: {e}")
        return 0.0

def obtener_precio_actual(client, symbol):
    """
    Obtiene el precio de mercado actual de un par de trading (símbolo) de Binance.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    try:
        ticker = client.get_symbol_ticker(symbol=symbol)
        return float(ticker['price'])
    except Exception as e:
        logging.error(f"❌ Error al obtener precio de {symbol}: {e}")
        return 0.0

def obtener_precio_eur(client):
    """
    Obtiene el tipo de cambio actual de USDT a EUR desde Binance (usando el par EURUSDT).
    Útil para mostrar el capital total en euros en los informes.
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    try:
        eur_usdt_price = client.get_avg_price(symbol='EURUSDT')
        return 1 / float(eur_usdt_price['price'])
    except Exception as e:
        logging.warning(f"⚠️ No se pudo obtener el precio de EURUSDT: {e}. Usando 0 para la conversión a EUR.")
        return 0.0

def get_step_size(client, symbol):
    """
    Obtiene el 'stepSize' para un símbolo de Binance.
    El 'stepSize' es el incremento mínimo permitido para la cantidad de una orden (ej. 0.001 BTC).
    Es crucial para ajustar las cantidades de compra/venta y evitar errores de precisión de la API (-1111).
    Requiere el objeto 'client' de Binance para interactuar con la API.
    """
    try:
        info = client.get_symbol_info(symbol)
        for f in info['filters']:
            if f['filterType'] == 'LOT_SIZE':
                return float(f['stepSize'])
        logging.warning(f"⚠️ No se encontró LOT_SIZE filter para {symbol}. Usando stepSize por defecto: 0.000001")
        return 0.000001
    except Exception as e:
        logging.error(f"❌ Error al obtener stepSize para {symbol}: {e}")
        return 0.000001

def ajustar_cantidad(cantidad, step_size):
    """
    Ajusta una cantidad dada para que sea un múltiplo exacto del 'step_size' de Binance
    y con la precisión correcta en decimales. Esto es vital para evitar el error -1111 de Binance.
    """
    if step_size == 0:
        logging.warning("⚠️ step_size es 0, no se puede ajustar la cantidad.")
        return 0.0

    s_step_size = str(step_size)
    if '.' in s_step_size:
        decimal_places = len(s_step_size.split('.')[1].rstrip('0'))
    else:
        decimal_places = 0

    try:
        factor = 10**decimal_places
        ajustada = (round(cantidad * factor / (step_size * factor)) * (step_size * factor)) / factor
        
        formatted_quantity_str = f"{ajustada:.{decimal_places}f}"
        return float(formatted_quantity_str)
    except Exception as e:
        logging.error(f"❌ Error al ajustar cantidad {cantidad} con step {step_size}: {e}")
        return 0.0

def obtener_saldos_formateados(client, posiciones_abiertas):
    """
    Formatea un mensaje con los saldos de USDT disponibles y el capital total estimado (en USDT y EUR).
    El capital total incluye el USDT disponible y el valor actual de todas las posiciones abiertas.
    Requiere el objeto 'client' de Binance y el diccionario 'posiciones_abiertas'.
    """
    try:
        saldo_usdt = obtener_saldo_moneda(client, "USDT")
        capital_total_usdt = saldo_usdt
        
        for symbol, pos in posiciones_abiertas.items():
            precio_actual = obtener_precio_actual(client, symbol)
            capital_total_usdt += pos['cantidad_base'] * precio_actual
        
        eur_usdt_rate = obtener_precio_eur(client)
        capital_total_eur = capital_total_usdt * eur_usdt_rate if eur_usdt_rate else 0

        return (f"💰 Saldo USDT: {saldo_usdt:.2f}\n"
                f"💲 Capital Total (USDT): {capital_total_usdt:.2f}\n"
                f"💶 Capital Total (EUR): {capital_total_eur:.2f}")
    except Exception as e:
        logging.error(f"❌ Error al obtener saldos formateados: {e}")
        return "❌ Error al obtener saldos."

def convert_dust_to_bnb(client):
    """
    Intenta convertir pequeños saldos de criptomonedas ("dust") a BNB.
    Utiliza la API de Binance para realizar la conversión.
    Requiere el objeto 'client' de Binance.
    """
    try:
        dust_assets = []
        account_info = client.get_account()
        for balance in account_info['balances']:
            asset = balance['asset']
            free = float(balance['free'])
            
            # Solo considerar activos que no son USDT o BNB y que tienen un saldo libre > 0
            if asset not in ["USDT", "BNB"] and free > 0:
                try:
                    # Intentar obtener el valor en USDT para determinar si es "dust"
                    symbol_pair = asset + "USDT"
                    price_usdt = obtener_precio_actual(client, symbol_pair)
                    value_usdt = free * price_usdt
                    
                    # Umbral de "dust" en USDT (ej. menos de 0.01 USDT)
                    # Este umbral es una aproximación, Binance tiene sus propios umbrales.
                    if value_usdt > 0 and value_usdt < 0.01: # Asegurarse de que no sea 0 y sea pequeño
                        dust_assets.append(asset)
                        logging.info(f"Identificado {free:.8f} {asset} como posible dust (valor: {value_usdt:.4f} USDT).")
                except Exception as ex:
                    # Si no se puede obtener el precio en USDT (ej. par no existe), se ignora.
                    logging.debug(f"No se pudo obtener el precio de {asset} en USDT para verificar dust: {ex}")
                    pass

        if not dust_assets:
            logging.info("No se encontraron activos elegibles para convertir a BNB (dust).")
            return {"status": "success", "message": "No se encontraron activos elegibles para convertir a BNB (dust)."}

        logging.info(f"Intentando convertir los siguientes activos a BNB: {', '.join(dust_assets)}")
        
        # Corregido: Usar client.transfer_dust() en lugar de client.dust_transfer()
        result = client.transfer_dust(asset=dust_assets)
        
        if result and result['totalServiceCharge'] is not None:
            total_transfered = float(result['totalTransfered'])
            total_service_charge = float(result['totalServiceCharge'])
            
            message = (f"✅ Conversión de dust a BNB exitosa!\n"
                       f"Total convertido a BNB: {total_transfered:.8f}\n"
                       f"Comisión total: {total_service_charge:.8f} BNB\n"
                       f"Activos convertidos: {[item['asset'] for item in result['transferResult'] if item['amount'] > 0]}")
            logging.info(message)
            return {"status": "success", "message": message, "result": result}
        else:
            message = f"⚠️ No se pudo convertir dust a BNB. Respuesta de la API: {result}"
            logging.warning(message)
            return {"status": "failed", "message": message, "result": result}

    except Exception as e:
        logging.error(f"❌ Error al intentar convertir dust a BNB: {e}", exc_info=True)
        return {"status": "error", "message": f"❌ Error al intentar convertir dust a BNB: {e}"}

