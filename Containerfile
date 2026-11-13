FROM registry.fedoraproject.org/fedora:42

# Python 3.13 (stessa versione del lock) e LibreOffice Writer per i documenti.
RUN dnf install -y python3 python3-pip libreoffice-writer liberation-fonts \
    && dnf clean all

WORKDIR /app

# Prima solo il lock: il layer delle dipendenze resta in cache finché non cambia.
COPY requirements.lock /app/requirements.lock
RUN python3 -m pip install --no-cache-dir --require-hashes -r requirements.lock

COPY . /app
RUN chmod +x scripts/*.sh \
    && mkdir -p /config /data/instance /backups

ENV MCORSI_ENV_FILE=/config/.env \
    MCORSI_INSTANCE_PATH=/data/instance \
    MCORSI_BACKUP_PATH=/backups \
    MCORSI_ENV=production

EXPOSE 5100
# Nessun punto di ingresso fisso: il comando lo decide il Quadlet.
