#!/usr/bin/env bash
set -euo pipefail

PLUGIN_DIR="/home/deck/homebrew/plugins/WiFi-BandLock"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing WiFi BandLock Decky Plugin..."
sudo mkdir -p "$PLUGIN_DIR/dist"
sudo cp "$SOURCE_DIR/plugin.json" "$PLUGIN_DIR/"
sudo cp "$SOURCE_DIR/package.json" "$PLUGIN_DIR/"
sudo cp "$SOURCE_DIR/main.py" "$PLUGIN_DIR/"
sudo cp "$SOURCE_DIR/LICENSE" "$PLUGIN_DIR/"
sudo cp "$SOURCE_DIR/README.md" "$PLUGIN_DIR/"
sudo cp "$SOURCE_DIR/dist/index.js" "$PLUGIN_DIR/dist/"
sudo chown -R deck:deck "$PLUGIN_DIR"
sudo chmod -R 755 "$PLUGIN_DIR"

echo "WiFi BandLock successfully installed to $PLUGIN_DIR!"
