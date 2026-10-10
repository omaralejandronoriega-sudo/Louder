FROM savonet/liquidsoap:v2.4.5
USER root
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
USER liquidsoap
