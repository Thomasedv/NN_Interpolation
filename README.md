# AI_Interpolation
A fork of the SuperSloMo repository, modified in various ways to experiment with the capabilitiets of the nural net. 
Source: https://github.com/avinashpaliwal/Super-SloMo  
(Special mention of this, which the above builds on: https://github.com/TheFairBear/Super-SlowMo)

## Motivation
This fork is just a personal fork, which features experiments with different parameters in the neural net and dateset creation, to attempt to create nice interpolations.
I personally do not know how to write or much about changing networks so this is a sandbox to try things out. 

Some notale changes:
- Dataset is made to keep resolution of 720p
- Images are loaded at full resolution, and random crop is almost full image. (Sadly the only values i managed to match nicely)
- The skip connections should be going to the first convolutional layer, as per the original paper the model was derived from, unlike the project i forked this from, which sends the skip connection to the secondary convolutional layers. Actual gain is unknown, but it seemed like a change i was able to do. 
- Learning rate decrease is lowered but for no other reason than to experiment. 

If i get any interesting results, i might update the repository with them. I used the adobe dataset as the orignal article, with a few clips from youtube. Personally might film some 240fps videos with mobile to create data samples myself. 
