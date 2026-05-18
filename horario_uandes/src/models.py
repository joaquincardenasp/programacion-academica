"""
models.py — Modelo de datos para el sistema de programación académica.

Este módulo define las estructuras de datos que representan todas las
entidades del dominio: cursos, secciones, profesores, salas y bloques
horarios. Estas estructuras son el output del Parser (Módulo 1) y el
input de los módulos de optimización (CP-SAT y GA).

Convención de tipos:
- Los IDs son strings para consistencia (NRC, códigos de curso, etc.)
- Los bloques horarios se representan como tuplas (día, hora_inicio, hora_fin)
- La disponibilidad de profesores se representa como set de sub-bloques
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


# =============================================================================
# ENUMS
# =============================================================================

class TipoReunion(Enum):
    """Tipos de reunión posibles para una sección.
    
    Corresponde al campo 'TIPO DE REUNIÓN' del Excel maestro.
    Cada sección de un curso tiene exactamente un tipo de reunión.
    """
    CLASE = "CLAS"
    AYUDANTIA = "AYUD"
    LABORATORIO = "LABT"
    PRUEBA = "PRBA"
    EXAMEN = "EXAM"


class TipoProfesor(Enum):
    """Clasificación contractual del profesor.
    
    Relevante para la restricción blanda de no asignar bloques
    extremos (8:30, 17:30) a profesores de jornada completa.
    """
    JORNADA = "JORNADA"
    HONORARIO = "HONORARIO"


class Dia(Enum):
    """Días de la semana lectiva."""
    LUNES = "Lunes"
    MARTES = "Martes"
    MIERCOLES = "Miercoles"
    JUEVES = "Jueves"
    VIERNES = "Viernes"


# =============================================================================
# BLOQUES HORARIOS
# =============================================================================

# Bloques estándar de 2 horas (50 min + 50 min) definidos por la universidad.
# Restricción dura: las clases solo pueden asignarse a estos bloques, no a
# horarios intermedios como 9:30-11:20.
BLOQUES_2H = [
    ("8:30", "10:20"),
    ("10:30", "12:20"),
    ("12:30", "14:20"),
    ("14:30", "16:20"),
    ("15:30", "17:20"),
    ("16:30", "18:20"),
    ("17:30", "19:20"),
]

# Bloques estándar de 3 horas seguidas.
# Restricción dura: solo pueden asignarse en estos dos horarios.
BLOQUES_3H = [
    ("10:30", "13:20"),
    ("12:30", "15:20"),
]

# Sub-bloques de 50 minutos (granularidad mínima del sistema).
# Se usan para representar la disponibilidad de profesores.
SUB_BLOQUES = [
    ("8:30", "9:20"),
    ("9:30", "10:20"),
    ("10:30", "11:20"),
    ("11:30", "12:20"),
    ("12:30", "13:20"),
    ("13:30", "14:20"),
    ("14:30", "15:20"),
    ("15:30", "16:20"),
    ("16:30", "17:20"),
    ("17:30", "18:20"),
    ("18:30", "19:20"),
]

# Bloques protegidos para cursos "Minor" (restricción dura).
# Los cursos de minor en semestres 3, 4 y 5 deben asignarse
# exclusivamente en estos bloques.
BLOQUES_MINOR = {
    Dia.MARTES: ("17:30", "19:20"),
    Dia.MIERCOLES: ("17:30", "19:20"),
    Dia.VIERNES: ("10:30", "12:20"),
}


@dataclass(frozen=True)
class SubBloque:
    """Unidad mínima de tiempo (50 minutos).
    
    Representa un slot individual como "Lunes 8:30-9:20".
    Se usa para mapear la disponibilidad de profesores y para
    verificar solapamientos entre bloques de distinta duración.
    
    Attributes:
        dia: Día de la semana.
        hora_inicio: Hora de inicio en formato "HH:MM".
        hora_fin: Hora de fin en formato "HH:MM".
    """
    dia: Dia
    hora_inicio: str
    hora_fin: str

    def __repr__(self) -> str:
        return f"{self.dia.value} {self.hora_inicio}-{self.hora_fin}"


@dataclass(frozen=True)
class BloqueHorario:
    """Bloque de tiempo asignable a una sección.
    
    Puede ser de 2 horas (2 sub-bloques) o 3 horas (3 sub-bloques).
    Este es el nivel al que opera CP-SAT: cada sección se asigna
    a un BloqueHorario.
    
    Attributes:
        dia: Día de la semana.
        hora_inicio: Hora de inicio del bloque.
        hora_fin: Hora de fin del bloque.
        sub_bloques: Lista de SubBloques que componen este bloque.
            Se usa para verificar solapamientos con la disponibilidad
            del profesor (que viene en granularidad de sub-bloques).
    """
    dia: Dia
    hora_inicio: str
    hora_fin: str
    sub_bloques: tuple = field(default_factory=tuple)

    def __repr__(self) -> str:
        return f"{self.dia.value} {self.hora_inicio}-{self.hora_fin}"

    @property
    def duracion_horas(self) -> int:
        """Retorna la duración aproximada en horas (2 o 3)."""
        subs = len(self.sub_bloques) if self.sub_bloques else 0
        if subs >= 3:
            return 3
        return 2


# =============================================================================
# ENTIDADES DEL DOMINIO
# =============================================================================

@dataclass
class Profesor:
    """Profesor asignado a una o más secciones.
    
    Attributes:
        id: Identificador único (nombre normalizado del profesor).
        nombre: Nombre completo tal como aparece en el maestro.
        tipo: JORNADA o HONORARIO. Los profesores de jornada no
            deberían dictar en primer (8:30) ni último (17:30) bloque
            (restricción blanda).
        email: Correo electrónico institucional.
        disponibilidad: Conjunto de SubBloques en los que el profesor
            declaró estar disponible. Proviene de las columnas
            LUNES-VIERNES (mayúsculas) del maestro o de la hoja
            RESPUESTAS. Si está vacío, se asume disponibilidad total.
    """
    id: str
    nombre: str
    tipo: TipoProfesor = TipoProfesor.HONORARIO
    email: str = ""
    disponibilidad: set = field(default_factory=set)

    def esta_disponible(self, bloque: BloqueHorario) -> bool:
        """Verifica si el profesor está disponible en un bloque.
        
        Si no tiene disponibilidad declarada (set vacío), se asume
        disponible en todo horario. Si tiene disponibilidad declarada,
        todos los sub-bloques del bloque deben estar en su disponibilidad.
        """
        if not self.disponibilidad:
            return True
        return all(sb in self.disponibilidad for sb in bloque.sub_bloques)


@dataclass
class SalaEspecial:
    """Sala especializada requerida por ciertos cursos.
    
    Nota: las salas normales NO son gestionadas por este sistema
    (las asigna otra área de la facultad). Este modelo solo
    representa las salas especiales de ingeniería.
    
    Attributes:
        nombre: Nombre descriptivo de la sala (ej: "LABORATORIO DE
            COMPUTACION EN INGENIERIA").
        aplica_en: Contexto en que aplica la sala especial (ej:
            "EN HORARIO DE LABORATORIO", "EN HORARIO DE CLASE").
            Un mismo curso puede necesitar sala especial solo para
            su componente de laboratorio y no para la cátedra.
    """
    nombre: str
    aplica_en: str = ""

    @property
    def nombre_corto(self) -> str:
        """Nombre simplificado para display."""
        return self.nombre.split(" EN HORARIO")[0] if " EN HORARIO" in self.nombre else self.nombre


@dataclass
class Curso:
    """Curso del catálogo académico.
    
    Representa un curso único (ej: "Álgebra Lineal" ING1201),
    independiente de cuántas secciones tenga. Contiene la información
    de la malla curricular y las horas semanales.
    
    Attributes:
        codigo: Código único del curso (ej: "ING1201").
        materia: Prefijo de materia (ej: "ING", "ICC").
        numero: Número del curso (ej: "1201").
        titulo: Nombre completo del curso.
        area: Área académica responsable (ej: "MATEMATICA", "COMPUTACION").
        plan_estudio: Plan de estudios al que pertenece (ej: "PE2023").
        semestres: Diccionario {carrera: semestre} que indica en qué
            semestre de cada carrera aparece este curso. Clave para la
            restricción de topes del mismo semestre.
        horas_clase: Horas semanales de cátedra.
        horas_ayudantia: Horas semanales de ayudantía.
        horas_lab: Horas semanales de laboratorio/taller.
        distribucion: "2+1" o "3" — cómo se distribuyen las horas de
            clase en la semana. "2+1" significa un bloque de 2h + otro
            de 1h, "3" significa un bloque de 3h seguidas.
        sala_especial: Sala especial requerida, si aplica.
        es_minor: Si el curso es de tipo Minor (semestres 3-5 con
            horario protegido).
        es_electivo: Si el curso es electivo.
    """
    codigo: str
    materia: str
    numero: str
    titulo: str
    area: str = ""
    plan_estudio: str = ""
    semestres: dict = field(default_factory=dict)
    horas_clase: int = 0
    horas_ayudantia: int = 0
    horas_lab: int = 0
    distribucion: str = ""
    sala_especial: Optional[SalaEspecial] = None
    es_minor: bool = False
    es_electivo: bool = False


@dataclass
class Seccion:
    """Sección específica de un curso a programar.
    
    Es la unidad fundamental de asignación: el sistema asigna un
    BloqueHorario a cada Seccion. Un curso puede tener múltiples
    secciones (ej: Álgebra Lineal secciones 1, 2, 3, 4).
    
    Attributes:
        id: Identificador único (LLAVE del maestro, ej: "ING12011").
        nrc: NRC asignado por Banner.
        curso: Referencia al Curso al que pertenece.
        numero_seccion: Número de sección (1, 2, 3...).
        tipo_reunion: CLAS, AYUD, LABT, etc.
        profesor: Profesor asignado a esta sección.
        profesor_lab: Profesor de laboratorio (puede ser distinto al
            de cátedra). Restricción dura: si profesor == profesor_lab,
            no pueden tener bloques simultáneos.
        cupos: Capacidad máxima de estudiantes.
        sala_especial: Sala especial requerida para esta sección
            específica (heredada del curso, filtrada por tipo_reunion).
        bloque_asignado: BloqueHorario asignado por el optimizador.
            None si aún no ha sido asignado.
    """
    id: str
    nrc: str
    curso: Curso
    numero_seccion: int
    tipo_reunion: TipoReunion
    profesor: Optional[Profesor] = None
    profesor_lab: Optional[Profesor] = None
    cupos: int = 0
    sala_especial: Optional[SalaEspecial] = None
    bloque_asignado: Optional[BloqueHorario] = None

    @property
    def semestres(self) -> dict:
        """Semestres del curso al que pertenece."""
        return self.curso.semestres

    @property
    def es_ayudantia(self) -> bool:
        return self.tipo_reunion == TipoReunion.AYUDANTIA

    @property
    def es_laboratorio(self) -> bool:
        return self.tipo_reunion == TipoReunion.LABORATORIO

    @property
    def es_clase(self) -> bool:
        return self.tipo_reunion == TipoReunion.CLASE

    def __repr__(self) -> str:
        return (f"Seccion({self.id}, {self.curso.titulo} S{self.numero_seccion}, "
                f"{self.tipo_reunion.value})")


@dataclass
class DatosProblema:
    """Contenedor principal con todos los datos del problema.
    
    Es el output del Parser y el input unificado para CP-SAT y GA.
    Contiene todas las entidades parseadas y listas para ser usadas
    por los módulos de optimización.
    
    Attributes:
        cursos: Diccionario {codigo: Curso} con todos los cursos.
        secciones: Lista de todas las secciones a programar.
        profesores: Diccionario {id: Profesor} con todos los profesores.
        salas_especiales: Lista de salas especiales disponibles.
        bloques_disponibles: Lista de todos los BloqueHorario válidos.
    """
    cursos: dict = field(default_factory=dict)
    secciones: list = field(default_factory=list)
    profesores: dict = field(default_factory=dict)
    salas_especiales: list = field(default_factory=list)
    bloques_disponibles: list = field(default_factory=list)

    @property
    def n_secciones(self) -> int:
        return len(self.secciones)

    @property
    def n_profesores(self) -> int:
        return len(self.profesores)

    @property
    def n_cursos(self) -> int:
        return len(self.cursos)

    def resumen(self) -> str:
        """Genera un resumen legible de los datos cargados."""
        lines = [
            "=" * 60,
            "RESUMEN DE DATOS CARGADOS",
            "=" * 60,
            f"Cursos únicos:        {self.n_cursos}",
            f"Secciones a programar: {self.n_secciones}",
            f"Profesores:           {self.n_profesores}",
            f"Salas especiales:     {len(self.salas_especiales)}",
            f"Bloques disponibles:  {len(self.bloques_disponibles)}",
            "",
            "Secciones por tipo:",
        ]
        conteo_tipo = {}
        for s in self.secciones:
            tipo = s.tipo_reunion.value
            conteo_tipo[tipo] = conteo_tipo.get(tipo, 0) + 1
        for tipo, n in sorted(conteo_tipo.items()):
            lines.append(f"  {tipo}: {n}")

        lines.append("")
        lines.append("Secciones con sala especial:")
        n_sala = sum(1 for s in self.secciones if s.sala_especial is not None)
        lines.append(f"  {n_sala} de {self.n_secciones}")

        lines.append("=" * 60)
        return "\n".join(lines)
