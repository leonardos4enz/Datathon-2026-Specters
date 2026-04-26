"""
Hey Banco — Motor de Inteligencia & Atención Personalizada
Pipeline 100% autónomo: HDBSCAN + Random Forest + Optuna + Nombrado con MiniMax
Datathon Hey 2026

Cambios v4 respecto a v3:
1. FEATURES_RF ampliado de 11 → 17 features: se agregan dias_desde_ultimo_login,
   satisfaccion_1_10, usa_hey_shop, tiene_seguro, patron_uso_atipico, sexo_enc.
2. codificar_categoricas() ahora también codifica 'sexo'.
3. Penalización Optuna ajustada (0.15, umbral 0.03).
4. Se mantiene class_weight='balanced' forzado y fallback RF para HDBSCAN -1.
"""
import os
import re
import json
import time
import warnings
from pathlib import Path

import anthropic
import hdbscan
import joblib
import matplotlib.pyplot as plt
import numpy as np
import optuna
import pandas as pd
from sklearn.decomposition import PCA
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, f1_score, recall_score
from sklearn.model_selection import StratifiedKFold, train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import silhouette_score

warnings.filterwarnings('ignore')
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────
MINIMAX_API_KEY  = os.environ.get("MINIMAX_API_KEY", "ENV")
MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"
MINIMAX_MODEL    = "MiniMax-M2.7"

BASE_PATH = Path(r"C:\Users\abiel\OneDrive\Documents\DSC2026\Datathon_Hey_2026_dataset_transacciones 1\dataset_transacciones")
CONV_PATH = Path(r"C:\Users\abiel\OneDrive\Documents\DSC2026\Datathon_Hey_2026_dataset_transacciones 1\dataset_transacciones\dataset_50k_anonymized.parquet")
MODEL_DIR = Path("hey_modelo_optuna")
MODEL_DIR.mkdir(exist_ok=True)

OPTUNA_TRIALS        = 50
OPTUNA_CV_FOLDS      = 3
PENALIZACION_RECALL  = 0.15
RECALL_MINIMO        = 0.03

# Features para HDBSCAN (usuarios con historial completo)
FEATURES_HDBSCAN = [
    'ingreso_mensual_mxn', 'gasto_total', 'edad', 'saldo_total_apps',
    'num_productos_total', 'ticket_promedio', 'uso_internacional',
    'tiene_tarjeta_credito', 'tiene_inversion',
    'total_mensajes', 'num_conversaciones',
    'intent_credito', 'intent_inversion', 'intent_cashback',
    'intent_soporte', 'intent_ahorro', 'intent_internacional', 'intent_negocio',
]

# ── CAMBIO v4: Features RF ampliadas de 11 → 17 ─────────────────────────────
FEATURES_RF = [
    # originales
    'edad', 'ingreso_mensual_mxn', 'score_buro',
    'antiguedad_dias', 'num_productos_activos',
    'es_hey_pro', 'nomina_domiciliada', 'recibe_remesas',
    'ocupacion_enc', 'nivel_educativo_enc', 'canal_apertura_enc',
    # ── NUEVAS v4: features que antes se desperdiciaban ──
    'dias_desde_ultimo_login',   # separa cluster 3 (42d) de cluster 4 (6.7d)
    'satisfaccion_1_10',         # separa Premium (8.0) de Endeudado (6.3)
    'usa_hey_shop',              # correlaciona con clusters de alto valor
    'tiene_seguro',              # proxy de inversión (c5=0.46 vs c0=0.22)
    'patron_uso_atipico',        # separa c0 (0.02) de c1 (0.05)
    'sexo_enc',                  # potencial diferenciación adicional
]
# ─────────────────────────────────────────────────────────────────────────────

INTENTS = {
    'intent_credito':       ['crédito', 'credito', 'tarjeta', 'límite', 'limite', 'deuda', 'pago mínimo', 'meses sin intereses'],
    'intent_inversion':     ['inver', 'acciones', 'rendimiento', 'fondos', 'cetes', 'plazo fijo'],
    'intent_cashback':      ['cashback', 'recompensa', 'promo', 'promoción', 'beneficio', 'puntos'],
    'intent_soporte':       ['aclaración', 'problema', 'error', 'no funciona', 'bloqueo', 'robo', 'queja'],
    'intent_ahorro':        ['ahorro', 'depositar', 'guardar', 'apartado', 'meta'],
    'intent_internacional': ['dólar', 'dolar', 'internacional', 'extranjero', 'divisas', 'viaje'],
    'intent_negocio':       ['negocio', 'empresa', 'pfae', 'factura', 'fiscal'],
}


# ─────────────────────────────────────────────────────────────────────────────
# ETAPA 1 — CARGA Y PROCESAMIENTO DE DATOS
# ─────────────────────────────────────────────────────────────────────────────
def cargar_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró: {path}")
    return pd.read_csv(path)


def cargar_transacciones() -> pd.DataFrame:
    print("--- Cargando datasets transaccionales ---")
    clientes      = cargar_csv(BASE_PATH / "hey_clientes.csv")
    productos     = cargar_csv(BASE_PATH / "hey_productos.csv")
    transacciones = cargar_csv(BASE_PATH / "hey_transacciones.csv")

    prod_agg = productos.groupby('user_id').agg(
        num_productos_total   = ('producto_id', 'count'),
        saldo_total_apps      = ('saldo_actual', 'sum'),
        tiene_tarjeta_credito = ('tipo_producto', lambda x: x.str.contains('tarjeta_credito').any()),
        tiene_inversion       = ('tipo_producto', lambda x: (x == 'inversion_hey').any()),
    ).reset_index()

    def safe_mode(x):
        m = x.mode()
        return m.iloc[0] if len(m) > 0 else 'N/A'

    trans_agg = transacciones.groupby('user_id').agg(
        gasto_total         = ('monto',           'sum'),
        transacciones_count = ('transaccion_id',  'count'),
        ticket_promedio     = ('monto',           'mean'),
        categoria_principal = ('categoria_mcc',   safe_mode),
        uso_internacional   = ('es_internacional', lambda x: x.sum()),
    ).reset_index()

    master = clientes.merge(prod_agg,  on='user_id', how='left')
    master = master.merge(trans_agg,   on='user_id', how='left')
    master = master.fillna({
        'num_productos_total': 0, 'saldo_total_apps': 0,
        'gasto_total': 0, 'transacciones_count': 0, 'ticket_promedio': 0,
        'uso_internacional': 0, 'tiene_tarjeta_credito': False,
        'tiene_inversion': False, 'categoria_principal': 'Sin Actividad',
    })

    # ── CAMBIO v4: convertir bools de las nuevas features a int ──────────────
    for col_bool in ['usa_hey_shop', 'tiene_seguro', 'patron_uso_atipico']:
        master[col_bool] = master[col_bool].astype(int)
    # ─────────────────────────────────────────────────────────────────────────

    return master


def extraer_features_conversacionales() -> pd.DataFrame:
    print("--- Procesando conversaciones ---")
    df_conv = pd.read_parquet(CONV_PATH)
    inp     = df_conv['input'].str.lower().fillna('')

    for col, kws in INTENTS.items():
        df_conv[col] = inp.str.contains('|'.join(kws), na=False).astype(int)

    conv_agg = df_conv.groupby('user_id').agg(
        total_mensajes     = ('input',   'count'),
        num_conversaciones = ('conv_id', 'nunique'),
        **{c: (c, 'sum') for c in INTENTS}
    ).reset_index()

    return conv_agg


def codificar_categoricas(df: pd.DataFrame) -> tuple:
    """
    CAMBIO v4: ahora también codifica 'sexo' → 'sexo_enc'.
    """
    encoders = {}
    for col in ['ocupacion', 'nivel_educativo', 'canal_apertura', 'sexo']:
        le      = LabelEncoder()
        col_enc = col + '_enc'
        df[col_enc] = le.fit_transform(df[col].fillna('Desconocido').astype(str))
        encoders[col] = le
    joblib.dump(encoders, MODEL_DIR / "encodersoptuna.pkl")
    return df, encoders


# ─────────────────────────────────────────────────────────────────────────────
# ETAPA 2 — HDBSCAN
# ─────────────────────────────────────────────────────────────────────────────
def entrenar_hdbscan(df: pd.DataFrame):
    print("\n--- Entrenando HDBSCAN ---")

    X = df[FEATURES_HDBSCAN].copy()
    X['tiene_tarjeta_credito'] = X['tiene_tarjeta_credito'].astype(int)
    X['tiene_inversion']       = X['tiene_inversion'].astype(int)
    X = X.fillna(0)

    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    clusterer = hdbscan.HDBSCAN(
        min_cluster_size         = 300,
        min_samples              = 30,
        cluster_selection_method = 'eom',
        prediction_data          = True,
    )
    labels = clusterer.fit_predict(X_scaled)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise    = (labels == -1).sum()
    print(f"Clusters descubiertos: {n_clusters}")
    print(f"Usuarios sin cluster:  {n_noise} ({n_noise / len(labels) * 100:.1f}%)")
    print(f"Distribución: {pd.Series(labels).value_counts().sort_index().to_dict()}")

    mask = labels != -1
    if mask.sum() > 500:
        score = silhouette_score(X_scaled[mask], labels[mask],
                                 sample_size=3000, random_state=42)
        print(f"Silhouette Score: {score:.4f}")

    joblib.dump(scaler,    MODEL_DIR / "scaler_hdbscanoptuna.pkl")
    joblib.dump(clusterer, MODEL_DIR / "hdbscanoptuna.pkl")
    return labels, scaler, clusterer, X_scaled


# ─────────────────────────────────────────────────────────────────────────────
# ETAPA 3 — RANDOM FOREST CON OPTUNA (v4: 17 features)
# ─────────────────────────────────────────────────────────────────────────────
def entrenar_random_forest(df: pd.DataFrame) -> RandomForestClassifier:
    print("\n--- Entrenando Random Forest con Optuna (v4 — 17 features) ---")

    df_train = df[df['cluster_hdbscan'] >= 0].copy()
    n_ruido  = (df['cluster_hdbscan'] == -1).sum()
    print(f"Usuarios para entrenamiento RF: {len(df_train):,} (excluidos {n_ruido:,} de ruido)")
    print(f"Features RF: {len(FEATURES_RF)} → {FEATURES_RF}")

    X_full = df_train[FEATURES_RF].fillna(0).values
    y_full = df_train['cluster_hdbscan'].values

    X_train, X_test, y_train, y_test = train_test_split(
        X_full, y_full, test_size=0.2, random_state=42, stratify=y_full
    )

    cv = StratifiedKFold(n_splits=OPTUNA_CV_FOLDS, shuffle=True, random_state=42)

    def objective(trial: optuna.Trial) -> float:
        params = {
            'n_estimators':      trial.suggest_int('n_estimators',      50,  500),
            'max_depth':         trial.suggest_int('max_depth',          5,   20),
            'min_samples_leaf':  trial.suggest_int('min_samples_leaf',   1,   20),
            'min_samples_split': trial.suggest_int('min_samples_split',  2,   20),
            'max_features':      trial.suggest_categorical('max_features', ['sqrt', 'log2', None]),
            'class_weight':      'balanced',
            'random_state':      42,
            'n_jobs':            -1,
        }

        fold_scores = []
        for fold_train_idx, fold_val_idx in cv.split(X_train, y_train):
            rf_cv = RandomForestClassifier(**params)
            rf_cv.fit(X_train[fold_train_idx], y_train[fold_train_idx])
            preds = rf_cv.predict(X_train[fold_val_idx])
            fold_scores.append(
                f1_score(y_train[fold_val_idx], preds, average='macro', zero_division=0)
            )

        return float(np.mean(fold_scores))

    print(f"\nBuscando hiperparámetros óptimos ({OPTUNA_TRIALS} trials × {OPTUNA_CV_FOLDS} folds)...")
    print(f"  Penalización: -{PENALIZACION_RECALL} por cada cluster con recall < {RECALL_MINIMO}")
    study = optuna.create_study(
        direction = 'maximize',
        sampler   = optuna.samplers.TPESampler(seed=42),
        pruner    = optuna.pruners.MedianPruner(n_startup_trials=10),
    )
    study.optimize(objective, n_trials=OPTUNA_TRIALS, show_progress_bar=True)

    best = study.best_params
    print(f"\nMejores hiperparámetros encontrados (score={study.best_value:.4f}):")
    for k, v in best.items():
        print(f"  {k}: {v}")

    param_importances = optuna.importance.get_param_importances(study)
    print("\nImportancia de hiperparámetros:")
    for k, v in param_importances.items():
        print(f"  {k}: {v:.4f}")

    with open(MODEL_DIR / "optuna_best_params.json", 'w', encoding='utf-8') as f:
        json.dump({
            'best_params':       best,
            'best_score_cv':     study.best_value,
            'param_importances': param_importances,
            'features_usadas':   FEATURES_RF,
            'nota':              'v4: 17 features, class_weight balanced forzado',
        }, f, ensure_ascii=False, indent=2)
    print(f"\nParámetros guardados en: {MODEL_DIR}/optuna_best_params.json")

    print("\nEntrenando modelo final (class_weight='balanced' forzado)...")
    rf_final = RandomForestClassifier(
        **{k: v for k, v in best.items() if k != 'class_weight'},
        class_weight = 'balanced',
        random_state = 42,
        n_jobs       = -1,
    )
    rf_final.fit(X_train, y_train)

    acc = rf_final.score(X_test, y_test)
    print(f"Accuracy del RF en test: {acc:.4f}")
    print("\nReporte de clasificación:")
    print(classification_report(y_test, rf_final.predict(X_test), zero_division=0))

    importancias = pd.Series(rf_final.feature_importances_, index=FEATURES_RF)
    print("\nFeatures más importantes (modelo optimizado):")
    print(importancias.sort_values(ascending=False).round(4).to_string())

    joblib.dump(rf_final, MODEL_DIR / "random_forestoptuna.pkl")
    print(f"\nRandom Forest guardado en: {MODEL_DIR}/random_forestoptuna.pkl")
    return rf_final


# ─────────────────────────────────────────────────────────────────────────────
# ETAPA 4 — NOMBRADO AUTOMÁTICO CON MINIMAX
# ─────────────────────────────────────────────────────────────────────────────
def construir_perfil_cluster(df: pd.DataFrame, cluster_id: int) -> dict:
    sub         = df[df['cluster_hdbscan'] == cluster_id]
    intent_cols = list(INTENTS.keys())
    intent_top  = (
        sub[intent_cols].sum()
        .sort_values(ascending=False)
        .head(3)
        .index.str.replace('intent_', '')
        .tolist()
    )
    return {
        'n':                 len(sub),
        'ingreso':           sub['ingreso_mensual_mxn'].mean(),
        'gasto':             sub['gasto_total'].mean(),
        'saldo':             sub['saldo_total_apps'].mean(),
        'edad':              sub['edad'].mean(),
        'ticket':            sub['ticket_promedio'].mean(),
        'pct_credito':       sub['tiene_tarjeta_credito'].astype(int).mean() * 100,
        'pct_inversion':     sub['tiene_inversion'].astype(int).mean() * 100,
        'uso_internacional': sub['uso_internacional'].mean(),
        'num_productos':     sub['num_productos_total'].mean(),
        'mensajes_prom':     sub['total_mensajes'].mean(),
        'intents_top':       intent_top,
    }


def extraer_json_de_texto(texto: str) -> dict:
    texto = texto.strip()
    inicio = texto.find('{')
    fin    = texto.rfind('}')
    if inicio != -1 and fin != -1 and fin > inicio:
        try:
            return json.loads(texto[inicio:fin + 1])
        except json.JSONDecodeError:
            pass
    limpio = re.sub(r"^```(?:json)?\s*\n?", "", texto)
    limpio = re.sub(r"\n?```\s*$", "", limpio).strip()
    inicio = limpio.find('{')
    fin    = limpio.rfind('}')
    if inicio != -1 and fin != -1 and fin > inicio:
        try:
            return json.loads(limpio[inicio:fin + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"No se encontró JSON válido en la respuesta:\n{texto[:300]}")


def nombrar_cluster_con_minimax(perfil: dict, cluster_id: int) -> dict:
    client = anthropic.Anthropic(
        base_url = MINIMAX_BASE_URL,
        api_key  = MINIMAX_API_KEY,
    )
    intents_str = ",".join(perfil["intents_top"])
    prompt = (
        f"Segmenta clientes de Hey Banco.\n\n"
        f"Datos cluster {cluster_id}:\n"
        f"ingreso=${perfil['ingreso']:,.0f}MXN | gasto=${perfil['gasto']:,.0f} | "
        f"saldo=${perfil['saldo']:,.0f} | edad={perfil['edad']:.0f}a | "
        f"ticket=${perfil['ticket']:,.0f} | credito={perfil['pct_credito']:.0f}% | "
        f"inversion={perfil['pct_inversion']:.0f}% | intl={perfil['uso_internacional']:.1f} | "
        f"productos={perfil['num_productos']:.1f} | intents={intents_str}\n\n"
        'Responde SOLO con JSON valido (sin markdown, sin texto extra):\n'
        '{"nombre":"2-3 palabras","descripcion":"max 15 palabras","acciones":["a1","a2","a3"]}'
    )
    ultimo_error = None
    for intento in range(3):
        try:
            texto = ""
            with client.messages.stream(
                model      = MINIMAX_MODEL,
                max_tokens = 100000,
                messages   = [{"role": "user", "content": prompt}],
            ) as stream:
                for chunk in stream.text_stream:
                    texto += chunk
            resultado = extraer_json_de_texto(texto)
            assert "nombre" in resultado and "descripcion" in resultado and "acciones" in resultado
            resultado["cluster_id"] = int(cluster_id)
            resultado["n_usuarios"] = int(perfil["n"])
            return resultado
        except Exception as e:
            ultimo_error = e
            print(f"    intento {intento + 1}/3 fallido: {e}")
            time.sleep(2)
    raise ValueError(f"Falló después de 3 intentos: {ultimo_error}")


def nombrar_todos_los_clusters(df: pd.DataFrame) -> dict:
    print("\n--- Nombrando clusters con MiniMax ---")
    clusters_validos = sorted([c for c in df['cluster_hdbscan'].unique() if c >= 0])
    catalogo = {}
    for cid in clusters_validos:
        try:
            perfil    = construir_perfil_cluster(df, cid)
            resultado = nombrar_cluster_con_minimax(perfil, cid)
            catalogo[cid] = resultado
            print(f"  Cluster {cid}: {resultado['nombre']} ({resultado['n_usuarios']:,} usuarios)")
            print(f"    → {resultado['descripcion']}")
        except Exception as e:
            print(f"  Cluster {cid}: error al nombrar — {e}")
            catalogo[cid] = {
                "nombre":      f"Segmento {cid}",
                "descripcion": "Perfil pendiente de descripción.",
                "acciones":    ["Análisis manual recomendado."],
                "cluster_id":  int(cid),
                "n_usuarios":  int((df['cluster_hdbscan'] == cid).sum()),
            }
    catalogo_path = MODEL_DIR / "catalogo_segmentos.json"
    catalogo_serializable = {int(k): v for k, v in catalogo.items()}
    with open(catalogo_path, 'w', encoding='utf-8') as f:
        json.dump(catalogo_serializable, f, ensure_ascii=False, indent=2)
    print(f"\nCatálogo oficial guardado en: {catalogo_path}")
    return catalogo


# ─────────────────────────────────────────────────────────────────────────────
# ETAPA 5 — CLASIFICACIÓN DE NUEVOS USUARIOS (con fallback RF)
# ─────────────────────────────────────────────────────────────────────────────
def clasificar_usuario(datos_usuario: dict, encoders: dict,
                       rf: RandomForestClassifier,
                       scaler_hdbscan, clusterer,
                       catalogo: dict,
                       tiene_historial: bool = False,
                       features_hdbscan: dict = None) -> dict:
    """
    v4: misma interfaz de salida. Ahora usa 17 features para el RF.
    Fallback RF cuando HDBSCAN devuelve -1.
    """

    def _preparar_features_rf(datos: dict) -> pd.DataFrame:
        """Prepara las 17 features del RF desde un dict de usuario."""
        datos_enc = datos.copy()
        for col in ['ocupacion', 'nivel_educativo', 'canal_apertura', 'sexo']:
            col_enc = col + '_enc'
            le      = encoders[col]
            valor   = datos.get(col, 'Desconocido')
            datos_enc[col_enc] = (
                le.transform([valor])[0] if valor in le.classes_ else 0
            )
        # Convertir bools a int por si vienen como True/False
        for col_bool in ['es_hey_pro', 'nomina_domiciliada', 'recibe_remesas',
                         'usa_hey_shop', 'tiene_seguro', 'patron_uso_atipico']:
            if col_bool in datos_enc:
                datos_enc[col_bool] = int(datos_enc[col_bool])
        return pd.DataFrame([datos_enc])[FEATURES_RF].fillna(0)

    if not tiene_historial:
        X            = _preparar_features_rf(datos_usuario)
        cluster_pred = int(rf.predict(X)[0])
        probas       = rf.predict_proba(X)[0]
        confianza    = float(probas.max())
        top2_idx     = probas.argsort()[::-1][:2]
        top2         = {str(rf.classes_[i]): round(float(probas[i]), 3) for i in top2_idx}
        modo         = "Random Forest (demográfico)"

    else:
        X = pd.DataFrame([features_hdbscan])[FEATURES_HDBSCAN].fillna(0)
        X['tiene_tarjeta_credito'] = X['tiene_tarjeta_credito'].astype(int)
        X['tiene_inversion']       = X['tiene_inversion'].astype(int)

        X_scaled          = scaler_hdbscan.transform(X)
        labels, strengths = hdbscan.approximate_predict(clusterer, X_scaled)
        cluster_pred      = int(labels[0])
        confianza_hdbscan = float(strengths[0])

        if cluster_pred != -1:
            info = catalogo.get(cluster_pred, catalogo.get(0, {}))
            return {
                'metodo':                    'HDBSCAN (historial completo)',
                'cluster_id':                cluster_pred,
                'nombre':                    info.get('nombre', f'Cluster {cluster_pred}'),
                'descripcion':               info.get('descripcion', ''),
                'acciones':                  info.get('acciones', []),
                'confianza':                 f'{confianza_hdbscan:.2f}',
                'distribucion_probabilidad': {str(cluster_pred): confianza_hdbscan},
            }

        # Fallback RF
        X_rf         = _preparar_features_rf(datos_usuario)
        cluster_pred = int(rf.predict(X_rf)[0])
        probas       = rf.predict_proba(X_rf)[0]
        confianza    = float(probas.max())
        top2_idx     = probas.argsort()[::-1][:2]
        top2         = {str(rf.classes_[i]): round(float(probas[i]), 3) for i in top2_idx}
        modo         = "HDBSCAN → RF fallback (perfil atípico)"

    info = catalogo.get(cluster_pred, catalogo.get(0, {}))
    return {
        'metodo':                    modo,
        'cluster_id':                cluster_pred,
        'nombre':                    info.get('nombre', f'Cluster {cluster_pred}'),
        'descripcion':               info.get('descripcion', ''),
        'acciones':                  info.get('acciones', []),
        'confianza':                 f'{confianza:.2f}',
        'distribucion_probabilidad': top2,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ETAPA 6 — VISUALIZACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def graficar_clusters(df: pd.DataFrame, catalogo: dict) -> None:
    df_plot = df[df['cluster_hdbscan'] >= 0].copy()

    X = df_plot[FEATURES_HDBSCAN].fillna(0).astype(float)
    X['tiene_tarjeta_credito'] = X['tiene_tarjeta_credito'].astype(int)
    X['tiene_inversion']       = X['tiene_inversion'].astype(int)

    coords = PCA(n_components=2, random_state=42).fit_transform(
        StandardScaler().fit_transform(X)
    )
    df_plot = df_plot.copy()
    df_plot['pca_x'] = coords[:, 0]
    df_plot['pca_y'] = coords[:, 1]

    colores = ['#E63946', '#2A9D8F', '#E9C46A', '#6A4C93', '#F4A261', '#264653']
    fig, ax = plt.subplots(figsize=(11, 7))

    for cid in sorted(df_plot['cluster_hdbscan'].unique()):
        nombre = catalogo.get(cid, {}).get('nombre', f'Cluster {cid}')
        m = df_plot['cluster_hdbscan'] == cid
        ax.scatter(df_plot.loc[m, 'pca_x'], df_plot.loc[m, 'pca_y'],
                   c=colores[cid % len(colores)],
                   label=f'{cid}: {nombre}', alpha=0.55, s=12)

    ax.set_title('Hey Twin — Segmentos descubiertos (HDBSCAN + PCA 2D)', fontsize=13)
    ax.set_xlabel('Componente Principal 1')
    ax.set_ylabel('Componente Principal 2')
    ax.legend(loc='upper right', fontsize=9)
    ax.grid(True, alpha=0.25)
    plt.tight_layout()
    plt.savefig('clusters_finales.png', dpi=150)
    plt.show()
    print("Gráfica guardada: clusters_finales.png")


# ─────────────────────────────────────────────────────────────────────────────
# EJECUCIÓN PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":

    print("=" * 60)
    print("FASE A: ENTRENAMIENTO DEL PIPELINE (Optuna v4 — 17 features)")
    print("=" * 60)

    df_trans = cargar_transacciones()
    conv_agg = extraer_features_conversacionales()
    df       = df_trans.merge(conv_agg, on='user_id', how='left').fillna(0)
    df, encoders = codificar_categoricas(df)
    print(f"\nDataset final: {df.shape[0]:,} usuarios, {df.shape[1]} columnas")

    labels, scaler_hdbscan, clusterer, X_scaled = entrenar_hdbscan(df)
    df['cluster_hdbscan'] = labels

    rf = entrenar_random_forest(df)

    catalogo = nombrar_todos_los_clusters(df)

    df['segmento_nombre'] = df['cluster_hdbscan'].map(
        {k: v['nombre'] for k, v in catalogo.items()}
    ).fillna('Perfil Atípico')

    df.to_csv("hey_segmentos_completo.csv", index=False)
    print("\nArchivo guardado: hey_segmentos_completo.csv")
    print("\n=== DISTRIBUCIÓN FINAL ===")
    print(df['segmento_nombre'].value_counts())

    graficar_clusters(df, catalogo)

    # ════════════════════════════════════════════════════════════════════════
    # FASE B — DEMO
    # ════════════════════════════════════════════════════════════════════════
    print("\n" + "=" * 60)
    print("FASE B: DEMO — CLASIFICACIÓN AUTÓNOMA DE USUARIOS")
    print("=" * 60)

    encoders_cargados = joblib.load(MODEL_DIR / "encodersoptuna.pkl")
    rf_cargado        = joblib.load(MODEL_DIR / "random_forestoptuna.pkl")
    scaler_cargado    = joblib.load(MODEL_DIR / "scaler_hdbscanoptuna.pkl")
    clusterer_cargado = joblib.load(MODEL_DIR / "hdbscanoptuna.pkl")
    with open(MODEL_DIR / "catalogo_segmentos.json", encoding='utf-8') as f:
        catalogo_cargado = {int(k): v for k, v in json.load(f).items()}

    # ── DEMO 1: v4 ahora incluye las nuevas features ─────────────────────
    print("\n[DEMO 1] Usuario recién registrado — 17 features demográficas:")
    usuario_nuevo = {
        'edad':                   26,
        'ingreso_mensual_mxn':    17000,
        'score_buro':             680,
        'antiguedad_dias':        1,
        'num_productos_activos':  1,
        'es_hey_pro':             0,
        'nomina_domiciliada':     0,
        'recibe_remesas':         0,
        'ocupacion':              'Empleado',
        'nivel_educativo':        'Universidad',
        'canal_apertura':         'app',
        # ── NUEVAS v4 ──
        'dias_desde_ultimo_login': 0,
        'satisfaccion_1_10':       7,
        'usa_hey_shop':            0,
        'tiene_seguro':            0,
        'patron_uso_atipico':      0,
        'sexo':                    'H',
    }
    r1 = clasificar_usuario(
        datos_usuario   = usuario_nuevo,
        encoders        = encoders_cargados,
        rf              = rf_cargado,
        scaler_hdbscan  = scaler_cargado,
        clusterer       = clusterer_cargado,
        catalogo        = catalogo_cargado,
        tiene_historial = False,
    )
    print(f"  Método:    {r1['metodo']}")
    print(f"  Segmento:  {r1['nombre']} (cluster {r1['cluster_id']})")
    print(f"  Confianza: {r1['confianza']}  |  Probabilidades: {r1['distribucion_probabilidad']}")
    print(f"  {r1['descripcion']}")
    print("  Acciones:")
    for a in r1['acciones']:
        print(f"    • {a}")

    # ── DEMO 2: Usuario con historial + fallback ──────────────────────────
    print("\n[DEMO 2] Usuario con historial — reclasificación (con fallback RF):")
    usuario_historial = {
        'edad': 41, 'ingreso_mensual_mxn': 55000, 'score_buro': 750,
        'antiguedad_dias': 720, 'num_productos_activos': 3,
        'es_hey_pro': 1, 'nomina_domiciliada': 1, 'recibe_remesas': 0,
        'ocupacion': 'Empresario', 'nivel_educativo': 'Posgrado',
        'canal_apertura': 'app',
        # nuevas v4
        'dias_desde_ultimo_login': 2,
        'satisfaccion_1_10':       9,
        'usa_hey_shop':            1,
        'tiene_seguro':            1,
        'patron_uso_atipico':      0,
        'sexo':                    'H',
        # features HDBSCAN
        'gasto_total': 480000, 'saldo_total_apps': 210000,
        'num_productos_total': 3, 'ticket_promedio': 8500,
        'uso_internacional': 4, 'tiene_tarjeta_credito': 1,
        'tiene_inversion': 1, 'total_mensajes': 6,
        'num_conversaciones': 3, 'intent_credito': 1,
        'intent_inversion': 2, 'intent_cashback': 0,
        'intent_soporte': 0, 'intent_ahorro': 1,
        'intent_internacional': 1, 'intent_negocio': 1,
    }
    r2 = clasificar_usuario(
        datos_usuario    = usuario_historial,
        encoders         = encoders_cargados,
        rf               = rf_cargado,
        scaler_hdbscan   = scaler_cargado,
        clusterer        = clusterer_cargado,
        catalogo         = catalogo_cargado,
        tiene_historial  = True,
        features_hdbscan = usuario_historial,
    )
    print(f"  Método:    {r2['metodo']}")
    print(f"  Segmento:  {r2['nombre']} (cluster {r2['cluster_id']})")
    print(f"  Confianza: {r2['confianza']}  |  Probabilidades: {r2['distribucion_probabilidad']}")
    print(f"  {r2['descripcion']}")
    print("  Acciones:")
    for a in r2['acciones']:
        print(f"    • {a}")