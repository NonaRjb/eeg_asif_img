"""
Load data proposed by:
    C. Spampinato, S. Palazzo, I. Kavasidis, D. Giordano, N. Souly, M. Shah, 
    Deep Learning Human Mind for Automated Visual Classification, International
    Conference on Computer Vision and Pattern Recognition, CVPR 2017
"""
import sys

sys.path.append("/proj/rep-learning-robotics/users/x_nonra/eeg_asif_img")
# sys.path.append("/mimer/NOBACKUP/groups/eeg_foundation_models/eeg_asif_img/")

import os
import numpy as np
import random
import torch
from torch.utils.data import DataLoader, Dataset
import torchvision.transforms as T
from scipy.interpolate import interp1d
from PIL import Image
import requests
import pickle
import argparse
import yaml
import zipfile

try:
    from torchvision.transforms import InterpolationMode

    BICUBIC = InterpolationMode.BICUBIC
except ImportError:
    BICUBIC = Image.BICUBIC


def expand2square(pil_img, background_color):
    width, height = pil_img.size
    if width == height:
        return pil_img
    elif width > height:
        result = Image.new(pil_img.mode, (width, width), background_color)
        result.paste(pil_img, (0, (width - height) // 2))
        return result
    else:
        result = Image.new(pil_img.mode, (height, height), background_color)
        result.paste(pil_img, ((height - width) // 2, 0))
        return result


def _convert_image_to_rgb(image):
    return image.convert("RGB")


def _transform(n_px):
    return T.Compose([
        T.Resize(n_px, interpolation=BICUBIC),
        T.CenterCrop(n_px),
        _convert_image_to_rgb,
        T.ToTensor(),
        T.Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711)),
    ])


def download_file(url, destination):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        with open(destination, 'wb') as f:
            for chunk in response.iter_content(chunk_size=1024):
                f.write(chunk)
    else:
        raise Exception(f"Failed to download file from {url}")


# Function to unzip any zip file in a directory
def unzip_nested_files(root_dir):
    # Iterate over all files and directories within the root directory
    for dirpath, dirnames, filenames in os.walk(root_dir):
        # Iterate over each file in the directory
        for filename in filenames:
            # Check if the file is a zip file
            if filename.endswith('.zip'):
                zip_file_path = os.path.join(dirpath, filename)
                # Unzip the file into the same directory
                print(f"Unzipping {zip_file_path}...")
                with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
                    # Extract all the contents to the directory where the zip file is located
                    zip_ref.extractall(dirpath)
                print(f"Unzipped {filename} in {dirpath}")
                os.remove(zip_file_path)


        # After unzipping, continue checking subdirectories
        for sub_dir in dirnames:
            # Join to get the full path of the subdirectory
            sub_dir_path = os.path.join(dirpath, sub_dir)
            # Recursively call the function on the subdirectory
            unzip_nested_files(sub_dir_path)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', type=str)
    parser.add_argument('-s', '--server', type=int, default=1)
    return parser.parse_args()


class EEGImagenet(Dataset):
    def __init__(
            self,
            data_path,
            n_classes,
            z_score=True,
            img_size=224,
            fs=256,
            time_low=-0.1,
            time_high=1.0,
            subject_id=0,
            download=False,
    ):

        self.z_score = z_score
        self.fs = fs
        self.eeg_data = None
        self.labels = None
        self.img_size = img_size
        self.time_low = int((time_low - 0.02) * self.fs)
        self.time_high = int((time_high - 0.02) * self.fs)
        print(f"image size = {img_size}")
        self.transforms = T.ToTensor()
        self.transforms_img = T.Compose([T.ToTensor(), T.ConvertImageDtype(dtype=torch.float32)])
        self.transforms_tensor2img = T.Compose([T.ToPILImage()])
        self.img_preprocess = _transform(img_size)

        data_path = os.path.join(data_path, "spampinato_all_subj_npy")
        os.makedirs(data_path, exist_ok=True)

        if download:

            os.system(f"wget https://files.de-1.osf.io/v1/resources/temjc/providers/osfstorage/6654754177ff4c43e4e046be/?zip= -O temp_spampinato.zip")
            os.system(f"export UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE")
            os.system(f"unzip temp_spampinato.zip -d {data_path}")
            os.system(f"rm temp_spampinato.zip")

            unzip_nested_files(data_path)
        
        self.labels = np.load(os.path.join(data_path, f"spampinato_et_al_label_{subject_id}.npy"), mmap_mode='r')
        self.eeg_data = np.load(os.path.join(data_path, f"spampinato_et_al_eeg_{subject_id}.npy"), mmap_mode='r')
        self.image_files = np.load(os.path.join(data_path, f"spampinato_et_al_img_{subject_id}.npy"), mmap_mode='r')
        self.pairs = np.load(os.path.join(data_path, f"images.npy"), mmap_mode='r')
        self.subjects = np.zeros((len(self.eeg_data),))

        max_classes = 40

        if n_classes < max_classes:
            sample_classes = sorted(random.sample(range(0, max_classes), n_classes))
            self.class_dict = {str(y): x for x, y in enumerate(sample_classes)}  # change str labels to indices
            print(f"sample_classes = {sample_classes}")
            self.indices = [i for i, label in enumerate(self.labels) if label in sample_classes]
        else:
            self.indices = list(range(0, len(self.labels)))
            self.class_dict = {str(y): y for y in range(0, n_classes)}
            print(f"training on classes: all 40 classes")
        print(f"class_dict: {self.class_dict}")

    def __len__(self):
        return len(self.indices)

    def __getitem__(self, item):
        if torch.is_tensor(item):
            item = item.tolist()

        eeg = self.eeg_data[self.indices[item]]
        eeg = eeg.copy()
        if eeg.shape[0] > 1:
            eeg = np.expand_dims(eeg, axis=0)
        eeg = eeg[:, :, self.time_low:self.time_high]

        # set time length to 512
        if eeg.shape[-1] > 512:
            idx = np.random.randint(0, int(eeg.shape[-1] - 512) + 1)

            eeg = eeg[..., idx: idx + 512]
        else:
            x1 = np.linspace(0, 1, eeg.shape[-1])
            x2 = np.linspace(0, 1, 512)
            f = interp1d(x1, eeg, axis=-1)
            eeg = f(x2)

        if self.z_score:
            # z_score normalization
            eeg = (eeg - np.mean(eeg, axis=-1, keepdims=True)) / (np.std(eeg, axis=-1, keepdims=True) + 1e-08)

        pair = self.pairs[self.image_files[self.indices[item]]].copy()
        sample = (torch.from_numpy(eeg).to(torch.float), (self.img_preprocess(pair).to(torch.float)))
        label = self.class_dict[str(self.labels[self.indices[item]])]
        # img_file = self.image_files[self.indices[item]].copy()

        return sample, label

# Dataset class
class SpampinatoDataset:
    
    # Constructor
    def __init__(
        self, 
        data_path,
        subject_id,
        time_low=0.02,
        time_high=0.46,
        fs=1000,
        download=False
        ):

        self.fs = fs
        self.time_low = int((time_low - 0.02) * self.fs)
        self.time_high = int((time_high - 0.02) * self.fs)
        self.subject_id = subject_id

        data_path = os.path.join(data_path, "spampinato_et_al")
        os.makedirs(data_path, exist_ok=True)

        if download:

            os.system(f"wget https://files.de-1.osf.io/v1/resources/temjc/providers/osfstorage/66e8279aaee31b2bbb1c3e62/?zip= -O temp_spampinato.zip")
            os.system(f"export UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE")
            os.system(f"unzip temp_spampinato.zip -d {data_path}")
            os.system(f"rm temp_spampinato.zip")

            unzip_nested_files(data_path)

        # Load EEG signals
        eeg_signals_path = os.path.join(data_path, "eeg_14_70_std.pth")
        image_data_path="/proj/common-datasets/ImageNet/train/"
        loaded = torch.load(eeg_signals_path)
        if subject_id!=0:
            self.data = [loaded['dataset'][i] for i in range(len(loaded['dataset']) ) if loaded['dataset'][i]['subject']==opt.subject]
        else:
            self.data=loaded['dataset']      
        print(self.data[0].keys())  
        self.labels = loaded["labels"]
        self.images = loaded["images"]
        
        # Compute size
        self.size = len(self.data)

    # Get size
    def __len__(self):
        return self.size

    # Get item
    def __getitem__(self, i):
        # Process EEG
        eeg = self.data[i]["eeg"].float().t()
        eeg = eeg[self.time_low:self.time_high,:]
        # Get image
        # Get label
        label = self.data[i]["label"]
        # Return
        return eeg, label

class Splitter(Dataset):
    def __init__(self, dataset, split_path, split_num=0, split_name="train"):
        # Set EEG dataset
        self.dataset = dataset
        # Load split
        loaded = torch.load(split_path)
        self.split_idx = loaded["splits"][split_num][split_name]
        # Compute size
        self.size = len(self.split_idx)

    # Get size
    def __len__(self):
        return self.size

    # Get item
    def __getitem__(self, i):
        # Get sample from dataset
        sample, label, img_file = self.dataset[self.split_idx[i]]
        # Return
        return sample, label, img_file

class ThingsEEG2(Dataset):
    def __init__(
        self,
        data_path,
        subject_id,
        img_size=224,
        load_img=False,
        download=False,
        ):

        self.load_img = load_img
        self.img_transform = _transform(img_size)
        data_path = os.path.join(data_path, "things_eeg_2")
        os.makedirs(data_path, exist_ok=True)

        if download:
            # download raw EEG
            # os.makedirs(os.path.join(data_path, "raw_eeg"), exist_ok=True)
            # os.system(f"wget https://files.osf.io/v1/resources/crxs4/providers/googledrive/?zip= -O temp_things2_raw.zip")
            # os.system(f"export UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE")
            # os.system(f"unzip temp_things2_raw.zip -d {os.path.join(data_path, 'raw_eeg')}")
            # os.system(f"rm temp_things2_raw.zip")
            # download preprocessed EEG
            os.makedirs(os.path.join(data_path, "preprocessed_eeg"), exist_ok=True)
            os.system(f"wget https://files.de-1.osf.io/v1/resources/anp5v/providers/osfstorage/?zip= -O temp_things2_preprocessed.zip")
            os.system(f"export UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE")
            os.system(f"unzip temp_things2_preprocessed.zip -d {os.path.join(data_path, 'preprocessed_eeg')}")
            os.system(f"rm temp_things2_preprocessed.zip")
            # download images
            os.makedirs(os.path.join(data_path, "images"), exist_ok=True)
            os.system(f"wget https://files.de-1.osf.io/v1/resources/y63gw/providers/osfstorage/?zip= -O temp_images.zip")
            os.system(f"export UNZIP_DISABLE_ZIPBOMB_DETECTION=TRUE")
            os.system(f"unzip temp_images.zip -d {os.path.join(data_path, 'images')}")
            os.system(f"rm temp_images.zip")

            unzip_nested_files(data_path)

        self.eeg_parent_dir = os.path.join(data_path, 'preprocessed_eeg', 'sub-'+"{:02d}".format(subject_id))
        self.eeg_data_train = np.load(os.path.join(self.eeg_parent_dir,
                'preprocessed_eeg_training.npy'), allow_pickle=True).item()
        self.eeg_data_test = np.load(os.path.join(self.eeg_parent_dir,
                'preprocessed_eeg_test.npy'), allow_pickle=True).item() 
        
        # img_data['train_img_concepts'] defines the classes 
        self.img_parent_dir  = os.path.join(data_path, 'images')
        self.img_metadata = np.load(os.path.join(self.img_parent_dir, 'image_metadata.npy'),
	            allow_pickle=True).item()

        self.eeg_data = self.eeg_data_train['preprocessed_eeg_data']
        self.labels = self.img_metadata['train_img_concepts']


    def __len__(self):
        return len(self.eeg_data)

    def __getitem__(self, item):
        if torch.is_tensor(item):
            item = item.tolist()
        eeg = self.eeg_data[item]
        eeg = eeg.copy()
        if eeg.shape[0] > 1:
            eeg = np.expand_dims(eeg, axis=0)

        # set time length to 128
        x1 = np.linspace(0, 1, eeg.shape[-1])
        x2 = np.linspace(0, 1, 128)
        f = interp1d(x1, eeg, axis=-1)
        eeg = f(x2)

        if self.load_img:
            train_img_file = os.path.join(self.img_parent_dir, 'training_images', 
                    self.img_metadata['train_img_concepts'][item], self.img_metadata['train_img_files'][item])
            pair = Image.open(train_img_file).convert('RGB')
            sample = (torch.from_numpy(eeg).to(torch.float), (self.img_transform(pair).to(torch.float)))
            label = self.labels[item]
        else:
            sample = torch.from_numpy(eeg).to(torch.float)
            label = self.labels[item]
        # img_file = self.image_files[self.indices[item]].copy()

        return sample, label

        


if __name__ == "__main__":
    selected = "spampinato"
    eeg_path = "/proj/rep-learning-robotics/users/x_nonra/eeg_asif_img/data/"
    if selected == "spampinato_all":
        data_loaded = EEGImagenet(
            data_path=eeg_path,
            z_score=False,
            n_classes=40,
            img_size=224,
            fs=1000,
            time_low=0.02,
            time_high=0.46,
            download=True
        )
    elif selected == "spampinato":
        data_loaded = SpampinatoDataset(
            data_path=eeg_path,
            subject_id=1,
            fs=1000,
            time_low=0.02,
            time_high=0.46,
            download=True
        )
    elif selected == "things-eeg-2":
        data_loaded = ThingsEEG2(
            data_path=eeg_path,
            subject_id=1,
            download=False,
            load_img=True,
        )
    print(len(data_loaded))
    x, l = data_loaded[0]
    print("x = ", x)
    print("l = ", l)