#!/usr/bin/env bash
# ONNX (from export_y26.py) -> cv181x cvimodel for MaixCAM, INT8 with the
# detection head in BF16. Run inside WSL/Linux with TPU-MLIR 1.12 active.
#
#   bash convert.sh <model.onnx> <calib_dir> <test_image> <out_dir>
#
# Why BF16 for the head: in pure INT8 the class logits before the sigmoid came
# out in ~0.7 steps, so every score on the device was 0.5 / 0.67 / 0.8 and the
# winning denomination was decided by rounding (33/40 on the test split vs 36/40
# in float). With the last convs + sigmoid in BF16: 34/40, same 10 ms.
set -euo pipefail
ONNX=$(realpath "$1"); CALIB=$(realpath "$2"); IMG=$(realpath "$3"); OUT=$4
NAME=uang_yolo26n
S=0.00392156862745098
mkdir -p "$OUT" && cd "$OUT"

model_transform --model_name $NAME --model_def "$ONNX" \
  --input_shapes [[1,3,224,320]] --mean 0,0,0 --scale $S,$S,$S \
  --keep_aspect_ratio --pixel_format rgb --channel_format nchw \
  --output_names boxes,scores \
  --test_input "$IMG" --test_result ${NAME}_top_outputs.npz \
  --tolerance 0.99,0.99 --mlir $NAME.mlir

run_calibration $NAME.mlir --dataset "$CALIB" --input_num 126 -o ${NAME}_cali_table

cat > qtable_head_bf16 <<'EOF'
/model.23/cv2.0/cv2.0.2/Conv_output_0_Conv BF16
/model.23/cv2.1/cv2.1.2/Conv_output_0_Conv BF16
/model.23/cv2.2/cv2.2.2/Conv_output_0_Conv BF16
/model.23/Reshape_output_0_Reshape BF16
/model.23/Reshape_1_output_0_Reshape BF16
/model.23/Reshape_2_output_0_Reshape BF16
/model.23/Concat_output_0_Concat BF16
boxes_Reshape BF16
/model.23/cv3.0/cv3.0.2/Conv_output_0_Conv BF16
/model.23/cv3.1/cv3.1.2/Conv_output_0_Conv BF16
/model.23/cv3.2/cv3.2.2/Conv_output_0_Conv BF16
/model.23/Reshape_3_output_0_Reshape BF16
/model.23/Reshape_4_output_0_Reshape BF16
/model.23/Reshape_5_output_0_Reshape BF16
/model.23/Concat_1_output_0_Concat BF16
scores_Sigmoid BF16
EOF

model_deploy --mlir $NAME.mlir --quantize INT8 --quant_input \
  --calibration_table ${NAME}_cali_table --quantize_table qtable_head_bf16 \
  --processor cv181x --test_input ${NAME}_in_f32.npz \
  --test_reference ${NAME}_top_outputs.npz --tolerance 0.9,0.6 \
  --model ${NAME}_320x224_mix.cvimodel
