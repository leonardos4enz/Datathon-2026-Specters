"""
Hey Banco — API de Clasificación de Usuarios
Recibe datos de un usuario vía POST y devuelve su segmento con acciones personalizadas.
Diseñada para integrarse con n8n u otros flujos de automatización.

Instalación:
    pip install fastapi uvicorn joblib hdbscan scikit-learn pandas

Arrancar:
    uvicorn api:app --host 0.0.0.0 --port 8000 --reload

Endpoint principal:
    POST http://localhost:8000/clasificar

En n8n: usa un nodo HTTP Request apuntando a este endpoint.
"""
import json
import joblib
import hdbscan
import pandas as pd
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────────────────────
MODEL_DIR = Path("hey_modelo")

FEATURES_RF = [
    'edad', 'ingreso_mensual_mxn', 'score_buro',
    'antiguedad_dias', 'num_productos_activos',
    'es_hey_pro', 'nomina_domiciliada', 'recibe_remesas',
    'ocupacion_enc', 'nivel_educativo_enc', 'canal_apertura_enc',
]

FEATURES_HDBSCAN = [
    'ingreso_mensual_mxn', 'gasto_total', 'edad', 'saldo_total_apps',
    'num_productos_total', 'ticket_promedio', 'uso_internacional',
    'tiene_tarjeta_credito', 'tiene_inversion',
    'total_mensajes', 'num_conversaciones',
    'intent_credito', 'intent_inversion', 'intent_cashback',
    'intent_soporte', 'intent_ahorro', 'intent_internacional', 'intent_negocio',
]

# Modelos en memoria (se cargan una sola vez al arrancar)
MODELOS: dict = {}


# ─────────────────────────────────────────────────────────────────────────────
# CARGA DE MODELOS AL ARRANCAR
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Carga los modelos en memoria al iniciar la API."""
    print("Cargando modelos Hey Banco...")
    MODELOS['encoders']  = joblib.load(MODEL_DIR / "encoders.pkl")
    MODELOS['rf']        = joblib.load(MODEL_DIR / "random_forest.pkl")
    MODELOS['scaler']    = joblib.load(MODEL_DIR / "scaler_hdbscan.pkl")
    MODELOS['clusterer'] = joblib.load(MODEL_DIR / "hdbscan.pkl")
    with open(MODEL_DIR / "catalogo_segmentos.json", encoding="utf-8") as f:
        MODELOS['catalogo'] = {int(k): v for k, v in json.load(f).items()}
    print(f"✓ {len(MODELOS['catalogo'])} segmentos cargados y listos.")
    yield
    MODELOS.clear()


# ─────────────────────────────────────────────────────────────────────────────
# APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title       = "Hey Banco — Motor de Segmentación",
    description = "Clasifica usuarios en segmentos con acciones personalizadas.",
    version     = "1.0.0",
    lifespan    = lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# MODELOS DE DATOS (lo que n8n debe enviar en el POST)
# ─────────────────────────────────────────────────────────────────────────────
class DatosUsuario(BaseModel):
    """Datos demográficos — siempre requeridos (disponibles desde el registro)."""
    user_id:               Optional[str] = Field(None,  description="ID del usuario (opcional, se devuelve tal cual)")
    edad:                  int           = Field(...,   description="Edad en años")
    ingreso_mensual_mxn:   float         = Field(...,   description="Ingreso mensual en MXN")
    score_buro:            float         = Field(...,   description="Score buró de crédito")
    antiguedad_dias:       int           = Field(0,     description="Días desde el registro")
    num_productos_activos: int           = Field(1,     description="Número de productos activos")
    es_hey_pro:            int           = Field(0,     description="1 si es Hey Pro, 0 si no")
    nomina_domiciliada:    int           = Field(0,     description="1 si tiene nómina domiciliada")
    recibe_remesas:        int           = Field(0,     description="1 si recibe remesas")
    ocupacion:             str           = Field("Empleado",    description="Ocupación del usuario")
    nivel_educativo:       str           = Field("Universidad", description="Nivel educativo")
    canal_apertura:        str           = Field("app",         description="Canal de apertura de cuenta")

    # Historial — opcionales, solo si el usuario ya tiene transacciones
    gasto_total:           Optional[float] = Field(None, description="Gasto total acumulado")
    saldo_total_apps:      Optional[float] = Field(None, description="Saldo total en apps")
    num_productos_total:   Optional[int]   = Field(None, description="Total de productos")
    ticket_promedio:       Optional[float] = Field(None, description="Ticket promedio por transacción")
    uso_internacional:     Optional[float] = Field(None, description="Transacciones internacionales")
    tiene_tarjeta_credito: Optional[int]   = Field(None, description="1 si tiene tarjeta de crédito")
    tiene_inversion:       Optional[int]   = Field(None, description="1 si tiene inversión")
    total_mensajes:        Optional[int]   = Field(None, description="Mensajes de soporte enviados")
    num_conversaciones:    Optional[int]   = Field(None, description="Número de conversaciones")
    intent_credito:        Optional[int]   = Field(None)
    intent_inversion:      Optional[int]   = Field(None)
    intent_cashback:       Optional[int]   = Field(None)
    intent_soporte:        Optional[int]   = Field(None)
    intent_ahorro:         Optional[int]   = Field(None)
    intent_internacional:  Optional[int]   = Field(None)
    intent_negocio:        Optional[int]   = Field(None)


class RespuestaClasificacion(BaseModel):
    """Lo que la API devuelve a n8n."""
    user_id:          Optional[str]
    metodo:           str
    cluster_id:       int
    segmento:         str
    descripcion:      str
    acciones:         list[str]
    confianza:        float
    tiene_historial:  bool


# ─────────────────────────────────────────────────────────────────────────────
# LÓGICA DE CLASIFICACIÓN
# ─────────────────────────────────────────────────────────────────────────────
def _clasificar(datos: DatosUsuario) -> dict:
    encoders  = MODELOS['encoders']
    rf        = MODELOS['rf']
    scaler    = MODELOS['scaler']
    clusterer = MODELOS['clusterer']
    catalogo  = MODELOS['catalogo']

    # Detectar automáticamente si tiene historial
    tiene_historial = datos.gasto_total is not None and datos.antiguedad_dias > 30

    if not tiene_historial:
        # ── Random Forest con datos demográficos ──────────────────────────
        datos_enc = datos.model_dump()
        for col in ['ocupacion', 'nivel_educativo', 'canal_apertura']:
            le      = encoders[col]
            valor   = datos_enc.get(col, 'Desconocido')
            datos_enc[col + '_enc'] = int(le.transform([valor])[0]) if valor in le.classes_ else 0

        X            = pd.DataFrame([datos_enc])[FEATURES_RF].fillna(0)
        cluster_pred = int(rf.predict(X)[0])
        confianza    = float(rf.predict_proba(X)[0].max())
        metodo       = "Random Forest (demográfico)"

    else:
        # ── HDBSCAN con historial completo ────────────────────────────────
        features = datos.model_dump()
        X = pd.DataFrame([features])[FEATURES_HDBSCAN].fillna(0)
        X['tiene_tarjeta_credito'] = X['tiene_tarjeta_credito'].astype(int)
        X['tiene_inversion']       = X['tiene_inversion'].astype(int)

        X_scaled          = scaler.transform(X)
        labels, strengths = hdbscan.approximate_predict(clusterer, X_scaled)
        cluster_pred      = int(labels[0])
        confianza         = float(strengths[0])
        metodo            = "HDBSCAN (historial completo)"

        # Fallback a RF si HDBSCAN no reconoce el perfil
        if cluster_pred == -1:
            datos_enc = datos.model_dump()
            for col in ['ocupacion', 'nivel_educativo', 'canal_apertura']:
                le      = encoders[col]
                valor   = datos_enc.get(col, 'Desconocido')
                datos_enc[col + '_enc'] = int(le.transform([valor])[0]) if valor in le.classes_ else 0

            X_rf         = pd.DataFrame([datos_enc])[FEATURES_RF].fillna(0)
            cluster_pred = int(rf.predict(X_rf)[0])
            confianza    = float(rf.predict_proba(X_rf)[0].max())
            metodo       = "RF fallback (perfil atípico)"

    info = catalogo.get(cluster_pred, {})
    return {
        'user_id':         datos.user_id,
        'metodo':          metodo,
        'cluster_id':      cluster_pred,
        'segmento':        info.get('nombre',      f'Cluster {cluster_pred}'),
        'descripcion':     info.get('descripcion', ''),
        'acciones':        info.get('acciones',    []),
        'confianza':       round(confianza, 3),
        'tiene_historial': tiene_historial,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/")
def raiz():
    return {"status": "ok", "mensaje": "Hey Banco API corriendo ✓"}


@app.get("/segmentos")
def listar_segmentos():
    """Lista todos los segmentos disponibles con sus acciones."""
    return {"segmentos": MODELOS['catalogo']}


@app.post("/clasificar", response_model=RespuestaClasificacion)
def clasificar(datos: DatosUsuario):
    """
    Clasifica un usuario y devuelve su segmento con acciones personalizadas.

    - Si el usuario tiene menos de 30 días o no tiene historial → usa Random Forest
    - Si tiene historial completo → usa HDBSCAN (más preciso)
    - Si HDBSCAN no reconoce el perfil → fallback automático a Random Forest

    Ejemplo de body para n8n:
    {
        "user_id": "USR_001",
        "edad": 28,
        "ingreso_mensual_mxn": 22000,
        "score_buro": 710,
        "antiguedad_dias": 3,
        "num_productos_activos": 1,
        "es_hey_pro": 0,
        "nomina_domiciliada": 1,
        "recibe_remesas": 0,
        "ocupacion": "Empleado",
        "nivel_educativo": "Universidad",
        "canal_apertura": "app"
    }
    """
    try:
        resultado = _clasificar(datos)
        return resultado
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/clasificar/batch")
def clasificar_batch(usuarios: list[DatosUsuario]):
    """
    Clasifica múltiples usuarios en una sola llamada.
    Útil para procesar lotes desde n8n o bases de datos.
    Máximo 500 usuarios por llamada.
    """
    if len(usuarios) > 500:
        raise HTTPException(status_code=400, detail="Máximo 500 usuarios por llamada batch.")
    try:
        return {"resultados": [_clasificar(u) for u in usuarios]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
