FROM python:3.12-slim

WORKDIR /app
COPY engine.py lab.py selftest.py requirements.txt ./

ENV DATA_DIR=/data
ENV PORT=8090

EXPOSE 8090
CMD ["python", "lab.py", "serve"]
