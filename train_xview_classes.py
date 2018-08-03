import math
import random

import cv2
import torch
import torch.nn as nn
import torch.nn.functional as F

from utils import *

# import torchvision
# from torchvision import datasets, transforms

torch.set_printoptions(linewidth=320, precision=8)
np.set_printoptions(linewidth=320, formatter={'float_kind': '{:11.5g}'.format})  # format short g, %precision=5


def xview_class_weights(indices):  # weights of each class in the training set, normalized to mu = 1
    weights = 1 / torch.FloatTensor(
        [74, 364, 713, 71, 2925, 20976.7, 6925, 1101, 3612, 12134, 5871, 3640, 860, 4062, 895, 149, 174, 17, 1624, 1846,
         125, 122, 124, 662, 1452, 697, 222, 190, 786, 200, 450, 295, 79, 205, 156, 181, 70, 64, 337, 1352, 336, 78,
         628, 841, 287, 83, 702, 1177, 31386.5, 195, 1081, 882, 1059, 4175, 123, 1700, 2317, 1579, 368, 85])
    weights /= weights.sum()
    return weights[indices]


# Epoch 25: 98.60% test accuracy, 0.0555 test loss (normalize after relu)
# Epoch 11: 98.48% test accuracy, 0.0551 test loss (normalize after both)
class MLP(nn.Module):
    def __init__(self):
        super(MLP, self).__init__()
        self.fc1 = nn.Linear(784, 500, bias=True)
        self.fc2 = nn.Linear(500, 10, bias=True)

    def forward(self, x):
        x = x.view(-1, 28 * 28)
        x = self.fc1(x)
        x = F.relu(x)
        # x, _, _ = normalize(x, axis=1)
        x = self.fc2(x)
        return x


# 178  9.2745e-05    0.024801        99.2 default no augmentation
class ConvNeta(nn.Module):
    def __init__(self):
        super(ConvNeta, self).__init__()
        self.conv1 = nn.Conv2d(1, 10, kernel_size=5)
        self.conv2 = nn.Conv2d(10, 20, kernel_size=5)
        self.conv2_drop = nn.Dropout2d()
        self.fc1 = nn.Linear(320, 50)
        self.fc2 = nn.Linear(50, 10)

    def forward(self, x):
        x = F.relu(F.max_pool2d(self.conv1(x), 2))
        x = F.relu(F.max_pool2d(self.conv2_drop(self.conv2(x)), 2))
        x = x.view(-1, 320)
        x = F.relu(self.fc1(x))
        x = F.dropout(x, training=self.training)
        x = self.fc2(x)
        return x


# https://github.com/yunjey/pytorch-tutorial/tree/master/tutorials/02-intermediate
# 8    0.00023365    0.025934       99.14  default no augmentation
# 124      14.438    0.012876       99.55  LeakyReLU in place of ReLU
# 190  0.00059581    0.013831       99.58  default
class ConvNetb(nn.Module):
    def __init__(self, num_classes=60):
        super(ConvNetb, self).__init__()
        n = 64  # initial convolution size
        self.layer1 = nn.Sequential(
            nn.Conv2d(3, n, kernel_size=3, stride=1, padding=1, bias=False),
            nn.BatchNorm2d(n),
            nn.LeakyReLU())
        self.layer2 = nn.Sequential(
            nn.Conv2d(n, n * 2, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(n * 2),
            nn.LeakyReLU())
        self.layer3 = nn.Sequential(
            nn.Conv2d(n * 2, n * 4, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(n * 4),
            nn.LeakyReLU())
        self.layer4 = nn.Sequential(
            nn.Conv2d(n * 4, n * 8, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(n * 8),
            nn.LeakyReLU())
        self.layer5 = nn.Sequential(
            nn.Conv2d(n * 8, n * 16, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(n * 16),
            nn.LeakyReLU())
        self.layer6 = nn.Sequential(
            nn.Conv2d(n * 16, n * 32, kernel_size=3, stride=2, padding=1, bias=False),
            nn.BatchNorm2d(n * 32),
            nn.LeakyReLU())
        # self.fc = nn.Linear(65536, num_classes)  # 64 pixels, 3 layer, 64 filters
        # self.fc = nn.Linear(32768, num_classes)  # 64 pixels, 3 layer, 32 filters
        self.fc = nn.Linear(int(32768/4), num_classes)  # 64 pixels, 4 layer, 64 filters

    def forward(self, x):  # x.size() = [512, 1, 28, 28]
        x = self.layer1(x)
        x = self.layer2(x)
        x = self.layer3(x)
        x = self.layer4(x)
        x = self.layer5(x)
        x = self.layer6(x)
        x = x.reshape(x.size(0), -1)
        # x, _, _ = normalize(x,1)
        x = self.fc(x)
        return x


# @profile
def main(model):
    lr = .0001
    epochs = 1000
    printerval = 1
    patience = 500
    batch_size = 500
    cuda = torch.cuda.is_available()
    device = torch.device('cuda:0' if cuda else 'cpu')
    print('Running on %s\n%s' % (device.type, torch.cuda.get_device_properties(0) if cuda else ''))

    rgb_mean = torch.FloatTensor([60.134, 49.697, 40.746]).view((1, 3, 1, 1)).to(device)
    rgb_std = torch.FloatTensor([29.99, 24.498, 22.046]).view((1, 3, 1, 1)).to(device)

    np.random.seed(0)
    torch.manual_seed(0)
    if cuda:
        torch.cuda.manual_seed(0)
        torch.cuda.manual_seed_all(0)
        torch.backends.cudnn.benchmark = True

    # load < 2GB .mat files with scipy.io
    print('loading data...')
    # mat = scipy.io.loadmat('/Users/glennjocher/Documents/PyCharmProjects/yolo/utils/class_chips48.mat')
    # X = np.ascontiguousarray(mat['X'])  # 596154x3x32x32
    # Y = np.ascontiguousarray(mat['Y'])

    # load > 2GB .mat files with h5py
    import h5py
    with h5py.File('/Users/glennjocher/Documents/PyCharmProjects/yolo/class_chips64+64_tight.h5') as mat:
        X = mat.get('X').value
        Y = mat.get('Y').value

    # # load with pickle
    # pickle.dump({'X': X, 'Y': Y}, open('save.p', "wb"), protocol=4)
    # with pickle.load(open('save.p', "rb")) as save:
    #     X, Y = save['X'], save['Y']

    X = np.ascontiguousarray(X)
    Y = np.ascontiguousarray(Y.ravel())

    # print('creating batches...')
    # train_data = create_batches(x=X, y=Y, batch_size=batch_size, shuffle=True)
    # del X, Y

    # Load saved model
    resume = False
    start_epoch = 0
    best_loss = float('inf')
    if resume:
        checkpoint = torch.load('best64_6layer.pt', map_location='cuda:0' if cuda else 'cpu')

        model.load_state_dict(checkpoint['model'])
        model = model.to(device).train()

        # Set optimizer
        optimizer = torch.optim.Adam(filter(lambda p: p.requires_grad, model.parameters()), lr=lr)
        optimizer.load_state_dict(checkpoint['optimizer'])

        start_epoch = checkpoint['epoch'] + 1
        best_loss = checkpoint['best_loss']
        del checkpoint
    else:
        model = model.to(device).train()
        optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    weights = xview_class_weights(range(60))[Y].numpy()
    weights /= weights.sum()
    criteria = nn.CrossEntropyLoss()  # weight=xview_class_weights(range(60)).to(device))
    stopper = patienceStopper(epochs=epochs, patience=patience, printerval=printerval)

    border = 32
    shape = X.shape[1:3]
    height = shape[0]
    modelinfo(model)

    def train(model):
        vC = torch.zeros(60).to(device)  # vector correct
        vS = torch.zeros(60).long().to(device)  # vecgtor samples
        loss_cum = torch.FloatTensor([0]).to(device)
        nS = len(Y)
        v = np.random.permutation(nS)
        for batch in range(int(nS / batch_size)):
            # i = v[batch * batch_size:(batch + 1) * batch_size]  # ordered chip selection
            i = np.random.choice(nS, size=batch_size, p=weights)  # weighted chip selection
            x, y = X[i], Y[i]

            # x = x.transpose([0, 2, 3, 1])  # torch to cv2
            for j in range(batch_size):
                M = random_affine(degrees=(-179.9, 179.9), translate=(.15, .15), scale=(.6, 1.40), shear=(-5, 5),
                                  shape=shape)

                x[j] = cv2.warpPerspective(x[j], M, dsize=shape, flags=cv2.INTER_LINEAR,
                                           borderValue=[60.134, 49.697, 40.746])  # RGB

            # import matplotlib.pyplot as plt
            # for pi in range(16):
            #     plt.subplot(4, 4, pi + 1).imshow(x[pi + 50])
            # for pi in range(16):
            #    plt.subplot(4, 4, pi + 1).imshow(x[pi + 50, border:height - border, border:height - border])

            x = x.transpose([0, 3, 1, 2])  # cv2 to torch

            x = x[:, :, border:height - border, border:height - border]

            # if random.random() > 0.25:
            #     np.rot90(x, k=np.random.choice([1, 2, 3]), axes=(2, 3))
            # if random.random() > 0.5:
            #     x = x[:, :, :, ::-1]  # = np.fliplr(x)
            if random.random() > 0.5:
                x = x[:, :, ::-1, :]  # = np.flipud(x)

            # 596154x3x64x64
            # x_shift = int(np.clip(random.gauss(8, 3), a_min=0, a_max=16) + 0.5)
            # y_shift = int(np.clip(random.gauss(8, 3), a_min=0, a_max=16) + 0.5)
            # x = x[:, :, y_shift:y_shift + 48, x_shift:x_shift + 48]

            x = np.ascontiguousarray(x)
            x = torch.from_numpy(x).to(device).float()
            y = torch.from_numpy(y).to(device).long()

            x -= rgb_mean
            x /= rgb_std

            yhat = model(x)
            loss = criteria(yhat, y)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            with torch.no_grad():
                loss_cum += loss.data
                correct = y == torch.argmax(yhat.data, 1)
                vS += torch.bincount(y, minlength=60)
                vC += torch.bincount(y, minlength=60, weights=correct).float()

        accuracy = vC / vS.float()
        return loss_cum.detach().cpu(), accuracy.detach().cpu()

    for epoch in range(epochs):
        epoch += start_epoch
        loss, accuracy = train(model.train())

        # Save best checkpoint
        if (epoch >= 0) & (loss.item() < best_loss):
            best_loss = loss.item()
            torch.save({'epoch': epoch,
                        'best_loss': best_loss,
                        'accuracy': accuracy,
                        'model': model.state_dict(),
                        'optimizer': optimizer.state_dict()},
                       'best64_6layerLeaky.pt')

        if stopper.step(loss, metrics=(*accuracy.mean().view(1),), model=model):
            break


def random_affine(degrees=(-10, 10), translate=(.1, .1), scale=(.9, 1.1), shear=(-2, 2), shape=(0, 0)):
    # torchvision.transforms.RandomAffine(degrees=(-10, 10), translate=(.1, .1), scale=(.9, 1.1), shear=(-10, 10))
    # https://medium.com/uruvideo/dataset-augmentation-with-random-homographies-a8f4b44830d4

    # Rotation and Scale
    R = np.eye(3)
    a = random.random() * (degrees[1] - degrees[0]) + degrees[0]
    # a += random.choice([-180, -90, 0, 90])  # random 90deg rotations added to small rotations

    s = random.random() * (scale[1] - scale[0]) + scale[0]
    R[:2] = cv2.getRotationMatrix2D(angle=a, center=(shape[1] / 2, shape[0] / 2), scale=s)

    # Translation
    T = np.eye(3)
    T[0, 2] = (random.random() * 2 - 1) * translate[0] * shape[0]  # x translation (pixels)
    T[1, 2] = (random.random() * 2 - 1) * translate[1] * shape[1]  # y translation (pixels)

    # Shear
    S = np.eye(3)
    S[0, 1] = math.tan((random.random() * (shear[1] - shear[0]) + shear[0]) * math.pi / 180)  # x shear (deg)
    S[1, 0] = math.tan((random.random() * (shear[1] - shear[0]) + shear[0]) * math.pi / 180)  # y shear (deg)

    M = S @ T @ R  # ORDER IS IMPORTANT HERE!!
    return M


if __name__ == '__main__':
    main(ConvNetb())

# 64+64 chips, 3 layer, 64 filter, 1e-4 lr, weighted choice
# 14 layers, 4.30393e+06 parameters, 4.30393e+06 gradients
#        epoch        time        loss   metric(s)
#            0      60.166      753.99     0.22382
#            1      56.689       624.4     0.33007
#            2      57.275       582.1     0.36716
#            3      56.846      550.78      0.3957
#            4      57.729      527.38     0.41853
#            5      56.764      513.21     0.43129
#            6      56.875      498.57      0.4469
#            7      56.738      488.15     0.45739
#            8      57.036      475.83     0.46783
#            9      55.792      467.88     0.47626
#           10      56.208      458.48     0.48439
#           11      56.211      450.75     0.49385
#           12      57.053      445.68     0.49811
#           13      57.328      441.04     0.50464
#           14      56.918      431.16     0.51161
#           15      57.427      426.65     0.51633
#           16      57.459      419.86     0.52306
#           17      57.065      417.16     0.52744
#           18      56.941      412.04     0.52933
#           19      57.092       408.4     0.53467
#           20      56.203      405.08     0.53933
#           21      56.807      401.29     0.54273

# 64+64 chips, 4 layer, 64 filter, 1e-4 lr, weighted choice
# 18 layers, 3.51904e+06 parameters, 3.51904e+06 gradients
#        epoch        time        loss   metric(s)
#            0      71.674      723.36     0.24818
#            1      68.146      578.31     0.36916
#            2      67.065      526.51     0.41884
#            3      65.809      489.59     0.45376
#            4      65.459       463.5     0.47846
#            5       66.26      444.56     0.49885
#            6      65.697       427.5     0.51586
#            7      66.678      411.46     0.52993
#            8      69.236      398.99     0.54557
#            9      67.304       387.8     0.55529
#           10       67.04      379.64     0.56469
#           11      68.929      366.64     0.57563
#           12      67.943      361.51     0.58113
#           13      67.129      351.83      0.5916
#           14      67.819      343.37     0.60065
#           15      66.663      336.71     0.60816
#           16      67.298      331.21     0.61232
#           17      66.624      327.19     0.61792
#           18      67.563      320.75     0.62496
#           19      66.685      314.04     0.63251
#           20      66.962      309.61     0.63594
#           21      69.335      306.29      0.6382

# 64+64 chips, 5 layer, 64 filter, 1e-4 lr, weighted choice
# 22 layers, 7.25766e+06 parameters, 7.25766e+06 gradients
#        epoch        time        loss   metric(s)
#            0      82.027      716.17     0.25299
#            1       78.31      553.02     0.39201
#            2       77.94      494.01     0.44724
#            3      77.881      453.51     0.48681
#            4      78.541      422.42     0.51708
#            5      78.871      399.53      0.5412
#            6      79.004      380.04     0.56051
#            7      79.195      363.01      0.5776
#            8      79.192      348.36     0.59654
#            9      78.873       334.8     0.60685
#           10      78.701      325.81     0.62028
#           11      78.211      309.74     0.63352
#           12      78.383      304.03     0.64136
#           13      78.598      294.14      0.6517
#           14      78.995      284.86      0.6618
#           15      78.926      279.32     0.66773
#           16      79.018      272.16     0.67526
#           17      78.783       265.8     0.68253
#           18      79.131      258.86     0.69176
#           19      79.578      252.74     0.69823
#           20      79.602      248.09     0.70239
#           21      79.201      242.78     0.70802

# 64+64 chips, 6 layer, 64 filter, 1e-4 lr, weighted choice
# 26 layers, 2.56467e+07 parameters, 2.56467e+07 gradients
#        epoch        time        loss   metric(s)
#            0      116.64      690.71     0.27556
#            1      112.58      519.11     0.42209
#            2      112.61      453.07      0.4859
#            3      111.94      405.52     0.53345
#            4      111.77       371.4      0.5683
#            5      111.45      346.25     0.59423
#            6      111.64      324.47     0.61758
#            7      111.63      303.77     0.63987
#            8      112.08      288.21     0.65884
#            9      112.17      275.39     0.67283
#           10      112.29      266.28     0.68319
#           11      111.44      251.77     0.69664
#           12      112.42      243.59     0.70702
#           13      112.55      234.84      0.7162
#           14      115.51      228.32     0.72272
#           15      115.35      219.51     0.73424
#           16      114.25       212.6     0.74147
#           17      111.66      208.52     0.74727
#           18      110.97       199.9     0.75598
#           19      111.33      196.14     0.76011
#           20      111.66      190.75     0.76805
#           21      111.73      184.98     0.77273
