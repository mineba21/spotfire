#!/bin/bash
# Spotfire 대시보드 실행 스크립트

PORT=8001
cd "$(dirname "$0")"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  SF Dashboard"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  허브       http://127.0.0.1:$PORT/"
echo "  인터락     http://127.0.0.1:$PORT/interlock-ai/"
echo "  정지로스   http://127.0.0.1:$PORT/stoploss-ai/"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 manage.py runserver $PORT
