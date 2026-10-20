FROM python:3.12-slim

WORKDIR /opt/f1
RUN python -m pip install --no-cache-dir trajectory-sdk==0.9.23 numpy==2.3.3
COPY f1env /opt/f1/f1env
COPY harness.py /opt/f1/harness.py

CMD ["sleep", "infinity"]
