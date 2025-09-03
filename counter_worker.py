# File: counter_worker.py

import cv2
import sqlite3
import datetime
import time
import json
import threading
from collections import defaultdict
from ultralytics import YOLO
import streamlink
from streamlink import Streamlink
import requests
from bs4 import BeautifulSoup
import re
import redis
import numpy as np
import argparse

# --- KELAS UNTUK PERFORMA STREAMING ---
class VideoStreamReader:
    def __init__(self, stream_url):
        self.cap = cv2.VideoCapture(stream_url)
        if not self.cap.isOpened(): raise IOError(f"Tidak dapat membuka stream: {stream_url}")
        self.grabbed, self.frame = self.cap.read()
        self.stopped = False
        self.thread = threading.Thread(target=self.update, args=()); self.thread.daemon = True; self.thread.start()
    def update(self):
        while not self.stopped:
            grabbed, frame = self.cap.read()
            if not grabbed: self.stopped = True; break
            self.grabbed, self.frame = grabbed, frame; time.sleep(0.01)
    def read(self): return self.grabbed, self.frame
    def stop(self):
        self.stopped = True
        if self.thread.is_alive(): self.thread.join()
        if self.cap.isOpened(): self.cap.release()
        print(f"[{threading.current_thread().name}] Thread VideoStreamReader dihentikan.")

# --- KONFIGURASI AWAL ---
print("Memulai Inisialisasi Worker Penghitung Lalu Lintas...")
DB_FILE = r"E:/GeminkDanLainLain/Tugas gwej/TOPIK MAGANG/REALTIME TRAFFIC COUNTER/web_prototype/traffic_data.db"
MODEL = YOLO('best1.pt') 
ATCS_PAGE_URL = "https://atcs.sumedangkab.go.id/lokasicctv"
CLASS_MAPPING = {
    "Kelas 1 Sepeda Motor": "kelas_1_sepeda_motor", 
    "Kelas 2 Minibus R4 Pribadi atau Elf": "kelas_2_minibus_r4_pribadi_atau_elf",
    "Kelas 3 Kendaraan Berat": "kelas_3_kendaraan_berat", 
    "Kelas 4 Bus Besar": "kelas_4_bus_besar", 
    "Kelas 5 Truk Besar": "kelas_5_truk_besar"
}
COLOR_MAPPING = {
    "Kelas 1 Sepeda Motor": (255, 0, 0),      # Biru
    "Kelas 2 Minibus R4 Pribadi atau Elf": (0, 255, 0), # Hijau
    "Kelas 3 Kendaraan Berat": (0, 165, 255), # Oranye
    "Kelas 4 Bus Besar": (0, 0, 255),      # Merah
    "Kelas 5 Truk Besar": (255, 0, 255)    # Magenta
}
REDIS_HOST = 'localhost'; REDIS_PORT = 6379; CCTV_CONFIG = {}

def get_all_fresh_stream_urls():
    try:
        print(f"Mengambil URL stream baru dari: {ATCS_PAGE_URL}")
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(ATCS_PAGE_URL, headers=headers, timeout=20); response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser'); cctv_urls = {}
        buttons = soup.find_all('button', onclick=re.compile(r"openLiveCam\("))
        for button in buttons:
            onclick_attr = button['onclick']
            url_match = re.search(r"openLiveCam\('(.*?)'\)", onclick_attr)
            if url_match:
                url = url_match.group(1); name_tag = button.find_next_sibling('div').find('p')
                if name_tag:
                    name = name_tag.text.strip()
                    cctv_id = name.lower().replace(' ', '_').replace('-', '_')
                    cctv_urls[cctv_id] = {'nama': name, 'url': url}
        print(f" Berhasil men-scrape {len(cctv_urls)} URL CCTV.")
        return cctv_urls
    except Exception as e:
        print(f" Terjadi error saat scraping URL: {e}"); return None

def url_refresh_manager():
    global CCTV_CONFIG
    while True:
        print("\nMemperbarui URL stream...")
        
        # 1. Ambil URL stream terbaru
        scraped_data = get_all_fresh_stream_urls()
        if not scraped_data:
            print("Gagal mengambil URL baru, mencoba lagi nanti.")
            time.sleep(3600) # Coba lagi 1 jam kemudian
            continue

        # 2. Baca file config.json asli yang berisi metadata (thumbnail, lat, lon)
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                cctv_metadata = json.load(f)
        except FileNotFoundError:
            print("Peringatan: config.json tidak ditemukan. Data thumbnail dan geo akan kosong.")
            cctv_metadata = {}
        
        # 3. Gabungkan data
        updated_config = {}
        for cctv_id, scraped_info in scraped_data.items():
            # Ambil data lama (metadata) jika ada
            existing_data = cctv_metadata.get(cctv_id, {})
            
            # Gabungkan: data lama di-update dengan data baru (URL)
            existing_data.update(scraped_info)
            updated_config[cctv_id] = existing_data
        
        CCTV_CONFIG = updated_config

        # 4. Simpan hasil gabungan ke file _latest.json
        try:
            with open('cctv_config_latest.json', 'w', encoding='utf-8') as f:
                json.dump(CCTV_CONFIG, f, indent=4, ensure_ascii=False)
            print(f"Berhasil menyimpan {len(CCTV_CONFIG)} CCTV ke cctv_config_latest.json")
        except Exception as e:
            print(f"Gagal menyimpan file: {e}")
        
        time.sleep(4 * 3600) # Refresh setiap 4 jam

def inisialisasi_database():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS traffic_stats_directional (
        cctv_id TEXT NOT NULL, direction TEXT NOT NULL, 
        kelas_1_sepeda_motor INTEGER DEFAULT 0,
        kelas_2_minibus_r4_pribadi_atau_elf INTEGER DEFAULT 0,
        kelas_3_kendaraan_berat INTEGER DEFAULT 0,
        kelas_4_bus_besar INTEGER DEFAULT 0,
        kelas_5_truk_besar INTEGER DEFAULT 0,
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
    print("Database 'traffic_stats_directional' siap digunakan oleh Worker.")

def process_cctv_stream(cctv_id, cctv_data):
        # --- TAMBAHKAN BLOK INISIALISASI DATABASE DI SINI ---
    try:
        conn_init = sqlite3.connect(DB_FILE, timeout=10)
        cursor_init = conn_init.cursor()
        # Pastikan tabel utama ada
        cursor_init.execute('''
        CREATE TABLE IF NOT EXISTS traffic_stats_directional (
            cctv_id TEXT NOT NULL, direction TEXT NOT NULL, 
            kelas_1_sepeda_motor INTEGER DEFAULT 0,
            kelas_2_minibus_r4_pribadi_atau_elf INTEGER DEFAULT 0, 
            kelas_3_kendaraan_berat INTEGER DEFAULT 0, 
            kelas_4_bus_besar INTEGER DEFAULT 0,
            kelas_5_truk_besar INTEGER DEFAULT 0,
            total INTEGER DEFAULT 0, start_time DATETIME, last_update DATETIME,
            PRIMARY KEY (cctv_id, direction)
        )
        ''')
        # Pastikan baris untuk CCTV ini ada
        cursor_init.execute("INSERT OR IGNORE INTO traffic_stats_directional (cctv_id, direction) VALUES (?, 'normal')", (cctv_id,))
        cursor_init.execute("INSERT OR IGNORE INTO traffic_stats_directional (cctv_id, direction) VALUES (?, 'opposite')", (cctv_id,))
        conn_init.commit()
        conn_init.close()
    except Exception as e:
        print(f"[{cctv_id}] GAGAL inisialisasi database di dalam thread: {e}")
        return # Hentikan thread jika gagal inisialisasi
    # --------------------------------------------------------  
    
    url_stream = cctv_data.get('url')
    headers = {'Referer': 'https://atcs.sumedangkab.go.id/', 'User-Agent': 'Mozilla/5.0'}
    y_normal = cctv_data.get('y_normal', 500)
    y_opposite = cctv_data.get('y_opposite', 405)
    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    track_history = defaultdict(lambda: []); crossed_ids = set()

    while True:
        vs = None
        try:
            print(f"[{cctv_id}] (Re)Connecting...")
            session = Streamlink(); session.set_option("http-headers", headers)
            streams = session.streams(url_stream)
            if not streams:
                print(f"[{cctv_id}] Stream tidak ditemukan. Mencoba lagi..."); time.sleep(15); continue
            
            stream_url = streams["best"].to_url()
            vs = VideoStreamReader(stream_url)
            print(f"[{cctv_id}] Berhasil terhubung. Memulai pemrosesan...")
            
            target_fps = 25
            delay = 1 / target_fps
            
            while True:
                success, frame = vs.read()
                if not success or vs.stopped:
                    print(f"[{cctv_id}] Frame kosong atau reader berhenti."); break
                
                processed_frame = frame.copy()
                frame_kecil = cv2.resize(frame, (640, 480))
                results = MODEL.track(frame_kecil, persist=True, conf=0.3, tracker="bytetrack.yaml", verbose=False, device=0)
                
                if results[0].boxes.id is not None:
                    boxes = results[0].boxes.xyxy.cpu().numpy(); track_ids = results[0].boxes.id.int().cpu().tolist()
                    class_ids = results[0].boxes.cls.int().cpu().tolist(); confs = results[0].boxes.conf.cpu().numpy()
                    scale_w = frame.shape[1] / frame_kecil.shape[1]; scale_h = frame.shape[0] / frame_kecil.shape[0]

                    for i, box in enumerate(boxes):
                        track_id, cls_id, conf = track_ids[i], class_ids[i], confs[i]
                        class_name = MODEL.names.get(cls_id, "unknown")
                        x1_s, y1_s = int(box[0] * scale_w), int(box[1] * scale_h)
                        x2_s, y2_s = int(box[2] * scale_w), int(box[3] * scale_h)
                        label = f"id:{track_id} {class_name} {conf:.2f}"
                        color = COLOR_MAPPING.get(class_name, (255, 255, 255)); thickness = 2; font_scale = 0.5
                        cv2.rectangle(processed_frame, (x1_s, y1_s), (x2_s, y2_s), color, thickness)
                        (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
                        cv2.rectangle(processed_frame, (x1_s, y1_s - h - 10), (x1_s + w, y1_s), color, -1)
                        cv2.putText(processed_frame, label, (x1_s, y1_s - 5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (0, 0, 0), 1)

                        center_y_asli = int((y1_s + y2_s) / 2)
                        track = track_history[track_id]; track.append(center_y_asli)
                        if len(track) > 5: track.pop(0)
                        if len(track) > 1 and track_id not in crossed_ids:
                            db_class_name = CLASS_MAPPING.get(class_name)
                            if not db_class_name: continue
                            direction = None
                            if track[-1] >= y_normal and any(y < y_normal for y in track): direction = "normal"
                            elif track[-1] <= y_opposite and any(y > y_opposite for y in track): direction = "opposite"
                            if direction:
                                crossed_ids.add(track_id)
                                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"); print(f"{timestamp} [{cctv_id}] DIHITUNG ({direction.upper()}): {class_name}")
                                conn = sqlite3.connect(DB_FILE, timeout=10); cursor = conn.cursor()
                                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                query = f"UPDATE traffic_stats_directional SET {db_class_name}={db_class_name}+1, total=total+1, start_time=COALESCE(start_time,?), last_update=? WHERE cctv_id=? AND direction=?"
                                cursor.execute(query, (now_str, now_str, cctv_id, direction)); conn.commit(); conn.close()
                                if track_id in track_history: track_history.pop(track_id)
                
                height, width, _ = processed_frame.shape
                cv2.line(processed_frame, (0, y_normal), (width, y_normal), (0, 255, 0), 2)
                cv2.line(processed_frame, (0, y_opposite), (width, y_opposite), (0, 0, 255), 2)

                ret, buffer = cv2.imencode('.jpg', processed_frame)
                if ret: r.publish(f"cctv_stream:{cctv_id}", buffer.tobytes())
                
                elapsed_time = time.time() - loop_start_time if 'loop_start_time' in locals() else 0
                sleep_time = max(0, delay - elapsed_time)
                if sleep_time > 0:
                        time.sleep(sleep_time)

        except Exception as e:
            print(f"Error besar di thread {cctv_id}: {e}")
        finally:
            if vs: vs.stop()
            print(f"[{cctv_id}] Mencoba lagi dalam 60 detik...")
            time.sleep(60)
            
def display_menu_and_get_choices(cctv_config):
    """Menampilkan menu CCTV dan meminta input dari pengguna."""
    print("\n===== PILIH CCTV UNTUK DIPROSES =====")
    
    # Buat daftar CCTV yang bisa dipilih
    cctv_options = list(cctv_config.keys())
    for i, cctv_id in enumerate(cctv_options):
        print(f"[{i+1}] {cctv_config[cctv_id].get('nama', cctv_id)}")
    print("[A] Proses Semua CCTV")
    print("=======================================")

    while True:
        choice_str = input("Masukkan nomor CCTV (pisahkan dengan koma jika lebih dari satu) atau 'A' untuk semua: ")
        
        if choice_str.strip().upper() == 'A':
            return cctv_options # Kembalikan semua ID CCTV

        try:
            choices = [int(c.strip()) for c in choice_str.split(',')]
            selected_cctvs = [cctv_options[i-1] for i in choices if 1 <= i <= len(cctv_options)]
            
            if selected_cctvs:
                return selected_cctvs
            else:
                print("Pilihan tidak valid, coba lagi.")
        except (ValueError, IndexError):
            print("Input salah. Masukkan nomor yang valid, pisahkan dengan koma.")

if __name__ == '__main__':
    print("--- MEMULAI WORKER ---")
    
    # Langkah 1: Mencoba mengambil data URL dari web
    print("\nMencoba mengambil URL stream dari web...")
    CCTV_CONFIG = get_all_fresh_stream_urls()

    # Periksa apakah scraping berhasil
    if not CCTV_CONFIG:
        print("\nTidak ada data CCTV yang berhasil diambil dari web. Proses berhenti.")
        print("Pastikan koneksi internet Anda stabil dan situs ATCS bisa diakses.")
    else:
        print(f"\nBerhasil mengambil {len(CCTV_CONFIG)} data CCTV dari web.")
        
        # Langkah 2: Mencoba menggabungkan dengan config.json (jika ada)
        print("\nMencoba membaca config.json untuk metadata tambahan...")
        try:
            with open('config.json', 'r', encoding='utf-8') as f:
                cctv_metadata = json.load(f)
                print("Berhasil membaca config.json.")
                # Lakukan penggabungan data
                for cctv_id, data in CCTV_CONFIG.items():
                    if cctv_id in cctv_metadata:
                        CCTV_CONFIG[cctv_id].update(cctv_metadata[cctv_id])
                print("Berhasil menggabungkan data.")
        except FileNotFoundError:
            print("Peringatan: config.json tidak ditemukan, melanjutkan tanpa metadata tambahan.")
        
        # Langkah 3: Mencoba menulis file cctv_config_latest.json
        print("\nMencoba menyimpan file cctv_config_latest.json...")
        try:
            with open('cctv_config_latest.json', 'w', encoding='utf-8') as f:
                json.dump(CCTV_CONFIG, f, indent=4, ensure_ascii=False)
            print("\nFile 'cctv_config_latest.json' berhasil diperbarui!")
        except Exception as e:
            print(f"\nTerjadi error saat mencoba menulis file: {e}")
            print("Pastikan Anda memiliki write permission di folder ini.")

    target_cctvs = display_menu_and_get_choices(CCTV_CONFIG)
    
    print(f"\nTarget CCTV yang dipilih: {', '.join(target_cctvs)}")

    parser = argparse.ArgumentParser(description="Menjalankan Worker Penghitung CCTV.")
    parser.add_argument(
        'targets', 
        nargs='*', # '*' berarti bisa menerima 0 atau lebih argumen
        default=None, # Defaultnya None jika tidak ada target yang diberikan
        help="ID CCTV yang ingin diproses. Jika kosong, proses semua."
    )
    args = parser.parse_args()
    
    threads = []
    for cctv_id in target_cctvs:
        if cctv_id in CCTV_CONFIG:
            cctv_data = CCTV_CONFIG[cctv_id]
            thread = threading.Thread(target=process_cctv_stream, args=(cctv_id, cctv_data), daemon=True)
            threads.append(thread)
            thread.start()
            time.sleep(2)
        else:
            print(f"Peringatan: CCTV target '{cctv_id}' tidak ditemukan.")

    print(f"\n{len(threads)} thread worker telah dimulai. Biarkan terminal ini tetap berjalan.")
    try:
        while True: time.sleep(10)
    except KeyboardInterrupt:
        print("\nCtrl+C terdeteksi. Menghentikan worker...")