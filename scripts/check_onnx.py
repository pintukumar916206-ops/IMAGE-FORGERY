import onnxruntime as ort
from pathlib import Path

try:
    model_path = Path(__file__).parent.parent / 'backend' / 'ml' / 'forgery_model.onnx'
    sess = ort.InferenceSession(str(model_path))
    print('Inputs:', [i.name for i in sess.get_inputs()])
    print('Shapes:', [i.shape for i in sess.get_inputs()])
    print('Outputs:', [o.name for o in sess.get_outputs()])
except Exception as e:
    print(f'Error: {e}')
