import os
import sys
import torch
import torch.distributed as dist

def main():
    # Initialize distributed backend
    backend = "nccl" if torch.cuda.is_available() else "gloo"
    dist.init_process_group(backend=backend)
    
    rank = dist.get_rank()
    world_size = dist.get_world_size()
    
    # Simple tensor communication test
    tensor = torch.tensor([rank], dtype=torch.float32)
    if torch.cuda.is_available():
        tensor = tensor.cuda()
        
    dist.all_reduce(tensor, op=dist.ReduceOp.SUM)
    
    expected_sum = sum(range(world_size))
    if int(tensor.item()) == expected_sum:
        print(f"Rank {rank}/{world_size} successfully communicated. All-reduce sum is correct ({expected_sum}).")
    else:
        print(f"Rank {rank}/{world_size} communication failed! Expected {expected_sum}, got {tensor.item()}")
        sys.exit(1)
        
    dist.destroy_process_group()

if __name__ == "__main__":
    main()
