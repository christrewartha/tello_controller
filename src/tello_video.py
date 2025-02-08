import numpy as np
import cv2
import time
import tello_pygame

take_snapshot = False
previous_error = 0

def take_a_snapshot():
    global take_snapshot
    take_snapshot = True


def drone_update_stream(drone, detect_face=False, track_face=False):
    # get the frame from the drone
    frame = drone.get_frame_read().frame

    global take_snapshot
    if take_snapshot:
        cv2.imwrite(f'../Resources/Images/{time.time()}.jpg', frame)
        take_snapshot = False

    if detect_face:
        _, info = find_face(frame)
        if info[1] != 0:
            # found a face
            if track_face:
                global previous_error
                previous_error = trackFace(drone, info, 1280, previous_error)

    # convert format to blit to pygame surface
    frame = cv2.resize(frame, tello_pygame.get_dimensions())
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    frame = frame.swapaxes(0, 1)
    frame = cv2.flip(frame, 0)
    tello_pygame.blit_frame(frame)


def find_face(img):
    xml_file = '../../haar-cascade-files-master/haarcascade_frontalface_default.xml'
    face_cascade = cv2.CascadeClassifier(xml_file)

    img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(img_gray, 1.2, 8)

    faces_centres = []
    faces_areas = []

    for (x, y, w, h) in faces:
        cv2.rectangle(img, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cx = x + w // 2
        cy = y + h // 2
        area = w * h
        cv2.circle(img, (cx, cy), 5, (0, 0, 255), cv2.FILLED)
        faces_centres.append([cx, cy])
        faces_areas.append(area)

    if len(faces_areas) != 0:
        i = faces_areas.index(max(faces_areas))
        return img, [faces_centres[i], faces_areas[i]]
    else:
        return img, [[0, 0], 0]


def trackFace(drone, info, width, previous_error):
    fb_range = [6200, 6800]
    pid = [0.4, 0.4, 0]
    fb = 0

    x, y = info[0]
    area = info[1]

    error = x - width // 2
    speed = pid[0] * error + pid[1] * (error - previous_error)
    speed = int(np.clip(speed, -100, 100))

    if fb_range[0] < area < fb_range[1]:
        fb = 0
    elif area > fb_range[1]:
        fb = -20
    elif area < fb_range[0] and area != 0:
        fb = 20

    # send these values to the drone

    return error
