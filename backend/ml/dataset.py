import os
from PIL import Image
from torch.utils.data import Dataset
import torchvision.transforms as transforms

class ImageForgeryDataset(Dataset):
    def __init__(self, root_dir: str, is_train: bool = True):
        self.root_dir = root_dir
        self.is_train = is_train
        self.samples = []
        authentic_dir = os.path.join(root_dir, "authentic")
        forged_dir = os.path.join(root_dir, "forged")
        if os.path.exists(authentic_dir):
            for f in os.listdir(authentic_dir):
                self.samples.append((os.path.join(authentic_dir, f), 0))
        if os.path.exists(forged_dir):
            for f in os.listdir(forged_dir):
                self.samples.append((os.path.join(forged_dir, f), 1))

        self.transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], 
                                 std=[0.229, 0.224, 0.225])
        ])

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        img_path, label = self.samples[idx]
        image = Image.open(img_path).convert("RGB")
        tensor = self.transform(image)
        return tensor, label
