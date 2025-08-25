# ai_optimizer.py
import pandas as pd
import json
import numpy as np
from sklearn.linear_model import LinearRegression
import optuna
import firestore_utils
import logging
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_squared_error

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')


def run_optimization():
    """
    Función principal que ejecuta la optimización de parámetros
    y guarda los resultados en ai_params.json y Firestore.
    Ahora incluye validación train/test y métricas más robustas.
    """
    db = firestore_utils.get_firestore_db()

    try:
        df = pd.read_csv('transacciones_historico.csv')
    except FileNotFoundError:
        logging.error("❌ No se encontró 'transacciones_historico.csv'")
        return

    # Validar columnas
    cols = ['TAKE_PROFIT_PORCENTAJE', 'TRAILING_STOP_PORCENTAJE',
            'RIESGO_POR_OPERACION_PORCENTAJE', 'ganancia_usdt']
    for col in cols:
        if col not in df.columns:
            logging.error(f"❌ Falta columna: {col}")
            return

    # Limpiar datos
    df['ganancia'] = pd.to_numeric(
        df['ganancia_usdt'], errors='coerce').fillna(0)
    df = df[df[cols[:-1]].apply(lambda x: x.astype(str).str.strip()
                                ).apply(pd.to_numeric, errors='coerce').notnull().all(axis=1)]
    df = df[
        (df['TAKE_PROFIT_PORCENTAJE'].between(0.01, 0.20)) &
        (df['TRAILING_STOP_PORCENTAJE'].between(0.005, 0.10)) &
        (df['RIESGO_POR_OPERACION_PORCENTAJE'].between(0.001, 0.05))
    ]

    if df.empty:
        logging.warning("⚠️ No hay suficientes datos válidos para optimizar.")
        return

    # Separar datos en train y test
    X = df[cols[:-1]]
    y = df['ganancia']
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42
    )

    model = LinearRegression().fit(X_train, y_train)
    y_pred = model.predict(X_test)
    mse = mean_squared_error(y_test, y_pred)
    logging.info(f"📊 Error cuadrático medio en validación: {mse:.4f}")

    # Optuna
    def objetivo(trial):
        tp = trial.suggest_float('TAKE_PROFIT_PORCENTAJE', 0.02, 0.12)
        ts = trial.suggest_float('TRAILING_STOP_PORCENTAJE', 0.01, 0.05)
        riesgo = trial.suggest_float(
            'RIESGO_POR_OPERACION_PORCENTAJE', 0.002, 0.01)

        ganancia_predicha = model.predict([[tp, ts, riesgo]])[0]

        # Calcular drawdown estimado (simulado como proporción del riesgo)
        drawdown = riesgo * 100

        # Ratio ganancia/riesgo
        ratio_gr = ganancia_predicha / (riesgo * 100) if riesgo > 0 else 0

        # Penalización si drawdown supera cierto umbral
        penalizacion = 0
        if drawdown > 5:
            penalizacion += (drawdown - 5)

        return ganancia_predicha + ratio_gr - penalizacion

    study = optuna.create_study(direction='maximize')
    study.optimize(objetivo, n_trials=50)

    # Resultados
    best = study.best_params
    next_params = {
        "TAKE_PROFIT_PORCENTAJE": round(max(0.02, min(0.12, best["TAKE_PROFIT_PORCENTAJE"])), 4),
        "TRAILING_STOP_PORCENTAJE": round(max(0.01, min(0.05, best["TRAILING_STOP_PORCENTAJE"])), 4),
        "RIESGO_POR_OPERACION_PORCENTAJE": round(max(0.002, min(0.01, best["RIESGO_POR_OPERACION_PORCENTAJE"])), 4),
        "ganancia_predicha": round(study.best_value, 2),
        "fuente_optimizacion": "optuna_bayesiano",
        "n_trials_optuna": len(study.trials),
        "mse_validacion": round(mse, 4)
    }

    # Guardar
    with open('ai_params.json', 'w') as f:
        json.dump(next_params, f, indent=2)

    if db:
        try:
            db.collection("ai_optimizer").document(
                "current_params").set(next_params)
            logging.info("✅ Parámetros IA guardados en Firestore.")
        except Exception as e:
            logging.error(f"❌ Error al guardar en Firestore: {e}")

    logging.info("✅ Optimización IA completada.")
    return True


# Permitir ejecución directa
if __name__ == "__main__":
    run_optimization()
