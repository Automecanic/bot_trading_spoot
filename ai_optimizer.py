# ai_optimizer.py
# Optimizador de parámetros para estrategias de trading
# Usa datos históricos y aprendizaje automático para encontrar los mejores
# valores de TAKE_PROFIT, TRAILING_STOP y RIESGO por operación.
# Resultados se guardan en JSON y en Firestore.

import pandas as pd
import json
import numpy as np
from sklearn.linear_model import LinearRegression
import optuna  # Para optimización bayesiana eficiente
import firestore_utils  # Módulo personalizado para conectar a Firestore

# -----------------------------------------------------------
# 1. Conectar a Google Firestore (base de datos en la nube)
# -----------------------------------------------------------
# Esto permite guardar los parámetros optimizados para que otros sistemas (como un bot de trading)
# puedan leerlos en tiempo real.
db = firestore_utils.get_firestore_db()

# Intentamos cargar parámetros previos (por si queremos usarlos como punto de partida)
ai_params = {}
if db:
    try:
        doc = db.collection("ai_optimizer").document("current_params").get()
        if doc.exists:
            ai_params = doc.to_dict()
            print("✅ Parámetros previos cargados desde Firestore.")
        else:
            print("⚠️  No se encontraron parámetros previos en Firestore.")
    except Exception as e:
        print(f"❌ Error al leer desde Firestore: {e}")
        db = None  # Desactivamos escritura si hay error
else:
    print("⚠️  No se pudo conectar a Firestore. Solo se guardará en JSON.")

# -----------------------------------------------------------
# 2. Cargar datos históricos de transacciones
# -----------------------------------------------------------
# El archivo CSV debe contener operaciones pasadas con:
# - Parámetros usados (TP, TS, Riesgo)
# - Resultado (ganancia en USDT)
try:
    df = pd.read_csv('transacciones_historico.csv')
    print(f"✅ Cargadas {len(df)} transacciones históricas.")
except FileNotFoundError:
    raise FileNotFoundError(
        "❌ No se encontró el archivo 'transacciones_historico.csv'")

# Verificar columnas necesarias
required_columns = [
    'TAKE_PROFIT_PORCENTAJE',
    'TRAILING_STOP_PORCENTAJE',
    'RIESGO_POR_OPERACION_PORCENTAJE',
    'ganancia_usdt'
]
for col in required_columns:
    if col not in df.columns:
        raise ValueError(f"❌ Falta la columna requerida en el CSV: '{col}'")

# -----------------------------------------------------------
# 3. Preparar datos: limpieza y conversión
# -----------------------------------------------------------
# Convertimos ganancia a numérico, manejando errores
df['ganancia'] = pd.to_numeric(df['ganancia_usdt'], errors='coerce').fillna(0)

# Eliminamos filas con datos inválidos en parámetros clave
df.dropna(subset=[
    'TAKE_PROFIT_PORCENTAJE',
    'TRAILING_STOP_PORCENTAJE',
    'RIESGO_POR_OPERACION_PORCENTAJE'
], inplace=True)

# Aseguramos que los parámetros estén en rango razonable
df = df[
    (df['TAKE_PROFIT_PORCENTAJE'].between(0.01, 0.20)) &
    (df['TRAILING_STOP_PORCENTAJE'].between(0.005, 0.10)) &
    (df['RIESGO_POR_OPERACION_PORCENTAJE'].between(0.001, 0.05))
]
print(f"✅ Datos limpios: {len(df)} transacciones después de filtrado.")

# -----------------------------------------------------------
# 4. Entrenar modelo predictivo: ¿qué combinación da más ganancia?
# -----------------------------------------------------------
# Usamos regresión lineal para modelar:
# ganancia = f(TP, TS, Riesgo)
X = df[['TAKE_PROFIT_PORCENTAJE', 'TRAILING_STOP_PORCENTAJE',
        'RIESGO_POR_OPERACION_PORCENTAJE']]
y = df['ganancia']

# Entrenamos el modelo
model = LinearRegression()
model.fit(X, y)

print(f"📊 Modelo entrenado. Fórmula aproximada:")
print(
    f"   Ganancia = {model.coef_[0]:.2f}*TP + {model.coef_[1]:.2f}*TS + {model.coef_[2]:.2f}*Riesgo + {model.intercept_:.2f}")

# -----------------------------------------------------------
# 5. Definir función objetivo para Optuna
# -----------------------------------------------------------
# Optuna buscará los valores de TP, TS y Riesgo que maximicen la ganancia predicha


def objetivo(trial):
    # Sugerimos valores dentro de rangos seguros
    tp = trial.suggest_float('TAKE_PROFIT_PORCENTAJE',
                             0.02, 0.12)      # 2% a 12%
    ts = trial.suggest_float('TRAILING_STOP_PORCENTAJE',
                             0.01, 0.05)     # 1% a 5%
    riesgo = trial.suggest_float(
        'RIESGO_POR_OPERACION_PORCENTAJE', 0.002, 0.01)  # 0.2% a 1%

    # Predecimos la ganancia esperada con esta combinación
    ganancia_predicha = model.predict([[tp, ts, riesgo]])[0]

    # Podríamos añadir penalizaciones (ej: evitar riesgo muy alto)
    # Ej: penalización por riesgo extremo
    penalizacion = 0
    if riesgo > 0.008:
        penalizacion += (riesgo - 0.008) * 100  # Penaliza riesgos altos
    if tp < 0.03 or tp > 0.10:
        penalizacion += 0.5  # Prefiere TP en rango medio

    return ganancia_predicha - penalizacion  # Maximizamos ganancia ajustada


# -----------------------------------------------------------
# 6. Ejecutar optimización con Optuna
# -----------------------------------------------------------
print("🔍 Iniciando optimización con Optuna...")

# Creamos un estudio para maximizar la ganancia predicha
study = optuna.create_study(direction='maximize')

# Ejecutamos 100 intentos (puedes ajustar)
study.optimize(objetivo, n_trials=100)

# Obtenemos los mejores parámetros encontrados
mejores_params = study.best_params
mejor_ganancia_predicha = study.best_value

print(f"🎯 Óptimo encontrado después de {len(study.trials)} intentos:")
for param, value in mejores_params.items():
    print(f"   {param}: {value:.4f}")
print(f"   Ganancia predicha: {mejor_ganancia_predicha:.2f} USDT")

# -----------------------------------------------------------
# 7. Ajustar y formatear resultados finales
# -----------------------------------------------------------
# Aseguramos que los valores estén dentro de límites operativos
next_params = {
    "TAKE_PROFIT_PORCENTAJE": max(0.02, min(0.12, round(mejores_params["TAKE_PROFIT_PORCENTAJE"], 4))),
    "TRAILING_STOP_PORCENTAJE": max(0.01, min(0.05, round(mejores_params["TRAILING_STOP_PORCENTAJE"], 4))),
    "RIESGO_POR_OPERACION_PORCENTAJE": max(0.002, min(0.01, round(mejores_params["RIESGO_POR_OPERACION_PORCENTAJE"], 4))),
    "ganancia_predicha": round(mejor_ganancia_predicha, 2),
    "fuente_optimizacion": "optuna_bayesiano_con_modelo_ml",
    "n_trials_optuna": len(study.trials)
}

# -----------------------------------------------------------
# 8. Guardar resultados
# -----------------------------------------------------------

# Guardar en archivo JSON local (para respaldo o uso local)
try:
    with open('ai_params.json', 'w') as f:
        json.dump(next_params, f, indent=2)
    print("✅ Parámetros guardados en 'ai_params.json'")
except Exception as e:
    print(f"❌ Error al guardar en JSON: {e}")

# Guardar en Firestore (para acceso remoto, ej: por un bot de trading)
if db:
    try:
        doc_ref = db.collection("ai_optimizer").document("current_params")
        doc_ref.set(next_params)
        print("✅ Parámetros guardados en Firestore.")
    except Exception as e:
        print(f"❌ Error al guardar en Firestore: {e}")

# -----------------------------------------------------------
# 9. Resumen final
# -----------------------------------------------------------
print("\n" + "="*50)
print("✅ OPTIMIZACIÓN COMPLETADA")
print("="*50)
print("Parámetros recomendados para próximas operaciones:")
for k, v in next_params.items():
    if k != "fuente_optimizacion" and k != "n_trials_optuna":
        print(f"  {k}: {v}")
print("="*50)
