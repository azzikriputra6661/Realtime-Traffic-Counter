Realtime Traffic Counter Prototype

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

git clone [https://github.com/azzikriputra6661/Realtime-Traffic-Counter.git](https://github.com/azzikriputra6661/Realtime-Traffic-Counter.git)
cd Realtime-Traffic-Counter/web_prototype

### Langkah 2: Setup Lingkungan (Metode Virtual Environment)

1. **Buat virtual environment**
python3 -m venv venv_gpu

2. **Aktifkan environment**
source venv_gpu/bin/activate

3. **Install semua library yang dibutuhkan**
pip install -r requirements.txt
