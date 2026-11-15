# TLG SmartPrint — O'quvchilar uchun Avtomatlashtirilgan Chop Etish Tizimi (Windows, Linux/macOS & Raspberry Pi 5)

O'quvchilar hujjatlarini (`.pdf`, `.docx`, `.doc`, `.pptx`, `.ppt`, `.xlsx`, `.xls`, `.png`, `.jpg`, `.webp`, `.bmp`, `.txt`, `.md`, `.csv`) yuklab, har bir betini brauzerda **1:1 asl ko'rinishda** ko'rib, kerakli betlarni tanlashi va avtomatlashtirilgan tarzda chop etishi uchun yaratilgan veb-platforma. Loyiha **noutbuklar (Windows / Linux / macOS)** hamda **Raspberry Pi 5** da ishlashga mo'ljallangan.

---

## Arxitektura

```text
O'quvchi (Brauzer)
   │  Hujjat yuklash (.pdf, .docx/.pptx/.xlsx, rasmlar, .txt/.md)
   ▼
Document Normalizer (backend/services/converter.py)
   │  Barcha formatlarni A4 PDF va 1:1 sahifa rasmlariga aylantirish (Office/LibreOffice + pypdfium2)
   ▼
Visual Page Studio (frontend/js/)
   │  Betlarni tanlash, Toq/Juft/Teskari, "1-3, 5", burish, Oq-qora / Rangli rejim
   ▼
PDF Slicer & Metrics (backend/services/pdf_processor.py)
   │  Tanlangan betlardan N-up (1/2/4-bet) va B&W/Color bo'laklangan print_ready.pdf yasash
   ▼
Queue & Payment Verifier (backend/main.py + backend/humo_verifier.py)
   │  Navbat (FIFO), ixtiyoriy HUMO karta to'lovi va @HUMOcardbot orqali avtomatik tekshiruv
   ▼
Printer Adapter (backend/services/printer_adapter.py)
   ├── DRY_RUN         (Test rejimi — jismoniy printerga yubormaydi)
   ├── WINDOWS_SPOOLER (Windows noutbuk/PK — GDI 300-DPI / win32print orqali)
   ├── LINUX_CUPS      (Raspberry Pi 5 / Linux / macOS — CUPS `lp` orqali)
   └── REMOTE_AGENT    (Sayt VPS/hostingda + Raspberry Pi 5 printer oldida `pi_print_agent.py` orqali)
```

---

## 1. Noutbuk / Kompyuterda o'rnatish va ishlatish

**Talablar:** Python `3.10+`, `Git`, hamda Word/PowerPoint/Excel hujjatlarni 1:1 PDF ga aylantirish uchun **Microsoft Office** (Windows) yoki **LibreOffice** (Windows/Linux/macOS).

### A) Windows noutbuk (PowerShell)

1. Loyihani yuklab oling va virtual muhit yarating:
```powershell
git clone https://github.com/mpython77/printer.git
cd printer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```
*(Agar PowerShell ruxsat bermasa, bir marta `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` bering.)*

2. Kutubxonalarni o'rnating:
```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

3. Serverni ishga tushiring:
- Faqat shu noutbukdan test qilish (`127.0.0.1:8000`):
  ```powershell
  python run.py
  ```
- Shu Wi-Fi / lokal tarmoqdagi boshqa telefon va noutbuklardan ham kirish uchun (`0.0.0.0:8000`):
  ```powershell
  $env:TLG_HOST = "0.0.0.0"
  python run.py
  ```
  *(Boshqa qurilmalar `http://<NOUTBUK-IP>:8000` orqali kiradi; kerak bo'lsa Windows Firewall da TCP `8000` portga ruxsat bering.)*

4. Windows printerini ulash:
   - Printeringizni (masalan, Canon/HP/Epson) USB yoki Wi-Fi orqali Windows ga o'rnating.
   - Saytdan **Admin panel** -> **Printer** bo'limiga kiring, rejimni **`WINDOWS_SPOOLER`** qilib printeringizni tanlang va saqlang.

### B) Linux / macOS noutbuk (Bash)

```bash
git clone https://github.com/mpython77/printer.git
cd printer
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Boshqa qurilmalardan Wi-Fi orqali kirish uchun:
TLG_HOST=0.0.0.0 python run.py
```
- Linux/macOS da `.docx/.pptx/.xlsx` fayllarni 1:1 ochish uchun `libreoffice` o'rnatilgan bo'lishi kerak.
- Haqiqiy printerga chiqarish uchun Admin panel -> **Printer** bo'limidan **`LINUX_CUPS`** rejimini tanlang (`lpstat -p -d` da ko'rinadigan CUPS printeri).

---

## 2. Raspberry Pi 5 da o'rnatish va ishlatish (Raspberry Pi OS 64-bit)

1. Printerni USB (yoki bir xil Wi-Fi tarmoq) orqali Raspberry Pi 5 ga ulang.
2. Loyihani yuklab olib, o'rnatish skriptini ishga tushiring:
```bash
git clone https://github.com/mpython77/printer.git
cd printer
chmod +x raspberry_pi/install_raspberry_pi.sh
./raspberry_pi/install_raspberry_pi.sh
```
Bu skript CUPS, `ipp-usb`, `printer-driver-gutenprint`, LibreOffice (`writer`/`impress`/`calc`), shriftlar va Python `.venv` muhitini avtomatik o'rnatadi.

3. CUPS printerini tekshiring / qo'shing:
   - Terminalda ko'rish: `lpstat -p -d`
   - Agar printer qo'lda qo'shish kerak bo'lsa brauzerdan CUPS panelini oching: `http://<PI-IP>:631` (Administration -> Add Printer).

### 1-usul (Eng oson): Hamma tizim Raspberry Pi 5 da (`LINUX_CUPS`)
Sayt ham, printer ham bitta binoda bo'lsa (`TLG_HOST=0.0.0.0`, `TLG_PRINTER_MODE=LINUX_CUPS`):
```bash
sudo cp raspberry_pi/tlg-smartprint.service /etc/systemd/system/
# Agar papka yoki foydalanuvchi nomi 'pi' dan farqli bo'lsa moslang:
sudo sed -i "s|/home/pi/TLG_PRINTER|$(pwd)|g; s|User=pi|User=$USER|g" /etc/systemd/system/tlg-smartprint.service
sudo systemctl daemon-reload
sudo systemctl enable --now tlg-smartprint
```
- Loglarni kuzatish: `sudo journalctl -u tlg-smartprint -f`
- O'quvchilar Wi-Fi orqali brauzerda `http://<PI-IP>:8000` ga kirib chop etishadi.

### 2-usul: Sayt VPS/Hostingda + Raspberry Pi 5 Printer Ko'prigi (`REMOTE_AGENT`)
Sayt internetdagi serverda tursa, printer esa boshqa xonada/binoda Raspberry Pi 5 ga ulangan bo'lsa:
1. Sayt **Admin panel** -> **Printer** bo'limida rejimni **`REMOTE_AGENT`** ga o'tkazing va **Raspberry Pi Agent kaliti (`X-Agent-Key`)** ni ko'chirib oling.
2. Raspberry Pi 5 da `raspberry_pi/tlg-pi-agent.service` faylini tahrirlab `TLG_SERVER_URL` (sayt manzili) va `TLG_AGENT_KEY` (Admin paneldagi kalit) ni yozing:
```bash
nano raspberry_pi/tlg-pi-agent.service
sudo cp raspberry_pi/tlg-pi-agent.service /etc/systemd/system/
sudo sed -i "s|/home/pi/TLG_PRINTER|$(pwd)|g; s|User=pi|User=$USER|g" /etc/systemd/system/tlg-pi-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now tlg-pi-agent
```
- Agent logini ko'rish: `sudo journalctl -u tlg-pi-agent -f`
- Qo'lda bir martalik test: `.venv/bin/python raspberry_pi/pi_print_agent.py --server-url https://SIZNING-SAYT --agent-key SIZNING-KALIT --once`

---

## 3. Admin Panel va Dastlabki Sozlash

Brauzerda yuqori o'ng burchakdagi **Admin panel** tugmasi orqali kiriladi:
- **Standart login:** `admin`
- **Standart parol:** `admin123`

Kirishingiz bilan quyidagilarni bajaring:
1. **Xavfsizlik** bo'limidan darhol yangi admin parol o'rnating (yoki birinchi ishga tushirishda `TLG_ADMIN_PASSWORD` env bering).
2. **Narxlar** bo'limida oq-qora / rangli chop etish narxlarini moslang.
3. **Printer** bo'limida rejim (`DRY_RUN` / `WINDOWS_SPOOLER` / `LINUX_CUPS` / `REMOTE_AGENT`) va printerni tanlang.
4. **To'lov va Telegram** bo'limida (agar karta to'lovi yoqilgan bo'lsa) HUMO karta ma'lumotlarini kiriting va `@HUMOcardbot` xabarlarini o'qish uchun Telegram akkauntingizni ulang.

---

## 4. Muhit o'zgaruvchilari (Environment Variables)

| O'zgaruvchi | Standart qiymat | Vazifasi |
| --- | --- | --- |
| `TLG_HOST` | `127.0.0.1` | Server tinglaydigan IP (`0.0.0.0` = Wi-Fi/LAN uchun ochiq) |
| `TLG_PORT` | `8000` | Web server porti |
| `TLG_PRINTER_MODE` | `DRY_RUN` | Ilk baza yaratilgandagi rejim (`WINDOWS_SPOOLER`, `LINUX_CUPS`, `REMOTE_AGENT`) |
| `TLG_PRINTER_NAME` | `""` | Ilk standart printer nomi |
| `TLG_ADMIN_PASSWORD` | `admin123` | Ilk baza yaratilganda admin paroli |
| `TLG_AGENT_KEY` | *(avto-random)* | Ilk `X-Agent-Key` kaliti (`REMOTE_AGENT` uchun) |
| `TLG_STORAGE_DIR` | `./storage` | Baza, fayllar va zaxiralarni saqlash papkasi (USB SSD ga o'tkazish uchun qulay) |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | *(public desktop)* | Ixtiyoriy shaxsiy Telethon API ma'lumotlari |

---

## 5. Ma'lumotlar saqlanishi, Quvvat o'chishidan himoya va Backup

- Barcha buyurtmalar, sozlamalar, to'lov cheklari va Telegram sessiyasi diskdagi `storage/` papkasida (`smartprint.db` — SQLite **`WAL + synchronous=FULL`**) saqlanadi. Kompyuter yoki Raspberry Pi kutilmaganda o'chib qolsa ham saqlangan ma'lumotlar yo'qolmaydi, chala qolgan chop etish navbati esa qayta yonganda avtomatik tasdiqlash holatiga tiklanadi.
- Server ishga tushganda `storage/backups/` ga atomik `.db` zaxira nusxa oladi (eng yangi 7 tasi saqlanadi). Shuningdek, **Admin panel -> Xavfsizlik** bo'limidan **Bazadan zaxira nusxa yuklab olish (.db)** tugmasi bilan nusxani istalgan payt yuklab olish mumkin.
- Raspberry Pi SD kartasi nosozligidan himoyalanish uchun USB SSD ulab, `TLG_STORAGE_DIR=/mnt/ssd/smartprint_storage` berish tavsiya etiladi.

---

## 6. Testlarni ishga tushirish

```bash
python -m unittest discover -s tests -v
```
