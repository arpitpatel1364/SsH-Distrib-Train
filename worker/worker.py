import torch
import json
import sys

def scan_worker():
    diagnostics = {
        "python_version": sys.version,
        "cuda_available": torch.cuda.is_available(),
        "gpu_count": 0,
        "gpus": [],
        "torch_version": torch.__version__
    }
    
    if diagnostics["cuda_available"]:
        diagnostics["gpu_count"] = torch.cuda.device_count()
        for i in range(diagnostics["gpu_count"]):
            diagnostics["gpus"].append({
                "id": i,
                "name": torch.cuda.get_device_name(i),
                "capability": torch.cuda.get_device_capability(i),
                "total_memory_mb": round(torch.cuda.get_device_properties(i).total_memory / (1024**2))
            })
            
    print(json.dumps(diagnostics, indent=2))

if __name__ == "__main__":
    scan_worker()
