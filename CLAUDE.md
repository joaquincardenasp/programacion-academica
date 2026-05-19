# CLAUDE.md — Generador Automático de Horario Base UANDES

**IMPORTANTE:** Antes de hacer cualquier cambio, lee `docs/PRD.md` y `docs/CONTEXT.md`. Este archivo es solo un resumen de orientación rápida.

---

## Qué es este proyecto

Sistema de optimización en dos fases (CP-SAT + Algoritmo Genético) para generar automáticamente horarios académicos de la Facultad de Ingeniería y Ciencias Aplicadas de la Universidad de los Andes. Cliente: Francisca Sáez (encargada de procesos curriculares). Proyecto académico del curso IA Aplicada 2026-10, Grupo 17.

**Stack:** Python 3.10+, OR-Tools (CP-SAT), DEAP, pandas, openpyxl.

---

## Estructura del proyecto

```
horario_uandes/
├── src/
│   ├── __init__.py
│   ├── models.py          ✅ Modelo de datos completo
│   ├── parser.py          ✅ Parser implementado y testeado
│   ├── solver_cpsat.py    🔴 Por implementar
│   ├── solver_ga.py       🔴 Por implementar
│   ├── exportador.py      🔴 Por implementar
│   └── generar_horario.py 🔴 Por implementar (script principal)
├── inputs/                Archivos Excel de entrada (no en git)
├── outputs/               Horarios generados (no en git)
docs/
├── PRD.md                 Especificación completa del sistema
└── CONTEXT.md             Decisiones de diseño y detalles técnicos
tests/                     (por crear)
README.md
```

---

## Estado de implementación

| Módulo | Archivo | Estado |
|--------|---------|--------|
| 1. Parser + Modelos | `models.py`, `parser.py` | ✅ HECHO |
| 2. Solver CP-SAT | `solver_cpsat.py` | 🔴 POR HACER |
| 3. Solver GA | `solver_ga.py` | 🔴 POR HACER |
| 4. Exportador Excel | `exportador.py` | 🔴 POR HACER |
| 5. Script principal | `generar_horario.py` | 🔴 POR HACER |

El flujo final será:
```python
datos = cargar_datos("inputs/Maestro.xlsx", "inputs/Salas.xlsx")  # Módulo 1
datos = resolver_cpsat(datos)                                      # Módulo 2
datos = optimizar_ga(datos)                                        # Módulo 3
exportar_excel(datos, "outputs/horario_generado.xlsx")             # Módulo 4
```

---

## Escala del problema (datos reales)

305 secciones totales (166 CLAS + 80 AYUD + 59 LABT), 129 profesores, 45 bloques horarios válidos, 10 tipos de sala especial. Los números provienen del parser corriendo sobre `Maestro_202520.xlsx`.

---

## Restricciones duras (CP-SAT) — resumen

| ID | Descripción | Cómo modelar |
|----|-------------|--------------|
| RD1 | Sin topes en plan común (mismo semestre) | `asignacion[s1] != asignacion[s2]` para pares de secciones con mismo semestre en Plan Común |
| RD2 | Disponibilidad del profesor | Pre-filtrar dominio de la variable |
| RD3 | Unicidad de profesor (no dos secciones simultáneas) | Prohibir bloques que se solapan para el mismo profesor |
| RD4 | Unicidad de sala especial | Igual que RD3 pero agrupando por nombre de sala |
| RD5 | Bloques fijos estándar | Ya garantizado por dominio generado en `generar_bloques_horarios()` |
| RD6 | Cursos 3h solo en bloques 3h (10:30-13:20 o 12:30-15:20) | Filtrar dominio |
| RD7 | Ayudantías solo desde 12:30 | Filtrar dominio |
| RD8 | Prof lab ≠ prof cátedra simultáneos | Caso particular de RD3 cruzando roles |
| RD9 | Cursos minor en horario protegido (Ma/Mi 17:30, Vi 10:30) | Filtrar dominio — **pendiente definir exactamente qué cursos son minor** |

**Dos bloques se solapan** si son del mismo día Y comparten al menos un sub-bloque de 50 min.

---

## Restricciones blandas (GA) — resumen

| ID | Descripción | Peso |
|----|-------------|------|
| RB1 | Labs de Programación en bloques consecutivos | 100 |
| RB2 | Profesores de jornada sin bloques extremos (8:30 o 17:30) | 80 |
| RB3 | Componentes del mismo curso en días distintos | 50 |
| RB4 | Sin concentración de sesiones del mismo tipo en un día | 50 |
| RB5 | Proximidad histórica al semestre anterior | 10 |

Los pesos están definidos como diccionario configurable al inicio de `solver_ga.py`.

---

## Decisiones de diseño críticas

- **Disponibilidad de profesores:** Un profesor está disponible para un bloque de 2h solo si está disponible en AMBOS sub-bloques. Si no tiene disponibilidad declarada, se asume disponible siempre.
- **Distribución "2+1":** Un curso "2+1" necesita DOS variables de decisión en CP-SAT (una para el bloque de 2h, otra para el sub-bloque de 1h). **Esta complejidad está pendiente de resolver.**
- **Solo filas con `CURSO MANDANTE == "SI":** Las demás son versiones de planes de estudio anteriores.
- **Columnas duplicadas en el maestro:** `LUNES` (mayúscula, col ~57) = disponibilidad; `Lunes` (minúscula, col ~62) = horario ya asignado. El parser distingue por posición.
- **Nombres de profesores:** Se normalizan a lowercase para cruzar entre hojas (Banner usa formato `"APELLIDO/NOMBRE"`).
- **CP-SAT en modo satisfacción:** Para la Fase 1, no es necesario optimizar, solo encontrar una solución factible. El GA hace la optimización posterior.
- **Mutaciones del GA:** Deben verificar factibilidad tras cada operación genética. Si el individuo viola una restricción dura, descartar la operación.

---

## Scope v1 — simplificaciones deliberadas

Estas dos funcionalidades quedan **fuera de la v1** para simplificar la implementación inicial:

- **Distribución "2+1":** Las secciones CLAS con distribución "2+1" (2h un día + 1h otro) se **omiten** en v1. Tratar todos los cursos como distribución "2" (un bloque de 2h). Se incluirá en una versión posterior.
- **RD9 — Cursos minor:** Se **omite** en v1 por falta de datos sobre qué cursos son minor. Se incluirá cuando el cliente provea la lista definitiva.

En el parser/solver, filtrar o ignorar las secciones con `distribucion == "2+1"` antes de resolver.

---

## Ambigüedades pendientes (para versiones posteriores)

1. Lista definitiva de cursos minor (para RD9).
2. Modelado del sub-bloque de 1h en distribución "2+1".
3. ¿Salas especiales ocupadas por otras facultades? (restricciones externas desconocidas).
4. ¿Los electivos tienen alguna restricción de horario especial?
5. Calibración final de pesos de restricciones blandas con feedback de Francisca.

---

## KPIs objetivo

| KPI | Objetivo |
|-----|----------|
| TVRD: Tasa de violaciones de restricciones duras | **0%** |
| TRPH: Reducción del tiempo de planificación | **>80%** |
| NAMP: Ajustes manuales posteriores | **<5% de secciones** |
