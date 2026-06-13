"""
Model Converter — Helper untuk konversi dan validasi model.
(Placeholder — akan dikembangkan di Phase 3)

Untuk sekarang, model didownload langsung dari MaixHub:
  https://maixhub.com/model/zoo/196  (YOLO11n COCO)

Usage (setelah diimplementasikan):
    python tools/model_converter.py --input yolo11n.pt --output yolo11n.mud
"""

import sys


def main():
    print("Model Converter — Placeholder (Phase 3)")
    print()
    print("Untuk Phase 0-2, download model langsung dari MaixHub:")
    print("  URL : https://maixhub.com/model/zoo/196")
    print("  Model: YOLO11n COCO (320x224)")
    print("  Format: .mud (MaixCAM native)")
    print()
    print("Setelah download:")
    print("  1. Rename ke yolo11n.mud")
    print("  2. Upload ke MaixCAM: /root/models/yolo11n.mud")
    print("     via MaixVision file manager atau:")
    print("     scp yolo11n.mud root@maixcam.local:/root/models/")


if __name__ == "__main__":
    main()
