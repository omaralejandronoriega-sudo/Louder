# Louder Cloud Studio playout engine
# Liquidsoap 2.4.5

settings.log.stdout := true
settings.log.level := 3

# The command server is reachable only inside the Docker network.
settings.server.telnet := true
settings.server.telnet.bind_addr := "0.0.0.0"
settings.server.telnet.port := 1234

# Browser microphone bridge / live source.
settings.harbor.bind_addrs := ["0.0.0.0"]

next_url = environment.get("LOUDER_NEXT_URL")
voice_password = environment.get("VOICE_HARBOR_PASSWORD")

# Final transport destination. YesStreaming is output-only.
ys_host = environment.get("YESSTREAMING_HOST")
ys_port = int_of_string(default=2720, environment.get(default="2720", "YESSTREAMING_PORT"))
ys_mount = environment.get(default="/stream", "YESSTREAMING_MOUNT")
ys_user = environment.get(default="source", "YESSTREAMING_USER")
ys_password = environment.get("YESSTREAMING_PASSWORD")

# Runtime controls exposed through Liquidsoap's command server.
studio_mode = interactive.string("studio_mode", "auto")
manual_deck = interactive.string("manual_deck", "none")

xf_duration = interactive.float("xf_duration", min=0., max=20., 4.5)
xf_in = interactive.float("xf_in", min=0., max=20., 1.2)
xf_out = interactive.float("xf_out", min=0., max=20., 2.8)

deck_a_gain = interactive.float("deck_a_gain", min=0., max=1.5, 1.)
deck_b_gain = interactive.float("deck_b_gain", min=0., max=1.5, 1.)
music_gain = interactive.float("music_gain", min=0., max=1.5, 1.)
voice_gain = interactive.float("voice_gain", min=0., max=2., 1.)

agc_enabled = interactive.bool("agc_enabled", true)
agc_target = interactive.float("agc_target", min=(-30.), max=(-3.), (-14.))
stereo_width_value = interactive.float("stereo_width", min=(-1.), max=1., 0.)
bass_gain = interactive.float("bass_gain", min=(-12.), max=12., 0.)
comp_enabled = interactive.bool("comp_enabled", true)
comp_threshold = interactive.float("comp_threshold", min=(-50.), max=0., (-10.))
comp_ratio = interactive.float("comp_ratio", min=1., max=20., 2.)
limiter_enabled = interactive.bool("limiter_enabled", true)

# Persist runtime mixer settings across restarts.
interactive.persistent("/data/liquidsoap-vars.json")

# Auto engine: ask Louder Director for the next playable URI.
def next_request() =
  if next_url == "" then
    null
  else
    command = "curl -fsS --max-time 10 " ^ process.quote(next_url)
    result = process.read.lines(command)
    uri = list.hd(default="", result)
    if uri == "" then null else request.create(uri) end
  end
end

auto_raw = request.dynamic(id="auto", prefetch=2, timeout=60., next_request)
auto = crossfade(
  id="auto_crossfade",
  duration=xf_duration,
  fade_in=xf_in,
  fade_out=xf_out,
  auto_raw
)

# Manual SAM-style decks.
deck_a_raw = request.queue(id="deck_a", prefetch=1)
deck_b_raw = request.queue(id="deck_b", prefetch=1)
deck_a = amplify(deck_a_gain, deck_a_raw)
deck_b = amplify(deck_b_gain, deck_b_raw)

manual = switch(
  id="manual",
  track_sensitive=false,
  [
    ({manual_deck() == "a"}, deck_a),
    ({manual_deck() == "b"}, deck_b)
  ]
)
manual_safe = fallback(track_sensitive=false, [manual, blank()])
auto_safe = fallback(track_sensitive=false, [auto, blank()])

program = switch(
  id="program",
  track_sensitive=false,
  [
    ({studio_mode() == "manual"}, manual_safe),
    ({true}, auto_safe)
  ]
)

# Voice FX / PTT: node streams browser PCM to this harbor source.
voice = input.harbor(
  id="voice",
  "voice",
  port=8005,
  user="source",
  password=voice_password,
  buffer=0.2,
  max=2.0
)
voice = amplify(voice_gain, voice)
music = amplify(music_gain, program)

# Talk-over mix. When voice is absent, music continues alone.
radio = add(id="voice_mix", normalize=false, [music, voice])

# Audio processing pipeline.
radio = normalize(
  id="agc",
  enabled=agc_enabled,
  target=agc_target,
  lufs=true,
  radio
)
radio = stereo.width(id="stereo_width_processor", stereo_width_value, radio)
radio = bass_boost(gain=bass_gain, frequency=180., radio)

comp_wet = {if comp_enabled() then 1. else 0. end}
compressed = compress(
  id="compressor",
  threshold=comp_threshold,
  ratio=comp_ratio,
  attack=25.,
  release=250.,
  radio
)
radio = dry_wet(comp_wet, radio, compressed)

limit_wet = {if limiter_enabled() then 1. else 0. end}
limited = limit(id="limiter", threshold=(-1.), ratio=20., radio)
radio = dry_wet(limit_wet, radio, limited)

# Metadata/historical event hooks are available from the command server.
radio.on_metadata(
  synchronous=false,
  fun(m) -> log.info("LOUDER_METADATA #{m}") end
)

# Final source: YesStreaming only receives the finished 320 kbps signal.
output.icecast(
  id="out",
  %mp3(bitrate=320, samplerate=44100, stereo=true),
  host=ys_host,
  port=ys_port,
  user=ys_user,
  password=ys_password,
  mount=ys_mount,
  name="Louder",
  description="Louder - la única alternativa",
  genre="Indie / Alternative",
  public=false,
  fallible=true,
  start=false,
  radio
)
