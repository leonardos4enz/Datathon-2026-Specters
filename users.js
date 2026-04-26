const PROFILES = {
  jeft: {
    user_id: 'USR-08347',
    nombre: 'Jeft',
    edad: 22,
    ingreso_mensual_mxn: 18000,
    score_buro: 610,
    antiguedad_dias: 30,
    num_productos_activos: 1,
    es_hey_pro: 0,
    nomina_domiciliada: 0,
    recibe_remesas: 0,
    ocupacion: 'Estudiante',
    nivel_educativo: 'Universidad',
    canal_apertura: 'app',
  },
  leo: {
    user_id: 'USR-12651',
    nombre: 'Leo',
    edad: 35,
    ingreso_mensual_mxn: 52000,
    score_buro: 780,
    antiguedad_dias: 365,
    num_productos_activos: 3,
    es_hey_pro: 1,
    nomina_domiciliada: 1,
    recibe_remesas: 0,
    ocupacion: 'Empleado',
    nivel_educativo: 'Universidad',
    canal_apertura: 'app',
  },
  manuel: {
    user_id: 'USR-03782',
    nombre: 'Manuel',
    edad: 50,
    ingreso_mensual_mxn: 80000,
    score_buro: 830,
    antiguedad_dias: 1200,
    num_productos_activos: 5,
    es_hey_pro: 1,
    nomina_domiciliada: 1,
    recibe_remesas: 0,
    ocupacion: 'Empresario',
    nivel_educativo: 'Posgrado',
    canal_apertura: 'web',
  },
  david: {
    user_id: 'USR-14256',
    nombre: 'David',
    edad: 29,
    ingreso_mensual_mxn: 31000,
    score_buro: 700,
    antiguedad_dias: 120,
    num_productos_activos: 2,
    es_hey_pro: 0,
    nomina_domiciliada: 1,
    recibe_remesas: 1,
    ocupacion: 'Empleado',
    nivel_educativo: 'Universidad',
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
