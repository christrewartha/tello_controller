# tello_controller
Control the DJI Tello drone with keyboard - also use the camera for face recognition / tracking

Using this tello package: https://github.com/damiafuentes/DJITelloPy

And following this tutorial initially: https://youtu.be/LmEcyQnfpDA


Those files are in the "tutorial" folder. They are a bit rough and ready, I've tried to clean them up a bit in files in the root folder as I didn't really like how he used pygame in the tutorial. This needs a bit more work though.

Next steps are:
- the face tracking isn't tested on tello yet
- adjust the movement a bit to include smoothing and maybe some counter-steer when lifting off
- try object detection with opencv

