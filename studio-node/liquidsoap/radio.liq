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
history_url = environment.get(default="", "LOUDER_HISTORY_URL")
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

xf_enabled = interactive.bool("xf_enabled", true)
xf_smart = interactive.bool("xf_smart", true)
xf_duration = interactive.float("xf_duration", min=0., max=20., 4.5)
xf_in = interactive.float("xf_in", min=0., max=20., 1.2)
xf_out = interactive.float("xf_out", min=0., max=20., 2.8)
xf_overlap_db = interactive.float("xf_overlap_db", min=(-60.), max=0., (-9.))
xf_jingles = interactive.bool("xf_jingles", false)
gap_enabled = interactive.bool("gap_enabled", true)
gap_threshold = interactive.float("gap_threshold", min=(-80.), max=(-10.), (-48.))
gap_max = interactive.float("gap_max", min=0.1, max=30., 0.9)

deck_a_gain = interactive.float("deck_a_gain", min=0., max=1.5, 1.)
deck_b_gain = interactive.float("deck_b_gain", min=0., max=1.5, 1.)
music_gain = interactive.float("music_gain", min=0., max=1.5, 1.)
voice_gain = interactive.float("voice_gain", min=0., max=2., 1.)
voice_active = interactive.bool("voice_active", false)
aux_1_gain = interactive.float("aux_1_gain", min=0., max=2., 1.)
aux_2_gain = interactive.float("aux_2_gain", min=0., max=2., 1.)
aux_3_gain = interactive.float("aux_3_gain", min=0., max=2., 1.)
aux_1_active = interactive.bool("aux_1_active", false)
aux_2_active = interactive.bool("aux_2_active", false)
aux_3_active = interactive.bool("aux_3_active", false)

mixer_enabled = interactive.bool("mixer_enabled", true)
mixer_input_gain = interactive.float("mixer_input_gain", min=0., max=2., 1.)
mixer_output_gain = interactive.float("mixer_output_gain", min=0., max=2., 1.)

eq_enabled = interactive.bool("eq_enabled", true)
eq_low = interactive.float("eq_low", min=(-12.), max=12., 0.)
eq_mid = interactive.float("eq_mid", min=(-12.), max=12., 0.)
eq_high = interactive.float("eq_high", min=(-12.), max=12., 0.)

agc_enabled = interactive.bool("agc_enabled", true)
agc_target = interactive.float("agc_target", min=(-30.), max=(-3.), (-14.))
agc_up = interactive.float("agc_up", min=0.1, max=30., 10.)
agc_down = interactive.float("agc_down", min=0.02, max=5., 0.1)

stereo_enabled = interactive.bool("stereo_enabled", false)
stereo_width_value = interactive.float("stereo_width", min=(-1.), max=1., 0.)

bass_enabled = interactive.bool("bass_enabled", false)
bass_frequency = interactive.float("bass_frequency", min=60., max=400., 180.)
bass_gain = interactive.float("bass_gain", min=(-12.), max=12., 0.)

comp_enabled = interactive.bool("comp_enabled", true)
comp_threshold = interactive.float("comp_threshold", min=(-50.), max=0., (-10.))
comp_ratio = interactive.float("comp_ratio", min=1., max=20., 2.)

limiter_enabled = interactive.bool("limiter_enabled", true)
limiter_threshold = interactive.float("limiter_threshold", min=(-6.), max=(-0.1), (-1.))

# Runtime values are restored by the Control API from /data/studio-state.json.
# We intentionally avoid interactive.persistent here because the API is the
# single source of truth for persisted settings.

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

# Dynamic gap killer. Threshold and maximum blank duration are controlled
# from Cloud Studio without restarting Liquidsoap.
auto_detected = blank.detect(
  id="auto_blank_detector",
  max_blank=gap_max,
  threshold=gap_threshold,
  auto_raw
)
def on_auto_blank() =
  if gap_enabled() then
    auto_raw.skip()
  end
end
auto_detected.on_blank(synchronous=false, on_auto_blank)

# SAM-style Crossfade Rules. The transition is evaluated at each track change,
# so all interactive values below can change live.
def louder_transition(a, b) =
  category_a = a.metadata["category"]
  category_b = b.metadata["category"]
  special =
    category_a == "Jingles" or category_a == "Station IDs" or
    category_b == "Jingles" or category_b == "Station IDs"

  if not xf_enabled() then
    sequence([a.source, b.source])
  elsif special and not xf_jingles() then
    sequence([a.source, b.source])
  elsif xf_smart() and (a.db_level >= xf_overlap_db() or b.db_level >= xf_overlap_db()) then
    # Smart mode keeps loud endings/starts back-to-back to avoid muddy overlap.
    sequence([a.source, b.source])
  else
    # fade.in/out honor liq_fade_*_type and liq_fade_*_curve metadata,
    # so the browser's SAM-style curve controls are real.
    ending = fade.out(duration=xf_out(), a.source)
    starting = fade.in(duration=xf_in(), b.source)
    add(normalize=false, [ending, starting])
  end
end

auto = cross(
  id="auto_crossfade",
  duration=xf_duration,
  louder_transition,
  auto_detected
)

# Manual SAM-style decks.
deck_a_raw = request.queue(id="deck_a", prefetch=1)
deck_b_raw = request.queue(id="deck_b", prefetch=1)
deck_a = amplify(deck_a_gain, deck_a_raw)
deck_b = amplify(deck_b_gain, deck_b_raw)
deck_a = rms.smooth(id="deck_a_meter", duration=0.1, deck_a)
deck_b = rms.smooth(id="deck_b_meter", duration=0.1, deck_b)

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
voice = switch(
  id="voice_gate",
  track_sensitive=false,
  [({voice_active()}, voice), ({true}, blank())]
)
music = amplify(music_gain, program)

# SAM-style Auxiliary Decks.
aux_1_queue = request.queue(id="aux_1", prefetch=1)
aux_2_queue = request.queue(id="aux_2", prefetch=1)
aux_3_queue = request.queue(id="aux_3", prefetch=1)

aux_1_source = amplify(aux_1_gain, aux_1_queue)
aux_2_source = amplify(aux_2_gain, aux_2_queue)
aux_3_source = amplify(aux_3_gain, aux_3_queue)

aux_1 = switch(track_sensitive=false, [({aux_1_active()}, aux_1_source), ({true}, blank())])
aux_2 = switch(track_sensitive=false, [({aux_2_active()}, aux_2_source), ({true}, blank())])
aux_3 = switch(track_sensitive=false, [({aux_3_active()}, aux_3_source), ({true}, blank())])

# SAM-style Sound FX bus. Files are uploaded by the control API into /data.
fx = request.queue(id="fx", prefetch=1)
fx_gain = interactive.float("fx_gain", min=0., max=2., 1.)
fx = amplify(fx_gain, fx)

# Talk-over + auxiliary players + FX mix.
radio = add(
  id="voice_aux_fx_mix",
  normalize=false,
  [music, voice, aux_1, aux_2, aux_3, fx]
)

# Audio processing pipeline. Every visible Cloud Studio control below maps to
# a real interactive DSP parameter.
mixer_in = {if mixer_enabled() then mixer_input_gain() else 1. end}
mixer_out = {if mixer_enabled() then mixer_output_gain() else 1. end}
radio = amplify(mixer_in, radio)

low_gain = {if eq_enabled() then eq_low() else 0. end}
mid_gain = {if eq_enabled() then eq_mid() else 0. end}
high_gain = {if eq_enabled() then eq_high() else 0. end}
radio = filter.iir.eq.peak(id="eq_low", frequency=120., gain=low_gain, q=0.8, radio)
radio = filter.iir.eq.peak(id="eq_mid", frequency=1200., gain=mid_gain, q=1.0, radio)
radio = filter.iir.eq.peak(id="eq_high", frequency=8500., gain=high_gain, q=0.8, radio)

radio = normalize(
  id="agc",
  enabled=agc_enabled,
  target=agc_target,
  up=agc_up,
  down=agc_down,
  lufs=true,
  radio
)

width = {if stereo_enabled() then stereo_width_value() else 0. end}
radio = stereo.width(id="stereo_width_processor", width, radio)

bass_effective_gain = {if bass_enabled() then bass_gain() else 0. end}
radio = bass_boost(
  frequency=bass_frequency,
  gain=bass_effective_gain,
  radio
)

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
limited = limit(id="limiter", threshold=limiter_threshold, ratio=20., radio)
radio = dry_wet(limit_wet, radio, limited)
radio = amplify(mixer_out, radio)

# Real program meter used by the SAM-style VU display.
radio = rms.smooth(id="program_meter", duration=0.1, radio)

# Real played-track history. This callback fires when metadata reaches the
# final program signal, not when a future request is merely prefetched.
def report_history(m) =
  log.info("LOUDER_METADATA #{m}")
  if history_url != "" then
    payload = metadata.json.stringify(compact=true, m)
    _ = http.post(
      headers=[("Content-Type", "application/json")],
      data=payload,
      timeout=5.,
      history_url
    )
  end
end

radio.on_metadata(synchronous=false, report_history)

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
