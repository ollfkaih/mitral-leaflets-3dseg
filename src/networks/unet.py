import monai.networks.nets as mnn
import torch.nn as nn

from networks.core import EnhancedLightningModule



class BasicUNet(EnhancedLightningModule):
    def __init__(self,
                 # EnhancedLightningModule parameters
                 loss=nn.BCELoss(), optimizer={"name": "Adam", "params": {}},
                 lr_scheduler=True, final_activation=nn.Softmax(dim=1), metrics=[],
                 # Monai's BasicUNet parameters
                 spatial_dims=3, in_channels=1, out_channels=1,
                 features=(32, 32, 64, 128, 256, 32),
                 act=("LeakyReLU", {"negative_slope": 0.1, "inplace": True}),
                 norm=("instance", {"affine": True}), bias=True, dropout=0.0,
                 upsample="deconv"):
        super(BasicUNet, self).__init__(
                loss=loss, optimizer=optimizer, lr_scheduler=lr_scheduler,
                final_activation=final_activation, metrics=metrics
                )
        self.model = mnn.BasicUNet(
                spatial_dims=spatial_dims, in_channels=in_channels,
                out_channels=out_channels, features=features, act=act,
                norm=norm, bias=bias, dropout=dropout, upsample=upsample
                )

    def forward(self, x):
        return self.model(x)

class UNet(EnhancedLightningModule):
    def __init__(self,
                 # EnhancedLightningModule parameters
                 loss=nn.BCELoss(), optimizer={"name": "Adam", "params": {}},
                 lr_scheduler=True, final_activation=nn.Softmax(dim=1), metrics=[],
                 # Monai's UNet arguments
                 spatial_dims=3, in_channels=1, out_channels=1,
                 channels=(8, 16, 32), strides=(2, 2), kernel_size=3,
                 up_kernel_size=3, num_res_units=0, act="PRELU", norm="INSTANCE",
                 dropout=0, bias=True, adn_ordering="NDA"):
        super(UNet, self).__init__(
                loss=loss, optimizer=optimizer, lr_scheduler=lr_scheduler,
                final_activation=final_activation, metrics=metrics
                )
        self.model = mnn.UNet(
                spatial_dims, in_channels, out_channels, channels, strides,
                kernel_size=kernel_size, up_kernel_size=up_kernel_size,
                num_res_units=num_res_units, act=act, norm=norm,
                dropout=dropout, bias=bias, adn_ordering=adn_ordering
                )

    def forward(self, x):
        return self.model(x)
