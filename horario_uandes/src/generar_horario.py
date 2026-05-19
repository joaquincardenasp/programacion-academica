"""
generar_horario.py — Script principal del sistema de horarios UANDES.

Orquesta el pipeline completo:
    Módulo 1 (Parser)   → carga datos del Excel maestro y salas especiales
    Módulo 2 (CP-SAT)   → asigna bloques cumpliendo restricciones duras (RD1-RD8)
    Módulo 3 (GA)       → optimiza restricciones blandas (RB1-RB4)
    Módulo 4 (Exportar) → genera el Excel de salida

Uso:
    python generar_horario.py
    python generar_horario.py --maestro inputs/Maestro.xlsx --salas inputs/Salas.xlsx
    python generar_horario.py --sin-ga  (solo CP-SAT, sin optimización GA)

Salida:
    outputs/horario_YYYYMMDD_HHMM.xlsx
"""

import argparse
import io
import sys
import time
from pathlib import Path

# Codificación UTF-8 para salida en consola Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Agregar el directorio actual al path para imports locales
sys.path.insert(0, str(Path(__file__).parent))

from parser import cargar_datos
from solver_cpsat import resolver_cpsat
from solver_ga import optimizar_ga
from exportador import exportar_excel


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generador automático de horario base — FICA UANDES"
    )
    parser.add_argument(
        "--maestro",
        default="inputs/Maestro_202520.xlsx",
        help="Ruta al archivo Maestro Excel (default: inputs/Maestro_202520.xlsx)",
    )
    parser.add_argument(
        "--salas",
        default="inputs/SALAS_ESPECIALES_ING.xlsx",
        help="Ruta al archivo de salas especiales (default: inputs/SALAS_ESPECIALES_ING.xlsx)",
    )
    parser.add_argument(
        "--salida",
        default=None,
        help="Ruta del archivo de salida (default: outputs/horario_YYYYMMDD_HHMM.xlsx)",
    )
    parser.add_argument(
        "--sin-ga",
        action="store_true",
        help="Omitir el optimizador GA (solo CP-SAT)",
    )
    parser.add_argument(
        "--rb1", type=int, default=100, help="Peso RB1 (labs Programación consecutivos)"
    )
    parser.add_argument(
        "--rb2", type=int, default=80, help="Peso RB2 (prof jornada sin extremos)"
    )
    parser.add_argument(
        "--rb3", type=int, default=50, help="Peso RB3 (espaciado semanal)"
    )
    parser.add_argument(
        "--rb4", type=int, default=50, help="Peso RB4 (concentración diaria)"
    )
    args = parser.parse_args()

    # Ruta de salida con timestamp si no se especifica
    if args.salida is None:
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M")
        args.salida = f"outputs/horario_{ts}.xlsx"

    pesos = {
        "RB1": args.rb1,
        "RB2": args.rb2,
        "RB3": args.rb3,
        "RB4": args.rb4,
        "RB5": 0,
    }

    t0 = time.time()

    # --- Módulo 1: Parser ---
    datos = cargar_datos(args.maestro, args.salas)

    # --- Módulo 2: CP-SAT ---
    datos = resolver_cpsat(datos)

    asignadas_cpsat = sum(1 for s in datos.secciones if s.bloque_asignado is not None)
    if asignadas_cpsat == 0:
        print("\n  ERROR CRÍTICO: CP-SAT no encontró solución. Abortando.")
        sys.exit(1)

    # --- Módulo 3: GA (opcional) ---
    if not args.sin_ga:
        datos = optimizar_ga(datos, pesos=pesos)
    else:
        print("\n  [Módulo 3 GA omitido por --sin-ga]")

    # --- Módulo 4: Exportar ---
    exportar_excel(datos, args.salida)

    t_total = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"  Pipeline completado en {t_total:.1f}s")
    print(f"  Salida: {args.salida}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
