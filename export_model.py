# export_model.py
from ultralytics import YOLO

# Muat model .pt Anda
model = YOLO('best.pt')

# Ekspor ke format ONNX
# opset=12 adalah versi yang umumnya stabil
model.export(format='onnx', opset=12) 

print("Model berhasil diekspor ke 'best.onnx'")