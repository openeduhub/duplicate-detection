"""Analyze which tensors are taking up space in the ONNX model."""

import sys
from pathlib import Path
import onnx
import numpy as np
from collections import defaultdict

MODEL_PATH = Path(__file__).parent.parent / "models" / "embedding-model" / "model.onnx"

def analyze():
    print(f"Loading {MODEL_PATH}...")
    m = onnx.load(str(MODEL_PATH))
    
    type_names = {1: "FP32", 10: "FP16", 3: "INT8", 2: "UINT8", 6: "INT32", 7: "INT64"}
    bytes_per_type = {1: 4, 10: 2, 3: 1, 2: 1, 6: 4, 7: 8}
    
    # Group by type and calculate size
    by_type = defaultdict(list)
    
    for init in m.graph.initializer:
        size_bytes = np.prod(init.dims) * bytes_per_type.get(init.data_type, 4)
        by_type[init.data_type].append((init.name, size_bytes, init.dims))
    
    print("\n" + "="*80)
    print("WEIGHT ANALYSIS")
    print("="*80)
    
    total = 0
    for dtype, tensors in sorted(by_type.items(), key=lambda x: -sum(t[1] for t in x[1])):
        type_name = type_names.get(dtype, f"TYPE_{dtype}")
        type_total = sum(t[1] for t in tensors)
        total += type_total
        
        print(f"\n{type_name}: {len(tensors)} tensors, {type_total / (1024*1024):.2f} MB total")
        
        # Show top 10 largest
        sorted_tensors = sorted(tensors, key=lambda x: -x[1])[:10]
        for name, size, dims in sorted_tensors:
            print(f"  {size/1024/1024:8.2f} MB  {dims}  {name[:60]}")
    
    print(f"\n{'='*80}")
    print(f"TOTAL: {total / (1024*1024):.2f} MB")
    
    # Find embedding layer
    print("\n" + "="*80)
    print("EMBEDDING LAYER ANALYSIS")
    print("="*80)
    
    for init in m.graph.initializer:
        if "embed" in init.name.lower():
            size = np.prod(init.dims) * bytes_per_type.get(init.data_type, 4)
            print(f"  {init.name}")
            print(f"    Shape: {init.dims}")
            print(f"    Type: {type_names.get(init.data_type, init.data_type)}")
            print(f"    Size: {size / (1024*1024):.2f} MB")


if __name__ == "__main__":
    analyze()
