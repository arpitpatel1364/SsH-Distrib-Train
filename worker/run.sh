#!/bin/bash
# Worker agent execution runner script
set -e

# Change to the script's directory
cd "$(dirname "$0")"

echo "========================================================"
echo " 🚀 Starting YOLO Distributed Worker Agent"
echo "========================================================"

# Default VENV_DIR
VENV_DIR="$HOME/venv"

# Check if venv exists
if [ ! -d "$VENV_DIR" ]; then
    # Check if there is a local venv in the current directory
    if [ -d "venv" ]; then
        VENV_DIR="venv"
    else
        echo "❌ ERROR: Virtual environment not found at $VENV_DIR or ./venv. Please run ./install.sh first."
        exit 1
    fi
fi

echo "--> Activating Virtual Environment..."
source "$VENV_DIR/bin/activate"

if [ ! -z "$1" ]; then
    MASTER_URL="$1"
    # Process argument only once
    shift
elif [ -f ".master_url" ] && [ -s ".master_url" ]; then
    MASTER_URL="$(cat .master_url)"
fi

while true; do
    if [ -z "$MASTER_URL" ]; then
        if [ ! -t 0 ]; then
            echo "❌ ERROR: No MASTER_URL provided and not running interactively."
            exit 1
        fi
        read -p "Enter Master Orchestrator URL (e.g., http://[IP_ADDRESS]:8000): " MASTER_URL
    fi

    # Trim trailing slash
    MASTER_URL="${MASTER_URL%/}"

    if [ -z "$MASTER_URL" ]; then
        echo "[!] Master URL cannot be empty."
        continue
    fi

    # Format check
    if [[ "$MASTER_URL" != http://* ]] && [[ "$MASTER_URL" != https://* ]]; then
        echo "'$MASTER_URL' is invalid (must start with http:// or https://)."
        MASTER_URL=""
        continue
    fi

    echo "--> Testing connection to $MASTER_URL/health ..."
    if curl -s -f -m 5 "$MASTER_URL/health" > /dev/null; then
        echo " Connected to master successfully!"
        echo "$MASTER_URL" > .master_url
        break
    else
        echo " Could not reach $MASTER_URL. Please check the URL and network."
        MASTER_URL=""
        # Don't keep broken URL in file
        rm -f .master_url
    fi
done

echo "--> Launching worker agent targeting master: $MASTER_URL"
exec python worker.py --master "$MASTER_URL"
