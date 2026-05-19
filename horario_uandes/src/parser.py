"""
parser.py — Módulo 1: Parser e integración de datos.

Lee los archivos Excel del proceso actual (Maestro, Catálogo, Salas
Especiales) y los transforma en la estructura de datos estandarizada
definida en models.py.

Flujo del parser:
1. Lee la hoja MAESTRO y extrae secciones con sus datos base.
2. Lee la hoja CATALOGO para completar horas semanales y semestres.
3. Lee SALAS_ESPECIALES para mapear qué cursos requieren qué sala.
4. Lee PROFESORES y RESPUESTAS para construir disponibilidad.
5. Genera los bloques horarios válidos.
6. Ensambla todo en un DatosProblema.

Uso:
    from parser import cargar_datos
    datos = cargar_datos("ruta/Maestro.xlsx", "ruta/Salas.xlsx")
    print(datos.resumen())
"""

import pandas as pd
import numpy as np
from typing import Optional
from models import (
    Curso, Seccion, Profesor, SalaEspecial, DatosProblema,
    BloqueHorario, SubBloque, TipoReunion, TipoProfesor, Dia,
    BLOQUES_2H, BLOQUES_3H, SUB_BLOQUES
)


# =============================================================================
# UTILIDADES DE PARSING
# =============================================================================

def normalizar_nombre_profesor(nombre: str) -> str:
    """Normaliza el nombre del profesor para usarlo como ID.
    
    El maestro tiene nombres en dos formatos:
    - "APELLIDO/SEGUNDO NOMBRE" (ej: "ABELL/MENA JOSE ANTONIO")
    - "Nombre Apellido" (ej: "Alexander Dulovits")
    
    Esta función unifica ambos a un formato consistente para
    poder cruzar datos entre hojas.
    
    Args:
        nombre: Nombre tal como aparece en el Excel.
    
    Returns:
        Nombre normalizado en minúsculas, sin espacios extra.
    """
    if pd.isna(nombre) or not str(nombre).strip():
        return ""
    nombre = str(nombre).strip()
    # Formato BANNER: "APELLIDO/SEGUNDO NOMBRE"
    if "/" in nombre:
        partes = nombre.split("/")
        apellido = partes[0].strip()
        resto = partes[1].strip() if len(partes) > 1 else ""
        # Tomar el primer nombre del resto
        nombres = resto.split()
        primer_nombre = nombres[0] if nombres else ""
        nombre = f"{primer_nombre} {apellido}".strip()
    return nombre.lower().strip()


def parsear_disponibilidad_str(disponibilidad_str: str, dia: Dia) -> set:
    """Parsea un string de disponibilidad en un conjunto de SubBloques.
    
    La disponibilidad en el maestro viene como string separado por comas:
    "8:30-9:20,9:30-10:20,10:30-11:20,..."
    
    Cada elemento es un sub-bloque de 50 minutos que indica que el
    profesor ESTÁ disponible en ese horario.
    
    Args:
        disponibilidad_str: String con bloques separados por coma.
        dia: Día de la semana al que corresponde.
    
    Returns:
        Conjunto de SubBloques representando la disponibilidad.
    """
    if pd.isna(disponibilidad_str) or not str(disponibilidad_str).strip():
        return set()
    
    sub_bloques = set()
    bloques = str(disponibilidad_str).split(",")
    for bloque in bloques:
        bloque = bloque.strip()
        if "-" not in bloque:
            continue
        partes = bloque.split("-")
        if len(partes) == 2:
            hora_inicio = partes[0].strip()
            hora_fin = partes[1].strip()
            sub_bloques.add(SubBloque(dia=dia, hora_inicio=hora_inicio, hora_fin=hora_fin))
    return sub_bloques


def parsear_tipo_reunion(tipo_str: str) -> Optional[TipoReunion]:
    """Convierte un string de tipo de reunión al enum.
    
    Args:
        tipo_str: String del tipo (ej: "CLAS", "AYUD", "LABT").
    
    Returns:
        TipoReunion correspondiente, o None si no es reconocido.
    """
    if pd.isna(tipo_str):
        return None
    tipo_str = str(tipo_str).strip().upper()
    mapping = {
        "CLAS": TipoReunion.CLASE,
        "AYUD": TipoReunion.AYUDANTIA,
        "LABT": TipoReunion.LABORATORIO,
        "PRBA": TipoReunion.PRUEBA,
        "EXAM": TipoReunion.EXAMEN,
    }
    return mapping.get(tipo_str, None)


def safe_int(val, default=0) -> int:
    """Convierte un valor a entero de forma segura."""
    if pd.isna(val):
        return default
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return default


def safe_str(val, default="") -> str:
    """Convierte un valor a string de forma segura."""
    if pd.isna(val):
        return default
    return str(val).strip()


# =============================================================================
# GENERACIÓN DE BLOQUES HORARIOS
# =============================================================================

def generar_bloques_horarios() -> list:
    """Genera todos los bloques horarios válidos del sistema.
    
    Combina los bloques estándar de 2h y 3h con todos los días
    de la semana, y calcula los sub-bloques que componen cada uno.
    
    Restricción dura implementada aquí: solo se generan bloques
    en horarios estándar (8:30-10:20, 10:30-12:20, etc.), nunca
    intermedios como 9:30-11:20.
    
    Returns:
        Lista de BloqueHorario con todos los bloques válidos.
    """
    bloques = []
    
    for dia in Dia:
        # Bloques de 2 horas
        for h_inicio, h_fin in BLOQUES_2H:
            subs = _calcular_sub_bloques(dia, h_inicio, h_fin)
            bloques.append(BloqueHorario(
                dia=dia, hora_inicio=h_inicio, hora_fin=h_fin,
                sub_bloques=tuple(subs)
            ))
        # Bloques de 3 horas
        for h_inicio, h_fin in BLOQUES_3H:
            subs = _calcular_sub_bloques(dia, h_inicio, h_fin)
            bloques.append(BloqueHorario(
                dia=dia, hora_inicio=h_inicio, hora_fin=h_fin,
                sub_bloques=tuple(subs)
            ))
    
    return bloques


def _calcular_sub_bloques(dia: Dia, h_inicio: str, h_fin: str) -> list:
    """Calcula qué sub-bloques de 50min están contenidos en un bloque.
    
    Compara por posición en la lista de SUB_BLOQUES para determinar
    cuáles caen dentro del rango [h_inicio, h_fin].
    
    Args:
        dia: Día del bloque.
        h_inicio: Hora de inicio del bloque.
        h_fin: Hora de fin del bloque.
    
    Returns:
        Lista de SubBloques contenidos en el rango.
    """
    resultado = []
    inicio_idx = None
    fin_idx = None
    
    for i, (sb_inicio, sb_fin) in enumerate(SUB_BLOQUES):
        if sb_inicio == h_inicio:
            inicio_idx = i
        if sb_fin == h_fin:
            fin_idx = i
    
    if inicio_idx is not None and fin_idx is not None:
        for i in range(inicio_idx, fin_idx + 1):
            sb_inicio, sb_fin = SUB_BLOQUES[i]
            resultado.append(SubBloque(dia=dia, hora_inicio=sb_inicio, hora_fin=sb_fin))
    
    return resultado


# =============================================================================
# PARSING DE SALAS ESPECIALES
# =============================================================================

def cargar_salas_especiales(ruta_salas: str) -> dict:
    """Lee el archivo de salas especiales y construye un mapeo.
    
    El archivo SALAS_ESPECIALES_ING.xlsx tiene una fila por cada
    curso que requiere sala especial, con el tipo de sala y en qué
    contexto aplica (lab, clase, prueba, etc.).
    
    Args:
        ruta_salas: Ruta al archivo SALAS_ESPECIALES_ING.xlsx.
    
    Returns:
        Diccionario {codigo_curso: SalaEspecial}.
    """
    df = pd.read_excel(ruta_salas)
    salas = {}
    
    for _, row in df.iterrows():
        codigo = safe_str(row.get("CODIGO", ""))
        sala_str = safe_str(row.get("SALA ESPECIAL", ""))
        
        if not codigo or not sala_str:
            continue
        
        # Separar nombre de sala del contexto de aplicación
        # Formato: "LABORATORIO DE X EN HORARIO DE Y"
        nombre = sala_str
        aplica_en = ""
        if " EN HORARIO DE " in sala_str:
            partes = sala_str.split(" EN HORARIO DE ")
            nombre = partes[0].strip()
            aplica_en = partes[1].strip() if len(partes) > 1 else ""
        
        salas[codigo] = SalaEspecial(nombre=nombre, aplica_en=aplica_en)
    
    return salas


# =============================================================================
# PARSING DE PROFESORES
# =============================================================================

def cargar_profesores_jornada(df_profesores: pd.DataFrame) -> dict:
    """Carga la lista de profesores de jornada completa.
    
    La hoja PROFESORES del maestro contiene exclusivamente los
    profesores de jornada. Esto es relevante para la restricción
    blanda de no asignarles el primer/último bloque.
    
    Args:
        df_profesores: DataFrame de la hoja PROFESORES.
    
    Returns:
        Set de IDs (nombres normalizados) de profesores de jornada.
    """
    jornada_ids = set()
    col_nombre = [c for c in df_profesores.columns if "NOMBRE" in str(c).upper()]
    col_email = [c for c in df_profesores.columns if "EMAIL" in str(c).upper()]
    
    if not col_nombre:
        return jornada_ids
    
    for _, row in df_profesores.iterrows():
        nombre = safe_str(row[col_nombre[0]])
        if nombre:
            jornada_ids.add(normalizar_nombre_profesor(nombre))
    
    return jornada_ids


def construir_disponibilidad_profesor(row: pd.Series, dias_cols: dict) -> set:
    """Extrae la disponibilidad de un profesor desde una fila del maestro.
    
    Las columnas LUNES-VIERNES (mayúsculas) del maestro contienen
    la disponibilidad declarada como bloques separados por coma.
    
    Args:
        row: Fila del DataFrame del maestro.
        dias_cols: Mapeo {Dia: nombre_columna} para las columnas
            de disponibilidad.
    
    Returns:
        Conjunto de SubBloques disponibles.
    """
    disponibilidad = set()
    for dia, col in dias_cols.items():
        val = row.get(col, np.nan)
        disponibilidad |= parsear_disponibilidad_str(val, dia)
    return disponibilidad


# =============================================================================
# PARSING PRINCIPAL DEL MAESTRO
# =============================================================================

def cargar_datos(ruta_maestro: str, ruta_salas: str) -> DatosProblema:
    """Función principal del parser. Lee todos los archivos y construye
    el DatosProblema completo.
    
    Este es el punto de entrada del Módulo 1. Lee el Excel maestro,
    el archivo de salas especiales, y ensambla todas las entidades
    en una estructura unificada lista para los módulos de optimización.
    
    Args:
        ruta_maestro: Ruta al archivo Maestro_XXXXXX.xlsx.
        ruta_salas: Ruta al archivo SALAS_ESPECIALES_ING.xlsx.
    
    Returns:
        DatosProblema con todos los datos cargados y validados.
    
    Raises:
        FileNotFoundError: Si algún archivo no existe.
        ValueError: Si los datos tienen inconsistencias críticas.
    """
    print("=" * 60)
    print("MÓDULO 1: Parser e integración de datos")
    print("=" * 60)
    
    # -------------------------------------------------------------------------
    # 1. Cargar salas especiales
    # -------------------------------------------------------------------------
    print("\n[1/5] Cargando salas especiales...")
    salas_por_curso = cargar_salas_especiales(ruta_salas)
    salas_unicas = list({s.nombre: s for s in salas_por_curso.values()}.values())
    print(f"  → {len(salas_por_curso)} cursos con sala especial")
    print(f"  → {len(salas_unicas)} tipos de sala únicos")
    
    # -------------------------------------------------------------------------
    # 2. Cargar profesores de jornada
    # -------------------------------------------------------------------------
    print("\n[2/5] Cargando profesores...")
    df_prof = pd.read_excel(ruta_maestro, sheet_name="PROFESORES", header=0)
    profesores_jornada = cargar_profesores_jornada(df_prof)
    print(f"  → {len(profesores_jornada)} profesores de jornada")
    
    # -------------------------------------------------------------------------
    # 3. Cargar catálogo (horas semanales, semestres)
    # -------------------------------------------------------------------------
    print("\n[3/5] Cargando catálogo...")
    df_catalogo = pd.read_excel(ruta_maestro, sheet_name="CATALOGO", header=0)
    catalogo_info = {}
    for _, row in df_catalogo.iterrows():
        codigo = safe_str(row.get("CODIGO", ""))
        if not codigo:
            continue
        
        # Construir diccionario de semestres por carrera
        semestres = {}
        for carrera in ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA"]:
            val = row.get(carrera, np.nan)
            if not pd.isna(val):
                try:
                    sem = int(float(str(val).replace("i", "").replace("p", "").strip()))
                    semestres[carrera] = sem
                except (ValueError, TypeError):
                    pass
        
        catalogo_info[codigo] = {
            "area": safe_str(row.get("AREA", "")),
            "semestres": semestres,
            "horas_clase": safe_int(row.get("Clases", 0)),
            "horas_ayudantia": safe_int(row.get("Ayudantías", 0)),
            "horas_lab": safe_int(row.get("Laboratorios o Talleres", 0)),
            "horas_clase_prog": safe_int(row.get("Clases A PROGRAMAR", 0)),
            "horas_ayud_prog": safe_int(row.get("Ayudantías PROGRAMAR", 0)),
            "horas_lab_prog": safe_int(row.get("Laboratorios o Talleres PROGRAMAR", 0)),
        }
    print(f"  → {len(catalogo_info)} cursos en catálogo")
    
    # -------------------------------------------------------------------------
    # 4. Cargar maestro (secciones, profesores, disponibilidad)
    # -------------------------------------------------------------------------
    print("\n[4/5] Cargando maestro...")
    df_maestro = pd.read_excel(ruta_maestro, sheet_name="MAESTRO", header=0)
    
    # Columnas de disponibilidad (MAYÚSCULAS = disponibilidad del profesor)
    # Hay que encontrarlas por posición porque hay columnas duplicadas
    cols = df_maestro.columns.tolist()
    dias_disp_cols = {}
    # Las columnas LUNES-VIERNES en mayúsculas son las de disponibilidad
    for i, col in enumerate(cols):
        if col == "LUNES" and i > 50:
            dias_disp_cols[Dia.LUNES] = cols[i]
        elif col == "MARTES" and i > 50:
            dias_disp_cols[Dia.MARTES] = cols[i]
        elif col == "MIERCOLES" and i > 50:
            dias_disp_cols[Dia.MIERCOLES] = cols[i]
        elif col == "JUEVES" and i > 50:
            dias_disp_cols[Dia.JUEVES] = cols[i]
        elif col == "VIERNES" and i > 50:
            dias_disp_cols[Dia.VIERNES] = cols[i]
    
    # Si no encontramos por posición, usar las primeras ocurrencias
    if not dias_disp_cols:
        for dia, nombre in [(Dia.LUNES, "LUNES"), (Dia.MARTES, "MARTES"),
                            (Dia.MIERCOLES, "MIERCOLES"), (Dia.JUEVES, "JUEVES"),
                            (Dia.VIERNES, "VIERNES")]:
            if nombre in cols:
                dias_disp_cols[dia] = nombre
    
    cursos = {}
    secciones = []
    profesores = {}
    
    for idx, row in df_maestro.iterrows():
        # --- Filtrar filas válidas ---
        materia = safe_str(row.get("MATERIA", ""))
        curso_num = safe_str(row.get("CURSO", ""))
        titulo = safe_str(row.get("TITULO", ""))
        llave = safe_str(row.get("LLAVE Código- sec", ""))
        nrc = safe_str(row.get("NRC", ""))
        
        if not materia or not curso_num or not titulo:
            continue
        
        # Solo procesar cursos mandantes
        mandante = safe_str(row.get("CURSO MANDANTE", ""))
        if mandante.upper() == "NO":
            continue
        
        codigo = f"{materia}{curso_num}"
        
        # --- Crear o recuperar Curso ---
        if codigo not in cursos:
            cat = catalogo_info.get(codigo, {})
            semestres = cat.get("semestres", {})
            
            # Si no está en catálogo, usar info del maestro
            if not semestres:
                for carrera in ["Plan Común", "ICI", "IOC", "ICE", "ICC", "ICA"]:
                    val = row.get(carrera, np.nan)
                    if not pd.isna(val):
                        try:
                            sem = int(float(str(val).replace("i", "").replace("p", "").strip()))
                            semestres[carrera] = sem
                        except (ValueError, TypeError):
                            pass
            
            sala_esp = salas_por_curso.get(codigo, None)
            distribucion = safe_str(row.get("2+1 o 3? (distribución horario de clases)", ""))
            
            cursos[codigo] = Curso(
                codigo=codigo,
                materia=materia,
                numero=str(curso_num),
                titulo=titulo,
                area=safe_str(row.get("AREA", "")),
                plan_estudio=safe_str(row.get("PLAN DE ESTUDIO", "")),
                semestres=semestres,
                horas_clase=cat.get("horas_clase", safe_int(row.get("Clases", 0))),
                horas_ayudantia=cat.get("horas_ayudantia", safe_int(row.get("Ayudantías", 0))),
                horas_lab=cat.get("horas_lab", safe_int(row.get("Laboratorios o Talleres", 0))),
                distribucion=distribucion,
                sala_especial=sala_esp,
                es_electivo=safe_str(row.get("ELECTIVO", "")).upper() in ["SI", "SÍ", "YES"],
            )
        
        curso_obj = cursos[codigo]
        
        # --- Crear o recuperar Profesor ---
        nombre_prof = safe_str(row.get(
            "NOMBRE PROFESOR BANNER 1 (PROFESOR PRINCIPAL SESIÓN 01)", ""))
        prof_id = normalizar_nombre_profesor(nombre_prof)
        
        if prof_id and prof_id not in profesores:
            tipo = TipoProfesor.JORNADA if prof_id in profesores_jornada else TipoProfesor.HONORARIO
            email = safe_str(row.get("EMAIL PROFESOR 1", ""))
            disponibilidad = construir_disponibilidad_profesor(row, dias_disp_cols)
            
            profesores[prof_id] = Profesor(
                id=prof_id,
                nombre=nombre_prof,
                tipo=tipo,
                email=email,
                disponibilidad=disponibilidad,
            )
        
        profesor_obj = profesores.get(prof_id, None)
        
        # --- Profesor de laboratorio (si existe) ---
        nombre_prof_lab = safe_str(row.get("PROFESOR LABT", ""))
        prof_lab_id = normalizar_nombre_profesor(nombre_prof_lab)
        profesor_lab_obj = None
        if prof_lab_id and prof_lab_id != prof_id:
            if prof_lab_id not in profesores:
                profesores[prof_lab_id] = Profesor(
                    id=prof_lab_id,
                    nombre=nombre_prof_lab,
                    tipo=TipoProfesor.HONORARIO,
                )
            profesor_lab_obj = profesores[prof_lab_id]
        
        # --- Determinar secciones a crear ---
        # Cada fila del maestro es una sección. El tipo de reunión
        # se infiere de las horas programables: si tiene horas de clase,
        # se crea una sección CLAS; si tiene horas de ayudantía, AYUD; etc.
        numero_seccion = safe_int(row.get("SECCIONES", 1))
        # Algunos LLAVEs no incluyen el número de sección al final (ej: "FRM2100"
        # en vez de "FRM210031"). Incorporar el valor de SECCIONES al ID garantiza
        # unicidad global sin depender del formato del LLAVE.
        seccion_str = safe_str(row.get("SECCIONES", "")) or str(numero_seccion)
        sec_id_base = f"{llave}_{seccion_str}"
        
        # Sección de CLASE
        horas_clase = safe_int(row.get("Clases", 0))
        if horas_clase > 0:
            # Determinar sala especial para clases
            sala_clase = None
            if curso_obj.sala_especial:
                aplica = curso_obj.sala_especial.aplica_en.upper()
                if "CLASE" in aplica or not aplica:
                    sala_clase = curso_obj.sala_especial
            
            secciones.append(Seccion(
                id=f"{sec_id_base}_CLAS",
                nrc=nrc,
                curso=curso_obj,
                numero_seccion=numero_seccion,
                tipo_reunion=TipoReunion.CLASE,
                profesor=profesor_obj,
                cupos=safe_int(row.get("CUPOS", 0)),
                sala_especial=sala_clase,
            ))
        
        # Sección de AYUDANTÍA
        horas_ayud = safe_int(row.get("Ayudantías", 0))
        if horas_ayud > 0:
            secciones.append(Seccion(
                id=f"{sec_id_base}_AYUD",
                nrc=nrc,
                curso=curso_obj,
                numero_seccion=numero_seccion,
                tipo_reunion=TipoReunion.AYUDANTIA,
                profesor=profesor_obj,
                cupos=safe_int(row.get("CUPOS", 0)),
            ))
        
        # Sección de LABORATORIO
        horas_lab = safe_int(row.get("Laboratorios o Talleres", 0))
        if horas_lab > 0:
            sala_lab = None
            if curso_obj.sala_especial:
                aplica = curso_obj.sala_especial.aplica_en.upper()
                if "LABORATORIO" in aplica or not aplica:
                    sala_lab = curso_obj.sala_especial
            
            secciones.append(Seccion(
                id=f"{sec_id_base}_LABT",
                nrc=nrc,
                curso=curso_obj,
                numero_seccion=numero_seccion,
                tipo_reunion=TipoReunion.LABORATORIO,
                profesor=profesor_lab_obj if profesor_lab_obj else profesor_obj,
                cupos=safe_int(row.get("CUPOS", 0)),
                sala_especial=sala_lab,
            ))
    
    # -------------------------------------------------------------------------
    # 5. Generar bloques horarios
    # -------------------------------------------------------------------------
    print("\n[5/5] Generando bloques horarios...")
    bloques = generar_bloques_horarios()
    print(f"  → {len(bloques)} bloques horarios válidos")
    
    # -------------------------------------------------------------------------
    # 6. Ensamblar DatosProblema
    # -------------------------------------------------------------------------
    datos = DatosProblema(
        cursos=cursos,
        secciones=secciones,
        profesores=profesores,
        salas_especiales=salas_unicas,
        bloques_disponibles=bloques,
    )
    
    print("\n" + datos.resumen())
    return datos


# =============================================================================
# EJECUCIÓN DIRECTA (para testing)
# =============================================================================

if __name__ == "__main__":
    import sys
    
    ruta_maestro = sys.argv[1] if len(sys.argv) > 1 else "inputs/Maestro_202520.xlsx"
    ruta_salas = sys.argv[2] if len(sys.argv) > 2 else "inputs/SALAS_ESPECIALES_ING.xlsx"
    
    datos = cargar_datos(ruta_maestro, ruta_salas)
