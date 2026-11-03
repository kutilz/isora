"""On-device check of the money model through MaixPy's own YOLOv8 decoder.

Set A: dataset-1 test images with YOLO labels. Set B: images whose filename
starts with "<idx>_<value>k_". Prints top-1 accuracy per conf threshold and
the detect() time at 320x224.
"""
import os, re, sys, time
from maix import nn, image

MUD = sys.argv[1]
D1_VALUES = [100000, 1000, 2000, 5000, 10000, 20000, 50000]


def value(label):
    m = re.search(r"(\d+)\s*k", label, re.I)
    return int(m.group(1)) * 1000 if m else None


det = nn.YOLOv8(model=MUD)
vals = [value(l) for l in det.labels]
print("labels", det.labels, "->", vals, "input", det.input_width(), det.input_height())


def items_a(d):
    out = []
    for f in sorted(os.listdir(d)):
        if f.endswith(".jpg"):
            lab = os.path.join(d, f[:-4] + ".txt")
            if os.path.exists(lab):
                rows = [l.split() for l in open(lab) if l.strip()]
                if rows:
                    out.append((os.path.join(d, f), {D1_VALUES[int(r[0])] for r in rows}))
    return out


def items_b(d):
    return [(os.path.join(d, f), {value(f.split("_", 1)[1])}) for f in sorted(os.listdir(d)) if f.endswith(".jpg")]


times = []
for name, items in (("A", items_a(sys.argv[2])), ("B", items_b(sys.argv[3]))):
    right = {0.4: 0, 0.5: 0, 0.6: 0}
    for p, truth in items:
        img = image.load(p, image.Format.FMT_RGB888)
        t = time.time()
        objs = det.detect(img, conf_th=0.4, iou_th=0.45)
        times.append((time.time() - t) * 1000)
        objs = sorted(objs, key=lambda o: -o.score)
        for th in right:
            o = [x for x in objs if x.score >= th]
            if o and vals[o[0].class_id] in truth:
                right[th] += 1
        if not objs or vals[objs[0].class_id] not in truth:
            print("  miss", os.path.basename(p)[:36], "truth", sorted(truth),
                  "got", [(vals[o.class_id], round(o.score, 2)) for o in objs[:3]])
    print(f"set {name} ({len(items)}): " + "  ".join(f"conf>={t}: {r}/{len(items)}" for t, r in right.items()))
times.sort()
print(f"detect() incl. letterbox from full-size jpg: median {times[len(times)//2]:.1f} ms")
img = image.Image(320, 224, image.Format.FMT_RGB888)
ts = []
for _ in range(20):
    t = time.time(); det.detect(img, conf_th=0.4, iou_th=0.45); ts.append((time.time() - t) * 1000)
ts.sort()
print(f"detect() on a 320x224 camera-sized frame: median {ts[10]:.1f} ms")
