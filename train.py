# [Super SloMo]
##High Quality Estimation of Multiple Intermediate Frames for Video Interpolation

import argparse
import torch
import torchvision
import torchvision.transforms as transforms
import torch.optim as optim
from torch.optim.adamw import AdamW
import torch.nn as nn
import model
import dataloader
import sys
from math import log10
import datetime
from tensorboardX import SummaryWriter


def train():
    global writer
    # For parsing commandline arguments
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_root", type=str, required=True,
                        help='path to dataset folder containing train-test-validation folders')
    parser.add_argument("--checkpoint_dir", type=str, required=True, help='path to folder for saving checkpoints')
    parser.add_argument("--checkpoint", type=str, help='path of checkpoint for pretrained model')
    parser.add_argument("--train_continue", type=bool, default=False,
                        help='If resuming from checkpoint, set to True and set `checkpoint` path. Default: False.')
    parser.add_argument("--epochs", type=int, default=200, help='number of epochs to train. Default: 200.')
    parser.add_argument("--train_batch_size", type=int, default=3, help='batch size for training. Default: 6.')
    parser.add_argument("--validation_batch_size", type=int, default=6, help='batch size for validation. Default: 10.')
    parser.add_argument("--init_learning_rate", type=float, default=0.0001,
                        help='set initial learning rate. Default: 0.0001.')
    parser.add_argument("--milestones", type=list, default=[25, 50],
                        help='UNUSED NOW: Set to epoch values where you want to decrease learning rate by a factor of 0.1. Default: [100, 150]')
    parser.add_argument("--progress_iter", type=int, default=200,
                        help='frequency of reporting progress and validation. N: after every N iterations. Default: 100.')
    parser.add_argument("--checkpoint_epoch", type=int, default=5,
                        help='checkpoint saving frequency. N: after every N epochs. Each checkpoint is roughly of size 151 MB.Default: 5.')
    args = parser.parse_args()

    ##[TensorboardX](https://github.com/lanpa/tensorboardX)
    ### For visualizing loss and interpolated frames

    ###Initialize flow computation and arbitrary-time flow interpolation CNNs.

    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")

    print(device)
    flowComp = model.UNet(6, 4)
    flowComp.to(device)
    ArbTimeFlowIntrp = model.UNet(20, 5)
    ArbTimeFlowIntrp.to(device)

    ###Initialze backward warpers for train and validation datasets

    train_W_dim = 352
    train_H_dim = 352

    trainFlowBackWarp = model.backWarp(train_W_dim, train_H_dim, device)
    trainFlowBackWarp = trainFlowBackWarp.to(device)
    validationFlowBackWarp = model.backWarp(train_W_dim * 2, train_H_dim, device)
    validationFlowBackWarp = validationFlowBackWarp.to(device)

    ###Load Datasets

    # Channel wise mean calculated on custom training dataset
    # mean = [0.43702903766008444, 0.43715053433990597, 0.40436416782660994]
    mean = [0.5] * 3
    std = [1, 1, 1]
    normalize = transforms.Normalize(mean=mean,
                                     std=std)
    transform = transforms.Compose([transforms.ToTensor(), normalize])

    trainset = dataloader.SuperSloMo(root=args.dataset_root + '/train', randomCropSize=(train_W_dim, train_H_dim),
                                     transform=transform, train=True)
    trainloader = torch.utils.data.DataLoader(trainset, batch_size=args.train_batch_size, shuffle=True, num_workers=2,
                                              pin_memory=True)

    validationset = dataloader.SuperSloMo(root=args.dataset_root + '/validation', transform=transform,
                                          randomCropSize=(2 * train_W_dim, train_H_dim), train=False)
    validationloader = torch.utils.data.DataLoader(validationset, batch_size=args.validation_batch_size, shuffle=False,
                                                   num_workers=2,
                                                   pin_memory=True)

    print(trainset, validationset)

    ###Create transform to display image from tensor

    negmean = [x * -1 for x in mean]
    revNormalize = transforms.Normalize(mean=negmean, std=std)
    TP = transforms.Compose([revNormalize, transforms.ToPILImage()])

    ###Utils

    def get_lr(optimizer):
        for param_group in optimizer.param_groups:
            return param_group['lr']

    ###Loss and Optimizer

    L1_lossFn = nn.L1Loss()
    MSE_LossFn = nn.MSELoss()

    if args.train_continue:
        dict1 = torch.load(args.checkpoint)
        last_epoch = dict1['epoch'] * len(trainloader)
    else:
        last_epoch = -1

    params = list(ArbTimeFlowIntrp.parameters()) + list(flowComp.parameters())

    optimizer = AdamW(params, lr=args.init_learning_rate, amsgrad=True)
    # optimizer = optim.SGD(params, lr=args.init_learning_rate, momentum=0.9, nesterov=True)

    # scheduler to decrease learning rate by a factor of 10 at milestones.
    # Patience suggested value:
    # patience = number of item in train dataset / train_batch_size * (Number of epochs patience)
    # It does say epoch, but in this case, the number of progress iterations is what's really being worked with.
    # As such, each epoch will be given by the above formula (roughly, if using a rough dataset count)
    # If the model seems to equalize fast, reduce the number of epochs accordingly.

    # scheduler = optim.lr_scheduler.CyclicLR(optimizer,
    #                                         base_lr=1e-8,
    #                                         max_lr=9.0e-3,
    #                                         step_size_up=3500,
    #                                         mode='triangular2',
    #                                         cycle_momentum=False,
    #                                         last_epoch=last_epoch)

    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer,
                                                     mode='min',
                                                     factor=0.1,
                                                     patience=len(trainloader) * 3,
                                                     cooldown=len(trainloader) * 2,
                                                     verbose=True,
                                                     min_lr=1e-8)

    # Changed to use this to ensure a more adaptive model.
    # The changed model used here seems to converge or plateau faster with more rapid swings over time.
    # As such letting the model deal with stagnation more proactively than at a set stage seems more useful.

    ###Initializing VGG16 model for perceptual loss

    vgg16 = torchvision.models.vgg16(pretrained=True)
    vgg16_conv_4_3 = nn.Sequential(*list(vgg16.children())[0][:22])
    vgg16_conv_4_3.to(device)

    for param in vgg16_conv_4_3.parameters():
        param.requires_grad = False

    # Validation function

    def validate():
        # For details see training.
        psnr = 0
        tloss = 0
        flag = 1
        with torch.no_grad():
            for validationIndex, (validationData, validationFrameIndex) in enumerate(validationloader, 0):
                frame0, frameT, frame1 = validationData

                I0 = frame0.to(device)
                I1 = frame1.to(device)
                IFrame = frameT.to(device)

                torch.cuda.empty_cache()
                flowOut = flowComp(torch.cat((I0, I1), dim=1))
                F_0_1 = flowOut[:, :2, :, :]
                F_1_0 = flowOut[:, 2:, :, :]

                fCoeff = model.getFlowCoeff(validationFrameIndex, device)
                torch.cuda.empty_cache()
                F_t_0 = fCoeff[0] * F_0_1 + fCoeff[1] * F_1_0
                F_t_1 = fCoeff[2] * F_0_1 + fCoeff[3] * F_1_0

                g_I0_F_t_0 = validationFlowBackWarp(I0, F_t_0)
                g_I1_F_t_1 = validationFlowBackWarp(I1, F_t_1)
                torch.cuda.empty_cache()
                intrpOut = ArbTimeFlowIntrp(
                    torch.cat((I0, I1, F_0_1, F_1_0, F_t_1, F_t_0, g_I1_F_t_1, g_I0_F_t_0), dim=1))

                F_t_0_f = intrpOut[:, :2, :, :] + F_t_0
                F_t_1_f = intrpOut[:, 2:4, :, :] + F_t_1
                V_t_0 = torch.sigmoid(intrpOut[:, 4:5, :, :])
                V_t_1 = 1 - V_t_0
                # torch.cuda.empty_cache()
                g_I0_F_t_0_f = validationFlowBackWarp(I0, F_t_0_f)
                g_I1_F_t_1_f = validationFlowBackWarp(I1, F_t_1_f)

                wCoeff = model.getWarpCoeff(validationFrameIndex, device)
                torch.cuda.empty_cache()
                Ft_p = (wCoeff[0] * V_t_0 * g_I0_F_t_0_f + wCoeff[1] * V_t_1 * g_I1_F_t_1_f) / (
                        wCoeff[0] * V_t_0 + wCoeff[1] * V_t_1)

                # For tensorboard
                if (flag):
                    retImg = torchvision.utils.make_grid(
                        [revNormalize(frame0[0]), revNormalize(frameT[0]), revNormalize(Ft_p.cpu()[0]),
                         revNormalize(frame1[0])], padding=10)
                    flag = 0

                # loss
                recnLoss = L1_lossFn(Ft_p, IFrame)
                # torch.cuda.empty_cache()
                prcpLoss = MSE_LossFn(vgg16_conv_4_3(Ft_p), vgg16_conv_4_3(IFrame))

                warpLoss = L1_lossFn(g_I0_F_t_0, IFrame) + L1_lossFn(g_I1_F_t_1, IFrame) + L1_lossFn(
                    validationFlowBackWarp(I0, F_1_0), I1) + L1_lossFn(validationFlowBackWarp(I1, F_0_1), I0)
                torch.cuda.empty_cache()
                loss_smooth_1_0 = torch.mean(torch.abs(F_1_0[:, :, :, :-1] - F_1_0[:, :, :, 1:])) + torch.mean(
                    torch.abs(F_1_0[:, :, :-1, :] - F_1_0[:, :, 1:, :]))
                loss_smooth_0_1 = torch.mean(torch.abs(F_0_1[:, :, :, :-1] - F_0_1[:, :, :, 1:])) + torch.mean(
                    torch.abs(F_0_1[:, :, :-1, :] - F_0_1[:, :, 1:, :]))
                loss_smooth = loss_smooth_1_0 + loss_smooth_0_1

                # torch.cuda.empty_cache()
                loss = 204 * recnLoss + 102 * warpLoss + 0.005 * prcpLoss + loss_smooth
                tloss += loss.item()

                # psnr
                MSE_val = MSE_LossFn(Ft_p, IFrame)
                psnr += (10 * log10(1 / MSE_val.item()))
                torch.cuda.empty_cache()

        return (psnr / len(validationloader)), (tloss / len(validationloader)), retImg

    ### Initialization

    if args.train_continue:
        ArbTimeFlowIntrp.load_state_dict(dict1['state_dictAT'])
        flowComp.load_state_dict(dict1['state_dictFC'])

        optimizer.load_state_dict(dict1.get('state_optimizer', {}))
        scheduler.load_state_dict(dict1.get('state_scheduler', {}))

        for param_group in optimizer.param_groups:
            param_group['lr'] = dict1.get('learningRate', args.init_learning_rate)

    else:
        dict1 = {'loss': [], 'valLoss': [], 'valPSNR': [], 'epoch': -1}

    ### Training

    import time

    start = time.time()
    cLoss = dict1['loss']
    valLoss = dict1['valLoss']
    valPSNR = dict1['valPSNR']
    checkpoint_counter = 0

    ### Main training loop

    optimizer.step()

    for epoch in range(dict1['epoch'] + 1, args.epochs):
        print("Epoch: ", epoch)

        # Append and reset
        cLoss.append([])
        valLoss.append([])
        valPSNR.append([])
        iLoss = 0

        for trainIndex, (trainData, trainFrameIndex) in enumerate(trainloader, 0):

            ## Getting the input and the target from the training set
            frame0, frameT, frame1 = trainData

            I0 = frame0.to(device)
            I1 = frame1.to(device)
            IFrame = frameT.to(device)
            optimizer.zero_grad()
            # torch.cuda.empty_cache()
            # Calculate flow between reference frames I0 and I1
            flowOut = flowComp(torch.cat((I0, I1), dim=1))

            # Extracting flows between I0 and I1 - F_0_1 and F_1_0
            F_0_1 = flowOut[:, :2, :, :]
            F_1_0 = flowOut[:, 2:, :, :]

            fCoeff = model.getFlowCoeff(trainFrameIndex, device)

            # Calculate intermediate flows
            F_t_0 = fCoeff[0] * F_0_1 + fCoeff[1] * F_1_0
            F_t_1 = fCoeff[2] * F_0_1 + fCoeff[3] * F_1_0

            # Get intermediate frames from the intermediate flows
            g_I0_F_t_0 = trainFlowBackWarp(I0, F_t_0)
            g_I1_F_t_1 = trainFlowBackWarp(I1, F_t_1)
            torch.cuda.empty_cache()
            # Calculate optical flow residuals and visibility maps
            intrpOut = ArbTimeFlowIntrp(torch.cat((I0, I1, F_0_1, F_1_0, F_t_1, F_t_0, g_I1_F_t_1, g_I0_F_t_0), dim=1))

            # Extract optical flow residuals and visibility maps
            F_t_0_f = intrpOut[:, :2, :, :] + F_t_0
            F_t_1_f = intrpOut[:, 2:4, :, :] + F_t_1
            V_t_0 = torch.sigmoid(intrpOut[:, 4:5, :, :])
            V_t_1 = 1 - V_t_0
            # torch.cuda.empty_cache()
            # Get intermediate frames from the intermediate flows
            g_I0_F_t_0_f = trainFlowBackWarp(I0, F_t_0_f)
            g_I1_F_t_1_f = trainFlowBackWarp(I1, F_t_1_f)
            # torch.cuda.empty_cache()
            wCoeff = model.getWarpCoeff(trainFrameIndex, device)
            torch.cuda.empty_cache()
            # Calculate final intermediate frame
            Ft_p = (wCoeff[0] * V_t_0 * g_I0_F_t_0_f + wCoeff[1] * V_t_1 * g_I1_F_t_1_f) / (
                    wCoeff[0] * V_t_0 + wCoeff[1] * V_t_1)

            # Loss
            recnLoss = L1_lossFn(Ft_p, IFrame)
            # torch.cuda.empty_cache()

            prcpLoss = MSE_LossFn(vgg16_conv_4_3(Ft_p), vgg16_conv_4_3(IFrame))
            # torch.cuda.empty_cache()
            warpLoss = L1_lossFn(g_I0_F_t_0, IFrame) + L1_lossFn(g_I1_F_t_1, IFrame) + L1_lossFn(
                trainFlowBackWarp(I0, F_1_0), I1) + L1_lossFn(trainFlowBackWarp(I1, F_0_1), I0)

            loss_smooth_1_0 = torch.mean(torch.abs(F_1_0[:, :, :, :-1] - F_1_0[:, :, :, 1:])) + torch.mean(
                torch.abs(F_1_0[:, :, :-1, :] - F_1_0[:, :, 1:, :]))
            loss_smooth_0_1 = torch.mean(torch.abs(F_0_1[:, :, :, :-1] - F_0_1[:, :, :, 1:])) + torch.mean(
                torch.abs(F_0_1[:, :, :-1, :] - F_0_1[:, :, 1:, :]))
            loss_smooth = loss_smooth_1_0 + loss_smooth_0_1
            # torch.cuda.empty_cache()
            # Total Loss - Coefficients 204 and 102 are used instead of 0.8 and 0.4
            # since the loss in paper is calculated for input pixels in range 0-255
            # and the input to our network is in range 0-1
            loss = 204 * recnLoss + 102 * warpLoss + 0.005 * prcpLoss + loss_smooth

            # Backpropagate

            loss.backward()
            optimizer.step()
            scheduler.step(loss.item())

            iLoss += loss.item()
            torch.cuda.empty_cache()
            # Validation and progress every `args.progress_iter` iterations
            if ((trainIndex % args.progress_iter) == args.progress_iter - 1):
                # Increment scheduler count
                scheduler.step(iLoss / args.progress_iter)

                end = time.time()

                psnr, vLoss, valImg = validate()
                optimizer.zero_grad()
                # torch.cuda.empty_cache()
                valPSNR[epoch].append(psnr)
                valLoss[epoch].append(vLoss)

                # Tensorboard
                itr = trainIndex + epoch * (len(trainloader))

                writer.add_scalars('Loss', {'trainLoss': iLoss / args.progress_iter,
                                            'validationLoss': vLoss}, itr)
                writer.add_scalar('PSNR', psnr, itr)

                writer.add_image('Validation', valImg, itr)
                #####

                endVal = time.time()

                print(
                    " Loss: %0.6f  Iterations: %4d/%4d  TrainExecTime: %0.1f  ValLoss:%0.6f  ValPSNR: %0.4f  ValEvalTime: %0.2f LearningRate: %.1e" % (
                        iLoss / args.progress_iter, trainIndex, len(trainloader), end - start, vLoss, psnr,
                        endVal - end,
                        get_lr(optimizer)))

                # torch.cuda.empty_cache()
                cLoss[epoch].append(iLoss / args.progress_iter)
                iLoss = 0
                start = time.time()

        # Create checkpoint after every `args.checkpoint_epoch` epochs
        if (epoch % args.checkpoint_epoch) == args.checkpoint_epoch - 1:
            dict1 = {
                'Detail': "End to end Super SloMo.",
                'epoch': epoch,
                'timestamp': datetime.datetime.now(),
                'trainBatchSz': args.train_batch_size,
                'validationBatchSz': args.validation_batch_size,
                'learningRate': get_lr(optimizer),
                'loss': cLoss,
                'valLoss': valLoss,
                'valPSNR': valPSNR,
                'state_dictFC': flowComp.state_dict(),
                'state_dictAT': ArbTimeFlowIntrp.state_dict(),
                'state_optimizer': optimizer.state_dict(),
                'state_scheduler': scheduler.state_dict()
            }
            torch.save(dict1, args.checkpoint_dir + "/SuperSloMo" + str(checkpoint_counter) + ".ckpt")
            checkpoint_counter += 1


if __name__ == '__main__':
    # Ensure tensorboardx closes properly.
    try:
        writer = SummaryWriter('log')
        train()
    except Exception as e:
        if not isinstance(e, KeyboardInterrupt):
            import traceback

            traceback.print_exc()
    finally:
        writer.close()
        print('\n\nWriter closed')
        print('Exiting program')
        sys.exit(1)
