import sys
import os.path
import math
import json

import torch
import torch.nn as nn
import torch.optim as optim
import torch.backends.cudnn as cudnn
from torch.autograd import Variable
from tqdm import tqdm

import config
import data
import utils
import colors
from model_baseline import update_learning_rate, total_iterations

# Simple neural network to classify colors given resnet feature maps
color_net = nn.Sequential(
        nn.AdaptiveAvgPool2d((6,6)),
        nn.Flatten(),
        nn.Dropout(),
        nn.Linear(config.output_features * 6 * 6, 1024),
        nn.ReLU(inplace=True),
        nn.Dropout(),
        nn.Linear(1024, 128),
        nn.ReLU(inplace=True),
        nn.Linear(128, colors.num_colors),
        )

def run(net, loader, optimizer, tracker, train=False, prefix='', epoch=0):
    """ Run an epoch over the given loader """
    if train:
        net.train()
        tracker_class, tracker_params = tracker.MovingMeanMonitor, {'momentum': 0.99}
    else:
        net.eval()
        tracker_class, tracker_params = tracker.MeanMonitor, {}
        answ = []
        idxs = []
        accs = []

    tq = tqdm(loader, desc='{} E{:03d}'.format(prefix, epoch), ncols=0)
    loss_tracker = tracker.track('{}_loss'.format(prefix), tracker_class(**tracker_params))
    acc_tracker = tracker.track('{}_acc'.format(prefix), tracker_class(**tracker_params))

    log_softmax = nn.LogSoftmax().to("cuda:0" if torch.cuda.is_available() else "cpu")
    for v, q, a, idx, q_len in tq:
        var_params = {
            'requires_grad': False,
        }
        with torch.set_grad_enabled(train):
            v = Variable(v.to("cuda:0" if torch.cuda.is_available() else "cpu"), **var_params)
            q = Variable(q.to("cuda:0" if torch.cuda.is_available() else "cpu"), **var_params)
            a = Variable(a.to("cuda:0" if torch.cuda.is_available() else "cpu"), **var_params)
            q_len = Variable(q_len.to("cuda:0" if torch.cuda.is_available() else "cpu"), **var_params)

        out = net(v)
        nll = -log_softmax(out)
        loss = (nll * a / 10).sum(dim=1).mean()
        acc = utils.batch_accuracy_partial(out.data, a.data).cpu()

        if train:
            global total_iterations
            update_learning_rate(optimizer, total_iterations)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_iterations += 1
        else:
            # store information about evaluation of this minibatch
            _, answer = out.data.cpu().max(dim=1)
            answ.append(answer.view(-1))
            accs.append(acc.view(-1))
            idxs.append(idx.view(-1).clone())

        loss_tracker.append(loss.data.item())
        # acc_tracker.append(acc.mean())
        for a in acc:
            acc_tracker.append(a.item())
        fmt = '{:.4f}'.format
        tq.set_postfix(loss=fmt(loss_tracker.mean.value), acc=fmt(acc_tracker.mean.value))

    if not train:
        answ = list(torch.cat(answ, dim=0))
        accs = list(torch.cat(accs, dim=0))
        idxs = list(torch.cat(idxs, dim=0))
        return answ, accs, idxs


def main():
    print("running on", "cuda:0" if torch.cuda.is_available() else "cpu")
    if len(sys.argv) > 1:
        name = ' '.join(sys.argv[1:])
    else:
        from datetime import datetime
        name = datetime.now().strftime("%Y-%m-%d_%H:%M:%S")
    target_name = os.path.join('logs_color', '{}.pth'.format(name))
    print('will save to {}'.format(target_name))

    cudnn.benchmark = True

    train_loader = data.get_loader(train=True, color_only=True)
    val_loader = data.get_loader(val=True, color_only=True)

    net = nn.DataParallel(color_net).cuda()
    optimizer = optim.Adam([p for p in net.parameters() if p.requires_grad], weight_decay=0.01)

    tracker = utils.Tracker()
    config_as_dict = {k: v for k, v in vars(config).items() if not k.startswith('__')}

    for i in range(config.epochs):
        _ = run(net, train_loader, optimizer, tracker, train=True, prefix='train', epoch=i)
        r = run(net, val_loader, optimizer, tracker, train=False, prefix='val', epoch=i)

        results = {
            'name': name,
            'tracker': tracker.to_dict(),
            'config': config_as_dict,
            'weights': net.state_dict(),
            'eval': {
                'answers': r[0],
                'accuracies': r[1],
                'idx': r[2],
            },
            'vocab': train_loader.dataset.vocab,
        }
        torch.save(results, target_name)


if __name__ == '__main__':
    main()
