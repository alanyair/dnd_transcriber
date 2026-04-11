"""
╔══════════════════════════════════════════════════════════════╗
║          DnD Session Transcriber — Craig + Whisper           ║
║  Convierte las pistas de Craig en una transcripción unificada ║
╚══════════════════════════════════════════════════════════════╝

INSTALACIÓN DE DEPENDENCIAS:
    pip install openai-whisper tqdm

    También necesitas ffmpeg instalado en tu sistema:
    - Windows: https://ffmpeg.org/download.html  (o: winget install ffmpeg)
    - Mac:     brew install ffmpeg
    - Linux:   sudo apt install ffmpeg

    NOTA: pydub NO es necesario (no funciona en Python 3.13+).
    La detección de silencio se hace directamente con ffmpeg.

CÓMO USAR CRAIG:
    1. Invita a Craig a tu servidor de Discord: https://craig.chat
    2. Escribe !join en el canal de voz para iniciar la grabación
    3. Al terminar la sesión escribe !stop
    4. Craig te enviará un link de descarga con un .zip
    5. El .zip contiene archivos como:
         1-DungeonMaster.flac
         2-Arthas.flac
         3-Gandalf.flac
         ...
    6. Extrae el .zip en una carpeta y pásale la ruta a este script

USO BÁSICO:
    python dnd_transcriber.py --input ./sesion_dnd --output sesion_01.txt

USO CON NOMBRE DE SESIÓN:
    python dnd_transcriber.py --input ./sesion_dnd --output sesion_01.txt --titulo "Campaña Ravenloft - Sesión 1"

CAMBIAR MODELO DE WHISPER (más grande = más preciso pero más lento):
    python dnd_transcriber.py --input ./sesion_dnd --output sesion_01.txt --modelo medium
    Modelos disponibles: tiny, base, small, medium, large (default: small)

CAMBIAR IDIOMA (por defecto detecta automático, pero forzar español mejora precisión):
    python dnd_transcriber.py --input ./sesion_dnd --output sesion_01.txt --idioma es

LIMPIAR PISTAS CON RUIDO (aplica reducción de ruido antes de transcribir):
    python dnd_transcriber.py --input ./sesion_dnd --output sesion_01.txt \\
        --limpiar-pistas darknesswolf88 otrojugador

    Puedes poner uno o varios nombres separados por espacio. El nombre debe coincidir
    con el nombre del jugador en Craig (sin el número de pista).
    Requiere instalar: pip install noisereduce soundfile numpy
    Si no están instalados, el script avisa pero continúa sin limpiar.
"""