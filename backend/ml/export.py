import torch
import logging
from .train import create_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ml_export")

def export_to_onnx(model_path: str = "forgery_model.pth", export_path: str = "forgery_model.onnx"):
    """
    Export the trained PyTorch model to ONNX format.
    This allows the FastAPI backend to run inference without the massive PyTorch dependency overhead.
    """
    logger.info(f"Loading weights from {model_path}...")
    model = create_model()
    
    try:
        model.load_state_dict(torch.load(model_path, map_location=torch.device('cpu')))
    except FileNotFoundError:
        logger.error(f"Weights file not found at {model_path}. You must run train.py first.")
        return
        
    model.eval()

    # Dummy input representing a normalized 224x224 RGB image
    dummy_input = torch.randn(1, 3, 224, 224)
    
    logger.info(f"Exporting to {export_path}...")
    torch.onnx.export(
        model, 
        dummy_input, 
        export_path, 
        export_params=True, 
        opset_version=14, 
        do_constant_folding=True,
        input_names=['input'], 
        output_names=['output'],
        dynamic_axes={'input': {0: 'batch_size'}, 'output': {0: 'batch_size'}}
    )
    logger.info("Export complete. The backend can now load this ONNX file for lightweight inference.")

if __name__ == "__main__":
    export_to_onnx()
