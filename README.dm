╔══════════════════════════════════════════════════════════════╗
║          DnD Session Transcriber — Craig + Whisper           ║
║       Convierte las pistas de Craig en una transcripción     ║
╚══════════════════════════════════════════════════════════════╝

INSTALACIÓN DE DEPENDENCIAS:
    pip install openai-whisper tqdm

    También necesitas ffmpeg instalado en tu sistema:
    - Windows: https://ffmpeg.org/download.html  (o: winget install ffmpeg)
    - Mac:     brew install ffmpeg
    - Linux:   sudo apt install ffmpeg

    NOTA: pydub NO es necesario (no funciona en Python 3.13+).
    La detección de silencio se hace directamente con ffmpeg.

REQUISITOS DEL SISTEMA:
    Whisper consume recursos significativos. Los requisitos dependen del modelo:

    - Modelos 'tiny' / 'base' / 'small' (Recomendado):
        - RAM: 4GB mínimo.
        - CPU: Procesador moderno (Intel i5/Ryzen 5 o superior).
        - GPU: No es necesaria, pero acelera el proceso.
    - Modelo 'medium':
        - RAM: 8GB mínimo.
        - VRAM (GPU): 5GB mínimo (NVIDIA con CUDA).
    - Modelo 'large':
        - RAM: 16GB mínimo.
        - VRAM (GPU): 10GB mínimo (NVIDIA con CUDA).

    IMPORTANTE: Si no tienes una GPU NVIDIA (con soporte CUDA), el script usará
    la CPU, lo que puede tardar varias veces la duración real del audio.

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
        --limpiar-pistas jugador otrojugador

    Puedes poner uno o varios nombres separados por espacio. El nombre debe coincidir
    con el nombre del jugador en Craig (sin el número de pista).
    Requiere instalar: pip install noisereduce soundfile numpy
    Si no están instalados, el script avisa pero continúa sin limpiar.

╔══════════════════════════════════════════════════════════════╗
║          DnD Campaign Timeline — Línea de tiempo continua    ║
║  Une varios JSON de sesiones en UNA sola línea de tiempo.    ║
║  El segundo JSON empieza donde termina el primero.           ║
╚══════════════════════════════════════════════════════════════╝

CÓMO FUNCIONA:
    Toma los JSON en el orden que los pases (o alfabético si usas --carpeta).
    Calcula la duración de cada sesión y suma ese offset al siguiente.

    sesion_01.json  →  00:00:00 … 02:30:00
    sesion_02.json  →  02:30:00 … 05:10:00
    sesion_03.json  →  05:10:00 … 07:45:00

    El resultado es un único TXT sin separadores ni encabezados,
    como si toda la campaña fuera una sola grabación.

USO:
    # Archivos en orden cronológico
    python dnd_unir_campana.py --input sesion_01.json sesion_02.json sesion_03.json --output campana.txt

    # Carpeta completa (orden alfabético por nombre de archivo)
    python dnd_unir_campana.py --carpeta ./sesiones/ --output campana.txt

    # Con título y omitiendo jugador ruidoso
    python dnd_unir_campana.py --carpeta ./sesiones/ --output campana.txt \\
        --titulo "Campaña Ravenloft" --omitir name
