FROM savonet/liquidsoap:v2.3.3

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip ffmpeg ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir -r /app/requirements.txt

COPY app.py /app/app.py
COPY radio.liq /app/radio.liq
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && mkdir -p /app/state && chown -R liquidsoap:liquidsoap /app

USER liquidsoap
ENV LIQUIDSOAP_SOCKET=/tmp/louder-liquidsoap.sock
EXPOSE 8787
ENTRYPOINT ["/app/entrypoint.sh"]
