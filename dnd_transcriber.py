

import os
import re
import sys
import json
import argparse
import zipfile
import tempfile
from pathlib import Path
from datetime import timedelta

# ── Dependencias con mensajes de error amigables ─────────────────────────────

try:
    import whisper
except ImportError:
    print("❌ Falta whisper. Instálalo con:  pip install openai-whisper")
    sys.exit(1)

try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable, **kwargs):
        desc = kwargs.get("desc", "")
        total = kwargs.get("total", "?")
        for i, item in enumerate(iterable, 1):
            print(f"  {desc} [{i}/{total}]")
            yield item


# ── Utilidades ────────────────────────────────────────────────────────────────

def segundos_a_timestamp(segundos: float) -> str:
    """Convierte segundos a formato HH:MM:SS"""
    td = timedelta(seconds=int(segundos))
    horas, resto = divmod(td.seconds, 3600)
    minutos, segs = divmod(resto, 60)
    return f"{horas:02d}:{minutos:02d}:{segs:02d}"


def extraer_nombre_jugador(nombre_archivo: str) -> str:
    """
    Craig nombra los archivos como '1-NombreJugador.flac'.
    Esta función extrae solo el nombre del jugador.
    """
    stem = Path(nombre_archivo).stem          # '1-NombreJugador'
    partes = stem.split("-", maxsplit=1)      # ['1', 'NombreJugador']
    if len(partes) == 2:
        return partes[1].replace("_", " ").replace("-", " ").strip()
    return stem


def obtener_numero_pista(nombre_archivo: str) -> int:
    """Extrae el número de pista para ordenar los archivos correctamente."""
    stem = Path(nombre_archivo).stem
    match = re.match(r"^(\d+)", stem)
    return int(match.group(1)) if match else 999


def buscar_audios_craig(ruta: Path) -> list[Path]:
    """
    Busca archivos de audio válidos de Craig en la carpeta indicada.
    Craig produce .flac principalmente, pero también acepta .ogg y .mp3.
    """
    extensiones = {".flac", ".ogg", ".mp3", ".wav", ".m4a"}
    archivos = [
        f for f in ruta.iterdir()
        if f.is_file() and f.suffix.lower() in extensiones
    ]
    # Ordenar por número de pista (1-DM, 2-Jugador1, etc.)
    archivos.sort(key=lambda f: obtener_numero_pista(f.name))
    return archivos


def audio_tiene_voz(audio_path: Path, umbral_db: float = 50.0) -> bool:
    """
    Verifica si una pista tiene audio real usando ffmpeg directamente.
    Evita depender de pydub (incompatible con Python 3.13+).
    umbral_db: si el volumen medio es menor que -umbral_db dBFS se considera silencio.
    """
    import subprocess
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-i", str(audio_path),
                "-af", "volumedetect",
                "-f", "null", "-"
            ],
            capture_output=True, text=True, timeout=30
        )
        # ffmpeg escribe volumedetect en stderr
        output = result.stderr
        for linea in output.splitlines():
            if "mean_volume" in linea:
                # Ejemplo: "mean_volume: -91.5 dB"
                partes = linea.split(":")
                if len(partes) == 2:
                    valor = float(partes[1].strip().replace(" dB", ""))
                    return valor > -umbral_db
        return True  # Si no encontramos el dato, asumimos que tiene audio
    except Exception:
        return True  # Si ffmpeg falla, no saltamos la pista


# ── Limpieza de ruido ─────────────────────────────────────────────────────────

def limpiar_ruido_pista(audio_path: Path) -> Path:
    """
    Aplica reducción de ruido estacionario a una pista de audio.
    Usa los primeros 2 segundos como muestra del ruido de fondo (antes de que
    el jugador empiece a hablar) y lo elimina del resto del audio.

    Requiere: pip install noisereduce soundfile numpy

    Retorna la ruta del audio limpio (archivo temporal .wav).
    Si las dependencias no están o falla, retorna la ruta original sin cambios.
    """
    try:
        import noisereduce as nr
        import soundfile as sf
        import numpy as np
    except ImportError:
        print("   ⚠️  noisereduce/soundfile no instalados — transcribiendo sin limpiar.")
        print("      Instálalos con: pip install noisereduce soundfile numpy")
        return audio_path

    try:
        print(f"   🔉 Limpiando ruido de fondo...")

        # Leer el audio con soundfile (soporta .flac, .ogg, .wav, .mp3 vía ffmpeg)
        audio, sr = sf.read(str(audio_path), always_2d=False)

        # Si es estéreo, convertir a mono promediando canales
        if audio.ndim == 2:
            audio = audio.mean(axis=1)

        # Usar los primeros 2 segundos como perfil de ruido
        # (normalmente es el silencio/ruido antes de que el jugador hable)
        muestra_ruido = audio[:sr * 60]

        # Reducción de ruido estacionario
        # stationary=True  → ideal para ruidos constantes (ventilador, hum eléctrico)
        # prop_decrease     → qué tanto reducir el ruido (0.0 = nada, 1.0 = todo)
        audio_limpio = nr.reduce_noise(
            y=audio,
            sr=sr,
            y_noise=muestra_ruido,
            prop_decrease=0.90,
            stationary=True,
            n_jobs=-1,          # usar todos los núcleos disponibles
        )

        # Guardar en un archivo temporal .wav (Whisper lo acepta bien)
        tmp = tempfile.NamedTemporaryFile(
            suffix="_limpio.wav",
            prefix=audio_path.stem + "_",
            delete=False,
        )
        sf.write(tmp.name, audio_limpio, sr)
        print(f"   ✓  Audio limpio guardado temporalmente")
        return Path(tmp.name)

    except Exception as e:
        print(f"   ⚠️  Error al limpiar ruido: {e} — usando audio original")
        return audio_path


# ── Transcripción ─────────────────────────────────────────────────────────────

def transcribir_pista(
    modelo,
    audio_path: Path,
    idioma: str | None = None,
) -> list[dict]:
    """
    Transcribe una pista de audio usando Whisper.
    Retorna lista de segmentos con: start, end, text
    """
    opciones = {
        "task": "transcribe",
        "verbose": False,
    }
    if idioma:
        opciones["language"] = idioma

    resultado = modelo.transcribe(str(audio_path), **opciones)
    return resultado.get("segments", [])


# ── Mezcla de pistas ──────────────────────────────────────────────────────────

def mezclar_segmentos(pistas_transcritas: list[dict]) -> list[dict]:
    """
    Recibe una lista de pistas con sus segmentos y las ordena cronológicamente.

    pistas_transcritas: [
        {"jugador": "DungeonMaster", "segmentos": [{"start": 0.0, "end": 5.2, "text": "..."}, ...]},
        {"jugador": "Arthas",        "segmentos": [...]},
        ...
    ]

    Retorna una lista plana de segmentos ordenados por tiempo de inicio.
    """
    todos = []
    for pista in pistas_transcritas:
        for seg in pista["segmentos"]:
            todos.append({
                "jugador": pista["jugador"],
                "start":   seg["start"],
                "end":     seg["end"],
                "texto":   seg["text"].strip(),
            })

    # Ordenar por tiempo de inicio
    todos.sort(key=lambda s: s["start"])
    return todos


def limpiar_alucinaciones(segmentos: list[dict]) -> list[dict]:
    """
    Elimina el ruido que Whisper genera al transcribir silencio o micrófono abierto.
    Aplica tres filtros en cadena:

    FILTRO 1 — Tokens de ruido conocidos
        Whisper en español tiene tokens "favoritos" para representar silencio:
        sílabas sueltas ('de', 'y', 'la', 'el'), puntos suspensivos ('...'),
        frases genéricas de relleno, etc. Los eliminamos por texto exacto.

    FILTRO 2 — Segmentos demasiado cortos en relación a su duración
        Un segmento de 10 segundos con solo 1 palabra es casi siempre ruido.
        Ratio mínimo: al menos 1 palabra cada 4 segundos para segmentos largos.

    FILTRO 3 — Alucinaciones por repetición (el más importante para este caso)
        Cuando Whisper transcribe silencio prolongado en una pista, tiende a
        repetir en bucle la última frase real que escuchó. Detectamos esto
        buscando si un mismo texto aparece ≥ 3 veces en la misma pista.
        Las repeticiones extra se descartan, conservando solo la primera aparición.
    """

    # ── FILTRO 1: tokens de ruido conocidos ──────────────────────────────────
    # Texto normalizado (minúsculas, sin puntuación lateral) para comparar
    RUIDO_EXACTO = {
        # Sílabas sueltas frecuentes en español
        "de", "y", "la", "el", "en", "a", "e", "o", "i", "u",
        "del", "al", "un", "una", "los", "las",
        # Puntuación y tokens especiales de Whisper
        "...", "…", ".", ",", "-", "_",
        # Frases genéricas que Whisper inventa en silencio
        #"gracias", "gracias.", "ok", "ok.", "sí", "sí.", "no", "no.",
        #"hmm", "mmm", "eh", "ah", "uh",
        # Tokens internos que Whisper a veces filtra mal
        "[música]", "[music]", "[silencio]", "[ruido]",
        "(música)", "(music)",
    }

    def es_ruido_exacto(texto: str) -> bool:
        normalizado = texto.lower().strip().rstrip(".,;:!¡?¿").strip()
        return normalizado in RUIDO_EXACTO or normalizado == ""

    paso1 = [s for s in segmentos if not es_ruido_exacto(s["texto"])]

    # ── FILTRO 2: ratio palabras/duración ────────────────────────────────────
    def densidad_ok(seg: dict) -> bool:
        duracion = seg["end"] - seg["start"]
        palabras = len(seg["texto"].split())
        # Segmentos cortos (< 3s): mínimo 2 palabras
        if duracion < 3.0:
            return palabras >= 2
        # Segmentos largos: al menos 1 palabra por cada 4 segundos
        return palabras >= max(2, duracion / 4.0)

    paso2 = [s for s in paso1 if densidad_ok(s)]

    # ── FILTRO 3: alucinaciones por repetición ────────────────────────────────
    # Contamos cuántas veces aparece cada texto POR jugador
    from collections import defaultdict
    conteo: dict[tuple, int] = defaultdict(int)
    resultado = []

    for seg in paso2:
        clave = (seg["jugador"], seg["texto"].lower().strip())
        conteo[clave] += 1
        # Permitimos hasta 2 apariciones del mismo texto por jugador
        # (puede decir "gracias" dos veces de verdad, pero no 20)
        if conteo[clave] <= 2:
            resultado.append(seg)

    eliminados = len(segmentos) - len(resultado)
    if eliminados > 0:
        print(f"   🧹 Limpieza: {len(segmentos)} segmentos → {len(resultado)} "
              f"(eliminados {eliminados} alucinaciones/ruido)")

    return resultado


# ── Formato de salida ─────────────────────────────────────────────────────────

def formatear_transcripcion(
    segmentos: list[dict],
    titulo: str = "Transcripción de Sesión DnD",
    mostrar_timestamps: bool = True,
) -> str:
    """
    Genera el texto final de la transcripción.

    Ejemplo de salida:

        ═══════════════════════════════════════
        Transcripción de Sesión DnD
        ═══════════════════════════════════════

        [00:00:03] DungeonMaster:
          Bienvenidos a las mazmorras de Barovia...

        [00:00:15] Arthas:
          ¡Desenvainamos espadas!
    """
    lineas = []
    separador = "═" * 50

    lineas.append(separador)
    lineas.append(f"  {titulo}")
    lineas.append(separador)
    lineas.append("")

    jugador_anterior = None

    for seg in segmentos:
        jugador  = seg["jugador"]
        texto    = seg["texto"]
        ts_ini   = segundos_a_timestamp(seg["start"])

        # Agrupar líneas del mismo jugador si son consecutivas (evita spam de etiquetas)
        if jugador != jugador_anterior:
            if jugador_anterior is not None:
                lineas.append("")  # Línea en blanco entre cambios de hablante

            if mostrar_timestamps:
                lineas.append(f"[{ts_ini}] {jugador}:")
            else:
                lineas.append(f"{jugador}:")

        lineas.append(f"  {texto}")
        jugador_anterior = jugador

    lineas.append("")
    lineas.append(separador)
    lineas.append(f"  Total de segmentos: {len(segmentos)}")
    lineas.append(separador)

    return "\n".join(lineas)


def guardar_json(
    segmentos: list[dict],
    ruta_salida: Path,
) -> None:
    """
    Guarda también un JSON con todos los datos para uso en otros scripts.
    Útil si quieres hacer búsquedas, estadísticas o integrar con otras herramientas.
    """
    ruta_json = ruta_salida.with_suffix(".json")
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump(segmentos, f, ensure_ascii=False, indent=2)
    print(f"📄 JSON guardado en: {ruta_json}")


# ── Pipeline principal ────────────────────────────────────────────────────────

def procesar_sesion(
    ruta_entrada: str,
    ruta_salida: str,
    modelo_nombre: str = "small",
    idioma: str | None = None,
    titulo: str = "Transcripción de Sesión DnD",
    guardar_json_flag: bool = True,
    mostrar_timestamps: bool = True,
    pistas_a_limpiar: list[str] | None = None,
) -> None:
    """
    Pipeline completo:
    1. Busca los archivos de Craig en la carpeta indicada (o extrae un .zip)
    2. Carga el modelo Whisper
    3. Transcribe cada pista por separado (aplicando limpieza de ruido si se indica)
    4. Mezcla y ordena cronológicamente
    5. Genera el archivo de texto final
    """

    ruta_entrada = Path(ruta_entrada)
    ruta_salida  = Path(ruta_salida)

    # ── 1. Resolver la entrada ────────────────────────────────────────────────

    directorio_trabajo = ruta_entrada

    # Si pasaron directamente el .zip de Craig, lo extraemos en un temp dir
    if ruta_entrada.is_file() and ruta_entrada.suffix.lower() == ".zip":
        print(f"📦 Extrayendo ZIP de Craig: {ruta_entrada.name}")
        temp_dir = tempfile.mkdtemp(prefix="craig_")
        with zipfile.ZipFile(ruta_entrada, "r") as zf:
            zf.extractall(temp_dir)
        directorio_trabajo = Path(temp_dir)
        print(f"   Extraído en: {directorio_trabajo}")

    if not directorio_trabajo.is_dir():
        print(f"❌ No se encontró la carpeta: {directorio_trabajo}")
        sys.exit(1)

    # ── 2. Detectar pistas de Craig ───────────────────────────────────────────

    archivos_audio = buscar_audios_craig(directorio_trabajo)

    if not archivos_audio:
        print(f"❌ No se encontraron archivos de audio en: {directorio_trabajo}")
        print("   Formatos soportados: .flac, .ogg, .mp3, .wav, .m4a")
        sys.exit(1)

    print(f"\n🎲 {len(archivos_audio)} pistas de audio encontradas:")
    for af in archivos_audio:
        jugador = extraer_nombre_jugador(af.name)
        print(f"   🎙️  {jugador}  ({af.name})")

    # Filtrar pistas que son solo silencio
    pistas_activas = []
    for af in archivos_audio:
        if audio_tiene_voz(af):
            pistas_activas.append(af)
        else:
            print(f"   ⏭️  Saltando pista silenciosa: {af.name}")

    if not pistas_activas:
        print("❌ Todas las pistas están en silencio.")
        sys.exit(1)

    print(f"\n✅ {len(pistas_activas)} pistas con audio para transcribir\n")

    # ── 3. Cargar modelo Whisper ──────────────────────────────────────────────

    print(f"🧠 Cargando modelo Whisper '{modelo_nombre}'...")
    print("   (La primera vez descarga el modelo, puede tardar unos minutos)")
    modelo = whisper.load_model(modelo_nombre)
    print("   Modelo listo ✓\n")

    # ── 4. Transcribir cada pista ─────────────────────────────────────────────

    pistas_transcritas = []

    # Normalizar la lista de pistas a limpiar (minúsculas para comparar sin importar mayúsculas)
    limpiar_set = {n.lower() for n in (pistas_a_limpiar or [])}
    if limpiar_set:
        print(f"🔉 Pistas con reducción de ruido activada: {', '.join(pistas_a_limpiar)}\n")

    archivos_temporales = []  # para borrarlos al final

    for audio_path in tqdm(pistas_activas, desc="Transcribiendo pistas", total=len(pistas_activas)):
        jugador = extraer_nombre_jugador(audio_path.name)
        print(f"\n🎙️  Transcribiendo: {jugador}...")

        # Aplicar limpieza de ruido si este jugador está en la lista
        ruta_a_transcribir = audio_path
        if jugador.lower() in limpiar_set:
            ruta_limpia = limpiar_ruido_pista(audio_path)
            if ruta_limpia != audio_path:
                archivos_temporales.append(ruta_limpia)
                ruta_a_transcribir = ruta_limpia

        segmentos = transcribir_pista(modelo, ruta_a_transcribir, idioma)

        if not segmentos:
            print(f"   ⚠️  Sin segmentos reconocidos para {jugador}")
            continue

        pistas_transcritas.append({
            "jugador":   jugador,
            "segmentos": segmentos,
        })

        print(f"   ✓  {len(segmentos)} segmentos transcritos")

    if not pistas_transcritas:
        print("❌ No se pudo transcribir ninguna pista.")
        sys.exit(1)

    # ── 5. Mezclar y limpiar ──────────────────────────────────────────────────

    print("\n🔀 Mezclando y ordenando cronológicamente...")
    segmentos_mezclados = mezclar_segmentos(pistas_transcritas)

    print("🧹 Limpiando alucinaciones y ruido de fondo...")
    segmentos_limpios = limpiar_alucinaciones(segmentos_mezclados)



    # ── 6. Generar y guardar el resultado ─────────────────────────────────────

    transcripcion = formatear_transcripcion(
        segmentos_limpios,
        titulo=titulo,
        mostrar_timestamps=mostrar_timestamps,
    )

    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    ruta_salida.write_text(transcripcion, encoding="utf-8")
    print(f"\n✅ Transcripción guardada en: {ruta_salida}")

    if guardar_json_flag:
        guardar_json(segmentos_limpios, ruta_salida)

    # Limpiar archivos temporales de audio procesado
    for tmp in archivos_temporales:
        try:
            tmp.unlink()
        except Exception:
            pass

    # Vista previa de las primeras líneas
    print("\n── Vista previa ──────────────────────────────────────")
    for linea in transcripcion.split("\n")[:20]:
        print(linea)
    print("...")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Transcribe sesiones de DnD grabadas con Craig (Discord)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Carpeta con las pistas extraídas
  python dnd_transcriber.py --input ./sesion_01 --output sesion_01.txt

  # Directamente el ZIP de Craig
  python dnd_transcriber.py --input craig_sesion.zip --output sesion_01.txt

  # Con título y forzando español
  python dnd_transcriber.py --input ./sesion_01 --output sesion_01.txt \\
      --titulo "Ravenloft Sesión 3" --idioma es

  # Modelo grande para mejor precisión (más lento)
  python dnd_transcriber.py --input ./sesion_01 --output sesion_01.txt --modelo large
        """
    )

    parser.add_argument(
        "--input", "-i", required=True,
        help="Carpeta con las pistas de Craig, o ruta al .zip descargado de Craig"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="Archivo de texto de salida (ej: sesion_01.txt)"
    )
    parser.add_argument(
        "--modelo", "-m", default="small",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Modelo Whisper a usar (default: small). Mayor modelo = más preciso pero más lento"
    )
    parser.add_argument(
        "--idioma", "-l", default=None,
        help="Idioma del audio (ej: 'es' para español, 'en' para inglés). Omitir = autodetectar"
    )
    parser.add_argument(
        "--titulo", "-t", default="Transcripción de Sesión DnD",
        help="Título que aparecerá en el encabezado del archivo de transcripción"
    )
    parser.add_argument(
        "--sin-json", action="store_true",
        help="No generar el archivo JSON adicional con los datos en crudo"
    )
    parser.add_argument(
        "--sin-timestamps", action="store_true",
        help="Omitir los timestamps [HH:MM:SS] en la transcripción"
    )
    parser.add_argument(
        "--limpiar-pistas", nargs="+", metavar="JUGADOR", default=None,
        help=(
            "Nombres de jugadores cuya pista recibirá reducción de ruido antes de "
            "transcribir. Ej: --limpiar-pistas darknesswolf88 otrojugador\n"
            "Requiere: pip install noisereduce soundfile numpy"
        )
    )

    args = parser.parse_args()

    print("\n🐉 DnD Session Transcriber — Craig + Whisper\n")

    procesar_sesion(
        ruta_entrada        = args.input,
        ruta_salida         = args.output,
        modelo_nombre       = args.modelo,
        idioma              = args.idioma,
        titulo              = args.titulo,
        guardar_json_flag   = not args.sin_json,
        mostrar_timestamps  = not args.sin_timestamps,
        pistas_a_limpiar    = args.limpiar_pistas,
    )


if __name__ == "__main__":
    main()