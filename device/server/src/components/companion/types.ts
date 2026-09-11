/** Shape of /status returned by device server (post-C2). */
export interface DeviceStatus {
  mode: "explorer" | "context" | "qris";
  ai_focus: boolean;
  detections: unknown[];
  latency: {
    camera_ms?: number;
    inference_ms?: number;
    postproc_ms?: number;
    total_ms?: number;
    fps?: number;
  };
  audio_text: string;
  audio_mode: "chime" | "speech" | "both";
  last_caption: { text: string; time_iso: string; priority: string };
  battery: number | null;
  wifi_signal: number;
  wifi_ssid: string;
  temperature: number | null;
  setup_completed: boolean;
  cam_w: number;
  cam_h: number;
  /** Mode Ambil Data — when true every assistive feature is disabled. */
  data_collection_mode?: boolean;
  capturing?: boolean;
  capture_count?: number;
}

export interface HistoryItem {
  t: string;
  t_iso: string;
  mode: string;
  text: string;
  priority: "high" | "normal" | "low";
  module: string;
}
