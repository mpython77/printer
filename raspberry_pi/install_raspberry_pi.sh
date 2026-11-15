#!/usr/bin/env bash
# TLG SmartPrint — Raspberry Pi 5 (Debian Bookworm / Raspberry Pi OS 64-bit) Installer
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURRENT_USER="${SUDO_USER:-$USER}"

echo "=== [1/4] Tizim paketlari va CUPS printer drayverlari o'rnatilmoqda ==="
sudo apt-get update
sudo apt-get install -y \
  cups \
  cups-client \
  ipp-usb \
  printer-driver-gutenprint \
  python3-venv \
  python3-pip \
  fonts-dejavu-core

echo "=== [2/4] CUPS xizmati yoqilmoqda va foydalanuvchi lpadmin guruhiga qo'shilmoqda ==="
sudo systemctl enable --now cups
sudo usermod -aG lpadmin "$CURRENT_USER" || true
sudo cupsctl --remote-admin --share-printers || true
sudo systemctl restart cups

echo "=== [3/4] Python virtual muhiti (.venv) yaratilmoqda ==="
cd "$PROJECT_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== [4/4] O'rnatish yakunlandi ==="
echo ""
echo "Ulangan CUPS printerlarini ko'rish:"
echo "  lpstat -p -d"
echo ""
echo "Agar Canon/HP/Epson printer qo'lda qo'shish kerak bo'lsa brauzerdan oching:"
echo "  http://$(hostname -I | awk '{print $1}'):631"
echo ""
echo "--- A VARIANT (Hammasi Raspberry Pi 5 da ishlaydi) ---"
echo "  sudo cp raspberry_pi/tlg-smartprint.service /etc/systemd/system/"
echo "  sudo sed -i \"s|/home/pi/TLG_PRINTER|$PROJECT_DIR|g; s|User=pi|User=$CURRENT_USER|g\" /etc/systemd/system/tlg-smartprint.service"
echo "  sudo systemctl daemon-reload && sudo systemctl enable --now tlg-smartprint"
echo ""
echo "--- B VARIANT (Sayt hostingda, Raspberry Pi 5 faqat printer ko'prigi) ---"
echo "  1) raspberry_pi/tlg-pi-agent.service ichidagi TLG_SERVER_URL va TLG_AGENT_KEY ni tahrirlang"
echo "  2) sudo cp raspberry_pi/tlg-pi-agent.service /etc/systemd/system/"
echo "  3) sudo sed -i \"s|/home/pi/TLG_PRINTER|$PROJECT_DIR|g; s|User=pi|User=$CURRENT_USER|g\" /etc/systemd/system/tlg-pi-agent.service"
echo "  4) sudo systemctl daemon-reload && sudo systemctl enable --now tlg-pi-agent"
