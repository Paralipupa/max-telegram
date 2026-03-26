#!/bin/sh
set -e

run_bridge () {
  python /app/runner.py
}

run_bridge_debug () {
  python -m debugpy --listen 0.0.0.0:5005 --wait-for-client /app/runner.py
}

run_t2m () {
  exec python webhook.py
}

run_m2t () {
  exec python bridge.py
}

run_t2m_debug () {
  exec python -m debugpy --listen 0.0.0.0:5005 --wait-for-client webhook.py
}

run_m2t_debug () {
  exec python -m debugpy --listen 0.0.0.0:5006 --wait-for-client bridge.py
}

case "$1" in
  run_bridge) "$@"; exit;;
  run_bridge_debug) "$@"; exit;;
  run_t2m) "$@"; exit;;
  run_m2t) "$@"; exit;;
  run_t2m_debug) "$@"; exit;;
  run_m2t_debug) "$@"; exit;;
  *) exec "$@"; exit;;
esac
