"""
╔══════════════════════════════════════════════════════════════╗
║        DnD Session Merger — Combinador de Sesiones           ║
║  Toma varios JSON generados por dnd_transcriber.py y produce ║
║  una transcripción cronológica unificada en TXT              ║
╚══════════════════════════════════════════════════════════════╝

CÓMO FUNCIONA:
    Cada JSON generado por dnd_transcriber.py contiene segmentos con timestamps
    relativos al inicio de ESA sesión (00:00:00 = inicio de la grabación).

    Este script tiene dos modos:

    MODO 1 — Sesiones independientes (timestamps se reinician en cada sesión)
        Los diálogos de cada sesión se agrupan juntos con un encabezado.
        Útil para: "quiero ver todas las sesiones en un solo archivo pero separadas"

        Ejemplo de salida:
            ══════════════════════════════════════
              ▶ SESIÓN 1 — sesion_01.json
            ══════════════════════════════════════
            [00:00:05] velkanakhera:
              Bienvenidos...
            [00:00:10] setywolf:
              ¡Aventura!

            ══════════════════════════════════════
              ▶ SESIÓN 2 — sesion_02.json
            ══════════════════════════════════════
            [00:00:03] velkanakhera:
              Continuando desde donde lo dejamos...

    MODO 2 — Cronología continua (timestamps acumulados entre sesiones)
        Los timestamps se suman: si la sesión 1 duró 2h30m, la sesión 2
        empieza desde 02:30:00 en el archivo final.
        Útil para: "quiero leer toda la campaña como si fuera una sola sesión"

        Ejemplo de salida:
            [00:00:05] velkanakhera:
              Bienvenidos...
            [02:30:03] velkanakhera:   ← sesión 2, relativo al total acumulado
              Continuando desde donde lo dejamos...

USO BÁSICO (modo sesiones separadas, orden de los archivos que pases):
    python dnd_combinar_sesiones.py --input sesion_01.json sesion_02.json sesion_03.json --output campana.txt

USANDO UNA CARPETA (toma todos los JSON de la carpeta, ordena por nombre de archivo):
    python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt

MODO CRONOLOGÍA CONTINUA:
    python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt --continuo

CON TÍTULO:
    python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt --titulo "Campaña Ravenloft"

OMITIR JUGADORES (misma lógica que dnd_transcriber.py):
    python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt --omitir darknesswolf88
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import timedelta


# ── Utilidades ────────────────────────────────────────────────────────────────

def segundos_a_timestamp(segundos: float) -> str:
    """Convierte segundos a formato HH:MM:SS"""
    total = int(max(0, segundos))
    horas, resto = divmod(total, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segs:02d}"


def cargar_json(ruta: Path) -> list[dict]:
    """
    Carga un JSON de sesión generado por dnd_transcriber.py.
    Valida que tenga el formato esperado y avisa si algo falla.
    """
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Error al leer {ruta.name}: JSON inválido — {e}")
        sys.exit(1)
    except FileNotFoundError:
        print(f"❌ Archivo no encontrado: {ruta}")
        sys.exit(1)

    if not isinstance(datos, list):
        print(f"❌ {ruta.name} no tiene el formato esperado (debe ser una lista de segmentos)")
        sys.exit(1)

    if datos and not all(k in datos[0] for k in ("jugador", "start", "end", "texto")):
        print(f"⚠️  {ruta.name}: los segmentos no tienen los campos esperados "
              f"(jugador, start, end, texto). ¿Es un JSON de dnd_transcriber.py?")

    return datos


def duracion_sesion(segmentos: list[dict]) -> float:
    """Retorna el timestamp del último segmento (duración aproximada de la sesión)."""
    if not segmentos:
        return 0.0
    return max(s["end"] for s in segmentos)


# ── Carga y preparación ───────────────────────────────────────────────────────

def buscar_jsons_en_carpeta(carpeta: Path) -> list[Path]:
    """
    Busca todos los archivos .json en la carpeta y los ordena por nombre.
    El orden alfabético funciona bien si los archivos se llaman:
      sesion_01.json, sesion_02.json, ...
    """
    archivos = sorted(carpeta.glob("*.json"))
    if not archivos:
        print(f"❌ No se encontraron archivos .json en: {carpeta}")
        sys.exit(1)
    return archivos


def preparar_segmentos(
    archivos: list[Path],
    omitir: set[str],
    modo_continuo: bool,
) -> list[dict]:
    """
    Carga todos los JSON y prepara los segmentos para la salida final.

    Agrega dos campos a cada segmento:
      - sesion_nombre : nombre del archivo JSON de origen
      - sesion_idx    : índice de la sesión (0, 1, 2...) para desempate de timestamps
      - start_final   : timestamp definitivo (original o acumulado según modo)

    Regla de desempate para timestamps iguales entre sesiones distintas:
      Se ordena primero por start_final, luego por sesion_idx (el archivo que
      viene antes en la lista gana), y por último por el start original dentro
      de la misma sesión.
    """
    todos = []
    offset_acumulado = 0.0  # solo usado en modo continuo

    for idx, ruta in enumerate(archivos):
        print(f"   📂 Cargando: {ruta.name}")
        segmentos = cargar_json(ruta)

        # Filtrar jugadores omitidos
        antes = len(segmentos)
        segmentos = [s for s in segmentos if s["jugador"].lower() not in omitir]
        if antes != len(segmentos):
            print(f"      ⏭️  {antes - len(segmentos)} segmentos omitidos de jugadores en lista negra")

        if not segmentos:
            print(f"      ⚠️  Sin segmentos útiles en {ruta.name}, se saltará")
            continue

        dur = duracion_sesion(segmentos)

        for seg in segmentos:
            todos.append({
                **seg,
                "sesion_nombre": ruta.stem,
                "sesion_idx":    idx,
                "start_final":   seg["start"] + offset_acumulado,
            })

        if modo_continuo:
            offset_acumulado += dur
            print(f"      ✓  {len(segmentos)} segmentos | duración: {segundos_a_timestamp(dur)} "
                  f"| offset acumulado: {segundos_a_timestamp(offset_acumulado)}")
        else:
            print(f"      ✓  {len(segmentos)} segmentos | duración: {segundos_a_timestamp(dur)}")

    if not todos:
        print("❌ No quedaron segmentos después de filtrar. Revisa los archivos y la lista --omitir.")
        sys.exit(1)

    # Ordenar: primero por timestamp final, luego por índice de sesión (desempate)
    todos.sort(key=lambda s: (s["start_final"], s["sesion_idx"], s["start"]))

    return todos


# ── Formato de salida ─────────────────────────────────────────────────────────

def formatear_continuo(
    segmentos: list[dict],
    titulo: str,
) -> str:
    """
    Modo continuo: una sola línea de tiempo sin separadores de sesión.
    Los timestamps reflejan la posición acumulada en toda la campaña.
    """
    lineas = []
    sep = "═" * 50

    lineas.append(sep)
    lineas.append(f"  {titulo}")
    lineas.append(sep)
    lineas.append("")

    jugador_anterior = None
    sesion_anterior  = None

    for seg in segmentos:
        jugador = seg["jugador"]
        texto   = seg["texto"]
        ts      = segundos_a_timestamp(seg["start_final"])
        sesion  = seg["sesion_nombre"]

        # Pequeña nota cuando cambia de sesión (sin romper el flujo)
        if sesion != sesion_anterior:
            if sesion_anterior is not None:
                lineas.append("")
                lineas.append(f"  ── {sesion} ──")
                lineas.append("")
            sesion_anterior = sesion
            jugador_anterior = None  # forzar reimpresión del nombre

        if jugador != jugador_anterior:
            if jugador_anterior is not None:
                lineas.append("")
            lineas.append(f"[{ts}] {jugador}:")
            jugador_anterior = jugador

        lineas.append(f"  {texto}")

    lineas.append("")
    lineas.append(sep)
    lineas.append(f"  Total de segmentos: {len(segmentos)}")
    lineas.append(sep)

    return "\n".join(lineas)


def formatear_separado(
    segmentos: list[dict],
    titulo: str,
) -> str:
    """
    Modo separado: cada sesión tiene su propio encabezado.
    Los timestamps son relativos al inicio de cada sesión (como el original).
    """
    lineas = []
    sep       = "═" * 50
    sep_light = "─" * 50

    lineas.append(sep)
    lineas.append(f"  {titulo}")
    lineas.append(sep)

    sesion_actual    = None
    jugador_anterior = None
    total_sesiones   = len({s["sesion_nombre"] for s in segmentos})
    num_sesion       = 0

    for seg in segmentos:
        jugador = seg["jugador"]
        texto   = seg["texto"]
        ts      = segundos_a_timestamp(seg["start"])   # timestamp original de la sesión
        sesion  = seg["sesion_nombre"]

        # Encabezado de sesión
        if sesion != sesion_actual:
            num_sesion += 1
            sesion_actual    = sesion
            jugador_anterior = None

        if jugador != jugador_anterior:
            if jugador_anterior is not None:
                lineas.append("")
            lineas.append(f"[{ts}] {jugador}:")
            jugador_anterior = jugador

        lineas.append(f"  {texto}")

    lineas.append("")
    lineas.append(sep)
    lineas.append(f"  {total_sesiones} sesiones | {len(segmentos)} segmentos totales")
    lineas.append(sep)

    return "\n".join(lineas)


# ── Pipeline principal ────────────────────────────────────────────────────────

def combinar_sesiones(
    archivos:      list[Path],
    ruta_salida:   Path,
    titulo:        str  = "Campaña DnD",
    modo_continuo: bool = False,
    omitir:        list[str] | None = None,
) -> None:

    omitir_set = {n.lower() for n in (omitir or [])}

    print(f"\n📜 {len(archivos)} archivo(s) a combinar:")
    segmentos = preparar_segmentos(archivos, omitir_set, modo_continuo)

    print(f"\n✍️  Generando transcripción {'continua' if modo_continuo else 'por sesiones'}...")

    if modo_continuo:
        texto = formatear_continuo(segmentos, titulo)
    else:
        texto = formatear_separado(segmentos, titulo)

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(texto, encoding="utf-8")

    print(f"✅ Archivo generado: {ruta_salida}")
    print(f"   {len(segmentos)} segmentos totales\n")

    # Vista previa
    print("── Vista previa ──────────────────────────────────────")
    for linea in texto.split("\n")[:25]:
        print(linea)
    print("...")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Combina varios JSON de sesiones DnD en una transcripción cronológica",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Archivos específicos en orden cronológico
  python dnd_combinar_sesiones.py \\
      --input sesion_01.json sesion_02.json sesion_03.json \\
      --output campana.txt

  # Todos los JSON de una carpeta (orden alfabético)
  python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt

  # Cronología continua (timestamps acumulados)
  python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt --continuo

  # Con título y omitiendo un jugador ruidoso
  python dnd_combinar_sesiones.py --carpeta ./sesiones/ --output campana.txt \\
      --titulo "Campaña Ravenloft" --omitir darknesswolf88
        """
    )

    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument(
        "--input", "-i", nargs="+", metavar="ARCHIVO.json",
        help="Archivos JSON a combinar, en orden cronológico"
    )
    grupo.add_argument(
        "--carpeta", "-c", metavar="CARPETA",
        help="Carpeta con archivos .json (se ordenan por nombre de archivo)"
    )

    parser.add_argument(
        "--output", "-o", required=True,
        help="Archivo TXT de salida"
    )
    parser.add_argument(
        "--titulo", "-t", default="Campaña DnD",
        help="Título de la campaña para el encabezado (default: 'Campaña DnD')"
    )
    parser.add_argument(
        "--continuo", action="store_true",
        help="Modo cronología continua: los timestamps se acumulan entre sesiones"
    )
    parser.add_argument(
        "--omitir", nargs="+", metavar="JUGADOR", default=None,
        help="Jugadores a omitir completamente. Ej: --omitir darknesswolf88"
    )

    args = parser.parse_args()

    # Resolver lista de archivos
    if args.input:
        archivos = [Path(p) for p in args.input]
        for af in archivos:
            if not af.exists():
                print(f"❌ No se encontró el archivo: {af}")
                sys.exit(1)
    else:
        archivos = buscar_jsons_en_carpeta(Path(args.carpeta))

    print("\n🐉 DnD Session Merger\n")

    combinar_sesiones(
        archivos      = archivos,
        ruta_salida   = Path(args.output),
        titulo        = args.titulo,
        modo_continuo = args.continuo,
        omitir        = args.omitir,
    )


if __name__ == "__main__":
    main()
