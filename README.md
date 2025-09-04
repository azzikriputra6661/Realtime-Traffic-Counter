## Realtime Traffic Counter Prototype

Prototipe ini dikembangkan sebagai bagian dari program magang di Diskominfosanditik Kabupaten Sumedang. Sistem ini bertujuan untuk menyediakan solusi otomatis untuk mendeteksi, melacak, dan menghitung volume kendaraan berdasarkan klasifikasi dari stream CCTV ATCS Dishub.

Arsitektur Sistem

Sistem ini dibangun dengan arsitektur *worker-server* yang terpisah untuk memastikan skalabilitas dan efisiensi:

1.  **`counter_worker.py` (Worker / Prosesor AI):**
    * Berjalan sebagai proses *background* yang terus-menerus.
    * Secara otomatis mengambil URL stream CCTV terbaru dari situs ATCS.
    * Menggunakan model AI **YOLOv8** yang telah di-*fine-tune* untuk mendeteksi dan melacak kendaraan.
    * Menyimpan data hasil penghitungan ke dalam database **SQLite**.
    * (Pengembangan Lanjutan) Menyiarkan *frame* video yang telah diproses melalui **Redis**.

2.  **`app.py` (Web Server / Dasbor):**
    * Berjalan sebagai aplikasi web menggunakan **Flask**.
    * Menampilkan *dashboard* interaktif yang berisi:
    * Galeri CCTV dengan peta lokasi.
    * Tampilan *live stream* yang telah diolah oleh *worker*.
    * Dasbor rekapitulasi dengan grafik jumlah kendaraan.
    * Menyediakan **API** untuk diakses oleh *frontend* guna menampilkan data *real-time*.

## Tech Stack

* **Bahasa:** Python 3
* **AI / Computer Vision:**
    * `ultralytics` (YOLOv8)
    * `opencv-python-headless`
* **Backend:**
    * `Flask`
    * `gunicorn` (untuk produksi)
    * `redis` (untuk komunikasi antar proses)
* **Database:** `sqlite3`
* **Lainnya:** `streamlink`, `requests`, `beautifulsoup4`

---

## Panduan Instalasi & Menjalankan (Deployment)

Berikut adalah panduan untuk menjalankan aplikasi ini di server VPS (Linux).

### Prasyarat

1.  **Python 3.10+** dan `pip` terinstal.
2.  **Git** terinstal.
3.  **Docker & Docker Compose** (Sangat Direkomendasikan untuk kemudahan deployment).
4.  **Redis Server** berjalan (bisa di-host lokal atau melalui Docker).

### Langkah 1: Clone Repositori

`git clone [https://github.com/azzikriputra6661/Realtime-Traffic-Counter.git](https://github.com/azzikriputra6661/Realtime-Traffic-Counter.git)`
`cd Realtime-Traffic-Counter/web_prototype`

### Langkah 2: Setup Lingkungan (Metode Virtual Environment)

* **Buat virtual environment**
`python3 -m venv venv_gpu`

* **Aktifkan environment**
`source venv_gpu/bin/activate`

* **Install semua library yang dibutuhkan**
`pip install -r requirements.txt`

### Langkah 3: Jalankan Aplikasi
* **Aplikasi ini terdiri dari dua proses utama yang harus berjalan secara bersamaan, idealnya di dua terminal terpisah (menggunakan screen atau tmux di server sangat disarankan).**

* **Terminal 1: Jalankan Counter Worker**
* **Worker akan memulai proses AI di latar belakang. Anda bisa memilih CCTV mana yang akan dipantau.**
`python counter_worker.py`

* **Terminal 2: Jalankan Web Server Flask**
`python app.py`

* **Jalankan web server menggunakan Gunicorn untuk produksi**
`gunicorn --bind 0.0.0.0:5000 app:app`

### Langkah 4: Akses Aplikasi
* **Setelah kedua proses berjalan, aplikasi web dapat diakses melalui browser di alamat:**
`http://IP_SERVER_ANDA:5000`

### Cara Cepat Menjalankan (Untuk Windows)

Jika Anda menjalankan proyek ini di lingkungan Windows dan sudah menyelesaikan semua langkah setup di atas, Anda bisa menggunakan skrip `run.bat` untuk memulai semua layanan secara otomatis dengan satu kali klik.

1.  **Konfigurasi (Jika Perlu):** Buka file `run.bat` dengan editor teks. Anda bisa mengubah target CCTV yang ingin diproses di dalam file tersebut.
2.  **Jalankan:** Cukup klik dua kali pada file **`run.bat`**.
3.  **Proses:** Skrip ini akan secara otomatis:
    * Membuka jendela terminal baru untuk **Counter Worker** dan menjalankannya. Jendela ini akan menampilkan menu interaktif untuk memilih CCTV.
    * Membuka jendela terminal kedua untuk **Web Server Flask**.
4.  **Akses Aplikasi:** Setelah kedua jendela berjalan, buka browser dan akses `http://127.0.0.1:5000`.

**Catatan:** Skrip ini dirancang untuk kemudahan penggunaan di lingkungan pengembangan lokal. Untuk *deployment* di server produksi (Linux), ikuti panduan `systemd` atau **Docker Compose**.
