"""
Hey Banco — Reclasificación de Perfiles Atípicos
Usa el Random Forest como fallback para los usuarios que HDBSCAN marcó como ruido (-1).
Corre este script después de haber entrenado el pipeline principal.

Uso:
    python reclasificar_atipicos.py
"""
import json
import joblib
import numpy as np
import pandas as pd
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────
MODEL_DIR  = Path("hey_modelo")
CSV_ORIGEN = Path("hey_segmentos_completo.csv")   # generado por clasificador.py
CSV_SALIDA = Path("hey_segmentos_final.csv")       # resultado con todos clasificados

FEATURES_RF = [
    'edad', 'ingreso_mensual_mxn', 'score_buro',
    'antiguedad_dias', 'num_productos_activos',
    'es_hey_pro', 'nomina_domiciliada', 'recibe_remesas',
    'ocupacion_enc', 'nivel_educativo_enc', 'canal_apertura_enc',
]


# ─────────────────────────────────────────────────────────────────────────────
# CARGA
# ─────────────────────────────────────────────────────────────────────────────
def cargar_todo():
    print("Cargando modelos y CSV...")
    rf       = joblib.load(MODEL_DIR / "random_forest.pkl")
    encoders = joblib.load(MODEL_DIR / "encoders.pkl")
    with open(MODEL_DIR / "catalogo_segmentos.json", encoding="utf-8") as f:
        catalogo = {int(k): v for k, v in json.load(f).items()}

    df = pd.read_csv(CSV_ORIGEN)
    print(f"CSV cargado: {len(df):,} usuarios")
    print(f"\nDistribución actual:")
    print(df['segmento_nombre'].value_counts().to_string())
    return rf, encoders, catalogo, df


# ─────────────────────────────────────────────────────────────────────────────
# RECLASIFICACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def reclasificar_atipicos(df: pd.DataFrame, rf, encoders: dict, catalogo: dict) -> pd.DataFrame:
    """
    Para cada usuario con cluster_hdbscan == -1 (Perfil Atípico),
    usa el Random Forest para asignarle el cluster más probable
    basándose en sus datos demográficos.
    """
    mask_atipicos = df['cluster_hdbscan'] == -1
    n_atipicos    = mask_atipicos.sum()
    print(f"\nReclasificando {n_atipicos:,} perfiles atípicos con Random Forest...")

    df_atipicos = df[mask_atipicos].copy()

    # Codificar categóricas si no están ya codificadas
    for col in ['ocupacion', 'nivel_educativo', 'canal_apertura']:
        col_enc = col + '_enc'
        if col_enc not in df_atipicos.columns:
            le    = encoders[col]
            valor = df_atipicos[col].fillna('Desconocido').astype(str)
            df_atipicos[col_enc] = valor.apply(
                lambda v: int(le.transform([v])[0]) if v in le.classes_ else 0
            )

    X = df_atipicos[FEATURES_RF].fillna(0)

    # Predecir cluster y confianza
    clusters_pred = rf.predict(X)
    probas        = rf.predict_proba(X)
    confianza     = probas.max(axis=1)

    # Asignar resultados al dataframe original
    df.loc[mask_atipicos, 'cluster_rf_fallback'] = clusters_pred.astype(int)
    df.loc[mask_atipicos, 'confianza_rf']        = confianza.round(3)

    # Crear columna cluster_final: HDBSCAN donde pudo, RF donde no
    df['cluster_final'] = df['cluster_hdbscan'].copy()
    df.loc[mask_atipicos, 'cluster_final'] = clusters_pred.astype(int)

    # Asignar nombre del segmento final
    df['segmento_final'] = df['cluster_final'].map(
        {k: v['nombre'] for k, v in catalogo.items()}
    ).fillna('Sin Clasificar')

    # Marcar el método usado para cada usuario
    df['metodo_clasificacion'] = 'HDBSCAN'
    df.loc[mask_atipicos, 'metodo_clasificacion'] = 'RF_fallback'

    return df


# ─────────────────────────────────────────────────────────────────────────────
# REPORTE
# ─────────────────────────────────────────────────────────────────────────────
def imprimir_reporte(df: pd.DataFrame, catalogo: dict) -> None:
    print("\n" + "=" * 55)
    print("DISTRIBUCIÓN FINAL (todos los usuarios clasificados)")
    print("=" * 55)
    dist = df['segmento_final'].value_counts()
    total = len(df)
    for nombre, n in dist.items():
        print(f"  {nombre:<30} {n:>6,}  ({n/total*100:.1f}%)")

    print("\n" + "=" * 55)
    print("DETALLE DE RECLASIFICADOS (antes: Perfil Atípico)")
    print("=" * 55)
    reclasificados = df[df['metodo_clasificacion'] == 'RF_fallback']
    dist_reclas    = reclasificados['segmento_final'].value_counts()
    for nombre, n in dist_reclas.items():
        conf_media = reclasificados[reclasificados['segmento_final'] == nombre]['confianza_rf'].mean()
        print(f"  {nombre:<30} {n:>5,} usuarios  (confianza media: {conf_media:.2f})")

    print("\n" + "=" * 55)
    print("ACCIONES POR SEGMENTO")
    print("=" * 55)
    for cid, info in catalogo.items():
        n_hdbscan = ((df['cluster_hdbscan'] == cid)).sum()
        n_rf      = ((df['cluster_final'] == cid) & (df['metodo_clasificacion'] == 'RF_fallback')).sum()
        print(f"\n  [{cid}] {info['nombre']}  ({n_hdbscan:,} HDBSCAN + {n_rf:,} RF = {n_hdbscan+n_rf:,} total)")
        print(f"       {info['descripcion']}")
        for a in info['acciones']:
            print(f"       • {a}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    # 1. Cargar todo
    rf, encoders, catalogo, df = cargar_todo()

    # 2. Reclasificar atípicos
    df = reclasificar_atipicos(df, rf, encoders, catalogo)

    # 3. Reporte
    imprimir_reporte(df, catalogo)

    # 4. Guardar CSV final
    df.to_csv(CSV_SALIDA, index=False)
    print(f"\nCSV final guardado en: {CSV_SALIDA}")
    print(f"Columnas nuevas añadidas:")
    print(f"  • cluster_final        — cluster definitivo (HDBSCAN o RF)")
    print(f"  • segmento_final       — nombre del segmento definitivo")
    print(f"  • metodo_clasificacion — 'HDBSCAN' o 'RF_fallback'")
    print(f"  • cluster_rf_fallback  — cluster que asignó el RF (solo atípicos)")
    print(f"  • confianza_rf         — probabilidad del RF (solo atípicos)")