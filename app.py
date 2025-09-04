# File: app.py (Dengan Perbaikan NameError)

import json
from flask import Flask, render_template, Response, jsonify
import redis
import sqlite3
import datetime
import time
from collections import defaultdict

# --- Inisialisasi Aplikasi dan Konfigurasi ---
app = Flask(__name__)
DB_FILE = r"E:/GeminkDanLainLain/Tugas gwej/TOPIK MAGANG/REALTIME TRAFFIC COUNTER/web_prototype/traffic_data.db"
REDIS_HOST = 'localhost'
REDIS_PORT = 6379
CCTV_CONFIG = {}

def load_config():
    """Memuat konfigurasi CCTV terbaru yang sudah disiapkan oleh worker."""
    global CCTV_CONFIG
    try:
        with open('cctv_config_latest.json', 'r', encoding='utf-8') as f:
            CCTV_CONFIG = json.load(f)
        print(f"Berhasil memuat {len(CCTV_CONFIG)} CCTV dari 'cctv_config_latest.json' untuk dasbor.")
    except Exception as e:
        print(f"GAGAL MEMUAT 'cctv_config_latest.json': {e}. Pastikan counter_worker.py sudah dijalankan terlebih dahulu.")

# --- [PERBAIKAN] Fungsi bantuan ini sekarang menjadi fungsi global ---
def calculate_stats_for_data(data_row):
    """Menerima satu baris data dari database dan menghitung semua statistik."""
    default_cumulative = {
        'kelas_1_sepeda_motor': 0, 'kelas_2_minibus_r4_pribadi_atau_elf': 0, 
        'kelas_3_kendaraan_berat': 0, 'kelas_4_bus_besar': 0, 'kelas_5_truk_besar': 0, 
        'total': 0, 'last_update': None
    }

    if not data_row or not data_row['start_time']: 
        return {
            'cumulative': default_cumulative,
            'averages': {'per_minute': 0, 'per_5_minutes': 0, 'per_hour': 0, 'per_day': 0},
            'duration_string': 'Belum ada data'
        }
            
    start_time = datetime.datetime.fromisoformat(data_row['start_time']); now = datetime.datetime.now()
    duration = now - start_time; total_seconds = duration.total_seconds()
    total_minutes = max(1, total_seconds / 60)
    days, rem = divmod(total_seconds, 86400); hours, rem = divmod(rem, 3600); minutes, _ = divmod(rem, 60)
    duration_string = f"{int(days)}h {int(hours)}j {int(minutes)}m"
    total_vehicles = data_row['total']; avg_per_minute = total_vehicles / total_minutes
    
    cumulative_data = default_cumulative.copy()
    cumulative_data.update(dict(data_row))

    return {
        'cumulative': cumulative_data,
        'averages': {
            'per_minute': round(avg_per_minute, 1), 
            'per_5_minutes': round(avg_per_minute * 5, 1),
            'per_hour': round(avg_per_minute * 60, 1), 
            'per_day': round(avg_per_minute * 1440, 1)
        },
        'duration_string': duration_string
    }

# --- Flask Routes ---
@app.route('/')
def index():
    print(f"Total lokasi utama yang dimuat dari config: {len(CCTV_CONFIG)}")
    return render_template('index.html', active_page='index', cctv_list=CCTV_CONFIG)

@app.route('/cctv/<cctv_id>')
def cctv_view(cctv_id):
    cctv_name = CCTV_CONFIG.get(cctv_id, {}).get('nama', cctv_id.replace('_', ' ').title())
    return render_template('cctv_view.html', cctv_id=cctv_id, cctv_name=cctv_name)

@app.route('/video_feed/<cctv_id>')
def video_feed(cctv_id):
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT); p = r.pubsub(ignore_subscribe_messages=True)
    channel_name = f"cctv_stream:{cctv_id}"; p.subscribe(channel_name)
    print(f"[Web Client] Mendengarkan di: {channel_name}")
    def generate():
        try:
            for message in p.listen():
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + message['data'] + b'\r\n')
        finally:
            print(f"[Web Client] Berhenti mendengarkan: {channel_name}"); p.close()
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')
    
@app.route('/api/stats/<cctv_id>')
def get_traffic_stats(cctv_id):
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM traffic_stats_directional WHERE cctv_id = ? AND direction = 'normal'", (cctv_id,))
    normal_data_row = cursor.fetchone()
    
    cursor.execute("SELECT * FROM traffic_stats_directional WHERE cctv_id = ? AND direction = 'opposite'", (cctv_id,))
    opposite_data_row = cursor.fetchone()
    
    conn.close()
    
    # Panggil fungsi bantuan yang sudah global
    return jsonify({
        'normal': calculate_stats_for_data(normal_data_row), 
        'opposite': calculate_stats_for_data(opposite_data_row)
    })

@app.route('/api/summary/all_active')
def get_all_stats_summary():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM traffic_stats_directional WHERE start_time IS NOT NULL ORDER BY cctv_id, direction")
    all_data = cursor.fetchall()
    conn.close()

    summary = defaultdict(dict) # Gunakan defaultdict agar lebih mudah
    
    # Proses data dari database terlebih dahulu
    for row in all_data:
        cctv_id = row['cctv_id']
        direction = row['direction']
        summary[cctv_id][direction] = {
            "cumulative": dict(row),
        }
    
    # --- BAGIAN MODIFIKASI UTAMA ---
    # Gabungkan dengan data dari config.json
    summary_with_metadata = {}
    for cctv_id, data in summary.items():
        config_info = CCTV_CONFIG.get(cctv_id, {})
        
        # Buat entri baru yang sudah lengkap
        summary_with_metadata[cctv_id] = {
            "nama": config_info.get("nama", cctv_id),
            "label_normal": config_info.get("label_normal", "Arah Normal"),
            "label_opposite": config_info.get("label_opposite", "Arah Opposite"),
            "normal": data.get("normal", {}),
            "opposite": data.get("opposite", {})
        }
        
    return jsonify(summary_with_metadata)

@app.route('/summary')
def summary_view():
    return render_template('traffic_count_view.html', active_page='summary')

@app.route('/about')
def about_view():
    return render_template('about.html', active_page='about')

if __name__ == '__main__':
    load_config()
    app.run(debug=True, port=5000, use_reloader=False)