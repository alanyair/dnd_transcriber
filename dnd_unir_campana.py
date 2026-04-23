
import json
import sys
import argparse
from pathlib import Path


# ── Utilidades ────────────────────────────────────────────────────────────────

def segundos_a_timestamp(segundos: float) -> str:
    total = int(max(0, segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segs:02d}"


def cargar_json(ruta: Path) -> list[dict]:
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ JSON inválido en {ruta.name}: {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"❌ Archivo no encontrado: {ruta}")
        sys.exit(1)

    if not isinstance(datos, list):
        print(f"❌ {ruta.name} no tiene el formato esperado (lista de segmentos)")
        sys.exit(1)

    return datos


def buscar_jsons(carpeta: Path) -> list[Path]:
    archivos = sorted(carpeta.glob("*.json"))
    if not archivos:
        print(f"❌ No hay archivos .json en: {carpeta}")
        sys.exit(1)
    return archivos


# ── Pipeline ──────────────────────────────────────────────────────────────────

def construir_timeline(
    archivos: list[Path],
    omitir: set[str],
) -> list[dict]:
    """
    Carga cada JSON, aplica el offset acumulado a sus timestamps
    y devuelve una lista plana ordenada cronológicamente.

    Desempate de timestamps iguales: el archivo que viene antes en la lista
    siempre aparece primero (sesion_idx como criterio secundario).
    """
    timeline = []
    offset   = 0.0

    for idx, ruta in enumerate(archivos):
        segmentos = cargar_json(ruta)

        # Filtrar jugadores omitidos
        segmentos = [s for s in segmentos if s["jugador"].lower() not in omitir]

        if not segmentos:
            print(f"   ⚠️  {ruta.name}: sin segmentos útiles, se saltará")
            continue

        duracion = max(s["end"] for s in segmentos)

        print(f"   ✓  {ruta.name} — {len(segmentos)} segmentos "
              f"| duración {segundos_a_timestamp(duracion)} "
              f"| inicia en {segundos_a_timestamp(offset)}")

        for seg in segmentos:
            timeline.append({
                **seg,
                "start_abs":  seg["start"] + offset,
                "end_abs":    seg["end"]   + offset,
                "sesion_idx": idx,
            })

        offset += duracion

    if not timeline:
        print("❌ No quedaron segmentos. Revisa los archivos y la lista --omitir.")
        sys.exit(1)

    # Orden: timestamp absoluto → índice de sesión (desempate) → start original
    timeline.sort(key=lambda s: (s["start_abs"], s["sesion_idx"], s["start"]))

    print(f"\n   Duración total de la campaña: {segundos_a_timestamp(offset)}")
    print(f"   Segmentos totales: {len(timeline)}")

    return timeline


def formatear(timeline: list[dict], titulo: str) -> str:
    sep = "═" * 50
    lineas = []

    lineas.append(sep)
    lineas.append(f"  {titulo}")
    lineas.append(sep)
    lineas.append("")

    jugador_anterior = None

    for seg in timeline:
        jugador = seg["jugador"]
        texto   = seg["texto"]
        ts      = segundos_a_timestamp(seg["start_abs"])

        if jugador != jugador_anterior:
            if jugador_anterior is not None:
                lineas.append("")
            lineas.append(f"[{ts}] {jugador}:")
            jugador_anterior = jugador

        lineas.append(f"  {texto}")

    lineas.append("")
    lineas.append(sep)
    lineas.append(f"  Total de segmentos: {len(timeline)}")
    lineas.append(sep)

    return "\n".join(lineas)


def unir_campana(
    archivos:    list[Path],
    ruta_salida: Path,
    titulo:      str,
    omitir:      list[str] | None,
) -> None:
    omitir_set = {n.lower() for n in (omitir or [])}

    print(f"\n📜 {len(archivos)} sesión(es) a unir:\n")
    timeline = construir_timeline(archivos, omitir_set)

    print("\n✍️  Generando archivo...")
    texto = formatear(timeline, titulo)

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(texto, encoding="utf-8")

    print(f"✅ Guardado en: {ruta_salida}\n")

    print("── Vista previa ──────────────────────────────────────")
    for linea in texto.split("\n")[:20]:
        print(linea)
    print("...")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Une varios JSON de sesiones DnD en una línea de tiempo continua",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python dnd_unir_campana.py \\
      --input sesion_01.json sesion_02.json sesion_03.json \\
      --output campana.txt

  python dnd_unir_campana.py --carpeta ./sesiones/ --output campana.txt

  python dnd_unir_campana.py --carpeta ./sesiones/ --output campana.txt \\
      --titulo "Ravenloft: La Maldición de Strahd" --omitir darknesswolf88
        """
    )

    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--input", "-i", nargs="+", metavar="ARCHIVO.json",
        help="Archivos JSON en orden cronológico"
    )
    grupo.add_argument(
        "--carpeta", "-c", metavar="CARPETA",
        help="Carpeta con .json (ordenados alfabéticamente)"
    )
    parser.add_argument("--output",  "-o", required=True, help="Archivo TXT de salida")
    parser.add_argument("--titulo",  "-t", default="Campaña DnD", help="Título del encabezado")
    parser.add_argument(
        "--omitir", nargs="+", metavar="JUGADOR", default=None,
        help="Jugadores a omitir. Ej: --omitir darknesswolf88"
    )

    args = parser.parse_args()

    if args.input:
        archivos = [Path(p) for p in args.input]
        for af in archivos:
            if not af.exists():
                print(f"❌ No encontrado: {af}")
                sys.exit(1)
    else:
        archivos = buscar_jsons(Path(args.carpeta))

    print("\n🐉 DnD Campaign Timeline\n")

    unir_campana(
        archivos    = archivos,
        ruta_salida = Path(args.output),
        titulo      = args.titulo,
        omitir      = args.omitir,
    )


if __name__ == "__main__":
    main()
