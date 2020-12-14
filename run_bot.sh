#!/usr/bin/env bash

set -e

while [[ $# -gt 0 ]]; do
    case "$1" in
    -f)
        FILE_MODE=true
        shift
        ;;
    -l | --log_file)
        LOG_FILE="$2"
        shift
        shift
        ;;
    *)
        echo "Unknown argument: $1"
        exit
        ;;
    esac
done

if [ -n "${FILE_MODE}" ] && [ -z "${LOG_FILE}" ]; then
    LOG_FILE="archive/bot.log"
fi

cd "$(dirname "$0")"
source venv/bin/activate
if [ -z "${LOG_FILE}" ]; then
    python3 bot.py
else
    mkdir -p "$(dirname "${LOG_FILE}")"
    python3 bot.py &>"${LOG_FILE}"
fi
