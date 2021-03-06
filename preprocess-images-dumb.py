import h5py
from torch.autograd import Variable
import torch.nn as nn
import torch.backends.cudnn as cudnn
import torch.utils.data
import torchvision.models as models
from tqdm import tqdm

import config
import data
import utils
from resnet import resnet as caffe_resnet


class Net(nn.Module):
    def __init__(self):
        super(Net, self).__init__()
        self.model = caffe_resnet.resnet152(pretrained=True)

        def save_output(module, input, output):
            self.buffer = output
        self.model.layer4.register_forward_hook(save_output)

    def forward(self, x):
        self.model(x)
        return self.buffer


def create_vizwiz_loader(*paths):
    #transform = utils.get_transform(config.image_size, config.central_fraction)
    transform = utils.get_transform_unnormalized(config.image_size, config.central_fraction)
    datasets = [data.VizWizImages(path, transform=transform) for path in paths]
    dataset = data.Composite(*datasets)
    data_loader = torch.utils.data.DataLoader(
        dataset,
        batch_size=config.preprocess_batch_size,
        num_workers=config.data_workers,
        shuffle=False,
        pin_memory=True,
    )
    return data_loader


def main():
    print("running on", "cuda:0" if torch.cuda.is_available() else "cpu")
    # cudnn.benchmark = True

    # net = Net().to("cuda:0" if torch.cuda.is_available() else "cpu")
    # net.eval()

    # loader = create_vizwiz_loader(config.train_path, config.val_path)
    loader = create_vizwiz_loader(config.test_path)
    # loader = create_vizwiz_loader(config.val_path)
    features_shape = (
        len(loader.dataset),
        3,
        448,
        448
    )

    with h5py.File(config.test_unprocessed_path, 'w', libver='latest') as fd, torch.no_grad():
        features = fd.create_dataset('features', shape=features_shape, dtype='float16')
        coco_ids = fd.create_dataset('ids', shape=(len(loader.dataset),), dtype='int32')

        i = j = 0
        for ids, imgs in tqdm(loader):
            # imgs = Variable(imgs.to("cuda:0" if torch.cuda.is_available() else "cpu"))
            # out = net(imgs)
            # assert(False)
            j = i + imgs.size(0)
            features[i:j, :, :] = imgs.numpy().astype('float16')
            coco_ids[i:j] = ids.numpy().astype('int32')
            i = j


if __name__ == '__main__':
    main()
