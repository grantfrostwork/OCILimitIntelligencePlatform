FROM certbot/certbot:v5.6.0

RUN pip install --no-cache-dir "oci>=2.150,<3"

COPY backend/app/tools/certificate_publish.py /opt/oci-lip/certificate_publish.py
