import onnxruntime as ort
import numpy as np
import os
from pathlib import Path

model_path = str(Path(__file__).parent.parent / 'backend' / 'ml' / 'forgery_model.onnx')

def test_model():
    if not os.path.exists(model_path):
        print(f"ERROR: Model file NOT FOUND at {model_path}")
        return

    try:
        session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        input_name = session.get_inputs()[0].name
        input_shape = session.get_inputs()[0].shape
        output_name = session.get_outputs()[0].name
        
        print(f"SUCCESS: Model loaded.")
        print(f"Input Name: {input_name}")
        print(f"Input Shape: {input_shape}")
        print(f"Output Name: {output_name}")
        
        dummy_input = np.random.randn(1, 3, 224, 224).astype(np.float32)
        result = session.run([output_name], {input_name: dummy_input})
        print(f"Test Run Result: {result[0]}")
        
    except Exception as e:
        print(f"ERROR during model test: {e}")

if __name__ == "__main__":
    test_model()
