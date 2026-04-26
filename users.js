const PROFILES = {
  abiel: {
    user_id: 'USR-00001',
    nombre: 'Abiel',
    edad: 32,
    ingreso_mensual_mxn: 42000,
    score_buro: 750,
    antiguedad_dias: 180,
    num_productos_activos: 2,
    es_hey_pro: 1,
    nomina_domiciliada: 1,
    recibe_remesas: 0,
    ocupacion: 'Empleado',
    nivel_educativo: 'Universidad',
    canal_apertura: 'app',
  },
  david: {
    user_id: 'USR-00004',
    nombre: 'David',
    edad: 28,
    ingreso_mensual_mxn: 28000,
    score_buro: 680,
    antiguedad_dias: 90,
    num_productos_activos: 1,
    es_hey_pro: 0,
    nomina_domiciliada: 0,
    recibe_remesas: 1,
    ocupacion: 'Independiente',
    nivel_educativo: 'Preparatoria',
    canal_apertura: 'web',
  },
  leonardo: {
    user_id: 'USR-00011',
    nombre: 'Leonardo',
    edad: 45,
    ingreso_mensual_mxn: 65000,
    score_buro: 810,
    antiguedad_dias: 730,
    num_productos_activos: 4,
    es_hey_pro: 1,
    nomina_domiciliada: 1,
    recibe_remesas: 0,
    ocupacion: 'Empresario',
    nivel_educativo: 'Posgrado',
    canal_apertura: 'app',
  },
  manuel: {
    user_id: 'USR-00096',
    nombre: 'Manuel',
    edad: 35,
    ingreso_mensual_mxn: 38000,
    score_buro: 720,
    antiguedad_dias: 365,
    num_productos_activos: 3,
    es_hey_pro: 1,
    nomina_domiciliada: 1,
    recibe_remesas: 0,
    ocupacion: 'Empleado',
    nivel_educativo: 'Universidad',
    canal_apertura: 'app',
  },
};

const CLASSIFICATION_WEBHOOK_URL = 'https://n8n-n8n.ppnoc4.easypanel.host/webhook/1adfc1df-3641-43b8-b420-54fb19a9b85f';

async function fetchClassification(userId) {
  try {
    const res = await fetch(CLASSIFICATION_WEBHOOK_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: userId }),
    });
    const data = await res.json();
    return data.classificationString ?? data.classification ?? data.output ?? '';
  } catch (err) {
    console.error('No se pudo obtener classificationString', err);
    return '';
  }
}

const overlay = document.getElementById('loadingOverlay');

document.querySelectorAll('.profile-card').forEach((card) => {
  card.addEventListener('click', async () => {
    const key = card.dataset.user;
    const profile = PROFILES[key];
    if (overlay) overlay.classList.add('show');

    const classificationString = await fetchClassification(profile.user_id);
    const userWithClassification = { ...profile, classificationString };

    localStorage.setItem('havi_user', JSON.stringify(userWithClassification));
    window.location.href = 'index.html';
  });
});
