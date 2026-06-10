import torch
import torch.distributed as dist
import torch.nn as nn
import torch.optim as optim
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, Dataset
import argparse
import time
import json
import os
import random

# Simple dataset for distributed training test
class MockYOLODataset(Dataset):
    def __init__(self, size=200):
        self.size = size
    def __len__(self):
        return self.size
    def __getitem__(self, idx):
        # Return mock features (image batch) and dummy labels
        # e.g., features size 3x64x64, target bounding boxes
        x = torch.randn(3, 64, 64)
        y = torch.randint(0, 10, (5,)) # 5 dummy class predictions
        return x, y

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
    parser.add_argument("--job_id", type=int, default=1)
    parser.add_argument("--backend", type=str, default="nccl")
    parser.add_argument("--orchestrator_url", type=str, default="")
    args = parser.parse_args()

    # Determine backend (use the one commanded by master, or fallback to auto-detection)
    backend = args.backend

    # Setup environment variables for PyTorch Distributed
    if "MASTER_ADDR" not in os.environ:
        os.environ["MASTER_ADDR"] = args.master_addr
    if "MASTER_PORT" not in os.environ:
        os.environ["MASTER_PORT"] = args.master_port
    if "WORLD_SIZE" not in os.environ:
        os.environ["WORLD_SIZE"] = str(args.world_size)
    if "RANK" not in os.environ:
        os.environ["RANK"] = str(args.rank)

    env_rank = int(os.environ["RANK"])
    env_world_size = int(os.environ["WORLD_SIZE"])
    env_local_rank = int(os.environ.get("LOCAL_RANK", 0))

    use_cuda = torch.cuda.is_available()

    print(f"[Rank {env_rank}] Initializing process group using {backend} backend...")
    dist.init_process_group(backend=backend)
    print(f"[Rank {env_rank}] Process group initialized.")

    # Local rank device setup
    if use_cuda:
        device_id = env_local_rank % torch.cuda.device_count()
        torch.cuda.set_device(device_id)
        device = torch.device(f"cuda:{device_id}")
        print(f"[Rank {env_rank}] Running on GPU {device_id} (Local Rank: {env_local_rank})")
    else:
        device = torch.device("cpu")
        print(f"[Rank {env_rank}] Running on CPU")

    # Construct model (using a simple YOLO-mimicking CNN)
    class DummyYOLOModel(nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = nn.Sequential(
                nn.Conv2d(3, 16, kernel_size=3, padding=1),
                nn.ReLU(),
                nn.AdaptiveAvgPool2d((4, 4)),
                nn.Flatten()
            )
            # Box regressor head & classification head
            self.box_head = nn.Linear(16 * 4 * 4, 4)
            self.cls_head = nn.Linear(16 * 4 * 4, 10)

        def forward(self, x):
            feats = self.backbone(x)
            box = self.box_head(feats)
            cls_out = self.cls_head(feats)
            return box, cls_out

    model = DummyYOLOModel().to(device)
    if use_cuda:
        model = DDP(model, device_ids=[device_id])
    else:
        model = DDP(model)

    # Dataset & DDP Sampler
    dataset = MockYOLODataset()
    sampler = torch.utils.data.distributed.DistributedSampler(
        dataset, 
        num_replicas=env_world_size, 
        rank=env_rank,
        shuffle=True
    )
    dataloader = DataLoader(dataset, batch_size=args.batch_size, sampler=sampler)

    optimizer = optim.SGD(model.parameters(), lr=args.lr)
    
    # Check if checkpoint exists to resume
    checkpoint_path = f"worker/checkpoint_job_{args.job_id}.pt"
    start_epoch = 0
    if os.path.exists(checkpoint_path):
        print(f"[Rank {env_rank}] Resuming from checkpoint: {checkpoint_path}")
        try:
            checkpoint = torch.load(checkpoint_path, map_location=device)
            model.module.load_state_dict(checkpoint["model_state_dict"])
            optimizer.load_state_dict(checkpoint["optimizer_state_dict"])
            start_epoch = checkpoint["epoch"] + 1
            print(f"[Rank {env_rank}] Checkpoint loaded. Starting at epoch {start_epoch}")
        except Exception as e:
            print(f"[Rank {env_rank}] Failed to load checkpoint, starting from scratch: {e}")

    # Training Loop
    for epoch in range(start_epoch, args.epochs):
        sampler.set_epoch(epoch)
        model.train()
        epoch_loss = 0.0
        
        # Simulate processing batches
        for i, (imgs, targets) in enumerate(dataloader):
            imgs = imgs.to(device)
            optimizer.zero_grad()
            
            box_out, cls_out = model(imgs)
            
            # Simulated loss calculations representing YOLO losses
            loss_box = nn.MSELoss()(box_out, torch.zeros_like(box_out))
            loss_cls = nn.CrossEntropyLoss()(cls_out, torch.randint(0, 10, (imgs.size(0),)).to(device))
            loss = loss_box + loss_cls
            
            loss.backward()
            optimizer.step()
            
            epoch_loss += loss.item()
            time.sleep(0.05) # Simulate workload delay

        # Sync loss across ranks
        epoch_loss_tensor = torch.tensor(epoch_loss).to(device)
        dist.all_reduce(epoch_loss_tensor, op=dist.ReduceOp.SUM)
        avg_loss = epoch_loss_tensor.item() / (env_world_size * len(dataloader))

        # Evaluate mock metrics
        box_loss_val = avg_loss * 0.4 + random.uniform(-0.02, 0.02)
        cls_loss_val = avg_loss * 0.45 + random.uniform(-0.02, 0.02)
        dfl_loss_val = avg_loss * 0.15 + random.uniform(-0.01, 0.01)
        
        # Calculate simulated map score that improves with epochs
        progress = (epoch + 1) / args.epochs
        map50 = 0.3 + 0.62 * progress + random.uniform(-0.02, 0.02)
        map50_95 = 0.15 + 0.48 * progress + random.uniform(-0.01, 0.01)
        
        # Clamp bounds
        map50 = min(max(map50, 0.0), 1.0)
        map50_95 = min(max(map50_95, 0.0), 1.0)

        # Print structured metrics on Rank 0
        if env_rank == 0:
            metrics = {
                "epoch": epoch + 1,
                "box_loss": round(box_loss_val, 4),
                "cls_loss": round(cls_loss_val, 4),
                "dfl_loss": round(dfl_loss_val, 4),
                "map50": round(map50, 4),
                "map50_95": round(map50_95, 4)
            }
            print(f"METRICS: {json.dumps(metrics)}")
            
            # Save checkpoint state
            os.makedirs("worker", exist_ok=True)
            torch.save({
                "epoch": epoch,
                "model_state_dict": model.module.state_dict(),
                "optimizer_state_dict": optimizer.state_dict(),
                "loss": avg_loss
            }, checkpoint_path)
            print(f"[Rank 0] Saved training checkpoint to {checkpoint_path}")

            if args.orchestrator_url:
                try:
                    import requests
                    url = f"{args.orchestrator_url}/train/jobs/{args.job_id}/checkpoint"
                    print(f"[Rank 0] Uploading checkpoint to orchestrator: {url}")
                    with open(checkpoint_path, "rb") as f:
                        response = requests.post(url, files={"file": f}, timeout=30)
                    if response.status_code == 200:
                        print(f"[Rank 0] Checkpoint successfully uploaded to orchestrator.")
                    else:
                        print(f"[Rank 0] Checkpoint upload failed: {response.text}")
                except Exception as e:
                    print(f"[Rank 0] Checkpoint upload failed with error: {e}")

        dist.barrier() # Wait for checkpoints

    dist.destroy_process_group()
    print(f"[Rank {env_rank}] Training finished. Cleaned up process group.")

if __name__ == "__main__":
    main()
