    # check_db.py
import sqlite3

DB_FILE = "traffic_data.db"
TABLE_NAME = "counts"

print(f"Membaca isi dari database: {DB_FILE}")

try:
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    # Mengambil semua data dari tabel
    cursor.execute(f"SELECT * FROM {TABLE_NAME}")
    rows = cursor.fetchall()

    if not rows:
        print("DATABASE KOSONG! Tidak ada data yang ditemukan.")
    else:
        # Mengambil nama kolom
        column_names = [description[0] for description in cursor.description]
        print("=" * 40)
        print("ISI DATABASE SAAT INI:")
        for row in rows:
            print(dict(zip(column_names, row)))
        print("=" * 40)

    conn.close()

except Exception as e:
    print(f"Terjadi error saat membaca database: {e}")