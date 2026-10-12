# WordCraft (https://github.com/rickyb82/wordcraft) — word processor open source in Rust con server MCP.
# Qui viene compilata solo la CLI headless (wordcraft-cli): niente finestra, niente GPU. Il server MCP parla
# su stdio; socat lo espone sulla porta 7982 della rete Docker, dove il backend FamilAI lo raggiunge
# (una sessione WordCraft nuova per ogni connessione). I documenti passano dalla cartella condivisa /data.
#
# La prima build compila ~1 milione di righe di Rust: 15-40 minuti e qualche GB di cache. Le successive sono rapide.
ARG WORDCRAFT_REPO=https://github.com/rickyb82/wordcraft
ARG WORDCRAFT_REF=main

FROM rust:1-bookworm AS build
ARG WORDCRAFT_REPO
ARG WORDCRAFT_REF
RUN apt-get update && apt-get install -y --no-install-recommends git pkg-config cmake clang libfontconfig1-dev libfreetype6-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 --branch "$WORDCRAFT_REF" "$WORDCRAFT_REPO" . 
RUN --mount=type=cache,target=/usr/local/cargo/registry \
    --mount=type=cache,target=/src/target \
    cargo build --release -p wordcraft-cli && cp target/release/wordcraft-cli /usr/local/bin/wordcraft-cli

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends socat ca-certificates fontconfig \
    fonts-dejavu fonts-liberation2 fonts-noto-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/* && fc-cache -f
COPY --from=build /usr/local/bin/wordcraft-cli /usr/local/bin/wordcraft-cli
RUN mkdir -p /data/wordcraft
ENV WORDCRAFT_NO_PREFS=1
EXPOSE 7982
# lettura: tutta /data (allegati e file generati di FamilAI); scrittura: solo /data/wordcraft
CMD ["socat", "-d", "TCP-LISTEN:7982,fork,reuseaddr", "EXEC:wordcraft-cli mcp --author FamilAI --automation-read-root /data --automation-write-root /data/wordcraft"]
