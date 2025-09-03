@echo off
ECHO Menjalankan semua layanan untuk Realtime Traffic Counter...

ECHO Pastikan Docker Desktop sudah berjalan untuk Redis...
REM (Jika perlu)
docker start nama_kontainer_redis_anda

ECHO Menjalankan Counter Worker di jendela baru...
REM Hapus semua argumen setelah counter_worker.py
start "Counter Worker" cmd /k ".\..\venv_gpu\Scripts\activate && python counter_worker.py"

timeout /t 5

ECHO Menjalankan Web App Flask di jendela baru...
start "Web Server" cmd /k ".\..\venv_gpu\Scripts\activate && python app.py"

ECHO Semua layanan telah dimulai.