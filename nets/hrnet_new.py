"""
@author: qiuwenhui
@Software: VSCode
@Time: 2023-02-06 16:56:26
"""


import torch.nn as nn

BN_MOMENTUM = 0.1


class BasicBlock(nn.Module):
    expansion = 1

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(BasicBlock, self).__init__()
        self.conv1 = nn.Conv2d(
            inplanes, planes, kernel_size=3, stride=stride, padding=1, bias=False
        )
        self.bn1 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.conv2 = nn.Conv2d(
            planes, planes, kernel_size=3, stride=stride, padding=1, bias=False
        )
        self.bn2 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class Bottleneck(nn.Module):
    expansion = 4

    def __init__(self, inplanes, planes, stride=1, downsample=None):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(inplanes, planes, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.conv2 = nn.Conv2d(
            planes, planes, kernel_size=3, stride=stride, padding=1, bias=False
        )
        self.bn2 = nn.BatchNorm2d(planes, momentum=BN_MOMENTUM)
        self.conv3 = nn.Conv2d(
            planes, planes * self.expansion, kernel_size=1, bias=False
        )
        self.bn3 = nn.BatchNorm2d(planes * self.expansion, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)
        self.downsample = downsample
        self.stride = stride

    def forward(self, x):
        residual = x

        out = self.conv1(x)
        out = self.bn1(out)
        out = self.relu(out)

        out = self.conv2(out)
        out = self.bn2(out)
        out = self.relu(out)

        out = self.conv3(out)
        out = self.bn3(out)

        if self.downsample is not None:
            residual = self.downsample(x)

        out += residual
        out = self.relu(out)

        return out


class StageModule(nn.Module):
    def __init__(self, input_branches, output_branches, c):
        """
        ????????????stage???????????????????????????????????????
        :param input_branches: ???????????????????????????????????????????????????
        :param output_branches: ??????????????????
        :param c: ?????????????????????????????????
        """
        super().__init__()
        self.input_branches = input_branches
        self.output_branches = output_branches

        self.branches = nn.ModuleList()
        for i in range(self.input_branches):  # ???????????????????????????4???BasicBlock
            w = c * (2**i)  # ?????????i?????????????????????
            branch = nn.Sequential(
                BasicBlock(inplanes=w, planes=w),
                BasicBlock(inplanes=w, planes=w),
                BasicBlock(inplanes=w, planes=w),
                BasicBlock(inplanes=w, planes=w),
            )
            self.branches.append(branch)

        self.fuse_layers = nn.ModuleList()  # ????????????????????????????????????
        for i in range(self.output_branches):
            self.fuse_layers.append(nn.ModuleList())
            for j in range(self.input_branches):
                if i == j:
                    # ?????????????????????????????????????????????????????????
                    self.fuse_layers[-1].append(nn.Identity())
                elif i < j:
                    # ???????????????j??????????????????i???(?????????????????????????????????????????????????????????)???
                    # ???????????????????????????j??????????????????????????????????????????????????????
                    self.fuse_layers[-1].append(
                        nn.Sequential(
                            nn.Conv2d(
                                in_channels=c * (2**j),
                                out_channels=c * (2**i),
                                kernel_size=1,
                                stride=1,
                                bias=False,
                            ),
                            nn.BatchNorm2d(
                                num_features=c * (2**i), momentum=BN_MOMENTUM
                            ),
                            nn.Upsample(scale_factor=2.0 ** (j - i), mode="bilinear"),
                        )
                    )
                else:  # i > j
                    # ???????????????j??????????????????i???(?????????????????????????????????????????????????????????)???
                    # ???????????????????????????j??????????????????????????????????????????????????????
                    # ??????????????????????????????2x??????????????????3x3?????????????????????4x???????????????8x?????????????????????i-j???
                    ops = []
                    # ???i-j-1????????????????????????????????????????????????
                    for k in range(i - j - 1):
                        ops.append(
                            nn.Sequential(
                                nn.Conv2d(
                                    in_channels=c * (2**j),
                                    out_channels=c * (2**j),
                                    kernel_size=3,
                                    stride=2,
                                    padding=1,
                                    bias=False,
                                ),
                                nn.BatchNorm2d(
                                    num_features=c * (2**j), momentum=BN_MOMENTUM
                                ),
                                nn.ReLU(inplace=True),
                            )
                        )
                    # ??????????????????????????????????????????????????????????????????
                    ops.append(
                        nn.Sequential(
                            nn.Conv2d(
                                in_channels=c * (2**j),
                                out_channels=c * (2**i),
                                kernel_size=3,
                                stride=2,
                                padding=1,
                                bias=False,
                            ),
                            nn.BatchNorm2d(
                                num_features=c * (2**i), momentum=BN_MOMENTUM
                            ),
                        )
                    )
                    self.fuse_layers[-1].append(nn.Sequential(*ops))

        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        # ???????????????????????????block
        x = [branch(xi) for branch, xi in zip(self.branches, x)]

        # ??????????????????????????????
        x_fused = []
        for i in range(len(self.fuse_layers)):
            x_fused.append(
                self.relu(
                    sum(
                        [
                            self.fuse_layers[i][j](x[j])
                            for j in range(len(self.branches))
                        ]
                    )
                )
            )

        return x_fused


class HighResolutionNet(nn.Module):
    def __init__(self, base_channel: int = 32, num_joints: int = 17):
        super().__init__()
        # Stem ?????????????????????????????????????????????
        self.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=2, padding=1, bias=False)
        self.bn1 = nn.BatchNorm2d(64, momentum=BN_MOMENTUM)
        self.conv2 = nn.Conv2d(64, 64, kernel_size=3, stride=2, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(64, momentum=BN_MOMENTUM)
        self.relu = nn.ReLU(inplace=True)

        # Stage1
        downsample = nn.Sequential(
            nn.Conv2d(64, 256, kernel_size=1, stride=1, bias=False),
            nn.BatchNorm2d(256, momentum=BN_MOMENTUM),
        )
        self.layer1 = nn.Sequential(
            Bottleneck(inplanes=64, planes=64, downsample=downsample),
            Bottleneck(inplanes=256, planes=64),
            Bottleneck(inplanes=256, planes=64),
            Bottleneck(inplanes=256, planes=64),
        )

        self.transition1 = nn.ModuleList(
            [
                nn.Sequential(
                    nn.Conv2d(
                        in_channels=256,
                        out_channels=base_channel,
                        kernel_size=3,
                        stride=1,
                        padding=1,
                        bias=False,
                    ),
                    nn.BatchNorm2d(base_channel, momentum=BN_MOMENTUM),
                    nn.ReLU(inplace=True),
                ),
                nn.Sequential(
                    nn.Sequential(  # ?????????????????????Sequential??????????????????????????????????????????
                        nn.Conv2d(
                            in_channels=256,
                            out_channels=base_channel * 2,
                            kernel_size=3,
                            stride=2,
                            padding=1,
                            bias=False,
                        ),
                        nn.BatchNorm2d(base_channel * 2, momentum=BN_MOMENTUM),
                        nn.ReLU(inplace=True),
                    )
                ),
            ]
        )

        # Stage2
        self.stage2 = nn.Sequential(
            StageModule(input_branches=2, output_branches=2, c=base_channel)
        )

        # transition2
        self.transition2 = nn.ModuleList(
            [
                nn.Identity(),  # None,  - Used in place of "None" because it is callable
                nn.Identity(),  # None,  - Used in place of "None" because it is callable
                nn.Sequential(
                    nn.Sequential(
                        nn.Conv2d(
                            in_channels=base_channel * 2,
                            out_channels=base_channel * 4,
                            kernel_size=3,
                            stride=2,
                            padding=1,
                            bias=False,
                        ),
                        nn.BatchNorm2d(
                            num_features=base_channel * 4, momentum=BN_MOMENTUM
                        ),
                        nn.ReLU(inplace=True),
                    )
                ),
            ]
        )

        # Stage3
        self.stage3 = nn.Sequential(
            StageModule(input_branches=3, output_branches=3, c=base_channel),
            StageModule(input_branches=3, output_branches=3, c=base_channel),
            StageModule(input_branches=3, output_branches=3, c=base_channel),
            StageModule(input_branches=3, output_branches=3, c=base_channel),
        )

        # transition3
        self.transition3 = nn.ModuleList(
            [
                nn.Identity(),  # None,  - Used in place of "None" because it is callable
                nn.Identity(),  # None,  - Used in place of "None" because it is callable
                nn.Identity(),  # None,  - Used in place of "None" because it is callable
                nn.Sequential(
                    nn.Sequential(
                        nn.Conv2d(
                            in_channels=base_channel * 4,
                            out_channels=base_channel * 8,
                            kernel_size=3,
                            stride=2,
                            padding=1,
                            bias=False,
                        ),
                        nn.BatchNorm2d(
                            num_features=base_channel * 8, momentum=BN_MOMENTUM
                        ),
                        nn.ReLU(inplace=True),
                    )
                ),
            ]
        )

        # Stage4
        # ?????????????????????StageModule????????????????????????????????????
        self.stage4 = nn.Sequential(
            StageModule(input_branches=4, output_branches=4, c=base_channel),
            StageModule(input_branches=4, output_branches=4, c=base_channel),
            StageModule(input_branches=4, output_branches=1, c=base_channel),
        )


    def forward(self, x):
        x = self.conv1(x)  # x(B,3,H,W) -> x(B,64,H/2,W/2)
        x = self.bn1(x)
        x = self.relu(x)
        x = self.conv2(x)  # x(B,64,H/4,W/4)
        x = self.bn2(x)
        x = self.relu(x)

        x = self.layer1(x)  # x(B,256,H/4,W/4)
        low_level_features = x  # ??????????????????
        
        x = [
            trans(x) for trans in self.transition1
        ]  # Since now, x is a list  # x[x0(B,32,H/4,W/4), x1(B,64,H/8,W/8)]

        x = self.stage2(x)  # x[x0(B,32,H/4,W/4), x1(B,64,H/8,W/8)]
        x = [
            self.transition2[0](x[0]),
            self.transition2[1](x[1]),
            self.transition2[2](x[-1]),
        ]  # New branch derives from the "upper" branch only
        # x[x0(B,32,H/4,W/4), x1(B,64,H/8,W/8), x2(B,128,H/16,W/16)]

        x = self.stage3(x)  # x[x0(B,32,H/4,W/4), x1(B,64,H/8,W/8), x2(B,128,H/16,W/16)]
        x = [
            self.transition3[0](x[0]),
            self.transition3[1](x[1]),
            self.transition3[2](x[2]),
            self.transition3[3](x[-1]),
        ]  # New branch derives from the "upper" branch only
        # x[x0(B,32,H/4,W/4), x1(B,64,H/8,W/8), x2(B,128,H/16,W/16), x3(B,256,H/32,W/32)]

        x = self.stage4(x)  # x[x0(B,32,H/4,W/4)] ????????????????????????(H/4,W/4)???????????????????????????

        return low_level_features, x[0]


def HRNet_Backbone_New(model_type):
    if model_type == "hrnet_w18":
        backbone = HighResolutionNet(base_channel=18)
    elif model_type == "hrnet_w32":
        backbone = HighResolutionNet(base_channel=32)
    elif model_type == "hrnet_w48":
        backbone = HighResolutionNet(base_channel=48)
    
    return backbone
        