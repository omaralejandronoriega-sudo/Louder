# Louder Cloud Studio Node

Nodo de emisión para Louder Cloud Studio. Este componente es el único proceso que necesita estar
encendido 24/7. GitHub aloja el panel, configuración y código; Telegram funciona como biblioteca
maestra; YesStreaming recibe únicamente la señal final.

## Componentes

- `api/`: API de control, PAL, scheduler, requests, historial, estadísticas, Voice FX, Sound FX,
  clockwheel y sincronización del catálogo Telegram.
- `liquidsoap/`: motor de audio real: AutoDJ, Deck A/B, Aux 1/2/3, crossfade, gap killer, DSP,
  micrófono y encoder.
- `vault/`: puente privado Telegram -> HTTP reproducible por Liquidsoap.
- `docker-compose.yml`: despliegue completo.

## Requisitos

- Linux x86_64 o ARM64
- Docker + Docker Compose
- 512 MB RAM mínimo de laboratorio; 1 GB o más recomendado
- FFmpeg incluido en el contenedor API
- salida de red continua hacia YesStreaming
- HTTPS delante del API para usar micrófono desde navegadores modernos

## Despliegue

```bash
cp .env.example .env
# completar secretos
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8787/health
```

El puerto 1234 de Liquidsoap **nunca debe publicarse**. El servidor de comandos de Liquidsoap no
tiene autenticación propia; sólo el contenedor API habla con él dentro de la red Docker.

## Flujo de audio

```
Telegram Vault
      |
      v
Louder Director / request.dynamic
      |
      v
Liquidsoap
  |- Deck A / B
  |- Aux 1 / 2 / 3
  |- Sound FX
  |- Voice FX / browser microphone
  |- Crossfade / Gap killer
  |- EQ / AGC / stereo / bass / compressor / limiter
      |
      v
MP3 320 kbps
      |
      v
YesStreaming
```

## Micrófono

El navegador captura PCM de micrófono y lo envía por WebSocket al API. El API usa FFmpeg para
convertirlo a MP3 y lo entrega al mount privado `/voice` de Liquidsoap. El PTT controla al mismo
tiempo el gate de voz y el ducking del programa.

## Crossfade Rules

Los parámetros se aplican en vivo mediante variables interactivas de Liquidsoap:

- enable/disable
- duración
- fade-in
- fade-out
- smart level detection
- gap killer
- threshold de silencio
- tratamiento de Station IDs/Jingles

## DSP

Los controles del panel se traducen a parámetros reales de Liquidsoap:

- input/output gain
- EQ Low/Mid/High
- AGC/normalizer
- stereo width
- bass boost
- compressor
- limiter

## PAL

Comandos disponibles inicialmente:

```
LOG "texto"
WAIT 2
MODE AUTO
MODE QUEUE
MODE MANUAL
MODE RECOVERY
QUEUE CATEGORY "Novedades" 2
QUEUE URI "https://..."
ENCODER START
ENCODER STOP
ENCODER RESTART
SKIP
```

Los scripts pueden guardarse, cargarse, borrarse, ejecutarse y llamarse desde Scheduler.

## Estado de producción

La rama `cloud-studio-v1` no cambia el stream actual. El output YesStreaming inicia detenido
(`start=false`) y sólo se activa desde el panel/Control API durante la prueba de emisión.

Antes del corte definitivo deben pasar:
1. CI de interfaz;
2. typecheck de Liquidsoap;
3. build de los tres contenedores;
4. runtime smoke test API <-> Liquidsoap;
5. 7 días de burn-in en un nodo real;
6. prueba de micrófono;
7. prueba de caída/recuperación de Telegram;
8. prueba de reconexión a YesStreaming.
