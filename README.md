# TLG SmartPrint — O'quvchilar uchun Avtomatlashtirilgan Chop Etish Tizimi (Windows & Raspberry Pi 5)

O'quvchilar hujjatlarini (PDF, Word `.docx`, PowerPoint `.pptx`, rasmlar, `.txt`) yuklab, har bir betini brauzerda chiroyli ko'rinishda ko'rib, kerakli betlarni tanlashi (yoki hammasini tanlashi) va chop etish buyurtmasini shakllantirishi uchun yaratilgan to'liq veb-platforma. Loyiha ham **Windows**, ham **Raspberry Pi 5 (Linux CUPS + Masofaviy Pi Ko'prigi)** muhitlarida ishlashga moslashtirilgan.

## Arxitektura

```text
O'quvchi (Brauzer + PDF.js)
   │  Hujjat yuklash (.pdf, .docx, .pptx, .png, .jpg, .txt)
   ▼
Document Normalizer (backend/services/converter.py)
   │  Barcha formatlarni yagona A4 PDF ga o'tkazish (Linux DejaVu + Windows TTF shriftlari)
   ▼
Visual Page Studio (frontend/js/pageSelector.js + pdfRenderer.js)
   │  Betlarni bosib tanlash, Toq/Juft/Teskari, "1-3, 5, 8", burish, Oq-qora filtr
   ▼
PDF Slicer & Metrics (backend/services/pdf_processor.py)
   │  Faqat tanlangan betlarni ajratib olib (1/2/4-up, Kitob/Albom) print_ready.pdf yasash
   ▼
Printer Adapter (backend/services/printer_adapter.py)
   ├── DRY_RUN         (Test rejimi — jismoniy printerga yubormaydi)
   ├── LINUX_CUPS      (Raspberry Pi 5 / Linux — to'g'ridan-to'g'ri CUPS `lp` orqali chop etadi)
   ├── REMOTE_AGENT    (Sayt hostingda + Raspberry Pi 5 printer oldida `pi_print_agent.py` orqali)
   └── WINDOWS_SPOOLER (Windows mahalliy printer — win32print)
```

## Mahalliy ishga tushirish

```bash
python run.py
```

Brauzerda oching: `http://127.0.0.1:8000`

## Raspberry Pi 5 da o'rnatish (2 ta usul)

Loyihani Raspberry Pi 5 ga yuklab, o'rnatish skriptini ishga tushiring:

```bash
chmod +x raspberry_pi/install_raspberry_pi.sh
./raspberry_pi/install_raspberry_pi.sh
```

### 1-usul (Eng oson): Hamma tizim Raspberry Pi 5 da (`LINUX_CUPS`)
Agar sayt ham, printer ham bitta binoda bo'lsa:
- Printer USB yoki Wi-Fi orqali Raspberry Pi 5 ga ulanadi (`http://<PI-IP>:631` CUPS orqali qo'shiladi).
- `raspberry_pi/tlg-smartprint.service` yoqiladi (`TLG_PRINTER_MODE=LINUX_CUPS`).
- O'quvchilar Wi-Fi orqali to'g'ridan-to'g'ri Raspberry Pi ga kirib chop etadilar.

### 2-usul: Sayt Hostingda + Raspberry Pi 5 Printer Ko'prigi (`REMOTE_AGENT`)
Agar sayt internetdagi VPS/hostingda tursa, printer esa tashqarida (alohida xonada/binoda) bo'lsa:
1. Sayt Admin panelida chop etish rejimini `REMOTE_AGENT` ga o'tkazing va `X-Agent-Key` kalitini tekshiring.
2. Printer oldidagi Raspberry Pi 5 da `raspberry_pi/pi_print_agent.py` (yoki `raspberry_pi/tlg-pi-agent.service`) ni server manzili (`TLG_SERVER_URL`) va kalit (`TLG_AGENT_KEY`) bilan ishga tushiring.
3. Pi agent faqat tashqariga chiquvchi HTTPS/HTTP so'rov bilan buyurtmalarni olib, CUPS orqali chiqaradi va qog'oz chiqqach serverga natijani qaytaradi.

## Admin Panel (Login va Parol bilan kirish)

Yuqori o'ng burchakdagi **Admin kirish** tugmasi orqali kiriladi:
- **Standart login:** `admin`
- **Standart parol:** `admin123` (birinchi marta ishga tushirishda `TLG_ADMIN_PASSWORD` env orqali o'zgartirish yoki kirgach Admin paneldan darhol yangilash tavsiya etiladi)
- **Xavfsizlik eslatmasi:** `storage/` papkasi, `.env` fayllari va Telegram sessiyalari `.gitignore` ga kiritilgan. Public serverda `TLG_AGENT_KEY` uchun alohida kuchli kalit ishlating.

## Testlarni ishga tushirish

```bash
python -m unittest discover -s tests -v
```
