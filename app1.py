# app.py (VERSI FINAL DENGAN PANAH & DEBUG)

from flask import Flask, render_template, Response, jsonify
from ultralytics import YOLO
from collections import defaultdict
import cv2
import json
import sqlite3
import datetime
import numpy as np
import time

# Inisialisasi Aplikasi Flask
app = Flask(__name__)

# Muat Model (cukup sekali saat aplikasi dimulai)
model = YOLO('best.pt') 

# Muat Konfigurasi CCTV
with open('config.json', 'r') as f:
    cctv_config = json.load(f)

# Kunci DICTIONARY disesuaikan dengan output model custom Anda
CLASS_MAPPING = {
    "mobil": "mobil",
    "motor": "motor",
    "bus": "bus",
    "truk": "truk"
}

# Inisialisasi Database
DB_FILE = "traffic_data.db"

def inisialisasi_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Membuat tabel baru untuk menyimpan data volume per interval
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS traffic_volume (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cctv_id TEXT NOT NULL,
        timestamp DATETIME NOT NULL,
        interval_type TEXT NOT NULL, -- '5_min', 'hourly', 'daily'
        direction TEXT NOT NULL,     -- 'normal', 'opposite'
        motor INTEGER DEFAULT 0,
        mobil INTEGER DEFAULT 0,
        bus INTEGER DEFAULT 0,
        truk INTEGER DEFAULT 0,
        UNIQUE(cctv_id, timestamp, interval_type, direction)
    )
    ''')
    conn.commit()
    conn.close()
    print("Database 'traffic_volume' siap digunakan.")

inisialisasi_database()

def generate_frames(cctv_id):
    cctv_data = cctv_config.get(cctv_id)
    if not cctv_data:
        return

    url_stream = cctv_data.get('url')
    cap = cv2.VideoCapture(url_stream)
    track_history = defaultdict(lambda: [])
    
    Y_NORMAL_LINE = 500
    Y_OPPOSITE_LINE = 405
    
    crossed_ids = set()
    
    # Fungsi bantuan untuk menyimpan/update data volume
    def update_volume_data(timestamp, interval_type, direction, vehicle_class):
        conn = sqlite3.connect(DB_FILE, timeout=10)
        cursor = conn.cursor()
        
        # Menggunakan UPSERT (UPDATE atau INSERT) untuk efisiensi
        # Jika kombinasi unik sudah ada, ia akan UPDATE. Jika tidak, ia akan INSERT baris baru.
        query = f"""
        INSERT INTO traffic_volume (cctv_id, timestamp, interval_type, direction, {vehicle_class})
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(cctv_id, timestamp, interval_type, direction) DO UPDATE SET
        {vehicle_class} = {vehicle_class} + 1;
        """
        cursor.execute(query, (cctv_id, timestamp, interval_type, direction))
        conn.commit()
        conn.close()

    try:
        while True:
            success, frame = cap.read()
            if not success:
                time.sleep(2)
                cap.release(); cap = cv2.VideoCapture(url_stream)
                continue

            height, width, _ = frame.shape
            LINE_NORMAL_START = (0, Y_NORMAL_LINE)
            LINE_NORMAL_END = (width, Y_NORMAL_LINE)
            LINE_OPPOSITE_START = (0, Y_OPPOSITE_LINE)
            LINE_OPPOSITE_END = (width, Y_OPPOSITE_LINE)

            results = model.track(frame, persist=True, conf=0.3, tracker="bytetrack.yaml")
            
            processed_frame = results[0].plot()
            
            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu()
                track_ids = results[0].boxes.id.int().cpu().tolist()
                class_ids = results[0].boxes.cls.int().cpu().tolist()

                for box, track_id, cls_id in zip(boxes, track_ids, class_ids):
                    center_y = int((box[1] + box[3]) / 2)
                    track = track_history[track_id]
                    track.append(center_y)
                    if len(track) > 5: track.pop(0)

                    if len(track) > 1 and track_id not in crossed_ids:
                        class_name = model.names.get(cls_id, "unknown")
                        db_class_name = CLASS_MAPPING.get(class_name)

                        if not db_class_name:
                            continue

                        direction_to_check = None
                        # Cek Arah Normal
                        if track[-1] >= Y_NORMAL_LINE and any(y < Y_NORMAL_LINE for y in track):
                            direction_to_check = "normal"
                        # Cek Arah Opposite
                        elif track[-1] <= Y_OPPOSITE_LINE and any(y > Y_OPPOSITE_LINE for y in track):
                            direction_to_check = "opposite"
                        
                        # Jika ada kendaraan yang terdeteksi melintas
                        if direction_to_check:
                            crossed_ids.add(track_id)
                            print(f"✅ DIHITUNG ({direction_to_check.upper()}): ID {track_id}, KELAS: {class_name}")

                            # Hitung "ember waktu"
                            now = datetime.datetime.now()
                            ts_5_min = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)
                            ts_hourly = now.replace(minute=0, second=0, microsecond=0)
                            ts_daily = now.replace(hour=0, minute=0, second=0, microsecond=0)

                            # Simpan data untuk ketiga interval
                            update_volume_data(ts_5_min, '5_min', direction_to_check, db_class_name)
                            update_volume_data(ts_hourly, 'hourly', direction_to_check, db_class_name)
                            update_volume_data(ts_daily, 'daily', direction_to_check, db_class_name)

                            if track_id in track_history: track_history.pop(track_id)

            cv2.line(processed_frame, LINE_NORMAL_START, LINE_NORMAL_END, (0, 255, 0), 2)
            cv2.line(processed_frame, LINE_OPPOSITE_START, LINE_OPPOSITE_END, (0, 0, 255), 2)
            cv2.arrowedLine(processed_frame, (width - 25, Y_NORMAL_LINE - 15), (width - 25, Y_NORMAL_LINE + 15), (0, 255, 255), 2, tipLength=0.4)
            cv2.arrowedLine(processed_frame, (width - 25, Y_OPPOSITE_LINE + 15), (width - 25, Y_OPPOSITE_LINE - 15), (0, 255, 255), 2, tipLength=0.4)

            ret, buffer = cv2.imencode('.jpg', processed_frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    
    except Exception as e:
        print(f"Terjadi error pada stream {cctv_id}: {e}")
    finally:
        print(f"Menutup stream untuk {cctv_id}.")
        cap.release()

# --- Sisa FLASK ROUTES tidak perlu diubah ---
@app.route('/')
def index():
    return render_template('index.html', cctv_list=cctv_config, active_page='index')

@app.route('/cctv/<cctv_id>')
def cctv_view(cctv_id):
    cctv_data = cctv_config.get(cctv_id)
    if not cctv_data:
        return "CCTV tidak ditemukan", 404
    
    return render_template('cctv_view.html', 
                           cctv_id=cctv_id,
                           cctv_name=cctv_data.get('nama'),
                           show_back_button=True)

@app.route('/video_feed/<cctv_id>')
def video_feed(cctv_id):
    return Response(generate_frames(cctv_id), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/volume/current/<cctv_id>')
def get_current_volume(cctv_id):
    """
    Mengambil data volume untuk interval 5 menit saat ini.
    Ini yang akan Anda gunakan untuk 'Data Real-Time' di dashboard.
    """
    now = datetime.datetime.now()
    # Tentukan bucket 5 menit saat ini
    current_bucket = now.replace(minute=now.minute // 5 * 5, second=0, microsecond=0)

    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ambil data untuk arah Normal
    cursor.execute("""
        SELECT * FROM traffic_volume 
        WHERE cctv_id = ? AND interval_type = '5_min' AND direction = 'normal' AND timestamp = ?
    """, (cctv_id, current_bucket))
    normal_data = cursor.fetchone()

    # Ambil data untuk arah Opposite
    cursor.execute("""
        SELECT * FROM traffic_volume 
        WHERE cctv_id = ? AND interval_type = '5_min' AND direction = 'opposite' AND timestamp = ?
    """, (cctv_id, current_bucket))
    opposite_data = cursor.fetchone()
    
    conn.close()

    # Format data untuk dikirim sebagai JSON
    result = {
        'timestamp': current_bucket.isoformat(),
        'normal': dict(normal_data) if normal_data else {'motor': 0, 'mobil': 0, 'bus': 0, 'truk': 0},
        'opposite': dict(opposite_data) if opposite_data else {'motor': 0, 'mobil': 0, 'bus': 0, 'truk': 0}
    }
    
    return jsonify(result)

@app.route('/api/volume/summary/<cctv_id>')
def get_volume_summary(cctv_id):
    """
    Mengambil data rekapitulasi per jam untuk hari ini.
    Berguna untuk membuat grafik atau tabel harian.
    """
    today_bucket = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Ambil semua data per jam untuk hari ini
    cursor.execute("""
        SELECT timestamp, direction, motor, mobil, bus, truk 
        FROM traffic_volume
        WHERE cctv_id = ? AND interval_type = 'hourly' AND DATE(timestamp) = DATE(?)
        ORDER BY timestamp, direction
    """, (cctv_id, today_bucket))
    
    hourly_data = cursor.fetchall()
    conn.close()

    # Kelompokkan data untuk kemudahan penggunaan di frontend
    summary = {}
    for row in hourly_data:
        ts = row['timestamp']
        if ts not in summary:
            summary[ts] = {}
        summary[ts][row['direction']] = dict(row)

    return jsonify(summary)
@app.route('/api/reset/<cctv_id>', methods=['POST'])
def reset_counts(cctv_id):
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("UPDATE counts SET motor=0, mobil=0, bus=0, truk=0, last_update=? WHERE cctv_id = ?",
                       (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), cctv_id))
        conn.commit()
        conn.close()
        return jsonify({'status': 'success', 'message': f'Counter untuk {cctv_id} berhasil direset.'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, threaded=True)