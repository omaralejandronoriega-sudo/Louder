# Louder Cloud Studio

Rama experimental para el panel web de automatización de Louder.

## Primera entrega

Ya implementado en navegador:
- Desktop A/B/C.
- biblioteca real tomada del catálogo YesStreaming histórico de Louder;
- búsqueda y categorías;
- Queue con reordenamiento y persistencia local;
- Clockwheel editable y persistente;
- Event Scheduler local;
- PAL Louder DSL inicial (LOG, MODE, QUEUE CATEGORY, WAIT);
- Crossfade Rules con persistencia;
- Micrófono mediante Web Audio / getUserMedia;
- medidor de micrófono;
- Voice Tracking grabable y reproducible;
- Sound FX cargables y disparables;
- configuración de encoders;
- Audio Mixer Pipeline con módulos DSP y presets;
- configuración de Control API;
- separación estricta entre funciones locales y controles que requieren el nodo de playout.

## Regla

Todo control marcado con `data-node` queda deshabilitado mientras no haya un playout node conectado. No se simula una acción de aire.

## Siguiente backend

El nodo mínimo debe exponer:
- GET /status
- POST /mode
- POST /deck/a/play, pause, stop, cue, air
- POST /deck/b/play, pause, stop, cue, air
- POST /deck/a/volume
- POST /deck/b/volume
- POST /voice/ptt
- POST /encoder/start, stop, restart
- POST /crossfade/apply
- POST /dsp/apply

Liquidsoap será el motor de audio y YesStreaming sólo la salida final.
