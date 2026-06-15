import os
import sys
import json
import argparse
import subprocess
import traceback
import requests
import torch


def get_gpu_metrics():
    try:
        out = subprocess.check_output(
            "nvidia-smi --query-gpu=utilization.gpu,utilization.memory,temperature.gpu --format=csv,noheader,nounits",
            shell=True
        ).decode().strip()
        parts = [float(p.strip()) for p in out.split(',')]
        return parts[0], parts[1], parts[2]
    except Exception:
        return 0.0, 0.0, 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--world_size", type=int, default=1)
    parser.add_argument("--rank", type=int, default=0)
    parser.add_argument("--master_addr", type=str, default="127.0.0.1")
    parser.add_argument("--master_port", type=str, default="29500")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--batch_size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=0.01)
    parser.add_argument("--model", type=str, default="yolov8n.pt")
    parser.add_argument("--dataset", type=str, default="coco128.yaml")
    parser.add_argument("--job_id", type=str, default="1")
    parser.add_argument("--backend", type=str, default="nccl")
    parser.add_argument("--orchestrator_url", type=str, default="")
    args = parser.parse_args()

    # ── Environment ──────────────────────────────────────────────────────────
    # When launched via `torchrun`, these env vars are already set correctly.
    # We read them but do NOT override — Ultralytics' internal DDP bootstrap
    # needs to own them.
    master_addr = os.environ.get("MASTER_ADDR", args.master_addr)
    master_port = os.environ.get("MASTER_PORT", args.master_port)
    world_size  = int(os.environ.get("WORLD_SIZE", str(args.world_size)))
    rank        = int(os.environ.get("RANK", str(args.rank)))
    local_rank  = int(os.environ.get("LOCAL_RANK", "0"))

    # Only set these if not already present (don't stomp on torchrun's values)
    os.environ.setdefault("MASTER_ADDR", master_addr)
    os.environ.setdefault("MASTER_PORT", master_port)
    os.environ.setdefault("NCCL_SOCKET_IFNAME", "en,eth,em,bond,wlan,wlx")

    # ── Dataset path validation ───────────────────────────────────────────────
    if not os.path.exists(args.dataset):
        print(
            f"[Rank {rank}] WARNING: Dataset file not found at '{args.dataset}'! "
            f"Make sure this path is accessible on every worker node.",
            flush=True
        )

    # ── Device ───────────────────────────────────────────────────────────────
    use_cuda = torch.cuda.is_available()
    if use_cuda:
        device_id = local_rank % torch.cuda.device_count()
        device_str = str(device_id)          # Ultralytics wants "0", "1", …
    else:
        device_str = "cpu"

    print(f"[Rank {rank}] Starting Ultralytics YOLOv8 training on device={device_str}", flush=True)

    # ── Init process group ───────────────────────────────────────────────────
    # Ultralytics checks RANK != -1 (not dist.is_initialized()) to decide
    # whether to use DistributedSampler. torchrun always sets RANK, even for
    # world_size=1. So we MUST init the process group whenever torchrun launched
    # this script, regardless of world_size.
    import torch.distributed as dist
    import datetime
    if not dist.is_initialized():
        # Use gloo for single-process (world_size=1) — no network interface needed.
        # Use nccl for multi-process GPU training (world_size>1).
        backend = "nccl" if (use_cuda and world_size > 1) else "gloo"
        dist.init_process_group(
            backend=backend,
            init_method="env://",
            world_size=world_size,
            rank=rank,
            timeout=datetime.timedelta(seconds=120)
        )
    print(f"[Rank {rank}] Process group initialized (backend={os.environ.get('TORCH_DISTRIBUTED_BACKEND', backend)}, world_size={world_size})", flush=True)


    # ── AutoBatch ─────────────────────────────────────────────────────────────
    batch = args.batch_size
    if batch == -1 and world_size > 1:
        print(f"[Rank {rank}] WARNING: AutoBatch (batch=-1) is NOT supported in multi-node DDP training. Defaulting to batch=16.", flush=True)
        batch = 16

    # ── Checkpoint resume dir ─────────────────────────────────────────────────
    checkpoint_dir = os.path.join("worker", f"job_{args.job_id}")
    os.makedirs(checkpoint_dir, exist_ok=True)

    # ── Build YOLO model ──────────────────────────────────────────────────────
    from ultralytics import YOLO

    model = YOLO(args.model)

    # ── Callbacks ─────────────────────────────────────────────────────────────
    orchestrator_url = args.orchestrator_url
    job_id           = args.job_id

    def on_train_epoch_end(trainer):
        """Fires after every training epoch on every rank.
        We only POST to the orchestrator from Rank 0 to avoid duplicates."""

        current_rank = int(os.environ.get("RANK", "0"))
        if current_rank != 0:
            return

        epoch      = trainer.epoch + 1          # 1-indexed
        loss_items = trainer.loss_items          # tensor([box, cls, dfl])
        metrics    = trainer.metrics             # dict with mAP keys

        box_loss = float(loss_items[0]) if loss_items is not None else 0.0
        cls_loss = float(loss_items[1]) if loss_items is not None else 0.0
        dfl_loss = float(loss_items[2]) if loss_items is not None else 0.0
        map50    = float(metrics.get("metrics/mAP50(B)", 0.0))
        map50_95 = float(metrics.get("metrics/mAP50-95(B)", 0.0))

        gpu_util, vram_util, temp = get_gpu_metrics()

        payload = {
            "epoch":    epoch,
            "box_loss": round(box_loss, 4),
            "cls_loss": round(cls_loss, 4),
            "dfl_loss": round(dfl_loss, 4),
            "map50":    round(map50, 4),
            "map50_95": round(map50_95, 4),
            "gpu":      gpu_util,
            "vram":     vram_util,
            "temp":     temp,
        }

        # Print in the format the orchestrator already parses from stdout
        print(f"METRICS: {json.dumps(payload)}", flush=True)

        if orchestrator_url:
            try:
                requests.post(
                    f"{orchestrator_url}/train/metrics",
                    json={"job_id": job_id, **payload},
                    timeout=5
                )
            except Exception as exc:
                print(f"[Rank 0] Failed to send metrics: {exc}", flush=True)

    def on_train_end(trainer):
        """Upload final checkpoint to master orchestrator after all epochs finish."""
        current_rank = int(os.environ.get("RANK", "0"))
        if current_rank != 0 or not orchestrator_url:
            return

        best_ckpt = str(trainer.best)
        if not os.path.exists(best_ckpt):
            best_ckpt = str(trainer.last)

        # Upload checkpoint
        try:
            upload_chk_url = f"{orchestrator_url}/train/jobs/{job_id}/checkpoint"
            print(f"[Rank 0] Uploading checkpoint to master: {upload_chk_url}", flush=True)
            with open(best_ckpt, "rb") as f:
                resp = requests.post(upload_chk_url, files={"file": f}, timeout=60)
            print(
                f"[Rank 0] Checkpoint upload {'succeeded' if resp.status_code == 200 else 'FAILED: ' + resp.text}",
                flush=True
            )
        except Exception as exc:
            print(f"[Rank 0] Checkpoint upload error: {exc}", flush=True)

        # Upload final model
        try:
            upload_url = f"{orchestrator_url}/train/upload_model"
            print(f"[Rank 0] Uploading final model to master: {upload_url}", flush=True)
            with open(best_ckpt, "rb") as f:
                resp = requests.post(
                    upload_url,
                    data={"job_id": job_id},
                    files={"file": f},
                    timeout=60
                )
            print(
                f"[Rank 0] Model upload {'succeeded' if resp.status_code == 200 else 'FAILED: ' + resp.text}",
                flush=True
            )
        except Exception as exc:
            print(f"[Rank 0] Model upload error: {exc}", flush=True)

    model.add_callback("on_train_epoch_end", on_train_epoch_end)
    model.add_callback("on_train_end",       on_train_end)

    # ── Train ─────────────────────────────────────────────────────────────────
    # Ultralytics handles full DDP setup internally when launched via torchrun.
    # For single-GPU runs, launch with plain python (world_size=1, no torchrun).
    # For multi-GPU/multi-node, launch via:
    #   torchrun --nnodes=N --nproc_per_node=1 --rdzv_id=... trainer.py ...
    model.train(
        data=args.dataset,
        epochs=args.epochs,
        batch=batch,               # -1 = Ultralytics auto-batch
        lr0=args.lr,
        device=device_str,
        project=checkpoint_dir,
        name="run",
        exist_ok=True,
        verbose=(rank == 0),       # only rank-0 prints progress bars
        nbs=64,                    # nominal batch size for LR scaling
    )

    print(f"[Rank {rank}] Training finished.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n==========================================", file=sys.stderr)
        print(f"CRITICAL ERROR IN TRAINER.PY (Rank {os.environ.get('RANK', 'Unknown')}):", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        print(f"==========================================", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
