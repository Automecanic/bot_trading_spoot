# -*- coding: utf-8 -*-
"""
range_trading.py
Módulo para detectar mercados laterales usando ADX y Bandas de Bollinger.
Evita operaciones en rango lateral para reducir pérdidas.
"""

import numpy as np
import logging
from binance.client import Client

# Configuración de logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def detectar_rango_lateral(client, symbol, periodo=20, adx_umbral=25, band_width_max=0.05):
    """
    Detecta si el mercado está en rango lateral usando:
    - ADX < adx_umbral (falta de tendencia)
    - Ancho de Bollinger Bands < band_width_max (baja volatilidad)

    Args:
        client: Cliente de Binance.
        symbol: Par de trading (ej. 'BTCUSDT').
        periodo: Período para cálculo de indicadores.
        adx_umbral: Valor máximo de ADX para considerar rango.
        band_width_max: Ancho máximo de bandas (relativo al precio).

    Returns:
        tuple: (en_rango, soporte, resistencia)
    """
    try:
        # Obtener datos históricos (1H para mayor precisión)
        klines = client.get_klines(
            symbol=symbol,
            interval=Client.KLINE_INTERVAL_1HOUR,
            limit=periodo + 14  # Datos extra para ADX
        )

        if len(klines) < periodo + 14:
            logging.warning(f"Datos insuficientes para {symbol}")
            return False, 0, 0

        # Extraer precios
        highs = np.array([float(k[2]) for k in klines])
        lows = np.array([float(k[3]) for k in klines])
        closes = np.array([float(k[4]) for k in klines])

        # --- Bollinger Bands ---
        sma = np.mean(closes[-periodo:])
        std = np.std(closes[-periodo:])
        upper_band = sma + 2 * std
        lower_band = sma - 2 * std
        band_width = (upper_band - lower_band) / sma  # Normalizado

        # --- ADX Simplificado (aproximado) ---
        # Calculamos True Range (TR)
        tr = np.maximum(
            highs[1:] - lows[1:],
            np.maximum(
                np.abs(highs[1:] - closes[:-1]),
                np.abs(lows[1:] - closes[:-1])
            )
        )
        atr = np.mean(tr[-periodo:])

        # Direcciones +DM y -DM
        up_move = highs[1:] - np.roll(highs, 1)[1:]
        down_move = np.roll(lows, 1)[1:] - lows[1:]

        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) &
                            (down_move > 0), down_move, 0)

        # Suavizado con Wilder's MA (14 períodos)
        plus_di = 100 * (np.sum(plus_dm[-14:]) / np.sum(tr[-14:]))
        minus_di = 100 * (np.sum(minus_dm[-14:]) / np.sum(tr[-14:]))

        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
        adx = np.mean([dx] * periodo)  # ADX promedio simplificado

        # --- Criterio de Rango Lateral ---
        en_rango = adx < adx_umbral and band_width < band_width_max

        logging.info(
            f"{symbol} | ADX: {adx:.2f} | Band Width: {band_width:.4f} | Rango: {en_rango}")

        return en_rango, lower_band, upper_band

    except Exception as e:
        logging.error(f"Error detectando rango para {symbol}: {e}")
        return False, 0, 0


def estrategia_rango(client, symbol, soporte, resistencia, rsi, rsi_sobreventa=30, rsi_sobrecompra=70):
    """
    Estrategia de trading en rangos:
    - Compra cerca del soporte con RSI < rsi_sobreventa
    - Venta cerca de la resistencia con RSI > rsi_sobrecompra

    Args:
        client: Cliente Binance.
        symbol: Par de trading.
        soporte: Nivel de soporte estimado.
        resistencia: Nivel de resistencia estimado.
        rsi: Valor actual del RSI.

    Returns:
        str: 'COMPRA', 'VENTA', o None
    """
    try:
        precio_actual = float(client.get_symbol_ticker(symbol=symbol)['price'])
        rango = resistencia - soporte
        umbral_proximidad = 0.05 * rango  # 5% del rango

        # Señal de compra
        if precio_actual <= soporte + umbral_proximidad and rsi <= rsi_sobreventa:
            return 'COMPRA'

        # Señal de venta
        elif precio_actual >= resistencia - umbral_proximidad and rsi >= rsi_sobrecompra:
            return 'VENTA'

        return None

    except Exception as e:
        logging.error(f"Error en estrategia de rango para {symbol}: {e}")
        return None
