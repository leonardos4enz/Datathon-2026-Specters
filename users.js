const PROFILES = {
  carlos: {
    user_id: 'USR-08547',
    nombre: 'Carlos',
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
  maria: {
    user_id: 'USR-12384',
    nombre: 'María',
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
  jorge: {
    user_id: 'USR-03921',
    nombre: 'Jorge',
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
};

document.querySelectorAll('.profile-card').forEach((card) => {
  card.addEventListener('click', () => {
    const key = card.dataset.user;
    localStorage.setItem('havi_user', JSON.stringify(PROFILES[key]));
    window.location.href = 'index.html';
  });
});
