from ultralytics import YOLO
from collections import defaultdict
import cv2
import json
import sqlite3
import datetime
import time
import streamlink
from streamlink import Streamlink
import requests
from bs4 import BeautifulSoup

# Inisialisasi Aplikasi Flask
app = Flask(__name__)
model = YOLO('best.pt') 

with open('config.json', 'r') as f:
    cctv_config = json.load(f)

# Pastikan kunci dictionary sesuai dengan output model Anda
CLASS_MAPPING = { "mobil": "mobil", "motor": "motor", "bus": "bus", "truk": "truk" }
DB_FILE = "traffic_data.db"

# [SINKRON] Membuat tabel 'traffic_stats' yang benar
# Di app.py
def inisialisasi_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    # Tabel final dengan pemisahan arah
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS traffic_stats_directional (
        cctv_id TEXT NOT NULL,
        direction TEXT NOT NULL, -- 'normal' atau 'opposite'
        motor INTEGER DEFAULT 0,
        mobil INTEGER DEFAULT 0,
        bus INTEGER DEFAULT 0,
        truk INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0,
        start_time DATETIME,
        last_update DATETIME,
        PRIMARY KEY (cctv_id, direction)
    )
    ''')
    # Buat baris default untuk setiap CCTV dan setiap arah
    for cctv_id in cctv_config:
        cursor.execute("INSERT OR IGNORE INTO traffic_stats_directional (cctv_id, direction) VALUES (?, 'normal')", (cctv_id,))
        cursor.execute("INSERT OR IGNORE INTO traffic_stats_directional (cctv_id, direction) VALUES (?, 'opposite')", (cctv_id,))
    conn.commit()
    conn.close()
    print("Database 'traffic_stats_directional' siap digunakan.")   

inisialisasi_database()

# [SINKRON] Fungsi generate_frames yang menulis ke 'traffic_stats'
# Di app.py, ganti seluruh fungsi generate_frames
def generate_frames(cctv_id):
    # ... (bagian inisialisasi streamlink, cap, track_history, garis, dll tetap sama) ...
    cctv_data = cctv_config.get(cctv_id);
    if not cctv_data: return
    url_stream = cctv_data.get('url')
    headers = {'Referer': 'https://atcs.sumedangkab.go.id/', 'Origin': 'https://atcs.sumedangkab.go.id', 'User-Agent': 'Mozilla/5.0'}
    try:
        session = Streamlink(); session.set_option("http-headers", headers)
        streams = session.streams(url_stream)
        if not streams: print(f"Error: Tidak ada stream di {cctv_id}"); return
        stream_url = streams["best"].to_url()
        cap = cv2.VideoCapture(stream_url)
        print(f"Berhasil terhubung ke stream {cctv_id}")
    except Exception as e:
        print(f"Error saat inisialisasi streamlink: {e}"); return

    track_history = defaultdict(lambda: []); Y_NORMAL_LINE = 500; Y_OPPOSITE_LINE = 405; crossed_ids = set()
    
    try:
        while True:
            success, frame = cap.read()
            if not success:
                time.sleep(5); cap.release(); cap = cv2.VideoCapture(stream_url); continue

            height, width, _ = frame.shape
            LINE_NORMAL_START = (0, Y_NORMAL_LINE); LINE_NORMAL_END = (width, Y_NORMAL_LINE)
            LINE_OPPOSITE_START = (0, Y_OPPOSITE_LINE); LINE_OPPOSITE_END = (width, Y_OPPOSITE_LINE)
            results = model.track(frame, persist=True, conf=0.3, tracker="bytetrack.yaml")
            processed_frame = results[0].plot()
            
            if results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu(); track_ids = results[0].boxes.id.int().cpu().tolist(); class_ids = results[0].boxes.cls.int().cpu().tolist()

                for box, track_id, cls_id in zip(boxes, track_ids, class_ids):
                    center_y = int((box[1] + box[3]) / 2); track = track_history[track_id]; track.append(center_y)
                    if len(track) > 5: track.pop(0)

                    if len(track) > 1 and track_id not in crossed_ids:
                        class_name = model.names.get(cls_id, "unknown")
                        db_class_name = CLASS_MAPPING.get(class_name)
                        if not db_class_name: continue

                        direction = None
                        if track[-1] >= Y_NORMAL_LINE and any(y < Y_NORMAL_LINE for y in track):
                            direction = "normal"
                        elif track[-1] <= Y_OPPOSITE_LINE and any(y > Y_OPPOSITE_LINE for y in track):
                            direction = "opposite"
                        
                        if direction:
                            crossed_ids.add(track_id)
                            print(f"✅ DIHITUNG ({direction.upper()}): ID {track_id}, KELAS: {class_name}")

                            conn = sqlite3.connect(DB_FILE, timeout=10)
                            cursor = conn.cursor()
                            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            # [LOGIKA BARU] Update baris berdasarkan cctv_id DAN direction
                            query = f"""
                            UPDATE traffic_stats_directional 
                            SET 
                                {db_class_name} = {db_class_name} + 1,
                                total = total + 1,
                                start_time = COALESCE(start_time, ?),
                                last_update = ?
                            WHERE cctv_id = ? AND direction = ?
                            """
                            cursor.execute(query, (now_str, now_str, cctv_id, direction))
                            conn.commit()
                            conn.close()
                            
                            if track_id in track_history: track_history.pop(track_id)

            cv2.line(processed_frame, LINE_NORMAL_START, LINE_NORMAL_END, (0, 255, 0), 2)
            cv2.line(processed_frame, LINE_OPPOSITE_START, LINE_OPPOSITE_END, (0, 0, 255), 2)
            ret, buffer = cv2.imencode('.jpg', processed_frame)
            frame_bytes = buffer.tobytes()
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
    
    except Exception as e:
        print(f"Terjadi error pada stream {cctv_id}: {e}")
    finally:
        print(f"Menutup stream untuk {cctv_id}.")
        if 'cap' in locals() and cap.isOpened():
            cap.release()

# --- FLASK ROUTES ---
@app.route('/')
def index():
    return render_template('index.html', cctv_list=cctv_config, active_page='index')

@app.route('/cctv/<cctv_id>')
def cctv_view(cctv_id):
    return render_template('cctv_view.html', cctv_id=cctv_id, cctv_name=cctv_config.get(cctv_id, {}).get('nama'))

@app.route('/video_feed/<cctv_id>')
def video_feed(cctv_id):
    return Response(generate_frames(cctv_id), mimetype='multipart/x-mixed-replace; boundary=frame')

# [SINKRON] API baru '/api/stats/' untuk menghitung rata-rata
@app.route('/api/stats/<cctv_id>')
def get_traffic_stats(cctv_id):
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Fungsi bantuan untuk menghitung statistik untuk satu arah
    def calculate_stats_for_direction(direction):
        cursor.execute("SELECT * FROM traffic_stats_directional WHERE cctv_id = ? AND direction = ?", (cctv_id, direction))
        data = cursor.fetchone()

        if not data or not data['start_time']:
            return {
                'cumulative': {'motor': 0, 'mobil': 0, 'bus': 0, 'truk': 0, 'total': 0, 'last_update': None},
                'averages': {'per_minute': 0, 'per_5_minutes': 0, 'per_hour': 0, 'per_day': 0},
                'duration_string': 'Belum ada data'
            }

        start_time = datetime.datetime.fromisoformat(data['start_time'])
        now = datetime.datetime.now()
        duration = now - start_time
        total_seconds = duration.total_seconds()
        
        total_minutes = max(1, total_seconds / 60)
        
        days, rem = divmod(total_seconds, 86400); hours, rem = divmod(rem, 3600); minutes, _ = divmod(rem, 60)
        duration_string = f"{int(days)}h {int(hours)}j {int(minutes)}m"

        total_vehicles = data['total']
        avg_per_minute = total_vehicles / total_minutes
        
        return {
            'cumulative': dict(data),
            'averages': {
                'per_minute': round(avg_per_minute, 1),
                'per_5_minutes': round(avg_per_minute * 5, 1),
                'per_hour': round(avg_per_minute * 60, 1),
                'per_day': round(avg_per_minute * 1440, 1) # 60 menit * 24 jam
            },
            'duration_string': duration_string
        }

    # Hitung statistik untuk kedua arah
    stats_normal = calculate_stats_for_direction('normal')
    stats_opposite = calculate_stats_for_direction('opposite')
    
    conn.close()

    # Gabungkan hasilnya dalam satu JSON
    return jsonify({
        'normal': stats_normal,
        'opposite': stats_opposite
    })
if __name__ == '__main__':
    app.run(debug=True, threaded=True)