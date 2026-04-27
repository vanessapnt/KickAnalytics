from onnxruntime.quantization import quantize_dynamic, QuantType
import os

src = os.path.join(os.path.dirname(__file__), "model.onnx")
dst = os.path.join(os.path.dirname(__file__), "model_int8.onnx")

print(f"Quantification de {src} ...")
quantize_dynamic(src, dst, weight_type=QuantType.QUInt8)

src_mb = os.path.getsize(src) / 1e6
dst_mb = os.path.getsize(dst) / 1e6
print(f"OK → {dst}")
print(f"Taille : {src_mb:.1f} MB → {dst_mb:.1f} MB ({dst_mb/src_mb*100:.0f}%)")
