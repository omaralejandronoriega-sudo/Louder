# Louder Cloud Studio - Liquidsoap 2.3.x playout graph
# YesStreaming is output-only.

settings.log.stdout := true
settings.log.level := 3
settings.server.telnet := false
settings.server.socket := true
settings.server.socket.path := environment.get(default="/tmp/louder-liquidsoap.sock", "LIQUIDSOAP_SOCKET")

# Runtime controls exposed through the local Liquidsoap command socket.
deck_a_air = interactive.bool("deck_a_air", false)
deck_b_air = interactive.bool("deck_b_air", false)
mic_live = interactive.bool("mic_live", false)
deck_a_volume = interactive.float("deck_a_volume", 0.82)
deck_b_volume = interactive.float("deck_b_volume", 0.82)
mic_duck = interactive.float("mic_duck", 0.40)

xf_duration = interactive.float("xf_duration", 4.5)
xf_in = interactive.float("xf_in", 1.2)
xf_out = interactive.float("xf_out", 2.8)

agc_target = interactive.float("agc_target", -14.0)
comp_threshold = interactive.float("comp_threshold", -12.0)
limiter_threshold = interactive.float("limiter_threshold", -1.0)

# SAM-style manual decks and Auto DJ queue.
deck_a_raw = request.queue(id="deck_a")
deck_b_raw = request.queue(id="deck_b")
auto_raw = request.queue(id="auto_queue")

deck_a = amplify(deck_a_volume, deck_a_raw)
deck_b = amplify(deck_b_volume, deck_b_raw)

# Crossfade is applied to the automation queue. Values are live interactive getters.
auto = crossfade(
  duration=xf_duration,
  fade_in=xf_in,
  fade_out=xf_out,
  auto_raw
)

# Browser microphone arrives through a private local Harbor source. The API
# relays the browser WebSocket to this source with ffmpeg.
harbor_password = environment.get(default="change-me", "MIC_HARBOR_PASSWORD")
mic = input.harbor(
  id="browser_mic",
  port=8005,
  user="source",
  password=harbor_password,
  "/mic"
)

# Main selector. Manual decks override Auto DJ. Microphone is mixed separately
# so music can be ducked rather than abruptly replaced.
music = switch(
  track_sensitive=false,
  [
    (deck_a_air, deck_a),
    (deck_b_air, deck_b),
    ({true}, auto)
  ]
)

# Never let the station source fail: if no request is ready, emit silence.
music = fallback(track_sensitive=false, [music, blank()])

# Duck music while PTT is active.
ducked_music = amplify({if mic_live() then mic_duck() else 1.0 end}, music)
mic_on_air = switch(track_sensitive=false, [(mic_live, mic), ({true}, blank())])
program = add(normalize=false, [ducked_music, mic_on_air])

# Initial SAM-like processing chain. More detailed EQ/bass/stereo modules are
# configured in the web panel and can be mapped progressively without changing
# the public control API.
program = normalize(target=agc_target, program)
program = compress(
  threshold=comp_threshold,
  ratio=2.5,
  attack=20.0,
  release=250.0,
  program
)
program = compress(
  threshold=limiter_threshold,
  ratio=20.0,
  attack=2.0,
  release=80.0,
  lookahead=5.0,
  program
)

# YesStreaming source credentials. The output starts only after the web encoder
# panel explicitly starts it, so testing cannot accidentally take over air.
ys_host = environment.get(default="127.0.0.1", "YESSTREAMING_HOST")
ys_port = int_of_string(environment.get(default="2720", "YESSTREAMING_PORT"))
ys_password = environment.get(default="change-me", "YESSTREAMING_PASSWORD")
ys_mount = environment.get(default="/stream", "YESSTREAMING_MOUNT")
ys_user = environment.get(default="source", "YESSTREAMING_USER")

output.icecast(
  id="yesstreaming",
  %mp3(bitrate=320, stereo=true),
  host=ys_host,
  port=ys_port,
  user=ys_user,
  password=ys_password,
  mount=ys_mount,
  start=false,
  fallible=true,
  program
)
