import sys

sys.path.append("/proj/rep-learning-robotics/users/x_nonra/eeg_asif_img")

import torch.nn as nn

from src.models.image_architectures import VIT, DINO, DEIT

class ImageEncoder(nn.Module):
    def __init__(
        self,
        backbone: str = "ViT",
        embed_dim: int = None,
        add_ln_layer: bool = False,
        **kwargs
    ):
        super().__init__()
        self.backbone = backbone
        if backbone == "ViT":
            self.image_backbone = VIT()
        elif backbone == "DINO":
            self.image_backbone = DINO()
        elif backbone == "DeiT":
            self.image_backbone = DEIT()
        else:
            raise NotImplementedError

        # If add_ln_layer is true, add the FC layer
        if add_ln_layer:
            assert embed_dim is not None, "Embed_dim must be specified when adding FC layer"
            self.fc = nn.Linear(self.image_backbone.embedding_size, embed_dim)
            self.embed_dim = embed_dim
            # Freeze the backbone parameters and only train the FC layer
            for param in self.image_backbone.parameters():
                param.requires_grad = False
        else:
            self.fc = None
            self.embed_dim = self.image_backbone.embedding_size
            # If no FC layer, freeze all parameters (including the backbone)
            for param in self.parameters():
                param.requires_grad = False

        print("image embedding size = ", self.embed_dim)

    def forward(self, x):
        # Forward pass through the backbone encoder
        x = self.image_backbone.encode(x, alr_preprocessed=True)
        # If the FC layer exists, pass through it
        if self.fc is not None:
            x = self.fc(x)
        return x