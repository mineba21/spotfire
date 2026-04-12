#!/bin/bash
# Spotfire 대시보드 실행 스크립트

PORT=8100
cd "$(dirname "$0")"

echo "▶ Spotfire 서버 시작: http://127.0.0.1:$PORT/spotfire-ai/"
python3 manage.py runserver $PORT
