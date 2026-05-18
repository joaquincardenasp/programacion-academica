# Generador Automático de Horario Base — UANDES
## Proyecto IA Aplicada 2026-10 | Grupo 17

---

## Descripción General

Sistema de optimización para la generación automática de horarios académicos
de la Facultad de Ingeniería y Ciencias Aplicadas, Universidad de los Andes.

**Arquitectura:** CP-SAT (restricciones duras) → GA/DEAP (restricciones blandas)

**Autores:** Joaquín Cárdenas, Matías De la Sotta, Pablo Moyano

---

## Estructura del Proyecto

```
horario_uandes/
├── src/
│   ├── models.py          # Modelo de datos (dataclasses)
│   ├── parser.py          # Módulo 1: Parser e integración de datos
│   ├── solver_cpsat.py    # Módulo 2: Motor CP-SAT (restricciones duras)
│   ├── solver_ga.py       # Módulo 3: Algoritmo Genético (restricciones blandas)
│   └── exportador.py      # Módulo 4: Exportación a Excel
├── inputs/                # Archivos Excel de entrada
├── outputs/               # Horarios generados
├── docs/                  # Documentación adicional
├── tests/                 # Tests unitarios
└── README.md
```

---

## Módulos

### Módulo 1: Parser (`parser.py`)

**Responsabilidad:** Leer los archivos Excel del proceso actual y transformarlos
en la estructura de datos estandarizada (`DatosProblema`).

**Archivos de entrada:**
- `Maestro_XXXXXX.xlsx` — Excel maestro con todas las secciones, profesores,
  disponibilidad y horarios.
- `SALAS_ESPECIALES_ING.xlsx` — Mapeo de cursos a salas especiales requeridas.

**Hojas del maestro que se leen:**
| Hoja | Datos extraídos |
|------|----------------|
| MAESTRO | Secciones, profesores, disponibilidad, horas semanales |
| CATALOGO | Semestres por carrera, horas programables |
| PROFESORES | Lista de profesores de jornada completa |

**Output:** Objeto `DatosProblema` con:
- 117 cursos únicos
- 305 secciones a programar (166 CLAS + 80 AYUD + 59 LABT)
- 129 profesores (104 con disponibilidad declarada)
- 10 tipos de sala especial
- 45 bloques horarios válidos

**Decisiones de diseño:**
- Las salas normales quedan fuera del scope (las asigna otra área).
- Solo se procesan cursos con `CURSO MANDANTE = "SI"`.
- La disponibilidad del profesor se toma de las columnas LUNES-VIERNES
  (mayúsculas) del maestro, que contienen sub-bloques de 50 minutos.
- Los nombres de profesores se normalizan para poder cruzar entre hojas
  (el maestro usa dos formatos distintos).

---

### Módulo 2: Solver CP-SAT (`solver_cpsat.py`) — POR IMPLEMENTAR

**Responsabilidad:** Generar un horario base que satisfaga todas las
restricciones duras usando el motor CP-SAT de OR-Tools.

**Restricciones duras a implementar:**

| # | Restricción | Descripción |
|---|-------------|-------------|
| RD1 | Topes plan común | Ramos del mismo semestre del plan común no pueden coincidir en bloque |
| RD2 | Disponibilidad profesor | Secciones asignadas solo en bloques donde el profesor está disponible |
| RD3 | Unicidad profesor | Un profesor no puede dictar dos secciones simultáneamente |
| RD4 | Sala especial única | Dos secciones que requieren la misma sala especial no pueden coincidir |
| RD5 | Bloques fijos | Solo bloques estándar (8:30-10:20, 10:30-12:20, etc.) |
| RD6 | Bloques 3h | Cursos de 3h seguidas solo en 10:30-13:20 o 12:30-15:20 |
| RD7 | Ayudantías desde 12:30 | Ayudantías solo pueden asignarse a bloques que inician a las 12:30 o después |
| RD8 | Prof lab ≠ cátedra simultáneo | Si el prof de lab es el mismo que el de cátedra, no pueden coincidir |
| RD9 | Minors protegidos | Cursos minor solo en Ma/Mi 17:30-19:20 y Vi 10:30-12:20 |

---

### Módulo 3: Solver GA (`solver_ga.py`) — POR IMPLEMENTAR

**Responsabilidad:** Optimizar el horario factible de CP-SAT minimizando
violaciones de restricciones blandas.

**Restricciones blandas:**

| # | Restricción | Peso | Descripción |
|---|-------------|------|-------------|
| RB1 | Continuidad labs Programación | Alto (100) | Labs del ramo de Programación deben ser consecutivos entre secciones |
| RB2 | Prof jornada sin extremos | Alto (80) | Profesores de jornada no en 8:30 ni 17:30 |
| RB3 | Distribución semanal | Medio (50) | Clases/ayud/labs del mismo curso espaciados en la semana |
| RB4 | Concentración diaria | Medio (50) | Evitar concentrar sesiones de un curso en un solo día |
| RB5 | Proximidad histórica | Bajo (10) | Preferir bloques similares a semestres anteriores |

**Nota:** Los pesos son configurables y deben calibrarse con feedback del cliente.

---

### Módulo 4: Exportador (`exportador.py`) — POR IMPLEMENTAR

**Responsabilidad:** Exportar el horario optimizado a Excel en formato
compatible con el flujo actual.

---

## Modelo de Datos (`models.py`)

### Entidades principales

```
DatosProblema
├── cursos: dict[str, Curso]
│   └── Curso
│       ├── codigo, materia, titulo, area
│       ├── semestres: dict[carrera, semestre]
│       ├── horas_clase, horas_ayudantia, horas_lab
│       ├── distribucion: "2+1" | "3"
│       └── sala_especial: SalaEspecial?
├── secciones: list[Seccion]
│   └── Seccion
│       ├── id, nrc, numero_seccion
│       ├── curso: Curso
│       ├── tipo_reunion: CLAS | AYUD | LABT
│       ├── profesor: Profesor
│       ├── profesor_lab: Profesor?
│       ├── cupos: int
│       ├── sala_especial: SalaEspecial?
│       └── bloque_asignado: BloqueHorario?
├── profesores: dict[str, Profesor]
│   └── Profesor
│       ├── id, nombre, tipo, email
│       └── disponibilidad: set[SubBloque]
├── salas_especiales: list[SalaEspecial]
└── bloques_disponibles: list[BloqueHorario]
```

### Bloques horarios

El sistema opera con bloques horarios fijos:

**Bloques de 2 horas (50min + 50min):**
- 8:30-10:20, 10:30-12:20, 12:30-14:20, 14:30-16:20,
  15:30-17:20, 16:30-18:20, 17:30-19:20

**Bloques de 3 horas (50min × 3):**
- 10:30-13:20, 12:30-15:20

**Sub-bloques (granularidad mínima, 50min):**
- 8:30-9:20, 9:30-10:20, ..., 18:30-19:20
- Se usan para mapear disponibilidad de profesores.

---

## Ejecución

```bash
# Instalar dependencias
pip install ortools deap openpyxl pandas

# Ejecutar parser (testing)
cd src/
python parser.py ../inputs/Maestro_202520.xlsx ../inputs/SALAS_ESPECIALES_ING.xlsx

# Ejecutar sistema completo (cuando esté implementado)
python generar_horario.py
```

---

## Restricciones identificadas en reunión con cliente

### Restricciones duras (garantizadas por CP-SAT)
1. Sin topes entre ramos del plan común del mismo semestre
2. Respeto de disponibilidad horaria de profesores
3. Un profesor no puede dictar dos secciones al mismo tiempo
4. Sala especial no puede ser usada por dos secciones al mismo tiempo
5. Solo bloques horarios estándar (no intermedios)
6. Cursos de 3h solo en bloques 10:30-13:20 o 12:30-15:20
7. Ayudantías solo a partir de las 12:30
8. Prof de lab que es el mismo de cátedra no puede tener ambos simultáneamente
9. Cursos minor en horarios protegidos (Ma/Mi 17:30-19:20, Vi 10:30-12:20)

### Restricciones blandas (optimizadas por GA)
1. Labs de Programación consecutivos entre secciones (peso alto)
2. Profesores de jornada no en primer/último bloque (peso alto)
3. Clases, ayudantías y labs del mismo curso espaciados en la semana (peso medio)
4. Evitar concentración excesiva de un curso en un día (peso medio)
5. Preferir bloques similares a semestres anteriores (peso bajo)

### Fuera del MVP
- Compatibilidad entre semestres consecutivos (requiere datos de reprobación)
- Gestión de ayudantes
- Gestión curricular / mallas
- Programación de pruebas y exámenes
- Interfaz gráfica
