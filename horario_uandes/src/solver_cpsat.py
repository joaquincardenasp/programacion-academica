"""
solver_cpsat.py — Módulo 2: Solver CP-SAT.

Genera un horario factible asignando un BloqueHorario a cada Seccion
respetando todas las restricciones duras de la v1 (RD1-RD8).

Restricciones implementadas:
    RD1: Sin topes entre secciones de distintos cursos del mismo semestre Plan Común.
    RD2: Disponibilidad declarada del profesor (filtrado de dominio).
    RD3: Un profesor no puede estar en dos secciones al mismo tiempo.
    RD4: Dos secciones no pueden coincidir en la misma sala especial.
    RD5: Solo bloques estándar (garantizado por generar_bloques_horarios() en parser).
    RD6: Cursos de distribución "3" solo en bloques de 3h (filtrado de dominio).
    RD7: Ayudantías solo en bloques con hora_inicio >= 12:30 (filtrado de dominio).
    RD8: Profesor de lab y de cátedra de otra sección no pueden coincidir
         (cubierto dentro de RD3 al agrupar todos los roles por profesor).
    RD3/RD8 requieren IDs únicos por sección. El parser genera IDs como
    {LLAVE}_{SECCIONES}_{TIPO} para garantizar unicidad incluso cuando el
    campo LLAVE del maestro no incluye el número de sección.

Fuera de scope v1:
    RD9: Cursos minor en horario protegido (sin datos del cliente aún).
    Distribución "2+1": secciones omitidas, se suman en v2.

Uso:
    from solver_cpsat import resolver_cpsat
    datos = resolver_cpsat(datos)
"""

from collections import defaultdict
from ortools.sat.python import cp_model

from models import BloqueHorario, DatosProblema, Seccion, TipoReunion

# Tiempo máximo de búsqueda antes de retornar la mejor solución encontrada
TIEMPO_LIMITE_SEGUNDOS = 120.0

# 12:30 en minutos desde medianoche — límite inferior para ayudantías (RD7)
_MINUTOS_12_30 = 12 * 60 + 30

# Si aplicar disponibilidad del profesor (RD2) deja menos de este número de
# bloques, se ignora la disponibilidad para esa sección. Evita infactibilidad
# cuando los datos de disponibilidad son muy restrictivos o incorrectos.
_MIN_BLOQUES_DOMINIO = 3


# =============================================================================
# PUNTO DE ENTRADA PÚBLICO
# =============================================================================

def resolver_cpsat(datos: DatosProblema) -> DatosProblema:
    """Módulo 2: asigna un bloque horario a cada sección usando CP-SAT.

    Modifica datos.secciones in-place, rellenando bloque_asignado en cada
    sección programable. Las secciones con distribución "2+1" se omiten en v1
    y quedan con bloque_asignado = None.

    Args:
        datos: DatosProblema con secciones y bloques cargados por el parser.

    Returns:
        El mismo objeto datos con bloque_asignado rellenado donde fue posible.
    """
    print("=" * 60)
    print("MÓDULO 2: Solver CP-SAT")
    print("=" * 60)

    bloques = datos.bloques_disponibles

    # --- Separar secciones programables de las omitidas (2+1) ---
    secciones_prog, secciones_omitidas = _separar_secciones(datos.secciones)
    if secciones_omitidas:
        print(f"\n  [v1] {len(secciones_omitidas)} secciones con distribución '2+1' omitidas.")
    print(f"  Secciones a programar: {len(secciones_prog)}")

    # --- Calcular dominio válido para cada sección (RD2, RD6, RD7) ---
    print("\n[1/4] Calculando dominios de variables...")
    dominios = {s.id: _calcular_dominio(s, bloques) for s in secciones_prog}

    # --- Pre-calcular solapamientos entre bloques ---
    conflictos_bloques = _precalcular_conflictos(bloques)

    # --- Detectar y relajar RD2 para profesores cuyo grupo sería infactible ---
    dominios, profs_relajados = _ajustar_dominios_por_grupo_profesor(
        secciones_prog, dominios, bloques, conflictos_bloques
    )

    # Detectar secciones donde RD2 fue relajada (disponibilidad ignorada)
    rd2_relajadas = _detectar_rd2_relajadas(secciones_prog, bloques, dominios)
    if rd2_relajadas:
        print(f"  AVISO RD2: {len(rd2_relajadas)} secciones ignoraron disponibilidad del "
              f"profesor (dominio muy restrictivo para satisfacer RD3).")
        for s in rd2_relajadas[:5]:
            print(f"    - {s.id}  [{s.curso.titulo} | {s.tipo_reunion.value}]")
        if len(rd2_relajadas) > 5:
            print(f"    ... y {len(rd2_relajadas) - 5} más.")
    if profs_relajados:
        print(f"  AVISO RD2-grupo: {len(profs_relajados)} profesores con dominio expandido "
              f"(conflicto RD3 grupal, disponibilidad ignorada): {profs_relajados[:5]}")

    sin_dominio = [s for s in secciones_prog if not dominios[s.id]]
    if sin_dominio:
        print(f"  ADVERTENCIA: {len(sin_dominio)} secciones sin bloques válidos "
              f"(el problema puede ser infactible):")
        for s in sin_dominio[:10]:
            print(f"    - {s.id}  [{s.curso.titulo} | {s.tipo_reunion.value} | "
                  f"dist='{s.curso.distribucion}']")
        if len(sin_dominio) > 10:
            print(f"    ... y {len(sin_dominio) - 10} más.")

    # --- Construir modelo CP-SAT ---
    print("\n[2/4] Construyendo modelo CP-SAT...")
    model = cp_model.CpModel()
    vars_asig = _crear_variables(model, secciones_prog, dominios, len(bloques))

    n_rd1, omit_rd1 = _add_rd1(model, vars_asig, secciones_prog, dominios, conflictos_bloques)
    n_rd3, omit_rd3 = _add_rd3_rd8(model, vars_asig, secciones_prog, dominios, conflictos_bloques)
    n_rd4, omit_rd4 = _add_rd4(model, vars_asig, secciones_prog, dominios, conflictos_bloques)

    print(f"  RD1 topes plan común:    {n_rd1} pares restringidos")
    print(f"  RD3/RD8 unicidad prof:   {n_rd3} pares restringidos")
    print(f"  RD4 unicidad sala:       {n_rd4} pares restringidos")
    print(f"  RD2/RD6/RD7: aplicados vía filtrado de dominio")

    total_omitidos = len(omit_rd1) + len(omit_rd3) + len(omit_rd4)
    if total_omitidos:
        print(f"  VIOLACIONES INEVITABLES: {total_omitidos} pares omitidos "
              f"(RD1:{len(omit_rd1)} RD3:{len(omit_rd3)} RD4:{len(omit_rd4)}) → revisión manual")
        for s1, s2 in (omit_rd1 + omit_rd3 + omit_rd4)[:8]:
            print(f"    - {s1.id} / {s2.id}")

    # --- Resolver ---
    print(f"\n[3/4] Resolviendo (límite {TIEMPO_LIMITE_SEGUNDOS:.0f}s)...")
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = TIEMPO_LIMITE_SEGUNDOS
    status = solver.Solve(model)

    # --- Procesar resultado ---
    print(f"\n[4/4] Resultado: {solver.StatusName(status)}  "
          f"(tiempo: {solver.WallTime():.2f}s)")

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for s in secciones_prog:
            s.bloque_asignado = bloques[solver.Value(vars_asig[s.id])]
        _imprimir_resumen(datos.secciones)
    else:
        print("  ERROR: no se encontró solución factible.")
        print("  Sugerencia: revisar disponibilidad de profesores y "
              "número de secciones por semestre de Plan Común.")

    return datos


# =============================================================================
# SEPARACIÓN Y DOMINIO DE VARIABLES
# =============================================================================

def _separar_secciones(secciones: list) -> tuple[list, list]:
    """Divide secciones en programables y omitidas (distribución 2+1)."""
    prog, omitidas = [], []
    for s in secciones:
        (omitidas if _es_2_mas_1(s) else prog).append(s)
    return prog, omitidas


def _es_2_mas_1(seccion: Seccion) -> bool:
    """True si la sección tiene distribución '2+1' o '2-1' (omitida en v1)."""
    dist = seccion.curso.distribucion.strip()
    return "2+1" in dist or "2-1" in dist


def _hora_a_min(hora: str) -> int:
    """Convierte 'H:MM' o 'HH:MM' a minutos desde medianoche."""
    h, m = hora.split(":")
    return int(h) * 60 + int(m)


def _calcular_dominio_par(seccion: Seccion, bloques: list) -> tuple[list, list]:
    """Calcula dominios con y sin RD2 para una sección.

    Returns:
        (dominio_sin_rd2, dominio_con_rd2): ambos como listas de índices.
        dominio_con_rd2 puede ser vacío si la disponibilidad no cubre ningún bloque.
    """
    dist = seccion.curso.distribucion.strip()
    # distribucion ("3", "3-juntas") describes only the CLASS schedule.
    # Labs and ayudantías are always 2h blocks regardless of course distribution.
    es_ayud = seccion.tipo_reunion == TipoReunion.AYUDANTIA
    es_lab = seccion.tipo_reunion == TipoReunion.LABORATORIO
    es_3h = dist in {"3", "3-juntas"} and not es_ayud and not es_lab

    dominio_sin_rd2 = []
    dominio_con_rd2 = []

    for i, bloque in enumerate(bloques):
        if es_3h and bloque.duracion_horas != 3:
            continue
        if not es_3h and bloque.duracion_horas == 3:
            continue
        if es_ayud and _hora_a_min(bloque.hora_inicio) < _MINUTOS_12_30:
            continue
        dominio_sin_rd2.append(i)
        if not es_ayud and seccion.profesor and not seccion.profesor.esta_disponible(bloque):
            continue
        dominio_con_rd2.append(i)

    return dominio_sin_rd2, dominio_con_rd2


def _calcular_dominio(seccion: Seccion, bloques: list) -> list:
    """Índices de bloques válidos para una sección (aplica RD2, RD6, RD7).

    RD6: si distribución es "3" o "3-juntas", solo bloques de 3h (solo para CLAS).
          LABT y AYUD siempre usan bloques de 2h.
    RD7: ayudantías solo en bloques que inician a las 12:30 o después.
    RD2: solo bloques en los que el profesor declaró disponibilidad.
         No aplica a AYUD. Si aplicar RD2 deja menos de _MIN_BLOQUES_DOMINIO
         opciones, se relaja a dominio completo.

    Returns:
        Lista de índices válidos. Nunca vacía si existe al menos un bloque
        del tipo correcto (la relaxación de RD2 garantiza esto).
    """
    dominio_sin_rd2, dominio_con_rd2 = _calcular_dominio_par(seccion, bloques)
    if dominio_sin_rd2 and len(dominio_con_rd2) < _MIN_BLOQUES_DOMINIO:
        return dominio_sin_rd2
    return dominio_con_rd2


def _ajustar_dominios_por_grupo_profesor(
    secciones: list,
    dominios: dict,
    bloques: list,
    conflictos: dict,
) -> tuple[dict, list]:
    """Relaja RD2 para profesores cuya disponibilidad hace infactible RD3.

    Para cada grupo de secciones de un mismo profesor, verifica si existe
    una asignación no conflictiva dentro de sus dominios actuales. Si no
    la hay (infactible), expande todos sus dominios al conjunto sin RD2.

    Returns:
        (dominios_ajustados, lista_de_pids_relajados)
    """
    por_prof: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.profesor:
            por_prof[s.profesor.id].append(s)
        if s.profesor_lab and (not s.profesor or s.profesor_lab.id != s.profesor.id):
            por_prof[s.profesor_lab.id].append(s)

    relajados = []
    dominios_ajust = dict(dominios)

    for pid, grupo in por_prof.items():
        seen: set[str] = set()
        grupo_d = [s for s in grupo if s.id not in seen and not seen.add(s.id)]
        if len(grupo_d) < 2:
            continue

        # Mini-modelo CP-SAT solo con este grupo y sus dominios actuales
        m = cp_model.CpModel()
        va: dict[str, cp_model.IntVar] = {}
        for s in grupo_d:
            d = dominios_ajust.get(s.id, [])
            if d:
                va[s.id] = m.NewIntVarFromDomain(cp_model.Domain.FromValues(d), s.id)
        for i in range(len(grupo_d)):
            for j in range(i + 1, len(grupo_d)):
                s1, s2 = grupo_d[i], grupo_d[j]
                if s1.id not in va or s2.id not in va or s1.id == s2.id:
                    continue
                d1, d2 = dominios_ajust[s1.id], dominios_ajust[s2.id]
                forbidden = _pares_prohibidos(d1, d2, conflictos)
                if forbidden and len(forbidden) < len(d1) * len(d2):
                    m.AddForbiddenAssignments([va[s1.id], va[s2.id]], forbidden)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 5.0
        status = solver.Solve(m)
        if status != cp_model.INFEASIBLE:
            continue

        # Grupo infactible bajo RD2: expandir a dominio sin restricción
        relajados.append(pid)
        for s in grupo_d:
            dom_sin, _ = _calcular_dominio_par(s, bloques)
            if dom_sin:
                dominios_ajust[s.id] = dom_sin

    return dominios_ajust, relajados


def _detectar_conflictos_profesor(secciones: list) -> list:
    """Retorna lista de profesores que tienen más de una sección asignada.

    Se usa para reportar conflictos de horario potenciales (RD3) ya que
    esta restricción se omite en v1 por problemas con IDs duplicados en el maestro.
    """
    por_prof = defaultdict(set)
    for s in secciones:
        if s.profesor:
            por_prof[s.profesor.id].add(s.id)
        if s.profesor_lab:
            por_prof[s.profesor_lab.id].add(s.id)
    return [(pid, sids) for pid, sids in por_prof.items() if len(sids) > 1]


def _detectar_rd2_relajadas(secciones: list, bloques: list, dominios: dict) -> list:
    """Retorna secciones donde la disponibilidad del profesor fue ignorada.

    Compara el dominio final asignado vs. el dominio restrictivo con RD2.
    Si el dominio final es mayor (RD2 fue relajada), la sección se reporta.
    """
    relajadas = []
    for s in secciones:
        if s.tipo_reunion == TipoReunion.AYUDANTIA:
            continue
        if not s.profesor or not s.profesor.disponibilidad:
            continue
        _, con_rd2 = _calcular_dominio_par(s, bloques)
        final = dominios.get(s.id, [])
        # Si el dominio final es más grande que el con RD2, se relajó
        if set(final) != set(con_rd2):
            relajadas.append(s)
    return relajadas


# =============================================================================
# PRE-CÁLCULO DE CONFLICTOS ENTRE BLOQUES
# =============================================================================

def _precalcular_conflictos(bloques: list) -> dict:
    """Construye un mapa índice → conjunto de índices que se solapan con él.

    Dos bloques se solapan si son del mismo día y comparten al menos un
    sub-bloque de 50 minutos. El índice propio NO se incluye en el conjunto
    (el caso mismo-bloque se maneja en _pares_prohibidos).
    """
    n = len(bloques)
    mapa: dict[int, set] = {i: set() for i in range(n)}
    for i in range(n):
        for j in range(i + 1, n):
            if _solapan(bloques[i], bloques[j]):
                mapa[i].add(j)
                mapa[j].add(i)
    return mapa


def _solapan(b1: BloqueHorario, b2: BloqueHorario) -> bool:
    """True si b1 y b2 comparten día y al menos un sub-bloque de 50 min."""
    return b1.dia == b2.dia and bool(set(b1.sub_bloques) & set(b2.sub_bloques))


def _pares_prohibidos(dom1: list, dom2: list, conflictos: dict) -> list:
    """Pares (i, j) con i ∈ dom1, j ∈ dom2 cuyas asignaciones están prohibidas.

    Un par está prohibido si bloques[i] y bloques[j] se solapan en tiempo,
    incluyendo el caso i == j (mismo bloque asignado a dos secciones).
    """
    dom2_set = set(dom2)
    pares = []
    for i in dom1:
        conflictivos_en_dom2 = (conflictos.get(i, set()) | {i}) & dom2_set
        for j in conflictivos_en_dom2:
            pares.append((i, j))
    return pares


# =============================================================================
# CREACIÓN DE VARIABLES CP-SAT
# =============================================================================

def _crear_variables(
    model: cp_model.CpModel,
    secciones: list,
    dominios: dict,
    n_bloques: int,
) -> dict:
    """Crea una variable entera CP-SAT por sección con su dominio filtrado."""
    vars_asig = {}
    for s in secciones:
        d = dominios[s.id]
        if d:
            vars_asig[s.id] = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(d), s.id
            )
        else:
            # Dominio vacío: variable ficticia que hace el modelo infactible
            # para que el solver reporte claramente qué sección no tiene solución.
            var = model.NewIntVar(0, n_bloques - 1, s.id)
            model.Add(var < 0)  # Restricción siempre falsa → INFEASIBLE
            vars_asig[s.id] = var
    return vars_asig


# =============================================================================
# RESTRICCIONES DURAS
# =============================================================================

def _add_restriccion_pares(
    model: cp_model.CpModel,
    vars_asig: dict,
    pares_secciones: list[tuple],
    dominios: dict,
    conflictos: dict,
) -> tuple[int, list]:
    """Agrega AddForbiddenAssignments para cada par de secciones incompatibles.

    Si un par no tiene NINGUNA asignación válida no conflictiva (todos los
    pares del producto cartesiano de dominios están prohibidos), se salta el
    par y se registra como violación inevitable para revisión manual.

    Args:
        pares_secciones: Lista de tuplas (Seccion, Seccion) que no pueden solaparse.

    Returns:
        Tupla (n_restricciones_agregadas, lista_de_pares_omitidos).
    """
    n = 0
    omitidos = []
    for s1, s2 in pares_secciones:
        if s1.id not in vars_asig or s2.id not in vars_asig:
            continue
        # IDs duplicados en el maestro (varios profesores mismo LLAVE):
        # evitar agregar var != var, que hace el modelo trivialmente infactible.
        if s1.id == s2.id:
            continue
        d1, d2 = dominios[s1.id], dominios[s2.id]
        forbidden = _pares_prohibidos(d1, d2, conflictos)
        if not forbidden:
            continue
        # Si todos los pares posibles están prohibidos, no hay solución para este par.
        # Saltarlo evita infactibilidad; se registra para revisión manual.
        if len(forbidden) == len(d1) * len(d2):
            omitidos.append((s1, s2))
            continue
        model.AddForbiddenAssignments(
            [vars_asig[s1.id], vars_asig[s2.id]], forbidden
        )
        n += 1
    return n, omitidos


def _es_factible_rd1_rd3(grupo: list, dominios: dict, conflictos: dict, por_profesor: dict) -> bool:
    """Verifica si el grupo (carrera+sem) es factible bajo RD1 intra-grupo + RD3 local.

    Se usa para detectar cuando la combinación de RD1 y RD3 hace infactible
    un grupo completo (ej: ICI sem 8 con 4 cursos 3h y 2 profesores con 2 secciones c/u).

    Returns:
        True si es factible, False si mini-CP-SAT detecta infactibilidad.
    """
    ids_en_grupo = {s.id for s in grupo}

    m = cp_model.CpModel()
    va: dict[str, cp_model.IntVar] = {}
    for s in grupo:
        d = dominios.get(s.id, [])
        if d:
            va[s.id] = m.NewIntVarFromDomain(cp_model.Domain.FromValues(d), s.id)

    # RD1 intra-grupo: distintos cursos no solapan
    for i in range(len(grupo)):
        for j in range(i + 1, len(grupo)):
            s1, s2 = grupo[i], grupo[j]
            if s1.curso.codigo == s2.curso.codigo:
                continue
            if s1.id not in va or s2.id not in va:
                continue
            d1, d2 = dominios[s1.id], dominios[s2.id]
            forbidden = _pares_prohibidos(d1, d2, conflictos)
            if forbidden and len(forbidden) < len(d1) * len(d2):
                m.AddForbiddenAssignments([va[s1.id], va[s2.id]], forbidden)

    # RD3 local: profesores con múltiples secciones dentro del grupo
    for secs_prof in por_profesor.values():
        en_grupo = [s for s in secs_prof if s.id in ids_en_grupo and s.id in va]
        vistos: set[str] = set()
        en_grupo_d = [s for s in en_grupo if s.id not in vistos and not vistos.add(s.id)]
        if len(en_grupo_d) < 2:
            continue
        for i in range(len(en_grupo_d)):
            for j in range(i + 1, len(en_grupo_d)):
                s1, s2 = en_grupo_d[i], en_grupo_d[j]
                d1, d2 = dominios[s1.id], dominios[s2.id]
                forbidden = _pares_prohibidos(d1, d2, conflictos)
                if forbidden and len(forbidden) < len(d1) * len(d2):
                    m.AddForbiddenAssignments([va[s1.id], va[s2.id]], forbidden)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 5.0
    status = solver.Solve(m)
    return status != cp_model.INFEASIBLE


def _add_rd1(model, vars_asig, secciones, dominios, conflictos) -> tuple[int, list]:
    """RD1: Secciones de distintos cursos del mismo semestre de la misma carrera no solapan.

    Aplica independientemente por cada carrera [Plan Común, ICI, IOC, ICE, ICC, ICA].
    Un curso de ICI sem 5 puede coincidir con un curso de ICC sem 5 (carreras distintas).
    La restricción es solo DENTRO de cada carrera.

    Si un grupo (carrera, sem) es infactible bajo RD1+RD3 combinados (ej: ICI sem 8
    tiene 4 cursos 3h y profesores que dictan 2 secciones del mismo curso, lo que
    requiere más slots 3h independientes de los disponibles), se omiten sus pares RD1
    para preservar la factibilidad global. Los pares omitidos se reportan como
    violaciones inevitables para revisión manual.

    Deduplicación: si un par (A, B) aparece en un grupo infactible y luego en uno
    factible, se "rescata" y agrega al modelo (la restricción es válida desde el
    grupo factible).
    """
    CARRERAS = ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA"]

    por_carrera_sem: dict[tuple, list] = defaultdict(list)
    for s in secciones:
        for carrera in CARRERAS:
            sem = s.curso.semestres.get(carrera)
            if sem:
                por_carrera_sem[(carrera, int(sem))].append(s)

    # Pre-computar grupos de profesor para el check de factibilidad
    por_profesor: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.profesor:
            por_profesor[s.profesor.id].append(s)
        if s.profesor_lab and (not s.profesor or s.profesor_lab.id != s.profesor.id):
            por_profesor[s.profesor_lab.id].append(s)

    pares_set: set[frozenset] = set()
    omit_dict: dict[frozenset, tuple] = {}  # pares de grupos infactibles (rescatables)
    pares: list[tuple] = []
    conteo: dict[str, int] = defaultdict(int)
    grupos_skip: list[str] = []

    for (carrera, sem), grupo in sorted(por_carrera_sem.items()):
        solo_clas = sem >= 5
        grupo_efectivo = [
            s for s in grupo
            if not solo_clas or s.tipo_reunion == TipoReunion.CLASE
        ]

        # Construir pares locales para este grupo
        pares_locales: list[tuple] = []
        for i in range(len(grupo_efectivo)):
            for j in range(i + 1, len(grupo_efectivo)):
                s1, s2 = grupo_efectivo[i], grupo_efectivo[j]
                if s1.curso.codigo == s2.curso.codigo:
                    continue
                if s1.curso.es_electivo and s2.curso.es_electivo:
                    continue
                clave = frozenset([s1.id, s2.id])
                pares_locales.append((s1, s2, clave))

        if not pares_locales:
            continue

        # Condición necesaria para infactibilidad combinada RD1+RD3:
        # algún profesor tiene >1 sección en este grupo.
        ids_en_grupo = {s.id for s in grupo_efectivo}
        prof_multiples = any(
            sum(1 for s in secs if s.id in ids_en_grupo) > 1
            for secs in por_profesor.values()
        )

        if prof_multiples and not _es_factible_rd1_rd3(
            grupo_efectivo, dominios, conflictos, por_profesor
        ):
            grupos_skip.append(f"{carrera} sem {sem}")
            for s1, s2, clave in pares_locales:
                if clave not in pares_set and clave not in omit_dict:
                    omit_dict[clave] = (s1, s2)
            continue

        # Grupo factible: agregar pares con deduplicación
        for s1, s2, clave in pares_locales:
            if clave not in pares_set:
                pares_set.add(clave)
                omit_dict.pop(clave, None)  # rescatar si fue marcado como omitido
                pares.append((s1, s2))
                conteo[carrera] += 1

    if grupos_skip:
        print(f"    RD1 grupos infactibles (RD1+RD3): {grupos_skip} → pares omitidos")

    detalle = "  ".join(f"{c}:{n}" for c, n in sorted(conteo.items()))
    print(f"    RD1 desglose: {detalle}")

    omitidos_grupos = list(omit_dict.values())
    n, omit_pares = _add_restriccion_pares(model, vars_asig, pares, dominios, conflictos)
    return n, omitidos_grupos + omit_pares


def _add_rd3_rd8(model, vars_asig, secciones, dominios, conflictos) -> tuple[int, list]:
    """RD3/RD8: Ningún profesor puede dictar dos secciones simultáneas.

    Agrupa todas las secciones en las que un profesor participa (como profesor
    principal o como profesor de laboratorio) y agrega restricciones de no
    solapamiento entre cada par. Esto cubre RD8 automáticamente, ya que el
    cruce de roles (principal de una sección ↔ lab de otra) queda incluido.
    """
    por_profesor: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.profesor:
            por_profesor[s.profesor.id].append(s)
        if s.profesor_lab and (not s.profesor or s.profesor_lab.id != s.profesor.id):
            por_profesor[s.profesor_lab.id].append(s)

    pares = []
    for grupo in por_profesor.values():
        # Deduplicar por si una sección aparece dos veces en el grupo
        vistos: set[str] = set()
        grupo_dedup = []
        for s in grupo:
            if s.id not in vistos:
                vistos.add(s.id)
                grupo_dedup.append(s)

        for i in range(len(grupo_dedup)):
            for j in range(i + 1, len(grupo_dedup)):
                pares.append((grupo_dedup[i], grupo_dedup[j]))

    return _add_restriccion_pares(model, vars_asig, pares, dominios, conflictos)


def _add_rd4(model, vars_asig, secciones, dominios, conflictos) -> tuple[int, list]:
    """RD4: Dos secciones que requieren la misma sala especial no pueden coincidir."""
    por_sala: dict[str, list] = defaultdict(list)
    for s in secciones:
        if s.sala_especial:
            por_sala[s.sala_especial.nombre].append(s)

    pares = []
    for grupo in por_sala.values():
        for i in range(len(grupo)):
            for j in range(i + 1, len(grupo)):
                pares.append((grupo[i], grupo[j]))

    return _add_restriccion_pares(model, vars_asig, pares, dominios, conflictos)


# =============================================================================
# DIAGNÓSTICO
# =============================================================================

def _imprimir_resumen(secciones: list) -> None:
    """Imprime conteo de secciones asignadas vs. no asignadas."""
    asignadas = sum(1 for s in secciones if s.bloque_asignado)
    omitidas_2mas1 = sum(1 for s in secciones if _es_2_mas_1(s))
    total = len(secciones)

    print(f"\n  Asignadas:         {asignadas}")
    print(f"  Omitidas (2+1):    {omitidas_2mas1}")
    print(f"  Total secciones:   {total}")
