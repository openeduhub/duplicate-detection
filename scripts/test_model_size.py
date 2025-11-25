"""Test different model sizes."""

import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

# Test model with fewer languages (de, en, es, fr, it, nl, pl, pt)
MODEL_NAME = "h4g3n/multilingual-MiniLM-L12-de-en-es-fr-it-nl-pl-pt"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "embedding-model-test"


def test_model():
    """Test the model size after conversion and quantization."""
    
    logger.info(f"Testing model: {MODEL_NAME}")
    
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    try:
        import onnx
        import numpy as np
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer
        from onnxruntime.quantization import quantize_dynamic, QuantType
        
        logger.info("Loading tokenizer...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        vocab_size = tokenizer.vocab_size
        logger.info(f"Vocabulary size: {vocab_size:,}")
        
        tokenizer.save_pretrained(OUTPUT_DIR)
        
        logger.info("Exporting to ONNX...")
        model = ORTModelForFeatureExtraction.from_pretrained(MODEL_NAME, export=True)
        
        temp_dir = OUTPUT_DIR / "temp"
        temp_dir.mkdir(exist_ok=True)
        model.save_pretrained(temp_dir)
        shutil.copy(temp_dir / "config.json", OUTPUT_DIR / "config.json")
        
        fp32_path = temp_dir / "model.onnx"
        fp32_size = fp32_path.stat().st_size / (1024 * 1024)
        logger.info(f"FP32 ONNX: {fp32_size:.1f} MB")
        
        # Analyze embedding size
        m = onnx.load(str(fp32_path))
        for init in m.graph.initializer:
            if "word_embed" in init.name.lower():
                size = np.prod(init.dims) * 4 / (1024*1024)
                logger.info(f"Word embeddings: {init.dims} = {size:.1f} MB (FP32)")
        
        # Quantize to INT8
        logger.info("Quantizing to INT8...")
        int8_path = OUTPUT_DIR / "model.onnx"
        
        quantize_dynamic(
            model_input=str(fp32_path),
            model_output=str(int8_path),
            weight_type=QuantType.QInt8
        )
        
        int8_size = int8_path.stat().st_size / (1024 * 1024)
        logger.info(f"INT8 ONNX: {int8_size:.1f} MB")
        
        # Cleanup
        shutil.rmtree(temp_dir)
        
        # Total size
        total = sum(f.stat().st_size for f in OUTPUT_DIR.rglob("*") if f.is_file())
        
        logger.info("="*50)
        logger.info(f"RESULTS for {MODEL_NAME}:")
        logger.info(f"  Vocabulary: {vocab_size:,} tokens")
        logger.info(f"  FP32: {fp32_size:.1f} MB")
        logger.info(f"  INT8: {int8_size:.1f} MB")
        logger.info(f"  Total folder: {total/(1024*1024):.1f} MB")
        logger.info("="*50)
        
        if int8_size < 100:
            logger.success(f"✅ Model is {int8_size:.1f} MB - GitHub compatible!")
            return True
        else:
            logger.warning(f"⚠️ Model is {int8_size:.1f} MB - still over 100 MB")
            return False
        
    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="{time:HH:mm:ss} | {level:<8} | {message}")
    test_model()
