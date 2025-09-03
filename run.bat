@echo off
ECHO Menjalankan semua layanan untuk Realtime Traffic Counter...

REM Langkah 1: Pastikan Docker Desktop sudah berjalan (opsional, jika Redis di Docker)
ECHO Pastikan Docker Desktop sudah berjalan untuk Redis...
REM (Jika Anda menjalankan Redis langsung di Windows, Anda bisa menghapus bagian Docker)
docker start redis-traffic-counter

REM Langkah 2 & 3: Buka terminal baru, aktifkan venv, dan jalankan worker
ECHO Menjalankan Counter Worker di jendela baru...
start "Counter Worker" cmd /k ".\..\venv_gpu\Scripts\activate && python counter_worker.py"

REM Beri sedikit jeda agar worker sempat berjalan
timeout /t 5

REM Langkah 4 & 5: Buka terminal lain, aktifkan venv, dan jalankan web server
ECHO Menjalankan Web App Flask di jendela baru...
start "Web Server" cmd /k ".\..\venv_gpu\Scripts\activate && python app.py"

ECHO Semua layanan telah dimulai. Silakan buka http://127.0.0.1:5000 di browser Anda.