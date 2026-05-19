"""
solver_ga.py — Módulo 3: Optimizador Genético.

Toma la solución factible de CP-SAT y la mejora minimizando violaciones de
restricciones blandas (RB1-RB5) usando un algoritmo genético con DEAP.

Restricciones blandas implementadas:
    RB1 (peso 100): Labs de ING1103 (Programación) consecutivos en el mismo día.
    RB2 (peso  80): Profesores JORNADA no asignados a bloques extremos (8:30, 17:30).
    RB3 (peso  50): CLAS, AYUD y LABT de la misma sección (mismo NRC) en días distintos.
    RB4 (peso  50): No más de 1 sesión del mismo tipo por sección por día.
    RB5 (peso  10): No implementado (sin datos históricos).

Uso:
    from solver_ga import optimizar_ga
    datos = optimizar_ga(datos)
    datos = optimizar_ga(datos, pesos={"RB1": 200, "RB2": 80, "RB3": 50, "RB4": 50})
"""

import random
from collections import defaultdict

from deap import base, creator, tools

from models import DatosProblema, Seccion, TipoReunion, TipoProfesor

# ---------------------------------------------------------------------------
# Parámetros del GA
# ---------------------------------------------------------------------------

TAMANO_POBLACION = 100
P_MUTACION = 0.15         # probabilidad de mutar un individuo
P_CRUCE = 0.7             # probabilidad de cruzar un par de individuos
MAX_GENERACIONES = 500
PARADA_SIN_MEJORA = 100   # parar si no hay mejora en N generaciones
TORNEO_K = 3              # tamaño del torneo de selección
MAX_INTENTOS_MUTACION = 20  # intentos para encontrar bloque válido en mutación

PESOS_DEFAULT: dict[str, int] = {
    "RB1": 100,
    "RB2": 80,
    "RB3": 50,
    "RB4": 50,
    "RB5": 0,   # sin datos históricos en v1
}

# Bloques extremos: hora de inicio en minutos
_EXTREMOS_MIN = {8 * 60 + 30, 17 * 60 + 30}

# Código del curso de Programación para RB1
_CODIGO_PROGRAMACION = "ING1103"


# ---------------------------------------------------------------------------
# Punto de entrada público
# ---------------------------------------------------------------------------

def optimizar_ga(
    datos: DatosProblema,
    pesos: dict[str, int] | None = None,
) -> DatosProblema:
    """Módulo 3: optimiza restricciones blandas sobre la solución de CP-SAT.

    Requiere que datos.secciones tenga bloque_asignado != None para las
    secciones programables (resultado del CP-SAT). Las secciones sin bloque
    asignado (ej: 2+1) se ignoran.

    Modifica datos.secciones in-place, actualizando bloque_asignado con la
    mejor solución encontrada por el GA.

    Args:
        datos: DatosProblema con bloque_asignado rellenado por CP-SAT.
        pesos: Diccionario de pesos para las restricciones blandas. Si None,
               se usan los pesos por defecto.

    Returns:
        El mismo objeto datos con bloque_asignado optimizado.
    """
    print("=" * 60)
    print("MÓDULO 3: Optimizador Genético (GA)")
    print("=" * 60)

    if pesos is None:
        pesos = PESOS_DEFAULT

    bloques = datos.bloques_disponibles

    # Filtrar secciones que tienen bloque asignado (programables por CP-SAT)
    secciones_prog = [s for s in datos.secciones if s.bloque_asignado is not None]
    if not secciones_prog:
        print("  No hay secciones programadas. Abortando GA.")
        return datos

    print(f"\n  Secciones a optimizar: {len(secciones_prog)}")

    # --- Pre-cálculo de estructuras ---
    dominios, ind_por_id = _preparar_dominios(secciones_prog, bloques)
    bloque_a_idx = {b: i for i, b in enumerate(bloques)}
    conflictos_bloques = _precalcular_conflictos(bloques)
    vecinos = _precomputer_vecinos(secciones_prog, ind_por_id)
    por_nrc = _agrupar_por_nrc(secciones_prog)
    idx_labt_prog = _indices_labt_programacion(secciones_prog)

    print(f"  Bloques disponibles:   {len(bloques)}")
    print(f"  Pares de vecinos (hard constraints): "
          f"{sum(len(v) for v in vecinos.values()) // 2}")

    # --- Solución inicial (del CP-SAT) ---
    ind_inicial = [bloque_a_idx[s.bloque_asignado] for s in secciones_prog]
    fitness_inicial = _evaluar(
        ind_inicial, secciones_prog, bloques, pesos, por_nrc, idx_labt_prog
    )[0]
    print(f"\n  Fitness inicial (CP-SAT): {fitness_inicial:.0f}")

    # --- Configurar DEAP ---
    _init_deap()
    toolbox = _crear_toolbox(
        ind_inicial, secciones_prog, bloques, pesos,
        dominios, vecinos, conflictos_bloques, por_nrc, idx_labt_prog
    )

    # --- Población inicial: solución CP-SAT + variantes mutadas ---
    print(f"\n  Iniciando población de {TAMANO_POBLACION} individuos...")
    poblacion = _crear_poblacion(toolbox, ind_inicial, TAMANO_POBLACION)

    # Evaluar todos
    for ind in poblacion:
        ind.fitness.values = toolbox.evaluate(ind)

    # --- Bucle GA ---
    print(f"\n  Ejecutando GA (max {MAX_GENERACIONES} gen, "
          f"parada tras {PARADA_SIN_MEJORA} gen sin mejora)...")
    poblacion, generacion_final, mejor_fitness = _ejecutar_ga(
        poblacion, toolbox, MAX_GENERACIONES, PARADA_SIN_MEJORA
    )

    # --- Mejor individuo → actualizar bloque_asignado ---
    mejor = tools.selBest(poblacion, 1)[0]
    print(f"\n  Generaciones ejecutadas: {generacion_final + 1}")
    print(f"  Fitness inicial: {fitness_inicial:.0f}")
    print(f"  Fitness final:   {mejor.fitness.values[0]:.0f}")
    print(f"  Mejora:          {fitness_inicial - mejor.fitness.values[0]:.0f} puntos")

    for i, s in enumerate(secciones_prog):
        s.bloque_asignado = bloques[mejor[i]]

    _imprimir_reporte_soft(mejor, secciones_prog, bloques, pesos, por_nrc, idx_labt_prog)

    return datos


# ---------------------------------------------------------------------------
# Pre-cálculo de estructuras
# ---------------------------------------------------------------------------

def _hora_a_min(hora: str) -> int:
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def _solapan(b1, b2) -> bool:
    return b1.dia == b2.dia and bool(set(b1.sub_bloques) & set(b2.sub_bloques))


def _precalcular_conflictos(bloques: list) -> dict[int, set[int]]:
    n = len(bloques)
    mapa: dict[int, set] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _solapan(bloques[i], bloques[j]):
                mapa[i].add(j)
                mapa[j].add(i)
    return mapa


def _preparar_dominios(
    secciones: list,
    bloques: list,
) -> tuple[dict[int, list[int]], dict[str, int]]:
    """Calcula los dominios de bloque válidos para cada sección.

    Returns:
        (dominios, ind_por_id): dominios[i] es la lista de índices de bloque
        válidos para la sección i. ind_por_id mapea ID de sección a su índice.
    """
    ind_por_id = {s.id: i for i, s in enumerate(secciones)}
    dominios: dict[int, list] = {}

    for i, s in enumerate(secciones):
        dist = s.curso.distribucion.strip()
        es_ayud = s.tipo_reunion == TipoReunion.AYUDANTIA
        es_lab = s.tipo_reunion == TipoReunion.LABORATORIO
        es_3h = dist in {"3", "3-juntas"} and not es_ayud and not es_lab
        _min_12_30 = 12 * 60 + 30

        validos = []
        for j, bloque in enumerate(bloques):
            if es_3h and bloque.duracion_horas != 3:
                continue
            if not es_3h and bloque.duracion_horas == 3:
                continue
            if es_ayud and _hora_a_min(bloque.hora_inicio) < _min_12_30:
                continue
            validos.append(j)
        dominios[i] = validos if validos else list(range(len(bloques)))

    return dominios, ind_por_id


def _precomputer_vecinos(
    secciones: list,
    ind_por_id: dict[str, int],
) -> dict[int, set[int]]:
    """Vecinos[i] = indices de secciones que no pueden solaparse con i."""
    n = len(secciones)
    vecinos: dict[int, set] = {i: set() for i in range(n)}

    def _add_par(i: int, j: int) -> None:
        if i != j:
            vecinos[i].add(j)
            vecinos[j].add(i)

    def _add_grupo(grupo: list) -> None:
        seen: dict[str, int] = {}
        for s in grupo:
            sid = s.id
            idx = ind_por_id.get(sid)
            if idx is None or sid in seen:
                continue
            seen[sid] = idx
            for sid2, idx2 in seen.items():
                if sid2 != sid:
                    _add_par(idx, idx2)

    # RD3/RD8: mismo profesor
    por_prof: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.profesor:
            por_prof[s.profesor.id].append(s)
        if s.profesor_lab and (not s.profesor or s.profesor_lab.id != s.profesor.id):
            por_prof[s.profesor_lab.id].append(s)
    for grupo in por_prof.values():
        _add_grupo(grupo)

    # RD4: misma sala especial
    por_sala: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.sala_especial:
            por_sala[s.sala_especial.nombre].append(s)
    for grupo in por_sala.values():
        _add_grupo(grupo)

    # RD1: distintos cursos en mismo semestre Plan Común
    por_sem: dict[int, list] = defaultdict(list)
    for s in secciones:
        sem = s.curso.semestres.get("Plan Común")
        if sem:
            por_sem[int(sem)].append(s)
    for grupo in por_sem.values():
        seen: dict[str, int] = {}
        for s in grupo:
            sid = s.id
            idx = ind_por_id.get(sid)
            if idx is None or sid in seen:
                continue
            seen[sid] = idx
            for sid2, idx2 in seen.items():
                # Solo agregar si son de cursos distintos
                s2 = secciones[idx2]
                if s.curso.codigo != s2.curso.codigo:
                    _add_par(idx, idx2)

    return vecinos


def _agrupar_por_nrc(secciones: list) -> dict[str, list[int]]:
    """Agrupa índices de secciones por NRC (componentes de la misma sección física)."""
    por_nrc: dict[str, list] = defaultdict(list)
    for i, s in enumerate(secciones):
        por_nrc[s.nrc].append(i)
    return {nrc: idxs for nrc, idxs in por_nrc.items() if len(idxs) > 1}


def _indices_labt_programacion(secciones: list) -> list[int]:
    """Índices de las secciones LABT del curso de Programación (ING1103) para RB1."""
    return [
        i for i, s in enumerate(secciones)
        if s.tipo_reunion == TipoReunion.LABORATORIO
        and s.curso.codigo == _CODIGO_PROGRAMACION
    ]


# ---------------------------------------------------------------------------
# Evaluación de restricciones blandas
# ---------------------------------------------------------------------------

def _evaluar(
    individual: list[int],
    secciones: list,
    bloques: list,
    pesos: dict,
    por_nrc: dict,
    idx_labt_prog: list[int],
) -> tuple[float]:
    """Calcula la penalización total del individuo (menor es mejor)."""
    penalidad = 0.0

    # RB1: labs de Programación consecutivos en el mismo día
    if pesos.get("RB1", 0) > 0 and len(idx_labt_prog) > 1:
        penalidad += _penalidad_rb1(individual, bloques, idx_labt_prog, pesos["RB1"])

    # RB2: profesores JORNADA no en bloques extremos
    if pesos.get("RB2", 0) > 0:
        for i, s in enumerate(secciones):
            if s.profesor and s.profesor.tipo == TipoProfesor.JORNADA:
                b = bloques[individual[i]]
                if _hora_a_min(b.hora_inicio) in _EXTREMOS_MIN:
                    penalidad += pesos["RB2"]

    # RB3 + RB4: espaciado y concentración por NRC
    if pesos.get("RB3", 0) > 0 or pesos.get("RB4", 0) > 0:
        for idxs in por_nrc.values():
            dias = [bloques[individual[i]].dia for i in idxs]
            tipos = [secciones[i].tipo_reunion for i in idxs]

            # RB3: pares en el mismo día
            if pesos.get("RB3", 0) > 0:
                for a in range(len(dias)):
                    for b in range(a + 1, len(dias)):
                        if dias[a] == dias[b]:
                            penalidad += pesos["RB3"]

            # RB4: más de 1 sesión del mismo tipo en el mismo día
            if pesos.get("RB4", 0) > 0:
                conteo: dict = defaultdict(int)
                for tipo, dia in zip(tipos, dias):
                    conteo[(tipo, dia)] += 1
                for cnt in conteo.values():
                    if cnt > 1:
                        penalidad += pesos["RB4"] * (cnt - 1)

    return (penalidad,)


def _penalidad_rb1(
    individual: list[int],
    bloques: list,
    idx_labt_prog: list[int],
    peso: int,
) -> float:
    """RB1: labs de Programación deben estar en bloques consecutivos del mismo día.

    Dos bloques son consecutivos si están en el mismo día y el inicio de uno
    es igual al fin del otro (ej: 8:30-10:20 y 10:30-12:20).
    Penaliza pares de labs que NO están en bloques consecutivos.
    """
    penalidad = 0.0
    for a in range(len(idx_labt_prog)):
        for b in range(a + 1, len(idx_labt_prog)):
            ba = bloques[individual[idx_labt_prog[a]]]
            bb = bloques[individual[idx_labt_prog[b]]]
            if ba.dia != bb.dia or not _son_consecutivos(ba, bb):
                penalidad += peso
    return penalidad


def _son_consecutivos(b1, b2) -> bool:
    """True si b1 termina cuando b2 comienza (o viceversa), en el mismo día."""
    if b1.dia != b2.dia:
        return False
    return b1.hora_fin == b2.hora_inicio or b2.hora_fin == b1.hora_inicio


# ---------------------------------------------------------------------------
# Operadores genéticos
# ---------------------------------------------------------------------------

def _mutar(
    individual: list[int],
    dominios: dict[int, list[int]],
    vecinos: dict[int, set[int]],
    conflictos_bloques: dict[int, set[int]],
) -> tuple:
    """Mutación constraint-preserving: cambia un bloque por uno válido.

    Elige una sección aleatoria y busca un bloque alternativo en su dominio
    que no viole ninguna restricción dura (RD1, RD3, RD4). Si no encuentra
    ninguno, deja el individuo sin cambios.
    """
    n = len(individual)
    i = random.randrange(n)
    current = individual[i]

    # Bloques prohibidos para la sección i dado el estado actual
    forbidden: set[int] = set()
    for j in vecinos.get(i, set()):
        bj = individual[j]
        forbidden.add(bj)
        forbidden |= conflictos_bloques.get(bj, set())

    candidatos = [b for b in dominios[i] if b not in forbidden and b != current]
    if candidatos:
        individual[i] = random.choice(candidatos)

    return (individual,)


def _cruzar(
    ind1: list[int],
    ind2: list[int],
    dominios: dict[int, list[int]],
    vecinos: dict[int, set[int]],
    conflictos_bloques: dict[int, set[int]],
) -> tuple:
    """Cruce de un punto con reparación de restricciones duras.

    Genera dos hijos por cruce de un punto; cualquier sección cuya asignación
    viole una restricción dura con otra sección del mismo hijo se revierte al
    bloque del padre original.
    """
    n = len(ind1)
    punto = random.randint(1, n - 1)

    hijo1 = creator.Individual(ind1[:punto] + ind2[punto:])
    hijo2 = creator.Individual(ind2[:punto] + ind1[punto:])

    _reparar(hijo1, ind1, dominios, vecinos, conflictos_bloques)
    _reparar(hijo2, ind2, dominios, vecinos, conflictos_bloques)

    del hijo1.fitness.values
    del hijo2.fitness.values
    return hijo1, hijo2


def _reparar(
    hijo: list[int],
    padre: list[int],
    dominios: dict[int, list[int]],
    vecinos: dict[int, set[int]],
    conflictos_bloques: dict[int, set[int]],
) -> None:
    """Repara violaciones de restricciones duras en el hijo.

    Para cada sección cuya asignación conflictúa con algún vecino, intenta
    encontrar un bloque válido; si no lo hay, revierte al bloque del padre.
    """
    n = len(hijo)
    for i in range(n):
        forbidden: set[int] = set()
        for j in vecinos.get(i, set()):
            bj = hijo[j]
            forbidden.add(bj)
            forbidden |= conflictos_bloques.get(bj, set())

        if hijo[i] not in forbidden:
            continue  # sin conflicto

        # Intentar bloque válido del dominio
        candidatos = [b for b in dominios[i] if b not in forbidden]
        if candidatos:
            hijo[i] = random.choice(candidatos)
        else:
            hijo[i] = padre[i]  # revertir al padre


# ---------------------------------------------------------------------------
# Inicialización de DEAP
# ---------------------------------------------------------------------------

def _init_deap() -> None:
    """Registra FitnessMin e Individual en el creator (idempotente)."""
    if not hasattr(creator, "FitnessMin"):
        creator.create("FitnessMin", base.Fitness, weights=(-1.0,))
    if not hasattr(creator, "Individual"):
        creator.create("Individual", list, fitness=creator.FitnessMin)


def _crear_toolbox(
    ind_inicial: list[int],
    secciones: list,
    bloques: list,
    pesos: dict,
    dominios: dict,
    vecinos: dict,
    conflictos_bloques: dict,
    por_nrc: dict,
    idx_labt_prog: list,
) -> base.Toolbox:
    toolbox = base.Toolbox()

    toolbox.register(
        "evaluate",
        _evaluar,
        secciones=secciones,
        bloques=bloques,
        pesos=pesos,
        por_nrc=por_nrc,
        idx_labt_prog=idx_labt_prog,
    )
    toolbox.register(
        "mutate",
        _mutar,
        dominios=dominios,
        vecinos=vecinos,
        conflictos_bloques=conflictos_bloques,
    )
    toolbox.register(
        "mate",
        _cruzar,
        dominios=dominios,
        vecinos=vecinos,
        conflictos_bloques=conflictos_bloques,
    )
    toolbox.register("select", tools.selTournament, tournsize=TORNEO_K)
    toolbox.register("clone", lambda x: creator.Individual(x))

    return toolbox


def _crear_poblacion(
    toolbox: base.Toolbox,
    ind_inicial: list[int],
    tamano: int,
) -> list:
    """Crea la población inicial: solución CP-SAT + variantes mutadas."""
    poblacion = [creator.Individual(ind_inicial)]

    # Resto: variantes del individuo inicial con mutaciones para diversidad
    for _ in range(tamano - 1):
        variante = creator.Individual(ind_inicial)
        n_mutaciones = random.randint(1, max(1, len(ind_inicial) // 20))
        for _ in range(n_mutaciones):
            toolbox.mutate(variante)
        del variante.fitness.values  # marcar como no evaluado (puede lanzar si no estaba seteado — OK)
        poblacion.append(variante)

    return poblacion


# ---------------------------------------------------------------------------
# Bucle principal del GA
# ---------------------------------------------------------------------------

def _ejecutar_ga(
    poblacion: list,
    toolbox: base.Toolbox,
    n_gen_max: int,
    parada_sin_mejora: int,
) -> tuple[list, int, float]:
    """Ejecuta el bucle generacional del GA con parada anticipada.

    Returns:
        (poblacion_final, generacion_final, mejor_fitness)
    """
    mejor_fitness = min(ind.fitness.values[0] for ind in poblacion)
    gen_sin_mejora = 0
    generacion_final = 0
    intervalo_reporte = max(1, n_gen_max // 10)

    for gen in range(n_gen_max):
        generacion_final = gen

        # Selección (torneo)
        offspring = toolbox.select(poblacion, len(poblacion))
        offspring = [toolbox.clone(ind) for ind in offspring]

        # Cruce
        for i in range(0, len(offspring) - 1, 2):
            if random.random() < P_CRUCE:
                offspring[i], offspring[i + 1] = toolbox.mate(offspring[i], offspring[i + 1])

        # Mutación
        for ind in offspring:
            if random.random() < P_MUTACION:
                toolbox.mutate(ind)
                del ind.fitness.values

        # Evaluación de los modificados
        for ind in offspring:
            if not ind.fitness.valid:
                ind.fitness.values = toolbox.evaluate(ind)

        # Reemplazo μ+λ (élite): tomar los mejores de población + hijos
        combinados = poblacion + offspring
        poblacion[:] = tools.selBest(combinados, len(poblacion))

        # Control de parada anticipada
        mejor_actual = min(ind.fitness.values[0] for ind in poblacion)
        if mejor_actual < mejor_fitness:
            mejor_fitness = mejor_actual
            gen_sin_mejora = 0
        else:
            gen_sin_mejora += 1

        if gen % intervalo_reporte == 0:
            print(f"    Gen {gen:4d}: mejor={mejor_fitness:.0f}")

        if gen_sin_mejora >= parada_sin_mejora:
            print(f"    Parada anticipada en gen {gen} ({parada_sin_mejora} gen sin mejora)")
            break

    return poblacion, generacion_final, mejor_fitness


# ---------------------------------------------------------------------------
# Reporte de violaciones blandas
# ---------------------------------------------------------------------------

def _imprimir_reporte_soft(
    mejor: list[int],
    secciones: list,
    bloques: list,
    pesos: dict,
    por_nrc: dict,
    idx_labt_prog: list,
) -> None:
    """Imprime un resumen de las violaciones de restricciones blandas."""
    print("\n  Resumen de restricciones blandas:")

    if pesos.get("RB1", 0) > 0 and idx_labt_prog:
        p = _penalidad_rb1(mejor, bloques, idx_labt_prog, 1)
        print(f"    RB1 (labs progr. consecutivos): {int(p)} pares no consecutivos")

    rb2 = sum(
        1 for i, s in enumerate(secciones)
        if s.profesor and s.profesor.tipo == TipoProfesor.JORNADA
        and _hora_a_min(bloques[mejor[i]].hora_inicio) in _EXTREMOS_MIN
    )
    print(f"    RB2 (prof jornada en extremos):   {rb2} secciones")

    rb3 = rb4 = 0
    for idxs in por_nrc.values():
        dias = [bloques[mejor[i]].dia for i in idxs]
        tipos = [secciones[i].tipo_reunion for i in idxs]
        for a in range(len(dias)):
            for b in range(a + 1, len(dias)):
                if dias[a] == dias[b]:
                    rb3 += 1
        conteo: dict = defaultdict(int)
        for tipo, dia in zip(tipos, dias):
            conteo[(tipo, dia)] += 1
        for cnt in conteo.values():
            if cnt > 1:
                rb4 += cnt - 1
    print(f"    RB3 (misma sección mismo día):    {rb3} pares")
    print(f"    RB4 (mismo tipo mismo día):       {rb4} excesos")
