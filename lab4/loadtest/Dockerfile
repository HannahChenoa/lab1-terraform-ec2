# Imagen con wrk2 (https://github.com/giltene/wrk2) compilado, lista para
# generar carga contra el ALB del Lab4.
#
# Build:  docker build -t lab4-wrk2 .
# Uso:    docker run --rm lab4-wrk2 -t4 -c50 -d30s -R100 --latency "http://<alb_dns>/item/1"

FROM ubuntu:22.04

RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        build-essential libssl-dev git zlib1g-dev ca-certificates && \
    git clone -q https://github.com/giltene/wrk2.git /wrk2 && \
    cd /wrk2 && make -s && \
    apt-get purge -y -qq build-essential git && \
    apt-get autoremove -y -qq && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /wrk2
ENTRYPOINT ["./wrk"]
