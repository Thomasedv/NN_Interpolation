#!/bin/bash

clear;

echo 'DVF'
python3 eval_video_interpolation.py \
	--gt-dir ucf101_interp_ours \
	--motion-mask-dir motion_masks_ucf101_interp/ \
	--res-dir ucf101_interp_ours/ \
	--res-suffix _ours.png 

echo 'SepConv'
python3 eval_video_interpolation.py \
	--gt-dir ucf101_interp_ours \
	--motion-mask-dir motion_masks_ucf101_interp/ \
	--res-dir ucf101_sepconv/ \
	--res-suffix _gt.png 

echo 'SuperSloMo_Adobe240fps'
python3 eval_video_interpolation.py \
	--gt-dir ucf101_interp_ours \
	--motion-mask-dir motion_masks_ucf101_interp/ \
	--res-dir ucf101_superslomo_adobe240fps/ \
	--res-suffix _interp_001.png 

echo 'SuperSloMo'
python3 eval_video_interpolation.py \
	--gt-dir ucf101_interp_ours \
	--motion-mask-dir motion_masks_ucf101_interp/ \
	--res-dir ucf101_superslomo/ \
	--res-suffix _superslomo.png

# What I got were
# DVF
# 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 379/379 [00:10<00:00, 35.75it/s]
# PSNR: 29.37, SSIM: 0.861, IE: 16.37
# SepConv
# 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 379/379 [00:10<00:00, 34.74it/s]
# PSNR: 30.03, SSIM: 0.869, IE: 15.78
# SuperSloMo_Adobe240fps
# 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 379/379 [00:10<00:00, 35.65it/s]
# PSNR: 29.80, SSIM: 0.870, IE: 15.68
# SuperSloMo
# 100%|█████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████████| 379/379 [00:10<00:00, 35.31it/s]
# PSNR: 30.22, SSIM: 0.880, IE: 15.18
