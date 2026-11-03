"""Export YOLO26n to an ONNX that MaixPy's nn.YOLOv8 decoder can read.

YOLO26 has reg_max=1 (no DFL), so the raw box head is already what YOLOv8's
DFL conv emits: ltrb distances in grid units, one per anchor. The graph is
stopped there — boxes reshaped to [1,1,4,N] like YOLOv8's dfl/conv output, and
scores after the sigmoid [1,nc,N] — leaving anchors, stride scaling and NMS to
MaixPy. `head` picks the one-to-many (cv2/cv3) or one-to-one head.
"""
import sys
import torch
from ultralytics import YOLO

weights, out, head = sys.argv[1], sys.argv[2], sys.argv[3]
H, W = 224, 320
model = YOLO(weights).model.float().eval()
det = model.model[-1]
print("reg_max", det.reg_max, "nc", det.nc, "stride", det.stride.tolist(), "end2end", det.end2end)
box_head, cls_head = ((det.one2one_cv2, det.one2one_cv3) if head == "one2one"
                      else (det.cv2, det.cv3))


def raw_forward(xs):
    bs = xs[0].shape[0]
    boxes = torch.cat([box_head[i](xs[i]).view(bs, 4 * det.reg_max, -1) for i in range(det.nl)], -1)
    scores = torch.cat([cls_head[i](xs[i]).view(bs, det.nc, -1) for i in range(det.nl)], -1)
    return boxes.view(bs, 1, 4, -1), scores.sigmoid()


det.forward = raw_forward
im = torch.zeros(1, 3, H, W)
with torch.no_grad():
    b, s = model(im)
print("boxes", tuple(b.shape), "scores", tuple(s.shape))
torch.onnx.export(model, im, out, opset_version=17, do_constant_folding=True,
                  input_names=["images"], output_names=["boxes", "scores"])
import onnx  # noqa: E402
mo = onnx.load(out)
p = mo.metadata_props.add()
p.key, p.value = "names", ",".join(model.names[i] for i in sorted(model.names))
onnx.save(mo, out)
print("wrote", out)
