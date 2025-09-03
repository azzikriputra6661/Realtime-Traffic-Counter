# app.py (VERSI FINAL - SCRAPER + STREAMING DI FRONTEND + PERFORMA TINGGI)

import requests
from bs4 import BeautifulSoup
import re
import json
import threading
import copy
from flask import Flask, render_template, Response, jsonify
from ultralytics import YOLO
from collections import defaultdict
import cv2
import sqlite3
import datetime
import time
import streamlink
from streamlink import Streamlink

# --- [BARU] Kelas Pembaca Stream untuk Performa Tinggi ---
class VideoStreamReader:
    def __init__(self, stream_url):
        self.stream_url = stream_url
        self.cap = cv2.VideoCapture(self.stream_url)
        if not self.cap.isOpened():
            raise IOError(f"Tidak dapat membuka stream: {self.stream_url}")
        
        self.grabbed, self.frame = self.cap.read()
        self.stopped = False
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

    def update(self):
        while not self.stopped:
            grabbed, frame = self.cap.read()
            if not grabbed:
                self.stopped = True
                break
            self.grabbed, self.frame = grabbed, frame
            time.sleep(0.01)
    
    def read(self):
        return self.grabbed, self.frame

    def stop(self):
        self.stopped = True
        if self.thread.is_alive():
            self.thread.join()
        if self.cap.isOpened():
            self.cap.release()
        print("Thread VideoStreamReader dihentikan.")

# --- Inisialisasi Aplikasi dan Konfigurasi ---
app = Flask(__name__)
model = YOLO('best.pt')
DB_FILE = "traffic_data.db"
ATCS_PAGE_URL = "https://atcs.sumedangkab.go.id/lokasicctv"
CLASS_MAPPING = { "mobil": "mobil", "motor": "motor", "bus": "bus", "truk": "truk" }
COLOR_MAPPING = { "mobil": (0, 255, 0), "motor": (255, 0, 0), "bus": (0, 0, 255), "truk": (255, 255, 0) }
CCTV_CONFIG = {} 

def get_all_fresh_stream_urls():
    try:
        print(f"Mencoba mengambil SEMUA URL stream baru dari: {ATCS_PAGE_URL}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36'}
        response = requests.get(ATCS_PAGE_URL, headers=headers, timeout=20)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        cctv_urls = {}
        buttons = soup.find_all('button', onclick=re.compile(r"openLiveCam\("))
        for button in buttons:
            onclick_attr = button['onclick']
            url_match = re.search(r"openLiveCam\('(.*?)'\)", onclick_attr)
            if url_match:
                url = url_match.group(1)
                name_tag = button.find_next_sibling('div').find('p')
                if name_tag:
                    name = name_tag.text.strip()
                    cctv_id = name.lower().replace(' ', '_').replace('-', '_')
                    cctv_urls[cctv_id] = {'nama': name, 'url': url}
        print(f"Berhasil men-scrape {len(cctv_urls)} URL CCTV.")
        return cctv_urls
    except Exception as e:
        print(f"Terjadi error fatal saat scraping URL: {e}")
        return None

def load_config_and_initialize_db():
    global CCTV_CONFIG
    scraped_data = get_all_fresh_stream_urls() or {}
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            cctv_metadata = json.load(f)
    except FileNotFoundError:
        cctv_metadata = {}
    
    for cctv_id, data in scraped_data.items():
        CCTV_CONFIG[cctv_id] = data
        if cctv_id in cctv_metadata:
            CCTV_CONFIG[cctv_id].update(cctv_metadata[cctv_id])
    print("Penggabungan data dinamis dan statis selesai.")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS traffic_stats_directional (
        cctv_id TEXT NOT NULL, direction TEXT NOT NULL, motor INTEGER DEFAULT 0,
        mobil INTEGER DEFAULT 0, bus INTEGER DEFAULT 0, truk INTEGER DEFAULT 0,
        total INTEGER DEFAULT 0, start_time DATETIME, last_update DATETIME,
        PRIMARY KEY (cctv_id, direction)
    )
    ''')
    if CCTV_CONFIG:
        for cctv_id in CCTV_CONFIG.keys():
            cursor.execute("INSERT OR IGNORE INTO traffic_stats_directional (cctv_id, direction) VALUES (?, 'normal')", (cctv_id,))
            cursor.execute("INSERT OR IGNORE INTO traffic_stats_directional (cctv_id, direction) VALUES (?, 'opposite')", (cctv_id,))
    conn.commit()
    conn.close()
    print("Database 'traffic_stats_directional' siap digunakan.")

# --- FUNGSI GENERATE FRAMES DENGAN PERFORMA TINGGI ---
def generate_frames(cctv_id):
    cctv_data = CCTV_CONFIG.get(cctv_id)
    if not cctv_data or not cctv_data.get('url'):
        print(f"Konfigurasi atau URL untuk {cctv_id} tidak ditemukan."); return

    url_stream = cctv_data.get('url')
    headers = {'Referer': 'https://atcs.sumedangkab.go.id/','User-Agent': 'Mozilla/5.0'}
    
    y_normal = cctv_data.get('y_normal', 405)
    y_opposite = cctv_data.get('y_opposite', 500)

    # [BARU] Loop utama untuk menangani reconnect
    while True:
        vs = None
        try:
            print(f"[{cctv_id}] (Re)Connecting to stream...")
            session = Streamlink(); session.set_option("http-headers", headers)
            streams = session.streams(url_stream)
            if not streams:
                print(f"[{cctv_id}] Tidak ada stream ditemukan. Mencoba lagi dalam 15 detik...")
                time.sleep(15)
                continue # Kembali ke awal loop reconnect

            stream_url = streams["best"].to_url()
            
            # Gunakan VideoStreamReader untuk performa
            vs = VideoStreamReader(stream_url)
            print(f"[{cctv_id}] Berhasil terhubung. Memulai pemrosesan dan streaming...")
            
            track_history = defaultdict(lambda: [])
            crossed_ids = set()

            # Loop dalam untuk memproses frame
            while True:
                success, frame = vs.read()
                if not success or vs.stopped:
                    print(f"[{cctv_id}] Stream reader berhenti atau gagal membaca frame. Akan mencoba menyambung kembali.")
                    break # Keluar dari loop ini untuk memicu reconnect

                # --- Bagian pemrosesan & penggambaran frame ---
                processed_frame = frame.copy()
                frame_kecil = cv2.resize(frame, (640, 480))
                
                results = model.track(frame_kecil, persist=True, conf=0.3, tracker="bytetrack.yaml", verbose=False, device=0)
                
                if results[0].boxes.id is not None:
                    # Logika scaling dan gambar manual (tidak berubah)
                    boxes = results[0].boxes.xyxy.cpu().numpy()
                    track_ids = results[0].boxes.id.int().cpu().tolist()
                    class_ids = results[0].boxes.cls.int().cpu().tolist()
                    confs = results[0].boxes.conf.cpu().numpy()
                    scale_w = frame.shape[1] / frame_kecil.shape[1]
                    scale_h = frame.shape[0] / frame_kecil.shape[0]

                    for i, box in enumerate(boxes):
                        x1, y1, x2, y2 = box
                        track_id, cls_id, conf = track_ids[i], class_ids[i], confs[i]
                        class_name = model.names.get(cls_id, "unknown")
                        x1_s, y1_s = int(x1 * scale_w), int(y1 * scale_h)
                        x2_s, y2_s = int(x2 * scale_w), int(y2 * scale_h)

                        label = f"id:{track_id} {class_name} {conf:.2f}"
                        color = COLOR_MAPPING.get(class_name, (255, 0, 0)); thickness = 2; font_scale = 0.5
                        
                        cv2.rectangle(processed_frame, (x1_s, y1_s), (x2_s, y2_s), color, thickness)
                        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
                        cv2.rectangle(processed_frame, (x1_s, y1_s - h - 5), (x1_s + w, y1_s), color, -1)
                        cv2.putText(processed_frame, label, (x1_s, y1_s - 3), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 1)

                        # Logika penghitungan (tidak berubah)
                        center_y_asli = int((y1_s + y2_s) / 2)
                        track = track_history[track_id]
                        track.append(center_y_asli)
                        if len(track) > 5: track.pop(0)
                        if len(track) > 1 and track_id not in crossed_ids:
                            db_class_name = CLASS_MAPPING.get(class_name)
                            if not db_class_name: continue
                            direction = None
                            if track[-1] >= y_normal and any(y < y_normal for y in track): direction = "normal"
                            elif track[-1] <= y_opposite and any(y > y_opposite for y in track): direction = "opposite"
                            if direction:
                                crossed_ids.add(track_id)
                                print(f"✅ [{cctv_id}] DIHITUNG ({direction.upper()}): {class_name}")
                                conn = sqlite3.connect(DB_FILE, timeout=10)
                                cursor = conn.cursor()
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                query = f"UPDATE traffic_stats_directional SET {db_class_name}={db_class_name}+1, total=total+1, start_time=COALESCE(start_time,?), last_update=? WHERE cctv_id=? AND direction=?"
                                cursor.execute(query, (now_str, now_str, cctv_id, direction))
                                conn.commit()
                                conn.close()
                                if track_id in track_history: track_history.pop(track_id)
                
                # Gambar garis hitung
                height, width, _ = processed_frame.shape
                cv2.line(processed_frame, (0, y_normal), (width, y_normal), (0, 255, 0), 2)
                cv2.line(processed_frame, (0, y_opposite), (width, y_opposite), (0, 0, 255), 2)
                
                ret, buffer = cv2.imencode('.jpg', processed_frame)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        except Exception as e:
            print(f"Terjadi error pada stream {cctv_id}: {e}")
        
        finally:
            # Hentikan thread reader dan tutup koneksi saat ini
            if vs is not None:
                vs.stop()
            print(f"[{cctv_id}] Koneksi ditutup. Mencoba lagi dalam 15 detik...")
            time.sleep(15) # Jeda sebelum loop utama mencoba koneksi baru

# --- Flask Routes ---  
@app.route('/')
def index():
    return render_template('index.html', cctv_list=CCTV_CONFIG)

@app.route('/cctv/<cctv_id>')
def cctv_view(cctv_id):
    cctv_name = CCTV_CONFIG.get(cctv_id, {}).get('nama', 'CCTV Tidak Dikenal')
    return render_template('cctv_view.html', cctv_id=cctv_id, cctv_name=cctv_name)

@app.route('/video_feed/<cctv_id>')
def video_feed(cctv_id):
    return Response(generate_frames(cctv_id), mimetype='multipart/x-mixed-replace; boundary=frame')
    
@app.route('/api/stats/<cctv_id>')
def get_traffic_stats(cctv_id):
    # ... (Isi fungsi API tidak ada yang berubah, sudah benar) ...
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row; cursor = conn.cursor()
    def calculate_stats_for_direction(direction):
        cursor.execute("SELECT * FROM traffic_stats_directional WHERE cctv_id = ? AND direction = ?", (cctv_id, direction))
        data = cursor.fetchone()
        if not data or not data['start_time']: return {'cumulative': {'motor': 0, 'mobil': 0, 'bus': 0, 'truk': 0, 'total': 0, 'last_update': None},'averages': {'per_minute': 0, 'per_5_minutes': 0, 'per_hour': 0, 'per_day': 0},'duration_string': 'Belum ada data'}
        start_time = datetime.datetime.fromisoformat(data['start_time']); now = datetime.datetime.now()
        duration = now - start_time; total_seconds = duration.total_seconds()
        total_minutes = max(1, total_seconds / 60)
        days, rem = divmod(total_seconds, 86400); hours, rem = divmod(rem, 3600); minutes, _ = divmod(rem, 60)
        duration_string = f"{int(days)}h {int(hours)}j {int(minutes)}m"; total_vehicles = data['total']; avg_per_minute = total_vehicles / total_minutes
        return {'cumulative': dict(data),'averages': {'per_minute': round(avg_per_minute, 1), 'per_5_minutes': round(avg_per_minute * 5, 1),'per_hour': round(avg_per_minute * 60, 1), 'per_day': round(avg_per_minute * 1440, 1)},'duration_string': duration_string}
    stats_normal = calculate_stats_for_direction('normal'); stats_opposite = calculate_stats_for_direction('opposite'); conn.close()
    return jsonify({'normal': stats_normal, 'opposite': stats_opposite})


if __name__ == '__main__':
    load_config_and_initialize_db()
    app.run(debug=True, threaded=True, use_reloader=False)